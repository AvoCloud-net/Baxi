"""AI chatfilter admin feedback -  local few-shot store.

Bot admins can mark chatfilter log entries as false/true positives from the
dashboard. Each correction is appended to `data/ai_feedback.json` (FIFO,
capped by config.Chatfilter.feedback_max_entries). The chatfilter injects the
stored examples into the AI prompt at inference time, so future decisions are
biased by the corrections without needing to retrain or touch a KB.
"""
import asyncio
import json
from pathlib import Path
from typing import List

import assets.data as datasys
import config.config as config
from assets.share import admin_log as _admin_log
from reds_simple_logger import Logger

logger = Logger()

_lock = asyncio.Lock()


def _path() -> Path:
    return Path(config.Chatfilter.feedback_file_path)


def load_feedback_entries() -> List[dict]:
    """Read the feedback list. Returns [] on any error / missing file."""
    try:
        with _path().open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return data
    except FileNotFoundError:
        return []
    except (json.JSONDecodeError, OSError) as e:
        logger.warn(f"AI feedback | failed to read store: {e}")
    return []


def _write_entries(entries: List[dict]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(entries, fh, ensure_ascii=False, indent=2)
    tmp.replace(path)


def build_fewshot_block(max_entries: int | None = None) -> str:
    """Render the stored corrections as a markdown few-shot block to prepend
    to the AI user content. Returns "" if there are no entries."""
    entries = load_feedback_entries()
    if not entries:
        return ""
    cap = max_entries if max_entries is not None else config.Chatfilter.feedback_max_entries
    recent = entries[-cap:]
    lines = ["## Admin-Corrected Examples", ""]
    for e in recent:
        msg     = (e.get("message") or "").replace("\n", " ").strip()
        correct = str(e.get("correct") or "").strip().upper() or "?"
        reason  = (e.get("reason") or "").strip()
        suffix  = f" ({reason})" if reason else ""
        lines.append(f"- {msg!r} -> {correct}{suffix}")
    lines.append("")
    return "\n".join(lines)


async def submit_ai_feedback(
    log_id: str,
    message: str,
    ai_said: str,
    correct: str,
    reason: str,
    admin_name: str,
) -> dict:
    """Append a corrected example to the local feedback store and mark the
    originating chatfilter_log entry. Returns {"ok": True, "count": N}."""

    async with _lock:
        entries = load_feedback_entries()

        entries.append({
            "message": message,
            "ai_said": ai_said,
            "correct": correct,
            "reason":  reason,
            "admin":   admin_name,
            "log_id":  log_id,
        })

        cap = config.Chatfilter.feedback_max_entries
        if cap > 0 and len(entries) > cap:
            entries = entries[-cap:]

        _write_entries(entries)

        cf_log: dict = dict(datasys.load_data(1001, "chatfilter_log"))
        entry = cf_log.get(str(log_id))
        if entry is not None:
            entry["false_positive"] = (correct.upper() == "SAFE")
            entry["feedback"] = {
                "ai_said": ai_said,
                "correct": correct,
                "reason":  reason,
                "admin":   admin_name,
            }
            datasys.save_data(1001, "chatfilter_log", cf_log)

        _admin_log(
            "info",
            f"AI feedback stored -  log={log_id} ai_said={ai_said} "
            f"correct={correct} admin={admin_name} total={len(entries)}",
            source="Chatfilter",
        )
        return {"ok": True, "count": len(entries)}
