"""Verpackt ein Modell im Versionsformat der Bot-Modellverwaltung (Ordner + manifest.json mit SHA-256).

    python tools/safetext_trainer/v2/package_version.py --model <dir> --version <name> --out <dir> --metrics <grid.json> [--samples N]

Lädt nichts hoch und aktiviert nichts. Hochladen und Aktivieren bleibt Sache von train.py / dem Admin-Panel
(Bestätigung durch einen Menschen). Ergebnis: <out>/<version>/ mit Modelldateien + manifest.json.
"""
import argparse
import hashlib
import json
import shutil
import time
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--model", required=True)
ap.add_argument("--version", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--metrics", required=True)
ap.add_argument("--samples", type=int, default=0)
a = ap.parse_args()
dst = Path(a.out) / a.version
dst.mkdir(parents=True, exist_ok=True)
for p in Path(a.model).iterdir():
    if p.is_file() and p.name != "train_log.json":
        shutil.copy2(p, dst / p.name)


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


grid = json.loads(Path(a.metrics).read_text(encoding="utf-8"))
metrics = {k: {"recall": round(100 * v["recall"], 1), "fp_rate": round(100 * v["fp_rate"], 1), "n": v["n"]}
           for k, v in grid.items() if isinstance(v, dict) and "recall" in v}
manifest = {"version": a.version, "base_model": "textdetox/xlmr-large-toxicity-classifier",
            "created_at": int(time.time()), "samples": a.samples, "metrics": metrics,
            "eval_suite": sha(Path(__file__).resolve().parents[1] / "eval" / "discord.jsonl")[:12],
            "files": {p.name: sha(p) for p in sorted(dst.iterdir()) if p.is_file() and p.name != "manifest.json"}}
(dst / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
print("verpackt:", dst, "Dateien:", list(manifest["files"]))
