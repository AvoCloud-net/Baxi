"""
assets/repo/standalone.py — mc_links, trust profiles+events,
temp_voice owners/profiles/permanent, ai_feedback.
"""
from __future__ import annotations

import json

import assets.db as db

_MC_PROMOTED = {"uuid", "name", "linked_at", "bedrock_uuid", "bedrock_name"}


# ── MC links ──────────────────────────────────────────────────────────────────

def load_mc_links() -> dict:
    rows = db.query("SELECT * FROM mc_links")
    out: dict = {}
    for r in rows:
        extra = json.loads(r["extra_json"] or "{}")
        entry: dict = {
            "uuid":         str(r["uuid"] or ""),
            "name":         str(r["name"] or ""),
            "linked_at":    r["linked_at"],
            "bedrock_uuid": r["bedrock_uuid"],
            "bedrock_name": r["bedrock_name"],
        }
        entry.update(extra)
        gid = r["guild_id"]
        did = r["discord_id"]
        out.setdefault(gid, {})[did] = entry
    return out


def save_mc_links(data: dict) -> None:
    with db.transaction() as cx:
        cx.execute("DELETE FROM mc_links")
        for gid, users in data.items():
            for did, entry in users.items():
                extra = {k: v for k, v in entry.items() if k not in _MC_PROMOTED}
                cx.execute(
                    "INSERT INTO mc_links "
                    "(guild_id,discord_id,uuid,name,linked_at,bedrock_uuid,bedrock_name,extra_json) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (
                        str(gid), str(did),
                        str(entry.get("uuid", "")),
                        str(entry.get("name", "")),
                        entry.get("linked_at"),
                        entry.get("bedrock_uuid"),
                        entry.get("bedrock_name"),
                        json.dumps(extra),
                    ),
                )


# ── Safety denylist (human-gated) + opt-out ───────────────────────────────────
# Replaces the removed cross-server trust profile. Stores only a moderator-set fact.

def load_safety_flags() -> dict:
    rows = db.query("SELECT * FROM safety_flags")
    out: dict = {}
    for r in rows:
        out[r["user_id"]] = {
            "category":         str(r["category"] or "other"),
            "reason":           str(r["reason"] or ""),
            "flagged_by_guild": r["flagged_by_guild"],
            "flagged_by":       str(r["flagged_by"] or ""),
            "timestamp":        str(r["timestamp"] or ""),
        }
    return out


def get_safety_flag(user_id: str) -> dict | None:
    rows = db.query("SELECT * FROM safety_flags WHERE user_id=?", (str(user_id),))
    if not rows:
        return None
    r = rows[0]
    return {
        "category":         str(r["category"] or "other"),
        "reason":           str(r["reason"] or ""),
        "flagged_by_guild": r["flagged_by_guild"],
        "flagged_by":       str(r["flagged_by"] or ""),
        "timestamp":        str(r["timestamp"] or ""),
    }


def set_safety_flag(user_id: str, category: str, reason: str, flagged_by_guild: int,
                    flagged_by: str, timestamp: str) -> None:
    db.execute(
        "INSERT INTO safety_flags (user_id,category,reason,flagged_by_guild,flagged_by,timestamp) "
        "VALUES (?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET "
        "category=excluded.category,reason=excluded.reason,"
        "flagged_by_guild=excluded.flagged_by_guild,flagged_by=excluded.flagged_by,"
        "timestamp=excluded.timestamp",
        (str(user_id), str(category), str(reason), flagged_by_guild, str(flagged_by), str(timestamp)),
    )


def remove_safety_flag(user_id: str) -> None:
    db.execute("DELETE FROM safety_flags WHERE user_id=?", (str(user_id),))


def load_safety_optout() -> set:
    rows = db.query("SELECT user_id FROM safety_optout")
    return {r["user_id"] for r in rows}


def set_safety_optout(user_id: str, opted_out: bool) -> None:
    if opted_out:
        db.execute("INSERT OR IGNORE INTO safety_optout (user_id) VALUES (?)", (str(user_id),))
    else:
        db.execute("DELETE FROM safety_optout WHERE user_id=?", (str(user_id),))


# ── Temp voice owners ─────────────────────────────────────────────────────────

