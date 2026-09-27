"""SafeText classification log (append-only JSONL).

Only written for guilds that enabled the chatfilter (or the global chat). The raw
message is kept only when it is relevant for admin review - flagged, support
case, or a toxicity score of at least REVIEW_SCORE - everything else is stored
as a SHA-256 prefix (DSGVO data minimisation).

Set the env var `SAFETEXT_LOG_RAW=1` to store every raw message (dev only).
"""
import hashlib
import json
import os
import time
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Optional

from reds_simple_logger import Logger

logger = Logger()

LOG_FILE = Path("data/safetext/log.jsonl")
MAX_LINES = 10_000  # rotate when exceeded
REVIEW_SCORE = 0.30
_LOG_RAW = os.environ.get("SAFETEXT_LOG_RAW") == "1"
_ROTATE_EVERY = 500  # check file length every N writes, not on every message
_write_lock = Lock()
_writes_since_rotate = 0


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _entry_id() -> str:
    return f"{int(time.time() * 1000):x}"


def record(
    *,
    gid: int,
    user_id: int,
    stage: str,
    flagged: bool,
    result: Dict[str, Any],
    confidence: Optional[float],
    message: Optional[str] = None,
) -> str:
    """Append one entry to log.jsonl. Returns the entry id."""
    entry_id = _entry_id()
    entry = {
        "id":         entry_id,
        "ts":         int(time.time()),
        "gid":        gid,
        "user_id":    user_id,
        "stage":      stage,
        "flagged":    flagged,
        "confidence": confidence,
        "result":     result,
    }
    if message is not None:
        entry["msg_hash"] = _hash(message)
        review_worthy = flagged or bool(result.get("support")) or (confidence or 0.0) >= REVIEW_SCORE
        if _LOG_RAW or review_worthy:
            entry["message"] = message

    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        global _writes_since_rotate
        with _write_lock:
            with LOG_FILE.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            _writes_since_rotate += 1
            if _writes_since_rotate >= _ROTATE_EVERY:
                _writes_since_rotate = 0
                _rotate_if_needed()
    except OSError as e:
        logger.error(f"SafeText log write failed: {e}")

    return entry_id


def _rotate_if_needed() -> None:
    try:
        with LOG_FILE.open("r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError:
        return
    if len(lines) <= MAX_LINES:
        return
    keep = lines[-MAX_LINES:]
    tmp = LOG_FILE.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        fh.writelines(keep)
    tmp.replace(LOG_FILE)


def read_recent(limit: int = 200, guild_id: Optional[int] = None) -> list[dict]:
    """Return the most recent entries (newest first), optionally guild-filtered."""
    if not LOG_FILE.exists():
        return []
    try:
        with LOG_FILE.open("r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError as e:
        logger.error(f"SafeText log read failed: {e}")
        return []

    out: list[dict] = []
    for raw in reversed(lines):
        try:
            item = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if guild_id is not None and item.get("gid") != guild_id:
            continue
        out.append(item)
        if len(out) >= limit:
            break
    return out
