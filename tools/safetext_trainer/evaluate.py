"""Evaluate one model through the *full* chatfilter pipeline (rules + context + model).

Run as a subprocess by train.py (one process per model, so module state never
leaks between models):

    python tools/safetext_trainer/evaluate.py --model <path|hf-id> --work <dir> --out metrics.json

Test sets (sensitivity "medium"):
  hatecheck_de / hatecheck_en  HateCheck functional tests (Röttger et al.)
  discord                      tools/safetext_trainer/eval/discord.jsonl
  holdout                      admin-labelled samples never used for training
Per set: recall = harmful messages removed, fp_rate = harmless messages removed.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import sys
import types
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVAL_DIR = Path(__file__).resolve().parent / "eval"
HATECHECK = {
    "de": "https://huggingface.co/datasets/Paul/hatecheck-german/resolve/main/test.csv",
    "en": "https://huggingface.co/datasets/Paul/hatecheck/resolve/main/test.csv",
}
ALL_CATEGORIES = {"1", "2", "3", "4", "5"}


def _hatecheck(work: Path, lang: str) -> list[dict]:
    path = work / f"hatecheck_{lang}.csv"
    if not path.exists():
        print(f"  lade HateCheck {lang} ...", flush=True)
        urllib.request.urlretrieve(HATECHECK[lang], path)
    cases = []
    for r in csv.DictReader(path.open(encoding="utf-8")):
        func = r["functionality"]
        if func == "target_group_nh":        # abuse of non-protected groups: grey zone
            continue
        remove = func == "target_indiv_nh" or r["label_gold"] == "hateful"
        cases.append({"text": r["test_case"], "expect": "remove" if remove else "keep"})
    return cases


def _jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


async def _run(model: str, work: Path, holdout: Path) -> dict:
    os.environ["SAFETEXT_MODEL"] = model
    if "SAFETEXT_DEVICE" not in os.environ:
        try:
            import torch
            os.environ["SAFETEXT_DEVICE"] = "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            pass
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    share = types.ModuleType("assets.share")
    share.admin_log = lambda *a, **k: None
    share.phishing_url_list = set()
    sys.modules["assets.share"] = share
    from assets.message.safetext import feedback, models, pipeline
    pipeline.record = lambda **k: "eval"            # no classification log for test runs
    feedback.override_for = lambda *a, **k: None    # judge the model, not stored overrides
    models.preload()

    sets = {
        "hatecheck_de": _hatecheck(work, "de"),
        "hatecheck_en": _hatecheck(work, "en"),
        "discord": _jsonl(EVAL_DIR / "discord.jsonl"),
        "holdout": _jsonl(holdout),
    }
    metrics, decisions = {}, {}
    for name, cases in sets.items():
        if not cases:
            continue
        tp = fn = fp = tn = 0
        for c in cases:
            res = await pipeline.check(
                message=c["text"], gid=0, cid=0, user_id=0,
                chatfilter_data={"sensitivity": "medium"}, guild_lang="de",
                enabled_categories=ALL_CATEGORIES, targeted_hint=bool(c.get("reply")),
            )
            removed = bool(res["flagged"])
            decisions[f"{name}\t{c['text']}"] = removed
            if c["expect"] == "remove":
                tp += removed
                fn += not removed
            else:
                fp += removed
                tn += not removed
        metrics[name] = {
            "recall": round(100 * tp / max(1, tp + fn), 1),
            "fp_rate": round(100 * fp / max(1, fp + tn), 1),
            "n": len(cases),
        }
        print(f"  {name:13} erkannt {metrics[name]['recall']:5.1f}%   "
              f"falsch gelöscht {metrics[name]['fp_rate']:5.1f}%   ({len(cases)} Fälle)", flush=True)
    return {"metrics": metrics, "decisions": decisions}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--holdout", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = Path(a.out).resolve()
    result = asyncio.run(_run(a.model, Path(a.work).resolve(), Path(a.holdout).resolve()))
    out.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
