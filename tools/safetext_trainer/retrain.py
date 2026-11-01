"""One-command retraining: newest server model + the labelled samples you downloaded from the dash.

    python tools/safetext_trainer/retrain.py                       # newest model, newest ~/Downloads/safetext_labelled*.jsonl
    python tools/safetext_trainer/retrain.py --samples a.jsonl b.csv
    python tools/safetext_trainer/retrain.py --from base           # start from the base model instead
    python tools/safetext_trainer/retrain.py --from /path/to/model # start from a local model folder

What it does (live view in the terminal):
  1. fetch the newest model version from the server (cached, SHA-256 verified)
  2. read the labelled export(s) from the admin dash (JSONL / CSV) and merge them into a
     local label store, so labels accumulate across runs (the dash only exports what it
     still holds)
  3. continue training that model (LoRA, merged afterwards) on the labels it has not seen
     yet + a rehearsal slice of older labels + replay data (keeps old knowledge)
  4. evaluate start model vs. new model through the full pipeline, apply the same gate
     as train.py
  5. upload + activate ONLY after you confirm and only if the gate passes (--force overrides)

Every 5th label (fixed by message text) is never trained on, only used for testing.
"""
from __future__ import annotations

import argparse
import collections
import csv
import glob
import json
import random
import shutil
import subprocess
import sys
import time
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import train as T  # noqa: E402  (reuses data, evaluation, gate and upload code)
from remote import connect  # noqa: E402

try:
    from rich.console import Group
    from rich.live import Live
    from rich.panel import Panel
    from rich.progress_bar import ProgressBar
    from rich.table import Table
    from rich.text import Text
    HAVE_RICH = True
except ImportError:  # plain output fallback
    HAVE_RICH = False

DEFAULTS = {**T.DEFAULTS, "epochs": 2, "learning_rate": 5e-5, "new_label_weight": 3,
            "rehearsal_ratio": 1.0}   # continuing a model: gentler LR than from scratch
SPARK = "▁▂▃▄▅▆▇█"
say = T.say


# ── labelled export -> label store ──────────────────────────────────────────
def find_exports(patterns: list[str]) -> list[Path]:
    if patterns:
        files = [Path(f) for p in patterns for f in (glob.glob(str(Path(p).expanduser())) or [p])]
    else:
        dl = Path.home() / "Downloads"
        files = sorted(dl.glob("safetext_labelled*"), key=lambda p: p.stat().st_mtime)[-1:]
    files = [f for f in files if f.is_file()]
    if not files:
        raise SystemExit("Keine Sample-Datei gefunden. Im Admin-Dash 'Labelled (JSONL)' herunterladen "
                         "oder mit --samples <datei> angeben.")
    return files


def read_export(path: Path) -> list[dict]:
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))
    return T._jsonl(path)


def update_store(store: Path, files: list[Path]) -> tuple[int, int]:
    """Merge export rows into the local label store (newest file wins). -> (new, total)."""
    from assets.message.safetext.normalize import normalize
    have = {r["key"]: r for r in T._jsonl(store)}
    new = 0
    for f in files:
        for row in read_export(f):
            text = str(row.get("text", "")).strip()
            label = str(row.get("label", "")).upper().removeprefix("AI-")
            if not text or label not in T.TOXIC_LABELS | {"SAFE"}:
                continue    # DISCARD, personal data ("4" is a rule) and junk stay out
            key = normalize(text).key
            if key not in have:
                new += 1
            have[key] = {"key": key, "text": text, "y": int(label != "SAFE"), "label": label}
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in have.values()),
                     encoding="utf-8")
    return new, len(have)


