"""Admin feedback store for SafeText classifications.

Each record captures the original message, what the pipeline said, and the
admin-corrected label. Corrections act as exact-match overrides (see
`override_for`) and are kept as a labelled dataset for evaluating or
fine-tuning future models offline.

Corrections by a server's own moderators (guild_id set) stay with that server:
they live in GUILD_FEEDBACK_FILE, which the offline trainer never downloads (it
fetches feedback.jsonl from data/safetext). Older guild entries that were written
to feedback.jsonl are moved over once per process (_split_legacy).
"""
import asyncio
import json
import threading
import time
from pathlib import Path
from typing import Optional

from reds_simple_logger import Logger

logger = Logger()

FEEDBACK_FILE = Path("data/safetext/feedback.jsonl")
GUILD_FEEDBACK_FILE = Path("data/safetext/feedback_guild.jsonl")
_lock = asyncio.Lock()
_split_lock = threading.Lock()
_split_done = False


def _split_legacy() -> None:
    """Move guild-scoped entries out of feedback.jsonl (once per process)."""
    global _split_done
    if _split_done:
        return
    with _split_lock:
        if _split_done:
            return
        _split_done = True
        entries = _read_file(FEEDBACK_FILE)
        guild = [e for e in entries if e.get("guild_id")]
        if not guild:
            return
        try:
            GUILD_FEEDBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
            with GUILD_FEEDBACK_FILE.open("a", encoding="utf-8") as fh:
                for e in guild:
                    fh.write(json.dumps(e, ensure_ascii=False) + "\n")
            tmp = FEEDBACK_FILE.with_suffix(".tmp")
            with tmp.open("w", encoding="utf-8") as fh:
                for e in entries:
                    if not e.get("guild_id"):
                        fh.write(json.dumps(e, ensure_ascii=False) + "\n")
            tmp.replace(FEEDBACK_FILE)
            logger.info(f"SafeText feedback | moved {len(guild)} server-only corrections out of feedback.jsonl")
        except OSError as e:
            logger.error(f"SafeText feedback | split failed: {e}")


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

    _split_legacy()
    target = GUILD_FEEDBACK_FILE if guild_id is not None else FEEDBACK_FILE
    async with _lock:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as fh:
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
    """Network-wide and server-only corrections together (for overrides and the
    admin panel - never what the trainer downloads)."""
    _split_legacy()
    return _read_file(FEEDBACK_FILE) + _read_file(GUILD_FEEDBACK_FILE)


def _read_file(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
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
_overrides_mtime: tuple | None = None


def _mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def override_for(key: str, guild_id: int | None = None) -> Optional[str]:
    """Confirmed label ("SAFE" or "1".."5") for a normalised message key.

    Corrections apply immediately and exactly: once a message is marked safe (or
    harmful), the same message - in any spelling that normalises to the same key -
    gets that verdict. A server's own correction beats a network-wide one; within
    a scope the newest correction wins."""
    global _overrides, _overrides_mtime
    _split_legacy()
    mtime = (_mtime(FEEDBACK_FILE), _mtime(GUILD_FEEDBACK_FILE))
    if mtime == (None, None):
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

