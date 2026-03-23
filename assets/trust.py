"""
Baxi Prism — Automated Trust Scoring System v2
Tracks user behavior across all Baxi servers and generates a trust score (0–100).
Intelligently differentiates between offense severity with tiered scoring and recovery.
"""

import asyncio
import datetime
import os
from typing import Optional

import assets.data as datasys
from reds_simple_logger import Logger

logger = Logger()

# ── Severity Tiers ─────────────────────────────────────────────────────────────
# Tiers (worst → lightest): critical > severe > high > medium > low > minor > minimal
SEVERITY_TIERS: dict[str, str] = {
    "chatfilter_phishing":  "critical",
    "ban":                  "critical",
    "chatfilter_hate":      "severe",
    "chatfilter_violation": "high",
    "kick":                 "medium",
    "antispam":             "low",
    "warning":              "minor",
    "chatfilter_mild":      "minimal",
}

# ── Score weights ──────────────────────────────────────────────────────────────
EVENT_WEIGHTS: dict[str, int] = {
    "chatfilter_phishing":  -30,
    "ban":                  -25,
    "chatfilter_hate":      -20,
    "chatfilter_violation": -15,
    "kick":                 -12,
    "antispam":             -8,
    "warning":              -6,
    "chatfilter_mild":      -4,
}

# ── Recovery rates per severity tier ───────────────────────────────────────────
# (points_per_interval, interval_days) — based on the worst event in a user's history
RECOVERY_BY_TIER: dict[str, tuple[int, int]] = {
    "critical": (4,  30),   # +4 per 30 clean days (slow recovery)
    "severe":   (4,  30),
    "high":     (6,  20),   # +6 per 20 clean days (normal)
    "medium":   (6,  20),
    "low":      (10, 15),   # +10 per 15 clean days (fast recovery)
    "minor":    (10, 15),
    "minimal":  (10, 15),
}

# ── Thresholds ─────────────────────────────────────────────────────────────────
AUTO_FLAG_THRESHOLD   = 30   # score ≤ this → auto-flag
AUTO_UNFLAG_THRESHOLD = 50   # score ≥ this → auto-unflag (only if auto-flagged)
EVENT_DECAY_DAYS      = 90   # events older than this count at half weight

# ── Account age ramp ───────────────────────────────────────────────────────────
# New accounts start at (100 - AGE_MAX_PENALTY) and linearly reach 100 at AGE_FULL_TRUST_DAYS.
AGE_FULL_TRUST_DAYS = 90    # days until account age no longer penalises score
AGE_MAX_PENALTY     = 40    # maximum penalty for brand-new accounts (day 0 → score 60)

# ── Tiers that trigger staff channel notifications ─────────────────────────────
NOTIFY_TIERS = {"critical", "severe"}

# ── Display helpers ────────────────────────────────────────────────────────────
SEVERITY_LABELS: dict[str, str] = {
    "critical": "Critical",
    "severe":   "Severe",
    "high":     "High",
    "medium":   "Medium",
    "low":      "Low",
    "minor":    "Minor",
    "minimal":  "Minimal",
}

EVENT_LABELS: dict[str, str] = {
    "chatfilter_phishing":  "Phishing / Scam Link",
    "ban":                  "Ban",
    "chatfilter_hate":      "Hate Speech",
    "chatfilter_violation": "Content Violation",
    "kick":                 "Kick",
    "antispam":             "Spam",
    "warning":              "Warning",
    "chatfilter_mild":      "Mild Violation",
}

_TIER_ORDER = ["critical", "severe", "high", "medium", "low", "minor", "minimal"]


def get_event_severity(event_type: str) -> str:
    return SEVERITY_TIERS.get(event_type, "low")


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


def _worst_tier(events: list) -> str:
    """Return the worst severity tier present in the event list."""
    worst_idx = len(_TIER_ORDER) - 1
    worst     = _TIER_ORDER[worst_idx]
    for event in events:
        tier = SEVERITY_TIERS.get(event.get("type", ""), "low")
        idx  = _TIER_ORDER.index(tier) if tier in _TIER_ORDER else worst_idx
        if idx < worst_idx:
            worst     = tier
            worst_idx = idx
    return worst