# ── model fetch ──────────────────────────────────────────────────────────────
def fetch_model(remote, version: str, work: Path) -> Path:
    dest = work / "models" / version
    manifest_path = dest / "manifest.json"
    dest.mkdir(parents=True, exist_ok=True)
    if not remote.get(f"models/{version}/manifest.json", manifest_path):
        raise SystemExit(f"Modell {version} hat kein manifest.json auf dem Server.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for name, digest in manifest["files"].items():
        target = dest / name
        if target.exists() and T.sha256(target) == digest:
            continue
        say(f"  lade {name} ...")
        if not remote.get(f"models/{version}/{name}", target) or T.sha256(target) != digest:
            raise SystemExit(f"{name}: Download fehlerhaft (Prüfsumme) - abgebrochen.")
    return dest


def resolve_start(src: str, remote, work: Path) -> tuple[str, str, dict | None]:
    """-> (model path/hub id, version label, manifest metrics or None)"""
    if src == "base":
        return T.BASE_MODEL, "base", None
    if src not in ("newest", "active"):
        p = Path(src).expanduser()
        if not (p / "config.json").exists():
            raise SystemExit(f"{p} ist kein Modellordner.")
        return str(p), p.name, None
    versions = sorted(v for v in remote.listdir("models")
                      if v[:1].isdigit() and not v.endswith((".partial", ".tmp")))
    version = None
    if src == "active" or not versions:
        if remote.get("models/active.json", work / "active.json"):
            version = json.loads((work / "active.json").read_text()).get("version")
    else:
        version = versions[-1]
    if not version:
        say("  Kein Modell auf dem Server - starte vom Basis-Modell.")
        return T.BASE_MODEL, "base", None
    say(f"  Modell auf dem Server: {version}")
    path = fetch_model(remote, version, work)
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    return str(path), version, manifest.get("metrics")


# ── live view ────────────────────────────────────────────────────────────────
def gpu_stats() -> str:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw",
             "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=3).stdout.strip()
        util, used, total, temp, power = [x.strip() for x in out.splitlines()[0].split(",")]
        return f"GPU {util}% · VRAM {int(used)/1024:.1f}/{int(total)/1024:.1f} GB · {temp}°C · {float(power):.0f} W"
    except Exception:
        return "GPU: keine Daten (nvidia-smi nicht verfügbar)"


def fmt_t(sec: float) -> str:
    sec = int(max(sec, 0))
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


class LiveTrainView:
    """Progress callback for train.train(): rich live panel, or a plain line every 25 steps."""

    def __init__(self, title: str, batch_size: int):
        self.title, self.bs = title, batch_size
        self.t0 = time.time()
        self.losses: collections.deque = collections.deque(maxlen=48)
        self.ema = None
        self.best = float("inf")
        self.gpu, self.gpu_t = "", 0.0
        self.live = Live(refresh_per_second=4, transient=False) if HAVE_RICH else None
        self.last = None

    def __enter__(self):
        if self.live:
            self.live.__enter__()
        return self

    def __exit__(self, *exc):
        if self.live:
            if self.last:
                self.live.update(self._render(*self.last))
            self.live.__exit__(*exc)

    def __call__(self, epoch, step, steps, loss, lr):
        self.ema = loss if self.ema is None else 0.95 * self.ema + 0.05 * loss
        self.best = min(self.best, self.ema)
        self.losses.append(loss)
        if time.time() - self.gpu_t > 3:
            self.gpu, self.gpu_t = gpu_stats(), time.time()
        self.last = (epoch, step, steps, loss, lr)
        if self.live:
            self.live.update(self._render(*self.last))
        elif step % 25 == 0 or step == steps:
            say(f"  Schritt {step}/{steps} loss {loss:.4f} (Ø {self.ema:.4f}) lr {lr:.2e}")

    def _render(self, epoch, step, steps, loss, lr):
        el = time.time() - self.t0
        rate = step / el if el else 0.0
        eta = (steps - step) / rate if rate else 0.0
        lo, hi = min(self.losses), max(self.losses)
        spark = "".join(SPARK[int((v - lo) / (hi - lo + 1e-9) * (len(SPARK) - 1))] for v in self.losses)
        t = Table.grid(padding=(0, 2))
        t.add_column(style="dim")
        t.add_column()
        t.add_row("Fortschritt", Group(ProgressBar(total=steps, completed=step, width=46),
                                       Text(f"{step}/{steps}  ({step / steps:.0%})")))
        t.add_row("Epoche", f"{epoch}")
        t.add_row("Loss", f"{loss:.4f}   Ø {self.ema:.4f}   best Ø {self.best:.4f}")
        t.add_row("Verlauf", Text(spark, style="cyan"))
        t.add_row("Lernrate", f"{lr:.2e}")
        t.add_row("Tempo", f"{rate:.2f} Schritte/s · {rate * self.bs:.0f} Beispiele/s")
        t.add_row("Zeit", f"{fmt_t(el)} vergangen · noch ~{fmt_t(eta)}")
        t.add_row("Hardware", self.gpu)
        return Panel(t, title=self.title, border_style="cyan")


def phase(n: int, total: int, text: str) -> None:
    say(f"\n\033[1m[{n}/{total}] {text}\033[0m" if sys.stdout.isatty() else f"\n[{n}/{total}] {text}")


# ── main ─────────────────────────────────────────────────────────────────────
def main() -> None:
    ap = argparse.ArgumentParser(description="Continue training the Baxi chatfilter model")
    ap.add_argument("--samples", nargs="*", default=[], help="labelled export(s) from the dash "
                    "(default: newest ~/Downloads/safetext_labelled*)")
    ap.add_argument("--from", dest="start", default="newest",
                    help="newest (default) | active | base | <model folder>")
    ap.add_argument("--config", default=str(HERE / "config.toml"))
    ap.add_argument("--local", help="local folder mirroring the server's data/safetext")
    ap.add_argument("--work", help="work dir (default ~/.cache/baxi-safetext-trainer)")
    ap.add_argument("--epochs", type=int)
    ap.add_argument("--lr", type=float)
    ap.add_argument("--batch-size", type=int)
    ap.add_argument("--force", action="store_true", help="allow upload although the gate failed")
    ap.add_argument("--no-upload", action="store_true", help="train + evaluate only")
    args = ap.parse_args()

    cfg_file = Path(args.config)
    cfg = tomllib.loads(cfg_file.read_text(encoding="utf-8")) if cfg_file.exists() else {}
    tcfg = {**DEFAULTS, **cfg.get("training", {})}
    for key, val in (("epochs", args.epochs), ("learning_rate", args.lr), ("batch_size", args.batch_size)):
        if val:
            tcfg[key] = val
    work = Path(args.work or cfg.get("work_dir") or Path.home() / ".cache" / "baxi-safetext-trainer")
    work = work.expanduser().resolve()
    work.mkdir(parents=True, exist_ok=True)
    store = work / "retrain" / "labels.jsonl"
    state_file = work / "retrain" / "state.json"
    state = json.loads(state_file.read_text()) if state_file.exists() else {"trained": {}}
    total = 6

    phase(1, total, "Startmodell holen")
    remote = None
    if args.start in ("newest", "active") or not args.no_upload:
        if not cfg and not args.local:
            if args.start in ("newest", "active"):
                raise SystemExit(f"Keine Server-Config ({cfg_file}). Mit --from base / --from <ordner> "
                                 "geht es auch ohne Server (dann ohne Upload).")
        else:
            remote = connect(cfg, args.local)
    try:
        start_path, start_ver, start_metrics = resolve_start(args.start, remote, work)
        say(f"  Startmodell: {start_ver}")

        phase(2, total, "Samples einlesen")
        files = find_exports(args.samples)
        for f in files:
            say(f"  {f}")
        new, n_all = update_store(store, files)
        labels = T._jsonl(store)
        train_all = [r for r in labels if not T.is_holdout(r["key"])]
        hold = [r for r in labels if T.is_holdout(r["key"])]
        seen = set(state["trained"].get(start_ver, []))
        fresh = [r for r in train_all if r["key"] not in seen]
        old = [r for r in train_all if r["key"] in seen]
        say(f"  Label-Speicher: {n_all} ({new} neu aus dieser Datei) · "
            f"Training {len(train_all)} · Test {len(hold)}")
        say(f"  für {start_ver} neu: {len(fresh)} · schon gelernt: {len(old)} · "
            f"nicht okay: {sum(r['y'] for r in labels)}/{len(labels)}")
        if len(fresh) < tcfg["min_new_labels"]:
            raise SystemExit(f"Nur {len(fresh)} neue Labels (Minimum {tcfg['min_new_labels']}). "
                             "Erst mehr labeln oder --from base für ein Training auf allen Labels.")
        holdout = work / "holdout.jsonl"
        holdout.write_text("".join(json.dumps({"text": r["text"], "expect": "remove" if r["y"] else "keep"},
                                              ensure_ascii=False) + "\n" for r in hold), encoding="utf-8")

        phase(3, total, "Trainingsdaten mischen")
        rng = random.Random(13)
        rehearse = rng.sample(old, min(len(old), int(len(fresh) * tcfg["rehearsal_ratio"])))
        own = fresh + rehearse
        replay = T.replay_rows(work, max(2000, tcfg["replay_factor"] * len(own)))
        rows = [{"text": r["text"], "y": r["y"]} for r in own] * tcfg["new_label_weight"] + replay
        say(f"  {len(rows)} Beispiele: {len(fresh)} neue + {len(rehearse)} Wiederholung "
            f"(x{tcfg['new_label_weight']}) + {len(replay)} Replay")

        phase(4, total, f"Training ({tcfg['epochs']} Epochen, lr {tcfg['learning_rate']:g})")
        version = time.strftime("%Y%m%d-%H%M")
        cand_dir = work / "candidates" / version
        steps_title = f"{start_ver} → {version}"
        with LiveTrainView(steps_title, tcfg["batch_size"]) as view:
            T.train(rows, cand_dir, tcfg, base_model=start_path, progress=view)
        say(f"  Kandidat gespeichert: {cand_dir}")

        phase(5, total, "Auswertung (Startmodell vs. neues Modell)")
        ref = T.evaluate(start_path, work, holdout, "Startmodell")
        cand = T.evaluate(str(cand_dir), work, holdout, "neues Modell")
        say("\n(Spalte 'Basis' = Startmodell)")
        T.report(ref, cand, start_metrics)
        T.changed_examples(ref, cand)
        problems = T.gate(ref["metrics"], cand["metrics"])
        if problems:
            say("\nNICHT BESTANDEN - das neue Modell ist schlechter bei:")
            for p in problems:
                say(f"  - {p}")
        else:
            say("\nBESTANDEN - nirgends schlechter als das Startmodell.")

        phase(6, total, "Hochladen")
        if args.no_upload or remote is None:
            say(f"  Übersprungen. Kandidat: {cand_dir}")
        elif problems and not args.force:
            say(f"  Nichts hochgeladen. Kandidat liegt in {cand_dir}.")
        else:
            if input(f"\nVersion {version} hochladen und aktivieren? [j/N] ").strip().lower() \
                    not in ("j", "ja", "y", "yes"):
                say(f"Abgebrochen. Kandidat liegt in {cand_dir}.")
            else:
                T.upload(remote, cand_dir, version, cand["metrics"], len(labels), work, tcfg["keep_versions"])
                # the new model also inherits everything its start model had learned
                state["trained"] = {version: sorted({r["key"] for r in own} | seen)}
                state_file.write_text(json.dumps(state), encoding="utf-8")
    finally:
        if remote is not None:
            remote.close()


if __name__ == "__main__":
    main()
