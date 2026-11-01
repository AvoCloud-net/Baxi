"""Feintuning des SafeText-Klassifikators v2 auf dem Gemisch aus build_mix.py.

    python tools/safetext_trainer/v2/train_v2.py --base textdetox/xlmr-large-toxicity-classifier --out <dir> --mix <dir>

Binäre Klassifikation (1 = Moderator würde entfernen). Beste Epoche nach Val-Macro-F1. Seed 42, bf16-Autocast.
Das Modell ist danach über SAFETEXT_MODEL=<dir> in der Pipeline nutzbar (siehe evaluate.py).
Eingefrorene Testdaten (holdout_v2.jsonl, HateCheck, GermEval-Test) werden hier nicht gelesen.
"""
import argparse
import datetime as dt
import json
import random
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from sklearn.metrics import f1_score
from transformers import AutoModelForSequenceClassification, AutoTokenizer, get_linear_schedule_with_warmup

SEED = 42


def predict(model, tok, texts, device, maxlen, batch=128):
    model.eval()
    order = np.argsort([len(t) for t in texts])
    probs = np.empty(len(texts))
    with torch.inference_mode(), torch.autocast(device, dtype=torch.bfloat16):
        for i in range(0, len(texts), batch):
            idx = order[i:i + batch]
            enc = tok([texts[j] for j in idx], return_tensors="pt", truncation=True, max_length=maxlen,
                      padding=True).to(device)
            probs[idx] = torch.softmax(model(**enc).logits.float(), -1)[:, 1].cpu().numpy()
    return probs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--mix", required=True)
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--lr", type=float, default=2e-5)
    ap.add_argument("--maxlen", type=int, default=128)
    a = ap.parse_args()
    random.seed(SEED); np.random.seed(SEED); torch.manual_seed(SEED); torch.cuda.manual_seed_all(SEED)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    mix, out = Path(a.mix), Path(a.out)
    train, val = pd.read_json(mix / "train.jsonl", lines=True), pd.read_json(mix / "val.jsonl", lines=True)
    tok = AutoTokenizer.from_pretrained(a.base)
    model = AutoModelForSequenceClassification.from_pretrained(
        a.base, num_labels=2, id2label={0: "neutral", 1: "toxic"}, label2id={"neutral": 0, "toxic": 1},
        ignore_mismatched_sizes=True).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=a.lr, weight_decay=0.01)
    steps = a.epochs * ((len(train) + a.batch - 1) // a.batch)
    sched = get_linear_schedule_with_warmup(opt, int(0.1 * steps), steps)
    log = {"datum": dt.datetime.now().isoformat(timespec="seconds"), "basis": a.base, "seed": SEED,
           "args": vars(a), "train_n": len(train), "val_n": len(val), "epochen": []}
    best = -1.0
    for epoch in range(1, a.epochs + 1):
        model.train()
        order = np.random.permutation(len(train))
        total, t0 = 0.0, time.time()
        for i in range(0, len(order), a.batch):
            b = train.iloc[order[i:i + a.batch]]
            enc = tok(b.text.tolist(), return_tensors="pt", truncation=True, max_length=a.maxlen,
                      padding=True).to(device)
            labels = torch.tensor(b.label.values, device=device)
            with torch.autocast(device, dtype=torch.bfloat16):
                loss = torch.nn.functional.cross_entropy(model(**enc).logits.float(), labels)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step(); sched.step(); opt.zero_grad()
            total += loss.item() * len(b)
        pv = predict(model, tok, val.text.tolist(), device, a.maxlen)
        f1 = f1_score(val.label, pv >= 0.5, average="macro")
        per = {s: float(((pv[val.src == s] >= 0.5) == val.label[val.src == s]).mean()) for s in val.src.unique()}
        entry = {"epoche": epoch, "train_loss": total / len(train), "val_macro_f1": float(f1),
                 "val_acc_je_quelle": per, "sekunden": round(time.time() - t0)}
        log["epochen"].append(entry)
        print(entry, flush=True)
        if f1 > best:
            best = f1; log["beste_epoche"] = epoch
            out.mkdir(parents=True, exist_ok=True)
            model.save_pretrained(out); tok.save_pretrained(out)
    (out / "train_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    print("gespeichert:", out, "beste Epoche", log["beste_epoche"], "val macro-F1", round(best, 4))


if __name__ == "__main__":
    main()