# ── Score calculation ──────────────────────────────────────────────────────────

def calculate_score(events: list, account_age_days: int) -> int:
    """Pure function: derive trust score from event list and account age."""
    score = 100

    # Account age penalty: linear ramp from -AGE_MAX_PENALTY at day 0 to 0 at AGE_FULL_TRUST_DAYS
    if account_age_days < AGE_FULL_TRUST_DAYS:
        age_penalty = -round(AGE_MAX_PENALTY * (1 - account_age_days / AGE_FULL_TRUST_DAYS))
        score += age_penalty

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

    # Tier-based recovery: recovery rate depends on worst offense in history
    if events:
        try:
            last_ts    = max(datetime.datetime.fromisoformat(e["timestamp"]) for e in events)
            clean_days = (now - last_ts).days
            worst      = _worst_tier(events)
            rec_pts, rec_days = RECOVERY_BY_TIER.get(worst, (6, 20))
            if rec_days > 0:
                score += (clean_days // rec_days) * rec_pts
        except Exception:
            pass

    return max(0, min(100, score))


# ── Score explanation (for /my_trust command) ──────────────────────────────────

def get_score_explanation(user_id: int) -> Optional[dict]:
    """
    Returns a structured explanation of a user's trust score.
    Used by the /my_trust command to show the user their score with context.
    Returns None if user is not tracked.
    """
    data = _load()
    uid  = str(user_id)
    if uid not in data:
        return None

    profile = data[uid]
    events  = profile.get("events", [])
    score   = profile.get("score", 100)
    now     = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

    # Build impact list for the 5 most recent events
    event_impacts = []
    for event in reversed(events[-5:]):
        etype  = event.get("type", "unknown")
        weight = EVENT_WEIGHTS.get(etype, 0)
        try:
            ts       = datetime.datetime.fromisoformat(event["timestamp"])
            age_days = (now - ts).days
            decayed  = age_days > EVENT_DECAY_DAYS
            effective_weight = weight // 2 if decayed else weight
        except Exception:
            age_days         = 0
            decayed          = False
            effective_weight = weight

        event_impacts.append({
            "type":             etype,
            "label":            EVENT_LABELS.get(etype, etype),
            "weight":           effective_weight,
            "age_days":         age_days,
            "decayed":          decayed,
            "reason":           event.get("reason", ""),
            "severity":         get_event_severity(etype),
            "severity_label":   SEVERITY_LABELS.get(get_event_severity(etype), ""),
        })

    # Estimate days until score reaches 100
    recovery_days_remaining = None
    if events and score < 100:
        try:
            last_ts    = max(datetime.datetime.fromisoformat(e["timestamp"]) for e in events)
            clean_days = (now - last_ts).days
            worst      = _worst_tier(events)
            rec_pts, rec_days = RECOVERY_BY_TIER.get(worst, (6, 20))
            if rec_pts > 0:
                pts_needed        = 100 - score
                intervals_needed  = -(-pts_needed // rec_pts)   # ceiling division
                days_until_100    = max(0, intervals_needed * rec_days - clean_days)
                recovery_days_remaining = days_until_100
        except Exception:
            pass

    # Trend: falling if any event in last 7 days, rising if score is recovering
    has_recent = any(
        (now - datetime.datetime.fromisoformat(e["timestamp"])).days <= 7
        for e in events
        if "timestamp" in e
    ) if events else False

    if has_recent:
        trend = "falling"
    elif score < 100 and (recovery_days_remaining or 0) > 0:
        trend = "rising"
    else:
        trend = "stable"

    return {
        "score":                   score,
        "event_count":             len(events),
        "recent_impacts":          event_impacts,
        "recovery_days_remaining": recovery_days_remaining,
        "trend":                   trend,
        "account_age_days":        profile.get("account_age_days", 0),
    }


# ── Public API ─────────────────────────────────────────────────────────────────

def ensure_profile(user_id: int, user_name: str, account_age_days: int = 365):
    """
    Create a Prism profile for the user if one doesn't exist yet.
    Safe to call on every message — does nothing if the profile already exists.
    """
    data = _load()
    uid  = str(user_id)
    if uid in data:
        return
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    account_created_at = (now - datetime.timedelta(days=account_age_days)).isoformat()
    initial_score = calculate_score([], account_age_days)
    data[uid] = {
        "name":               user_name,
        "id":                 uid,
        "score":              initial_score,
        "auto_flagged":       False,
        "events":             [],
        "first_seen":         now.isoformat(),
        "last_seen":          now.isoformat(),
        "account_age_days":   account_age_days,
        "account_created_at": account_created_at,
    }
    _save(data)
    logger.debug.info(f"[Prism] Profile created for {user_name} ({uid}) — initial score {initial_score}")


def record_event(
    user_id:          int,
    user_name:        str,
    event_type:       str,
    guild_id:         int,
    reason:           str = "",
    account_age_days: int = 365,
) -> int:
    """
    Record a Prism event and return the new trust score.
    Triggers auto-flag logic and schedules staff notifications for critical/severe events.
    """
    logger.working(f"[Prism] record_event — user={user_name} ({user_id}) event={event_type} guild={guild_id}")

    # Guild-level opt-out check
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

    now_dt = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    account_created_at = (now_dt - datetime.timedelta(days=account_age_days)).isoformat()

    if uid not in data:
        data[uid] = {
            "name":               user_name,
            "id":                 uid,
            "score":              100,
            "auto_flagged":       False,
            "events":             [],
            "first_seen":         now,
            "last_seen":          now,
            "account_age_days":   account_age_days,
            "account_created_at": account_created_at,
        }
    else:
        data[uid]["name"]             = user_name
        data[uid]["last_seen"]        = now
        data[uid]["account_age_days"] = account_age_days
        # Backfill account_created_at for existing profiles that predate this field
        if not data[uid].get("account_created_at"):
            data[uid]["account_created_at"] = account_created_at

    data[uid]["events"].append({
        "type":      event_type,
        "reason":    reason,
        "guild_id":  str(guild_id),
        "timestamp": now,
    })

    score              = calculate_score(data[uid]["events"], account_age_days)
    data[uid]["score"] = score

    try:
        _save(data)
        logger.success(f"[Prism] Saved — {user_name} ({uid}) event={event_type} score={score}")
    except Exception as _save_err:
        logger.error(f"[Prism] _save() FAILED for {user_name} ({uid}): {_save_err}")
        return -1

    was_flagged = data[uid].get("auto_flagged", False)
    _auto_flag_check(uid, user_name, score, data)
    now_flagged = data[uid].get("auto_flagged", False)

    # Notify staff: newly auto-flagged OR critical/severe event
    severity = get_event_severity(event_type)
    if (not was_flagged and now_flagged) or severity in NOTIFY_TIERS:
        _schedule_notification(
            guild_id=guild_id,
            user_id=user_id,
            user_name=user_name,
            event_type=event_type,
            score=score,
            reason=reason,
            auto_flagged=now_flagged,
        )

    logger.info(f"[Prism] {user_name} ({uid}) event={event_type} severity={severity} score={score}")
    return score


def get_profile(user_id: int) -> Optional[dict]:
    """Return the Prism profile for a user, or None if not tracked."""
    return _load().get(str(user_id))


def get_all_profiles() -> dict:
    """Return all Prism profiles (uid → profile dict)."""
    return _load()


def clear_flag(user_id: int):
    """
    Manually clear the auto_flagged flag for a user.
    Called by the admin dashboard deflag action.
    """
    data = _load()
    uid  = str(user_id)
    if uid in data:
        data[uid]["auto_flagged"] = False
        _save(data)
        logger.info(f"[Prism] Manual deflag via admin dash for {uid}")


def clear_events(user_id: int):
    """Delete all recorded events for a user and reset their score to 100."""
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

    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

    for uid, profile in data.items():
        try:
            # Compute current account age dynamically so the score improves over time
            created_at_str = profile.get("account_created_at")
            if created_at_str:
                try:
                    created_dt   = datetime.datetime.fromisoformat(created_at_str)
                    current_age  = (now - created_dt).days
                    profile["account_age_days"] = current_age
                except Exception:
                    current_age = profile.get("account_age_days", 365)
            else:
                current_age = profile.get("account_age_days", 365)

            old_score = profile.get("score", 100)
            new_score = calculate_score(
                profile.get("events", []),
                current_age,
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

    profile           = trust_data.get(uid, {})
    currently_flagged = profile.get("auto_flagged", False)

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
        if uid in users_list and users_list[uid].get("auto_flagged", False):
            del users_list[uid]
            datasys.save_data(1001, "users", users_list)
        trust_data[uid]["auto_flagged"] = False
        _save(trust_data)
        logger.info(f"[Prism] Auto-unflagged {user_name} ({uid}) — Score: {score}")


# ── Staff channel notifications ────────────────────────────────────────────────

def _schedule_notification(
    guild_id:    int,
    user_id:     int,
    user_name:   str,
    event_type:  str,
    score:       int,
    reason:      str,
    auto_flagged: bool,
):
    """Schedule an async staff notification using the running event loop."""
    import assets.share as share
    bot = share.bot
    if bot is None:
        return
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(
            _send_staff_notification(bot, guild_id, user_id, user_name, event_type, score, reason, auto_flagged)
        )
    except RuntimeError:
        pass  # no running loop — skip notification


async def _send_staff_notification(
    bot,
    guild_id:    int,
    user_id:     int,
    user_name:   str,
    event_type:  str,
    score:       int,
    reason:      str,
    auto_flagged: bool,
):
    """Send a Prism alert embed to the guild's configured or auto-detected staff channel."""
    import discord
    import config.config as config

    try:
        guild = bot.get_guild(guild_id)
        if guild is None:
            return

        channel = await _resolve_notification_channel(guild)
        if channel is None:
            return

        severity = get_event_severity(event_type)
        color    = config.Discord.danger_color if severity == "critical" else config.Discord.warn_color

        flag_note = " · **Auto-Flagged**" if auto_flagged else ""
        embed = discord.Embed(
            title=f"{config.Icons.alert} Prism Alert{flag_note}",
            description=(
                f"**User:** {user_name} (`{user_id}`)\n"
                f"**Event:** {EVENT_LABELS.get(event_type, event_type)}"
                f" · Severity: **{SEVERITY_LABELS.get(severity, severity)}**\n"
                f"**Score:** {score}/100\n"
                + (f"**Reason:** {reason}\n" if reason else "")
                + f"\n*View full profile in the Baxi Dashboard.*"
            ),
            color=color,
        )
        embed.set_footer(text="Baxi Prism · avocloud.net")
        await channel.send(embed=embed)
        logger.info(f"[Prism] Staff notification sent in {guild.name} for {user_name}")
    except Exception as e:
        logger.error(f"[Prism] Staff notification failed: {e}")


async def _resolve_notification_channel(guild):
    """
    Resolve the staff notification channel for a guild.
    Priority:
    1. Guild config: prism_notification_channel (channel ID)
    2. Auto-detect: channel name contains staff/mod/admin/log keywords
    3. First text channel where bot can send messages
    """
    import discord

    # 1. Configured channel
    try:
        configured_id = datasys.load_data(guild.id, "notification_channel")
        if configured_id:
            channel = guild.get_channel(int(configured_id))
            if isinstance(channel, discord.TextChannel):
                if channel.permissions_for(guild.me).send_messages:
                    return channel
    except Exception:
        pass

    # 2. Auto-detect by channel name keywords
    keywords = {"baxi-updates", "baxi", "staff", "mod", "moderator", "admin", "log", "mod-log", "admin-log"}
    for channel in guild.text_channels:
        if any(kw in channel.name.lower() for kw in keywords):
            if channel.permissions_for(guild.me).send_messages:
                return channel

    # 3. First writable text channel
    for channel in guild.text_channels:
        if channel.permissions_for(guild.me).send_messages:
            return channel

    return None
