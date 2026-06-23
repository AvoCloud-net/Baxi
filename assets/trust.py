"""
Baxi safety module (formerly "Prism").

COMPLIANCE NOTE (Discord Developer Policy):
The old version stored a persistent, cross-server **behavioral trust score** per user, a
per-user **event dossier**, and **LLM-generated summaries of individuals**. The Developer
Policy forbids using API data to "profile Discord users, their identities, or relationships
with other users" and to use data "outside of what is necessary to provide your stated
functionality". All of that has been removed.

What remains is compliant:
  * Per-guild moderation (warnings, flags, mod events) lives in the guild that produced it.
  * Risk on join/message is computed LIVE from data Discord already exposes (account age) plus
    that guild's own history — never stored as a profile (see assets/moderation/risk.py).
  * A minimal, human-gated **safety denylist**: written only when a moderator bans / reports a
    user, storing a coarse category fact (raid/spam/hate/other) — no score, no event history,
    no message content. Opt-out is respected.

The legacy function names below are kept as thin shims/no-ops so existing call sites do not
break while they are migrated; they no longer collect or store cross-server behavioral data.
"""
from __future__ import annotations

import datetime
from typing import Optional

from reds_simple_logger import Logger

from assets.repo.standalone import (
    load_safety_flags, get_safety_flag, set_safety_flag, remove_safety_flag,
    load_safety_optout, set_safety_optout,
)

logger = Logger()

# Kept for user-facing "your account is still new" messaging in commands.py.
AGE_FULL_TRUST_DAYS = 90

# Valid coarse categories a moderator can assign on the safety denylist.
SAFETY_CATEGORIES = ("raid", "spam", "hate", "other")

# ── Legacy stubs referenced by not-yet-migrated UI (dash/commands) ──────────────
# These exist only so old screens render empty instead of crashing.
EVENT_WEIGHTS: dict[str, int] = {}
EVENT_LABELS: dict[str, str] = {}
SEVERITY_LABELS: dict[str, str] = {}
EVENT_DECAY_DAYS = 90


def get_event_severity(event_type: str) -> str:
    return "none"


# ── Opt-out (network safety list) ───────────────────────────────────────────────

def is_opted_out(user_id: int) -> bool:
    try:
        return str(user_id) in load_safety_optout()
    except Exception:
        return False


def set_opt_out(user_id: int, opted_out: bool) -> None:
    """User opts out of (or back into) the network safety list. Removes any existing flag."""
    set_safety_optout(str(user_id), opted_out)
    if opted_out:
        remove_safety_flag(str(user_id))


# ── Human-gated safety denylist ─────────────────────────────────────────────────

def flag_user(user_id: int, category: str, guild_id: int,
              moderator_name: str = "", reason: str = "") -> bool:
    """Add a user to the network safety denylist. MUST be called from a human moderator
    action (ban / explicit report), never from automated behavioral detection.

    Returns True if flagged, False if skipped (opted out)."""
    if is_opted_out(user_id):
        return False
    cat = category if category in SAFETY_CATEGORIES else "other"
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat()
    try:
        set_safety_flag(str(user_id), cat, reason, int(guild_id), moderator_name, now)
        logger.info(f"[Safety] flagged {user_id} category={cat} by {moderator_name} guild={guild_id}")
        return True
    except Exception as e:
        logger.error(f"[Safety] flag_user failed: {e}")
        return False


def unflag_user(user_id: int) -> None:
    try:
        remove_safety_flag(str(user_id))
        logger.info(f"[Safety] unflagged {user_id}")
    except Exception as e:
        logger.error(f"[Safety] unflag_user failed: {e}")


def is_flagged(user_id: int) -> bool:
    try:
        return get_safety_flag(str(user_id)) is not None
    except Exception:
        return False


def get_flag(user_id: int) -> Optional[dict]:
    try:
        return get_safety_flag(str(user_id))
    except Exception:
        return None


def all_flags() -> dict:
    try:
        return load_safety_flags()
    except Exception:
        return {}


# ── Legacy shims (no longer collect/store behavioral data) ──────────────────────
# Cross-server behavioral recording removed for compliance. These are intentional no-ops.

def record_event(user_id: int = 0, user_name: str = "", event_type: str = "",
                 guild_id: int = 0, reason: str = "", account_age_days: int = 365) -> int:
    return -1  # behavioral cross-server recording removed


def record_fp_correction(*args, **kwargs) -> int:
    return -1


def ensure_profile(*args, **kwargs) -> None:
    return None


def get_profile(user_id: int) -> Optional[dict]:
    return None


def get_all_profiles() -> dict:
    return {}


def get_score_explanation(user_id: int) -> Optional[dict]:
    return None


def recalculate_all() -> None:
    return None


def clear_flag(user_id: int) -> None:
    """Legacy admin deflag → maps to removing the safety-list entry."""
    unflag_user(user_id)


def clear_events(user_id: int) -> None:
    return None


def delete_event(user_id: int, event_timestamp: str) -> bool:
    return False


def delete_profile(user_id: int) -> bool:
    """Right-to-erasure: remove any safety flag + opt-out record for this user."""
    try:
        remove_safety_flag(str(user_id))
        set_safety_optout(str(user_id), False)
        return True
    except Exception:
        return False


async def _update_user_summary(uid) -> None:
    return None


async def update_pending_summaries() -> None:
    return None
