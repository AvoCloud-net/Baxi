"""Offline trainer for the Baxi chatfilter model (runs on a machine with a GPU).

    python tools/safetext_trainer/train.py              # uses tools/safetext_trainer/config.toml
    python tools/safetext_trainer/train.py --local DIR  # DIR mirrors the server's data/safetext

1. download the admin labels (samples.jsonl, labels.jsonl, feedback.jsonl) from the server
2. build a dataset: labelled samples + a replay slice of the model's original
   training data (so it does not forget what it already knows); every 5th label
   is held out for testing and never trained on
3. fine-tune the base model with LoRA, merge -> same size and speed as before
4. evaluate base model and candidate through the full chatfilter pipeline
5. print the comparison; upload + activate only after you confirm - and only if
   the candidate is not worse anywhere (--force overrides the gate)

Always trains from the base model on *all* labels, so every version is
reproducible and errors never accumulate across versions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import subprocess
import sys
import time
import tomllib
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from remote import connect  # noqa: E402

BASE_MODEL = "textdetox/xlmr-large-toxicity-classifier"
REPLAY_URL = "https://huggingface.co/datasets/textdetox/multilingual_toxicity_dataset/resolve/main/data/{lang}-00000-of-00001.parquet"
TOXIC_LABELS = {"1", "2", "3", "5"}     # "4" (personal data) is a rule, not toxicity
GATE_FP = 0.5      # candidate may raise a false-positive rate by at most this (points)
GATE_RECALL = 1.0  # ... and lower a recall by at most this
DEFAULTS = {"min_new_labels": 50, "epochs": 2, "batch_size": 16, "learning_rate": 2e-4,
            "lora_r": 16, "max_len": 128, "replay_factor": 4, "new_label_weight": 3,
            "keep_versions": 3}


def say(msg: str = "") -> None:
    print(msg, flush=True)


# ── data ─────────────────────────────────────────────────────────────────────
def _jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def build_labels(data: Path) -> list[dict]:
    """Admin labels -> [{text, y, key}], newest label per normalised message wins."""
    from assets.message.safetext.normalize import normalize

    samples = {s["id"]: s for s in _jsonl(data / "samples.jsonl")}
    by_key: dict[str, dict] = {}
    events = []
    for l in _jsonl(data / "labels.jsonl"):
        s = samples.get(str(l.get("id")))
        if s:
            events.append((l.get("ts", 0), s["text"], str(l.get("label", "")).upper()))
    for f in _jsonl(data / "feedback.jsonl"):
        log_id = str(f.get("log_id", ""))
        # bot-admin corrections only: guild-moderator reviews stay guild overrides
        if f.get("guild_id") or log_id.startswith(("review:", "sample:")):
            continue
        events.append((f.get("ts", 0), str(f.get("message", "")),
                       str(f.get("correct_label", "")).upper().removeprefix("AI-")))
    for ts, text, label in sorted(events):
        if not text.strip() or label not in TOXIC_LABELS | {"SAFE"}:
            continue
        key = normalize(text).key
        by_key[key] = {"text": text, "y": int(label != "SAFE"), "key": key}
    return list(by_key.values())


def is_holdout(key: str) -> bool:
    return int(hashlib.sha1(key.encode("utf-8")).hexdigest(), 16) % 5 == 0


def replay_rows(work: Path, n: int, seed: int = 13) -> list[dict]:
    import pandas as pd
    rows = []
    for lang in ("de", "en"):
        path = work / f"replay_{lang}.parquet"
        if not path.exists():
            say(f"  lade Replay-Daten ({lang}) ...")
            urllib.request.urlretrieve(REPLAY_URL.format(lang=lang), path)
        df = pd.read_parquet(path)
        rows += [{"text": str(t), "y": int(y)} for t, y in zip(df["text"], df["toxic"])]
    random.Random(seed).shuffle(rows)
    return rows[:n]


# ── training ─────────────────────────────────────────────────────────────────
def train(rows: list[dict], out_dir: Path, cfg: dict) -> None:
    import torch
    from peft import LoraConfig, TaskType, get_peft_model
    from transformers import (AutoModelForSequenceClassification, AutoTokenizer,
                              get_linear_schedule_with_warmup)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cpu":
        say("  WARNUNG: keine GPU gefunden - Training auf der CPU dauert sehr lange.")
    torch.manual_seed(13)
    tok = AutoTokenizer.from_pretrained(BASE_MODEL)
    model = AutoModelForSequenceClassification.from_pretrained(BASE_MODEL)
    model = get_peft_model(model, LoraConfig(
        task_type=TaskType.SEQ_CLS, r=cfg["lora_r"], lora_alpha=2 * cfg["lora_r"],
        lora_dropout=0.1, target_modules=r".*encoder.*\.(query|key|value|dense)$",
    )).to(device)

    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=cfg["learning_rate"], weight_decay=0.01)
    steps = cfg["epochs"] * ((len(rows) + cfg["batch_size"] - 1) // cfg["batch_size"])
    sched = get_linear_schedule_with_warmup(opt, int(0.06 * steps), steps)
    use_amp = device == "cuda"
    scaler = torch.amp.GradScaler("cuda", enabled=use_amp)

    model.train()
    step = 0
    for epoch in range(cfg["epochs"]):
        random.Random(epoch).shuffle(rows)
        for i in range(0, len(rows), cfg["batch_size"]):
            batch = rows[i:i + cfg["batch_size"]]
            enc = tok([r["text"] for r in batch], return_tensors="pt", truncation=True,
                      max_length=cfg["max_len"], padding=True).to(device)
            labels = torch.tensor([r["y"] for r in batch], device=device)
            with torch.autocast(device_type=device, dtype=torch.float16, enabled=use_amp):
                loss = torch.nn.functional.cross_entropy(model(**enc).logits.float(), labels)
            opt.zero_grad(set_to_none=True)
            scaler.scale(loss).backward()
            scaler.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(params, 1.0)
            scaler.step(opt)
            scaler.update()
            sched.step()
            step += 1
            if step % 50 == 0 or step == steps:
                say(f"  Epoche {epoch + 1}/{cfg['epochs']}  Schritt {step}/{steps}  loss {loss.item():.4f}")

    merged = model.merge_and_unload().to("cpu").eval()
    out_dir.mkdir(parents=True, exist_ok=True)
    merged.save_pretrained(out_dir, safe_serialization=True)
    tok.save_pretrained(out_dir)


# ── evaluation ───────────────────────────────────────────────────────────────
def evaluate(model: str, work: Path, holdout: Path, name: str) -> dict:
    out = work / f"eval_{name}.json"
    say(f"\nMesse {name} ...")
    subprocess.run([sys.executable, str(HERE / "evaluate.py"), "--model", model,
                    "--work", str(work), "--holdout", str(holdout), "--out", str(out)],
                   check=True)
    return json.loads(out.read_text(encoding="utf-8"))


def gate(ref: dict, cand: dict) -> list[str]:
    """Problems that make the candidate worse than *ref*."""
    problems = []
    for name in ("hatecheck_de", "hatecheck_en", "discord", "holdout"):
        r, c = ref.get(name), cand.get(name)
        if not r or not c or (name == "holdout" and c["n"] < 30):
            continue
        if c["fp_rate"] > r["fp_rate"] + GATE_FP:
            problems.append(f"{name}: falsch gelöscht {r['fp_rate']}% -> {c['fp_rate']}%")
        if c["recall"] < r["recall"] - GATE_RECALL:
            problems.append(f"{name}: erkannt {r['recall']}% -> {c['recall']}%")
    return problems


def report(base: dict, cand: dict, active: dict | None) -> None:
    say("\n" + "=" * 86)
    say(f"{'Testsatz':14} {'':10} {'Basis':>9} {'Aktiv':>9} {'NEU':>9} {'Diff':>8}")
    say("-" * 86)
    labels = {"hatecheck_de": "HateCheck DE", "hatecheck_en": "HateCheck EN",
              "discord": "Discord-Satz", "holdout": "Eure Labels"}
    for name, label in labels.items():
        b, c = base["metrics"].get(name), cand["metrics"].get(name)
        if not c:
            continue
        a = (active or {}).get(name)
        for key, text, good in (("recall", "erkannt", 1), ("fp_rate", "falsch gel.", -1)):
            diff = c[key] - b[key]
            mark = "  " if abs(diff) < 0.05 else ("✓ " if diff * good > 0 else "✗ ")
            av = f"{a[key]:8.1f}%" if a else f"{'–':>9}"
            say(f"{label if key == 'recall' else '':14} {text:10} {b[key]:8.1f}% {av} {c[key]:8.1f}% "
                f"{mark}{diff:+.1f}")
        if name == "holdout":
            say(f"{'':14} ({c['n']} Labels, nie trainiert)")
    say("=" * 86)


def changed_examples(base: dict, cand: dict, limit: int = 20) -> None:
    exp = {}
    for path in (HERE / "eval" / "discord.jsonl",):
        for c in _jsonl(path):
            exp[f"discord\t{c['text']}"] = c["expect"] == "remove"
    rows = []
    for k, new in cand["decisions"].items():
        old = base["decisions"].get(k)
        if old is None or old == new or not k.startswith(("discord\t", "holdout\t")):
            continue
        right = exp.get(k)
        tag = "" if right is None else (" ✓" if right == new else " ✗")
        rows.append(f"  {'jetzt gelöscht ' if new else 'jetzt erlaubt  '}{tag}  {k.split(chr(9), 1)[1][:90]}")
    if rows:
        say("\nGeänderte Entscheidungen (Discord-Satz / eure Labels):")
        for r in rows[:limit]:
            say(r)
        if len(rows) > limit:
            say(f"  ... und {len(rows) - limit} weitere")


# ── upload ───────────────────────────────────────────────────────────────────
def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def upload(remote, model_dir: Path, version: str, metrics: dict, n_labels: int,
           work: Path, keep: int) -> None:
    files = sorted(p for p in model_dir.iterdir() if p.is_file())
    manifest = {
        "version": version, "base_model": BASE_MODEL, "created_at": int(time.time()),
        "samples": n_labels, "metrics": metrics,
        "eval_suite": sha256(HERE / "eval" / "discord.jsonl")[:12],
        "files": {p.name: sha256(p) for p in files},
    }
    (model_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    partial = f"models/{version}.partial"
    remote.mkdir(partial)
    for p in files + [model_dir / "manifest.json"]:
        say(f"  lade hoch: {p.name} ({p.stat().st_size / 1e6:.0f} MB)")
        remote.put(p, f"{partial}/{p.name}")
        if remote.size(f"{partial}/{p.name}") != p.stat().st_size:
            raise SystemExit(f"Upload von {p.name} unvollständig - abgebrochen, nichts aktiviert.")
    remote.rename(partial, f"models/{version}")

    active_local = work / "active_current.json"
    previous = None
    if remote.get("models/active.json", active_local):
        previous = json.loads(active_local.read_text(encoding="utf-8")).get("version")
    remote.put_text(json.dumps({"version": version, "previous": previous,
                                "activated_at": int(time.time()), "activated_by": "trainer"},
                               indent=2), "models/active.json", work)
    say(f"\nAktiviert: {version} (vorher: {previous or 'Basis-Modell'}). "
        "Der Bot wechselt innerhalb einer Minute.")

    versions = [v for v in remote.listdir("models") if v not in ("active.json", "active.json.tmp")]
    protected = {version, previous}
    old = [v for v in sorted(versions, reverse=True) if v not in protected][max(0, keep - len(protected)):]
    for v in old:
        say(f"  entferne alte Version {v}")
        remote.rmtree(f"models/{v}")


# ── main ─────────────────────────────────────────────────────────────────────
def main() -> None:
    ap = argparse.ArgumentParser(description="Baxi chatfilter trainer")
    ap.add_argument("--config", default=str(HERE / "config.toml"))
    ap.add_argument("--local", help="local folder mirroring the server's data/safetext")
    ap.add_argument("--force", action="store_true", help="allow upload although the gate failed")
    ap.add_argument("--work", help="work dir for downloads and candidates (default: "
                                   "~/.cache/baxi-safetext-trainer - keep it out of synced folders)")
    args = ap.parse_args()

    cfg_file = Path(args.config)
    cfg = tomllib.loads(cfg_file.read_text(encoding="utf-8")) if cfg_file.exists() else {}
    if not cfg and not args.local:
        raise SystemExit(f"Keine Config gefunden: {cfg_file} (Vorlage: config.example.toml)")
    tcfg = {**DEFAULTS, **cfg.get("training", {})}
    work = Path(args.work or cfg.get("work_dir") or Path.home() / ".cache" / "baxi-safetext-trainer")
    work = work.expanduser().resolve()
    data = work / "data"
    data.mkdir(parents=True, exist_ok=True)

    say("Verbinde mit dem Server ...")
    remote = connect(cfg, args.local)
    try:
        for name in ("samples.jsonl", "labels.jsonl", "feedback.jsonl"):
            (data / name).unlink(missing_ok=True)
            ok = remote.get(name, data / name)
            say(f"  {name}: {'ok' if ok else 'nicht vorhanden'}")
        active_metrics = None
        if remote.get("models/active.json", data / "active.json"):
            active_version = json.loads((data / "active.json").read_text()).get("version")
            if active_version and remote.get(f"models/{active_version}/manifest.json",
                                             data / "active_manifest.json"):
                m = json.loads((data / "active_manifest.json").read_text())
                if m.get("eval_suite") == sha256(HERE / "eval" / "discord.jsonl")[:12]:
                    active_metrics = m.get("metrics")

        labels = build_labels(data)
        train_rows = [r for r in labels if not is_holdout(r["key"])]
        hold_rows = [r for r in labels if is_holdout(r["key"])]
        say(f"\nLabels: {len(labels)} (Training {len(train_rows)}, Test {len(hold_rows)}); "
            f"davon nicht okay: {sum(r['y'] for r in labels)}")
        if len(train_rows) < tcfg["min_new_labels"]:
            raise SystemExit(f"Zu wenige Labels für ein sinnvolles Training "
                             f"({len(train_rows)} < {tcfg['min_new_labels']}). Erst mehr labeln.")

        holdout = work / "holdout.jsonl"
        holdout.write_text("".join(json.dumps({"text": r["text"], "expect": "remove" if r["y"] else "keep"},
                                              ensure_ascii=False) + "\n" for r in hold_rows), encoding="utf-8")

        replay = replay_rows(work, max(2000, tcfg["replay_factor"] * len(train_rows)))
        rows = [{"text": r["text"], "y": r["y"]} for r in train_rows] * tcfg["new_label_weight"] + replay
        say(f"\nTrainiere auf {len(rows)} Beispielen ({len(train_rows)} eigene Labels "
            f"x{tcfg['new_label_weight']} + {len(replay)} Replay) ...")
        version = time.strftime("%Y%m%d-%H%M")
        cand_dir = work / "candidates" / version
        train(rows, cand_dir, tcfg)

        base = evaluate(BASE_MODEL, work, holdout, "Basis-Modell")
        cand = evaluate(str(cand_dir), work, holdout, "neues Modell")
        report(base, cand, active_metrics)
        changed_examples(base, cand)

        problems = gate(base["metrics"], cand["metrics"])
        if active_metrics:
            problems += [f"(vs. aktiv) {p}" for p in gate(active_metrics, cand["metrics"])]
        if problems:
            say("\nNICHT BESTANDEN - das neue Modell ist schlechter bei:")
            for p in problems:
                say(f"  - {p}")
            if not args.force:
                say(f"\nNichts hochgeladen. Kandidat liegt lokal in {cand_dir}.")
                return
        else:
            say("\nBESTANDEN - nirgends schlechter als das Vergleichsmodell.")

        answer = input(f"\nVersion {version} hochladen und aktivieren? [j/N] ").strip().lower()
        if answer not in ("j", "ja", "y", "yes"):
            say(f"Abgebrochen. Kandidat liegt lokal in {cand_dir}.")
            return
        upload(remote, cand_dir, version, cand["metrics"], len(labels), work, tcfg["keep_versions"])
    finally:
        remote.close()


if __name__ == "__main__":
    main()
