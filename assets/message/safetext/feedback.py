"""Admin feedback store for SafeText classifications.

Each record captures the original message, what the pipeline said, and the
admin-corrected label. Corrections act as exact-match overrides (see
`override_for`) and are kept as a labelled dataset for evaluating or
fine-tuning future models offline.
"""
import asyncio
import json
import time
from pathlib import Path
from typing import Optional

from reds_simple_logger import Logger

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
    guild_id: Optional[int] = None,
) -> dict:
    """Append a correction. Returns {"ok": True, "count": N, "untrained": U}.

    *guild_id*: corrections from a server's own moderators only apply to that
    server. Without it (bot admins) the correction applies network-wide."""
    entry = {
        "ts":            int(time.time()),
        "log_id":        log_id,
        "message":       message,
        "model_said":    model_said,
        "correct_label": correct_label,
        "admin":         admin,
        "reason":        reason or "",
        "trained":       False,
        "guild_id":      str(guild_id) if guild_id is not None else None,
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


_overrides: dict[tuple[str | None, str], str] = {}
_overrides_mtime: float | None = None


def override_for(key: str, guild_id: int | None = None) -> Optional[str]:
    """Confirmed label ("SAFE" or "1".."5") for a normalised message key.

    Corrections apply immediately and exactly: once a message is marked safe (or
    harmful), the same message - in any spelling that normalises to the same key -
    gets that verdict. A server's own correction beats a network-wide one; within
    a scope the newest correction wins."""
    global _overrides, _overrides_mtime
    try:
        mtime = FEEDBACK_FILE.stat().st_mtime
    except OSError:
        return None
    if mtime != _overrides_mtime:
        from assets.message.safetext.normalize import normalize
        table: dict[str, str] = {}
        for e in _read_all():
            msg = str(e.get("message", "")).strip()
            label = str(e.get("correct_label", "")).strip().upper().removeprefix("AI-")
            if msg and label in {"SAFE", "1", "2", "3", "4", "5"}:
                table[(e.get("guild_id"), normalize(msg).key)] = label
        _overrides, _overrides_mtime = table, mtime
    if guild_id is not None and (hit := _overrides.get((str(guild_id), key))):
        return hit
    return _overrides.get((None, key))


def override_count() -> int:
    override_for("")  # refresh the table if the file changed
    return len(_overrides)


def stats() -> dict:
    entries = _read_all()
    return {
        "total":     len(entries),
        "untrained": sum(1 for e in entries if not e.get("trained")),
    }

