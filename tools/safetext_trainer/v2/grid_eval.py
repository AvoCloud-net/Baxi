"""Schnelle Gesamtauswertung einer Pipeline-Konfiguration (ein Prozess, ein Modell, Sensitivity "medium").

    SAFETEXT_MODEL=<dir> [SAFETEXT_CF_FLOOR=..] [SAFETEXT_THR_TARGETED=..] [SAFETEXT_THR_GROUP=..] \\
        python tools/safetext_trainer/v2/grid_eval.py --name <label> --out <json>

Sets: holdout_v2 (eingefroren), discord.jsonl, fairness, synthetic, GermEval 2018 Test, GermEval 2021 Test, HateCheck DE/EN.
Gibt je Set Recall (erkannt) und Fehlsperren aus. Pfade der Testdaten: --public (prepare_data-Ausgabe), --subm (Einreichung, nur lesen).
"""
import argparse
import asyncio
import csv
import json
import os
import sys
import types
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
EVAL = ROOT / "tools" / "safetext_trainer" / "eval"
ALL = {"1", "2", "3", "4", "5"}


def hatecheck(work: Path, lang: str):
    rows = []
    for r in csv.DictReader((work / f"hatecheck_{lang}.csv").open(encoding="utf-8")):
        f = r["functionality"]
        if f == "target_group_nh":
            continue
        rows.append({"text": r["test_case"], "func": f,
                     "expect": "remove" if f == "target_indiv_nh" or r["label_gold"] == "hateful" else "keep"})
    return rows


def jl(p: Path):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--work", required=True, help="Ordner mit hatecheck_de.csv / hatecheck_en.csv")
    ap.add_argument("--subm", default=str(Path("~/Documents/bwki-baxi/bwki-submission").expanduser()))
    a = ap.parse_args()
    os.chdir(ROOT); sys.path.insert(0, str(ROOT))
    share = types.ModuleType("assets.share"); share.admin_log = lambda *x, **k: None; share.phishing_url_list = set()
    sys.modules["assets.share"] = share
    from assets.message.safetext import feedback, models, pipeline
    pipeline.record = lambda **k: "x"; feedback.override_for = lambda *x, **k: None
    models.preload()
    subm = Path(a.subm)
    ge18 = pd.read_csv(subm / "data/public/ge18_test.csv"); ge21 = pd.read_csv(subm / "data/public/ge21_test.csv")
    fair = jl(subm / "data/fairness.jsonl"); syn = jl(subm / "data/synthetic_discord.jsonl")
    sets = {
        "holdout_v2": jl(EVAL / "holdout_v2.jsonl"), "discord": jl(EVAL / "discord.jsonl"),
        "fairness": [{"text": r["text"], "expect": "keep"} for r in fair],
        "synthetic": [{"text": r["text"], "expect": r["label"]} for r in syn],
        "ge18_test": [{"text": t, "expect": "remove" if l else "keep"} for t, l in zip(ge18.text, ge18.label)],
        "ge21_test": [{"text": t, "expect": "remove" if l else "keep"} for t, l in zip(ge21.text, ge21.label)],
        "hatecheck_de": hatecheck(Path(a.work), "de"), "hatecheck_en": hatecheck(Path(a.work), "en"),
    }
    res = {"name": a.name, "env": {k: v for k, v in os.environ.items() if k.startswith("SAFETEXT_")}}
    for n, cases in sets.items():
        tp = fn = fp = tn = 0
        byfunc: dict = {}
        for c in cases:
            r = await pipeline.check(message=c["text"], gid=0, cid=0, user_id=0, chatfilter_data={"sensitivity": "medium"},
                                     guild_lang="de", enabled_categories=ALL)
            rem = bool(r["flagged"])
            if "func" in c:
                f = byfunc.setdefault(c["func"], {"n": 0, "removed": 0, "expect": c["expect"]})
                f["n"] += 1; f["removed"] += rem
            if c["expect"] == "remove":
                tp += rem; fn += not rem
            else:
                fp += rem; tn += not rem
        res[n] = {"n": len(cases), "tp": tp, "fn": fn, "fp": fp, "tn": tn,
                  "recall": tp / max(1, tp + fn), "fp_rate": fp / max(1, fp + tn), "precision": tp / max(1, tp + fp)}
        if byfunc:
            res[n]["functions"] = byfunc
        print(f"{a.name:28} {n:13} erkannt {100*res[n]['recall']:5.1f}%  falsch gelöscht {100*res[n]['fp_rate']:5.1f}%  prec {100*res[n]['precision']:5.1f}%", flush=True)
    Path(a.out).write_text(json.dumps(res, indent=1), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
