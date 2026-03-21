"""
Baxi Prism — Automated Trust Scoring System
Tracks user behavior across all Baxi servers and generates a trust score (0–100).
Users below the auto-flag threshold are automatically added to the global flagged list.
"""

import datetime
import os
from typing import Optional

import assets.data as datasys
from reds_simple_logger import Logger

logger = Logger()

# ── Score weights ──────────────────────────────────────────────────────────────
EVENT_WEIGHTS: dict[str, int] = {
    "chatfilter_violation": -15,
    "chatfilter_phishing":  -25,
    "antispam":             -10,
    "warning":               -8,
    "kick":                 -10,
    "ban":                  -20,
}

# ── Thresholds ─────────────────────────────────────────────────────────────────
AUTO_FLAG_THRESHOLD   = 30   # score ≤ this → auto-flag
AUTO_UNFLAG_THRESHOLD = 50   # score ≥ this → auto-unflag (only if auto-flagged)
RECOVERY_SCORE        = 8    # +8 per 20 clean days
RECOVERY_DAYS         = 20
EVENT_DECAY_DAYS      = 90   # events older than this count at half weight


# ── Internal helpers ───────────────────────────────────────────────────────────

def _trust_path() -> str:
    return os.path.join("data", "1001", "trust.json")


def _load() -> dict:
    path = _trust_path()
    if not os.path.exists(path):
        return {}
    try:
        return datasys.load_json(path)
    except Exception:
        return {}


def _save(data: dict):
    datasys.save_json(_trust_path(), data)


# ── Score calculation ──────────────────────────────────────────────────────────

