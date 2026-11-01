"""Baut das Trainingsgemisch für den SafeText-Klassifikator v2 aus öffentlichen Datensätzen.

    python tools/safetext_trainer/v2/build_mix.py --raw <dir> --out <dir> [--no-translate]

Quellen (alle mit Lizenz geprüft, siehe README der Quellen):
  GermEval 2018 Train      CC BY 4.0           deutsch, Tweets (PROFANITY ohne Adressat zählt als harmlos)
  Jigsaw Toxic Comments    CC0 (Kaggle-Spiegel) englisch, Wikipedia; Labels threat / identity_hate / insult / obscene
  Measuring Hate Speech    CC BY 4.0           englisch, hate_speech_score je Kommentar
  Maschinelle Übersetzung  Helsinki-NLP/opus-mt-en-de (CC BY 4.0): ein Teil der englischen Beispiele ins Deutsche
Nicht verwendet: HateCheck (nur Test), GermEval 2021 (Lizenz unklar, nur Test), holdout_v2.jsonl (eingefroren).

Label 1 = Nachricht, die ein Moderator entfernen würde: Drohung, Gruppenhass, schwere Beleidigung, gezielte
Beleidigung. Label 0 = harmlos, auch Fluchen ohne Adressat ("obscene" ohne Beleidigung).
"""
import argparse
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42
rng = np.random.default_rng(SEED)


def clean(t: str, n: int = 400) -> str:
    t = re.sub(r"https?://\S+", " ", str(t))
    t = re.sub(r"\s+", " ", t).strip()
    return t[:n]


def take(df: pd.DataFrame, n: int) -> pd.DataFrame:
    return df.sample(min(n, len(df)), random_state=SEED)


def jigsaw(raw: Path) -> pd.DataFrame:
    j = pd.read_csv(raw / "jigsaw_train.csv.gz")
    j["text"] = j.comment_text.map(clean)
    j = j[j.text.str.len() >= 8]
    hate = j[(j.identity_hate == 1)]
    thr = j[(j.threat == 1)]
    sev = j[(j.severe_toxic == 1) & (j.threat == 0) & (j.identity_hate == 0)]
    ins = j[(j.insult == 1) & (j.toxic == 1) & (j.severe_toxic == 0) & (j.threat == 0) & (j.identity_hate == 0)]
    obs = j[(j.obscene == 1) & (j.insult == 0) & (j.threat == 0) & (j.identity_hate == 0) & (j.severe_toxic == 0)]
    cln = j[(j[["toxic", "severe_toxic", "obscene", "threat", "insult", "identity_hate"]].sum(axis=1) == 0)]
    parts = [(thr, 1, "drohung", len(thr)), (hate, 1, "gruppenhass", len(hate)), (take(sev, 800), 1, "schwer", 800),
             (take(ins, 1500), 1, "beleidigung", 1500), (take(obs, 1500), 0, "fluchen", 1500),
             (take(cln, 5000), 0, "harmlos", 5000)]
    return pd.concat([p.assign(label=l, type=t)[["text", "label", "type"]] for p, l, t, _ in parts]).assign(src="jigsaw")


def mhs(raw: Path) -> pd.DataFrame:
    m = pd.read_parquet(raw / "mhs.parquet")
    tg = [c for c in m.columns if c.startswith("target_") and c.count("_") >= 2 and m[c].dtype == bool]
    g = m.groupby("comment_id").agg(text=("text", "first"), score=("hate_speech_score", "mean"),
                                    group=("target_race", "max")).reset_index()
    flags = m.groupby("comment_id")[tg].max().any(axis=1).rename("has_target")
    g = g.merge(flags, on="comment_id")
    g["text"] = g.text.map(clean)
    pos = g[g.score > 0.5]
    neg = g[g.score < -1]
    neg_t = neg[neg.has_target]
    neg_o = neg[~neg.has_target]
    parts = [(take(pos, 2500), 1, "gruppenhass"), (take(neg_t, 1500), 0, "gruppe_harmlos"), (take(neg_o, 2000), 0, "harmlos")]
    return pd.concat([p.assign(label=l, type=t)[["text", "label", "type"]] for p, l, t in parts]).assign(src="mhs")


def ge18(pub: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    out = []
    for name in ("ge18_train", "ge18_val"):
        d = pd.read_csv(pub / f"{name}.csv")
        d["label"] = ((d.label == 1) & (d.fine != 3)).astype(int)         # PROFANITY ohne Adressat: harmlos
        d["type"] = d.fine.map({0: "harmlos", 1: "abuse", 2: "beleidigung", 3: "fluchen"})
        out.append(d[["text", "label", "type"]].assign(src="ge18"))
    return out[0], out[1]


def translate(df: pd.DataFrame, device: str) -> pd.DataFrame:
    import torch
    from transformers import MarianMTModel, MarianTokenizer
    name = "Helsinki-NLP/opus-mt-en-de"
    tok, model = MarianTokenizer.from_pretrained(name), MarianMTModel.from_pretrained(name).to(device).eval()
    texts = df.text.tolist()
    order = np.argsort([len(t) for t in texts])
    out = [None] * len(texts)
    with torch.inference_mode():
        for i in range(0, len(texts), 48):
            idx = order[i:i + 48]
            enc = tok([texts[k] for k in idx], return_tensors="pt", truncation=True, max_length=160,
                      padding=True).to(device)
            gen = model.generate(**enc, num_beams=2, max_new_tokens=180)
            for k, s in zip(idx, tok.batch_decode(gen, skip_special_tokens=True)):
                out[k] = s
    return df.assign(text=out, src=df.src + "+mt-de")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--public", default="~/Documents/bwki-baxi/bwki-submission/data/public")
    ap.add_argument("--no-translate", action="store_true")
    a = ap.parse_args()
    raw, out = Path(a.raw).expanduser(), Path(a.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    jg, mh = jigsaw(raw), mhs(raw)
    g_train, g_val = ge18(Path(a.public).expanduser())
    parts = [jg, mh]
    if not a.no_translate:
        import torch
        dev = "cuda" if torch.cuda.is_available() else "cpu"
        sel = pd.concat([
            take(jg[jg.type == "drohung"], 478), take(jg[jg.type == "gruppenhass"], 800),
            take(jg[jg.type == "beleidigung"], 800), take(jg[jg.type == "harmlos"], 1500),
            take(jg[jg.type == "fluchen"], 600), take(mh[mh.type == "gruppe_harmlos"], 800),
            take(mh[mh.type == "gruppenhass"], 800)])
        parts.append(translate(sel, dev))
    allx = pd.concat(parts).drop_duplicates("text").reset_index(drop=True)
    allx["val"] = rng.random(len(allx)) < 0.05
    train = pd.concat([allx[~allx.val], g_train]).sample(frac=1, random_state=SEED)
    val = pd.concat([allx[allx.val], g_val]).sample(frac=1, random_state=SEED)
    for name, d in (("train", train), ("val", val)):
        d[["text", "label", "src", "type"]].to_json(out / f"{name}.jsonl", orient="records", lines=True, force_ascii=False)
        print(name, len(d), d.label.mean().round(3))
        print(d.groupby(["src", "type"]).label.agg(["count", "mean"]).round(2).to_string())


if __name__ == "__main__":
    main()