def load_temp_voice_owners() -> dict:
    rows = db.query("SELECT * FROM temp_voice_owners")
    return {
        str(r["channel_id"]): {
            "owner_id": int(r["owner_id"]),
            "guild_id": int(r["guild_id"]),
        }
        for r in rows
    }


def save_temp_voice_owners(data: dict) -> None:
    with db.transaction() as cx:
        cx.execute("DELETE FROM temp_voice_owners")
        for ch_id, v in data.items():
            cx.execute(
                "INSERT INTO temp_voice_owners (channel_id,owner_id,guild_id) VALUES (?,?,?)",
                (int(ch_id), int(v["owner_id"]), int(v["guild_id"])),
            )


def upsert_temp_voice_owner(channel_id: int, owner_id: int, guild_id: int) -> None:
    """Insert/update a single owner row. Never touches other channels' rows."""
    with db.transaction() as cx:
        cx.execute(
            "INSERT INTO temp_voice_owners (channel_id,owner_id,guild_id) VALUES (?,?,?) "
            "ON CONFLICT(channel_id) DO UPDATE SET "
            "owner_id=excluded.owner_id, guild_id=excluded.guild_id",
            (int(channel_id), int(owner_id), int(guild_id)),
        )


def delete_temp_voice_owner(channel_id: int) -> None:
    with db.transaction() as cx:
        cx.execute(
            "DELETE FROM temp_voice_owners WHERE channel_id=?", (int(channel_id),)
        )


# ── Temp voice profiles ───────────────────────────────────────────────────────

def load_temp_voice_profiles() -> dict:
    rows = db.query("SELECT profile_key, data_json FROM temp_voice_profiles")
    return {r["profile_key"]: json.loads(r["data_json"]) for r in rows}


def save_temp_voice_profiles(data: dict) -> None:
    with db.transaction() as cx:
        cx.execute("DELETE FROM temp_voice_profiles")
        for key, v in data.items():
            cx.execute(
                "INSERT INTO temp_voice_profiles (profile_key,data_json) VALUES (?,?)",
                (str(key), json.dumps(v)),
            )


# ── Temp voice permanent ──────────────────────────────────────────────────────

def load_temp_voice_permanent() -> list:
    rows = db.query("SELECT channel_id FROM temp_voice_permanent")
    return [int(r["channel_id"]) for r in rows]


def save_temp_voice_permanent(data: list) -> None:
    with db.transaction() as cx:
        cx.execute("DELETE FROM temp_voice_permanent")
        for ch_id in data:
            cx.execute(
                "INSERT OR IGNORE INTO temp_voice_permanent (channel_id) VALUES (?)", (int(ch_id),)
            )


def add_temp_voice_permanent(channel_id: int) -> None:
    """Mark a single channel permanent. Never touches other channels' rows."""
    with db.transaction() as cx:
        cx.execute(
            "INSERT OR IGNORE INTO temp_voice_permanent (channel_id) VALUES (?)",
            (int(channel_id),),
        )


def delete_temp_voice_permanent(channel_id: int) -> None:
    with db.transaction() as cx:
        cx.execute(
            "DELETE FROM temp_voice_permanent WHERE channel_id=?", (int(channel_id),)
        )


# ── AI feedback ───────────────────────────────────────────────────────────────

def load_ai_feedback() -> list:
    rows = db.query("SELECT * FROM ai_feedback ORDER BY pos")
    result = []
    for r in rows:
        result.append({
            "message": r["message"],
            "ai_said": r["ai_said"],
            "correct": r["correct"],
            "reason":  r["reason"],
            "admin":   r["admin"],
            "log_id":  r["log_id"],
        })
    return result


def save_ai_feedback(data: list) -> None:
    with db.transaction() as cx:
        cx.execute("DELETE FROM ai_feedback")
        for entry in data:
            cx.execute(
                "INSERT INTO ai_feedback (message,ai_said,correct,reason,admin,log_id) "
                "VALUES (?,?,?,?,?,?)",
                (
                    entry.get("message", ""),
                    entry.get("ai_said", ""),
                    entry.get("correct", ""),
                    entry.get("reason", ""),
                    entry.get("admin", ""),
                    entry.get("log_id", ""),
                ),
            )
