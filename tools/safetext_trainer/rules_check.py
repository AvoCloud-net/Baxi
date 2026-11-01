"""Schnelltest für die Regelstufen (Gruppenhass, Drohungen) mit kleinen, gezielten Fällen.

    python tools/safetext_trainer/rules_check.py            # mit Modell (SAFETEXT_DEVICE=cuda empfohlen)
    python tools/safetext_trainer/rules_check.py --no-model # nur Regeln

Fälle: tools/safetext_trainer/eval/rules_cases.jsonl (expect: remove/keep). Das sind Regressionsfälle,
keine Messung der Gesamtqualität: Die Auswertung dafür ist evaluate.py (HateCheck, Discord-Set).
Exit-Code 1, wenn ein Fall abweicht.
"""
import argparse
import asyncio
import json
import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASES = Path(__file__).resolve().parent / "eval" / "rules_cases.jsonl"


async def main(use_ml: bool, cases_path: Path = CASES) -> int:
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    share = types.ModuleType("assets.share")
    share.admin_log = lambda *a, **k: None
    share.phishing_url_list = set()
    sys.modules["assets.share"] = share
    from assets.message.safetext import feedback, models, pipeline
    pipeline.record = lambda **k: "test"
    feedback.override_for = lambda *a, **k: None
    if use_ml:
        models.preload()
    bad = 0
    cases = [json.loads(l) for l in cases_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    for c in cases:
        res = await pipeline.check(message=c["text"], gid=0, cid=0, user_id=0,
                                   chatfilter_data={"sensitivity": "medium"}, guild_lang="de",
                                   enabled_categories={"1", "2", "3", "4", "5"}, use_ml=use_ml)
        got = "remove" if res["flagged"] else "keep"
        ok = got == c["expect"]
        bad += not ok
        print(f"{'ok  ' if ok else 'FAIL'} erwartet {c['expect']:6} bekommen {got:6} "
              f"{res['json'].get('label', '-'):16} | {c['text']}")
    print(f"\n{len(cases) - bad}/{len(cases)} Fälle wie erwartet")
    return 1 if bad else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-model", action="store_true")
    ap.add_argument("--cases", default=str(CASES), help="JSONL mit text + expect (remove/keep)")
    a = ap.parse_args()
    sys.exit(asyncio.run(main(not a.no_model, Path(a.cases))))
