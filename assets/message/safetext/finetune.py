"""LoRA fine-tuning runner for the multilingual toxic classifier.

Two entry points:

  * `await start_job()` — non-blocking: spawns this module as a subprocess so
    the bot process stays responsive during training.
  * `python -m assets.message.safetext.finetune` — synchronous training run;
    used both by the async entry point and for manual runs.

Only toxic/hate feedback is consumed here. Doxxing, suicide keywords, NSFW
and phishing are rule-based and out of scope.

Status is written to `data/safetext/finetune_status.json` so the dashboard
can poll progress.
"""
import asyncio
import json
import os
import sys
import time
from collections import deque
from pathlib import Path
from typing import Optional

from reds_simple_logger import Logger

logger = Logger()

STATUS_FILE = Path("data/safetext/finetune_status.json")
LORA_DIR    = Path("data/safetext/model/lora")
MIN_SAMPLES = 8

TOXIC_MODEL   = "unitary/multilingual-toxic-xlm-roberta"
TOXIC_LABELS  = ["toxic", "severe_toxic", "obscene", "threat", "insult", "identity_hate"]


# ── status helpers ───────────────────────────────────────────────────────────
def _write_status(data: dict) -> None:
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATUS_FILE.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    tmp.replace(STATUS_FILE)


def read_status() -> dict:
    if not STATUS_FILE.exists():
        return {"state": "idle"}
    try:
        with STATUS_FILE.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {"state": "unknown"}


# ── label mapping ────────────────────────────────────────────────────────────
def _labels_for(correct: str) -> Optional[list[float]]:
    """Return target vector for the toxic head, or None to skip this sample."""
    c = (correct or "").strip().upper()
    if c == "SAFE":
        return [0.0] * len(TOXIC_LABELS)
    mapping = {
        "2": {"toxic": 1.0, "insult": 1.0},
        "3": {"toxic": 1.0, "identity_hate": 1.0},
    }
    c = c.removeprefix("AI-")
    if c not in mapping:
        return None
    vec = [0.0] * len(TOXIC_LABELS)
    for label, val in mapping[c].items():
        vec[TOXIC_LABELS.index(label)] = val
    return vec


# ── async launcher ───────────────────────────────────────────────────────────
async def start_job() -> dict:
    """Spawn the trainer in a subprocess. Returns immediately."""
    status = read_status()
    if status.get("state") == "running":
        return {"ok": False, "error": "already running"}

    _write_status({"state": "starting", "started_at": int(time.time())})

    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "assets.message.safetext.finetune",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )

    asyncio.create_task(_wait_and_log(proc))
    return {"ok": True, "pid": proc.pid}


async def _wait_and_log(proc: asyncio.subprocess.Process) -> None:
    assert proc.stdout is not None
    tail: deque[str] = deque(maxlen=60)
    async for line in proc.stdout:
        text = line.decode(errors="ignore").rstrip()
        tail.append(text)
        if any(kw in text for kw in ("Error", "Traceback", "Exception", "error:")):
            logger.error(f"SafeText finetune | {text}")
        else:
            logger.info(f"SafeText finetune | {text}")
    rc = await proc.wait()
    if rc != 0:
        logger.error(f"SafeText finetune | exited with code {rc}")
        cur = read_status()
        cur["state"] = "error"
        cur["error"] = f"subprocess exit {rc}"
        cur["last_output"] = list(tail)
        _write_status(cur)
    else:
        try:
            from assets.message.safetext.models import reload_models
            reload_models()
        except Exception:
            pass


# ── synchronous training ─────────────────────────────────────────────────────
def _train_sync() -> dict:
    from assets.message.safetext.feedback import list_entries, mark_all_trained

    entries = list_entries(only_untrained=True)

    # Only rows we can actually supervise the toxic head with.
    samples: list[tuple[str, list[float]]] = []
    for e in entries:
        vec = _labels_for(str(e.get("correct_label", "")))
        if vec is None:
            continue
        msg = str(e.get("message", "")).strip()
        if not msg:
            continue
        samples.append((msg, vec))

    if len(samples) < MIN_SAMPLES:
        _write_status({
            "state":      "skipped",
            "finished_at": int(time.time()),
            "reason":     f"need {MIN_SAMPLES} usable samples, have {len(samples)}",
            "samples":    len(samples),
        })
        return {"ok": False, "reason": "not enough samples", "samples": len(samples)}

    _write_status({"state": "running", "started_at": int(time.time()),
                   "samples": len(samples)})

    import torch
    from torch.utils.data import Dataset
    from transformers import (
        AutoModelForSequenceClassification,
        AutoTokenizer,
        Trainer,
        TrainingArguments,
    )
    from peft import LoraConfig, TaskType, get_peft_model

    tokenizer = AutoTokenizer.from_pretrained(TOXIC_MODEL)
    model     = AutoModelForSequenceClassification.from_pretrained(
        TOXIC_MODEL, problem_type="multi_label_classification"
    )

    lora_cfg = LoraConfig(
        task_type=TaskType.SEQ_CLS,
        r=8, lora_alpha=16, lora_dropout=0.05,
        target_modules=["query", "value"],
    )
    model = get_peft_model(model, lora_cfg)
    model.print_trainable_parameters()

    class FB(Dataset):
        def __init__(self, rows): self.rows = rows
        def __len__(self): return len(self.rows)
        def __getitem__(self, i):
            msg, vec = self.rows[i]
            enc = tokenizer(msg, truncation=True, max_length=256, padding="max_length",
                            return_tensors="pt")
            return {
                "input_ids":      enc["input_ids"].squeeze(0),
                "attention_mask": enc["attention_mask"].squeeze(0),
                "labels":         torch.tensor(vec, dtype=torch.float),
            }

    dataset = FB(samples)
    args = TrainingArguments(
        output_dir=str(LORA_DIR.parent / "train_out"),
        num_train_epochs=4,
        per_device_train_batch_size=4,
        learning_rate=5e-4,
        logging_steps=5,
        save_strategy="no",
        report_to="none",
        disable_tqdm=True,
    )
    trainer = Trainer(model=model, args=args, train_dataset=dataset)
    trainer.train()

    LORA_DIR.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(LORA_DIR))
    tokenizer.save_pretrained(str(LORA_DIR))

    flipped = mark_all_trained()

    _write_status({
        "state":       "done",
        "finished_at": int(time.time()),
        "samples":     len(samples),
        "flipped":     flipped,
        "lora_dir":    str(LORA_DIR),
    })
    return {"ok": True, "samples": len(samples), "flipped": flipped}


if __name__ == "__main__":
    # ensure project root is importable when launched via -m
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    os.chdir(Path(__file__).resolve().parents[3])
    try:
        result = _train_sync()
        print(json.dumps(result))
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print(tb, file=sys.stderr)
        try:
            _write_status({"state": "error", "finished_at": int(time.time()),
                           "error": str(e), "traceback": tb})
        except Exception:
            pass
        sys.exit(1)
