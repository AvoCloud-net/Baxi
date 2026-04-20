"""Admin feedback store for SafeText classifications.

Entries here drive LoRA fine-tuning of the toxic model. Each record captures
the original message, what the model said, and the admin-corrected label.
"""
import asyncio
import json
import time
from pathlib import Path
from typing import Optional

from reds_simple_logger import Logger

from assets.message.safetext.logstore import LOG_FILE, read_recent

logger = Logger()

FEEDBACK_FILE = Path("data/safetext/feedback.jsonl")
_lock = asyncio.Lock()


async def submit(
    *,
    log_id: str,
    message: str,
    model_said: str,
    correct_label: str,
    admin: str,
    reason: Optional[str] = None,
) -> dict:
    """Append a correction. Returns {"ok": True, "count": N, "untrained": U}."""
    entry = {
        "ts":            int(time.time()),
        "log_id":        log_id,
        "message":       message,
        "model_said":    model_said,
        "correct_label": correct_label,
        "admin":         admin,
        "reason":        reason or "",
        "trained":       False,
    }

    async with _lock:
        FEEDBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
        with FEEDBACK_FILE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    all_entries = _read_all()
    untrained = sum(1 for e in all_entries if not e.get("trained"))
    logger.info(
        f"SafeText feedback | log={log_id} model={model_said} "
        f"correct={correct_label} admin={admin} total={len(all_entries)} "
        f"untrained={untrained}"
    )
    return {"ok": True, "count": len(all_entries), "untrained": untrained}


def _read_all() -> list[dict]:
    if not FEEDBACK_FILE.exists():
        return []
    out: list[dict] = []
    try:
        with FEEDBACK_FILE.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError as e:
        logger.error(f"SafeText feedback read failed: {e}")
    return out


def list_entries(only_untrained: bool = False) -> list[dict]:
    entries = _read_all()
    if only_untrained:
        entries = [e for e in entries if not e.get("trained")]
    return entries


def stats() -> dict:
    entries = _read_all()
    return {
        "total":     len(entries),
        "untrained": sum(1 for e in entries if not e.get("trained")),
    }


def mark_all_trained() -> int:
    """Flip trained=True for all entries. Returns count flipped."""
    entries = _read_all()
    changed = 0
    for e in entries:
        if not e.get("trained"):
            e["trained"] = True
            changed += 1
    tmp = FEEDBACK_FILE.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for e in entries:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    tmp.replace(FEEDBACK_FILE)
    return changed