def calculate_score(events: list, account_age_days: int) -> int:
    """Pure function: derive trust score from event list and account age."""
    score = 100

    # Account age penalty (applied once at calculation time)
    if account_age_days < 7:
        score -= 20
    elif account_age_days < 30:
        score -= 10

    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

    for event in events:
        etype  = event.get("type", "")
        weight = EVENT_WEIGHTS.get(etype, 0)

        # Older events count at half penalty
        try:
            ts  = datetime.datetime.fromisoformat(event["timestamp"])
            age = (now - ts).days
            if age > EVENT_DECAY_DAYS:
                weight = weight // 2
        except Exception:
            pass

        score += weight

    # Recovery bonus: +5 per 30 clean days since last event
    if events:
        try:
            last_ts    = max(datetime.datetime.fromisoformat(e["timestamp"]) for e in events)
            clean_days = (now - last_ts).days
            score     += (clean_days // RECOVERY_DAYS) * RECOVERY_SCORE
        except Exception:
            pass

    return max(0, min(100, score))


# ── Public API ─────────────────────────────────────────────────────────────────

def record_event(
    user_id:    int,
    user_name:  str,
    event_type: str,
    guild_id:   int,
    reason:     str = "",
    account_age_days: int = 365,
) -> int:
    """
    Record a Prism event for a user and return the new trust score.
    Automatically triggers auto-flag logic after recording.
    """
    logger.working(f"[Prism] record_event called — user={user_name} ({user_id}) event={event_type} guild={guild_id}")

    # Guild-level opt-out check (default: enabled — only skip if explicitly False)
    try:
        prism_setting = datasys.load_data(guild_id, "prism_enabled")
        if prism_setting is False:
            logger.info(f"[Prism] Skipped — guild {guild_id} has Prism disabled")
            return -1
    except Exception as _opt_err:
        logger.warn(f"[Prism] Could not read prism_enabled for guild {guild_id}: {_opt_err}")

    data = _load()
    uid  = str(user_id)
    now  = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat()

    if uid not in data:
        data[uid] = {
            "name":             user_name,
            "id":               uid,
            "score":            100,
            "auto_flagged":     False,
            "events":           [],
            "first_seen":       now,
            "last_seen":        now,
            "account_age_days": account_age_days,
        }
    else:
        data[uid]["name"]             = user_name
        data[uid]["last_seen"]        = now
        data[uid]["account_age_days"] = account_age_days

    data[uid]["events"].append({
        "type":      event_type,
        "reason":    reason,
        "guild_id":  str(guild_id),
        "timestamp": now,
    })

    score               = calculate_score(data[uid]["events"], account_age_days)
    data[uid]["score"]  = score

    try:
        _save(data)
        logger.success(f"[Prism] Saved — {user_name} ({uid}) event={event_type} score={score} path={_trust_path()}")
    except Exception as _save_err:
        logger.error(f"[Prism] _save() FAILED for {user_name} ({uid}): {_save_err}")
        return -1

    _auto_flag_check(uid, user_name, score, data)
    logger.info(f"[Prism] {user_name} ({uid}) event={event_type} score={score}")
    return score


def get_profile(user_id: int) -> Optional[dict]:
    """Return the Prism profile for a user, or None if not tracked."""
    return _load().get(str(user_id))


def get_all_profiles() -> dict:
    """Return all Prism profiles (uid → profile dict)."""
    return _load()


def clear_flag(user_id: int):
    """
    Manually clear the auto_flagged flag for a user in trust.json.
    Called by the admin dashboard deflag action.
    Does NOT remove the user from trust tracking — only clears the flag.
    """
    data = _load()
    uid  = str(user_id)
    if uid in data:
        data[uid]["auto_flagged"] = False
        _save(data)
        logger.info(f"[Prism] Manual deflag via admin dash for {uid}")


def clear_events(user_id: int):
    """Delete all recorded events for a user and reset their score to 0."""
    data = _load()
    uid  = str(user_id)
    if uid in data:
        data[uid]["events"] = []
        data[uid]["score"]  = 100
        _save(data)
        logger.info(f"[Prism] Events cleared via admin dash for {uid}")


def recalculate_all():
    """Recalculate scores for every tracked user. Called by TrustScoreTask."""
    data    = _load()
    changed = False

    for uid, profile in data.items():
        try:
            old_score = profile.get("score", 100)
            new_score = calculate_score(
                profile.get("events", []),
                profile.get("account_age_days", 365),
            )
            if new_score != old_score:
                profile["score"] = new_score
                changed = True
            _auto_flag_check(uid, profile.get("name", uid), new_score, data)
        except Exception as e:
            logger.error(f"[Prism] Error recalculating {uid}: {e}")

    if changed:
        _save(data)
        logger.debug.success(f"[Prism] Recalculated scores for {len(data)} users")


# ── Internal auto-flag logic ───────────────────────────────────────────────────

def _auto_flag_check(uid: str, user_name: str, score: int, trust_data: dict):
    """Update the global users list based on current score."""
    try:
        users_list: dict = dict(datasys.load_data(1001, "users"))
    except Exception:
        users_list = {}

    profile            = trust_data.get(uid, {})
    currently_flagged  = profile.get("auto_flagged", False)

    if score <= AUTO_FLAG_THRESHOLD and not currently_flagged:
        users_list[uid] = {
            "id":           uid,
            "name":         user_name,
            "flagged":      True,
            "reason":       f"Prism Auto-Flag (Score: {score}/100)",
            "entry_date":   datetime.date.today().isoformat(),
            "auto_flagged": True,
        }
        datasys.save_data(1001, "users", users_list)
        trust_data[uid]["auto_flagged"] = True
        _save(trust_data)
        logger.warn(f"[Prism] Auto-flagged {user_name} ({uid}) — Score: {score}")

    elif score >= AUTO_UNFLAG_THRESHOLD and currently_flagged:
        # Only remove if it was auto-flagged, never touch manual flags
        if uid in users_list and users_list[uid].get("auto_flagged", False):
            del users_list[uid]
            datasys.save_data(1001, "users", users_list)
        trust_data[uid]["auto_flagged"] = False
        _save(trust_data)
        logger.info(f"[Prism] Auto-unflagged {user_name} ({uid}) — Score: {score}")
