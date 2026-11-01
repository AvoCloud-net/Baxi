"""
assets/repo/entities.py — users, stats, chatfilter_log, globalchat_message_data,
leveling_users.
"""
from __future__ import annotations

import json

import assets.db as db

_USERS_PROMOTED = {"name", "flagged", "reason", "entry_date", "auto_flagged"}


# ── Users ─────────────────────────────────────────────────────────────────────

def load_users(gid: int) -> dict:
    rows = db.query("SELECT * FROM users WHERE guild_id=?", (gid,))
    out: dict = {}
    for r in rows:
        extra = json.loads(r["extra_json"] or "{}")
        entry: dict = {
            "id":           r["user_id"],
            "name":         str(r["name"] or ""),
            "flagged":      bool(r["flagged"]),
            "reason":       str(r["reason"] or ""),
            "entry_date":   str(r["entry_date"] or ""),
            "auto_flagged": bool(r["auto_flagged"]),
        }
        entry.update(extra)
        out[r["user_id"]] = entry
    return out


def save_users(gid: int, data: dict) -> None:
    db.ensure_guild(gid)
    with db.transaction() as cx:
        cx.execute("DELETE FROM users WHERE guild_id=?", (gid,))
        for uid, entry in data.items():
            extra = {k: v for k, v in entry.items()
                     if k not in _USERS_PROMOTED and k != "id"}
            cx.execute(
                "INSERT INTO users "
                "(guild_id,user_id,name,flagged,reason,entry_date,auto_flagged,extra_json) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    gid, str(uid),
                    str(entry.get("name", "")),
                    int(bool(entry.get("flagged", False))),
                    str(entry.get("reason", "")),
                    str(entry.get("entry_date", "")),
                    int(bool(entry.get("auto_flagged", False))),
                    json.dumps(extra),
                ),
            )


# ── Stats ─────────────────────────────────────────────────────────────────────

def load_stats(gid: int) -> dict:
    rows = db.query("SELECT data_json FROM stats WHERE guild_id=?", (gid,))
    if not rows:
        return {}
    return json.loads(rows[0]["data_json"] or "{}")


def save_stats(gid: int, data: dict) -> None:
    db.ensure_guild(gid)
    db.execute(
        "INSERT INTO stats (guild_id,data_json) VALUES (?,?) "
        "ON CONFLICT(guild_id) DO UPDATE SET data_json=excluded.data_json",
        (gid, json.dumps(data)),
    )


# ── Chatfilter log ────────────────────────────────────────────────────────────

def load_chatfilter_log(gid: int) -> dict:
    rows = db.query("SELECT log_id, data_json FROM chatfilter_log WHERE guild_id=?", (gid,))
    return {r["log_id"]: json.loads(r["data_json"]) for r in rows}


def save_chatfilter_log(gid: int, data: dict) -> None:
    db.ensure_guild(gid)
    with db.transaction() as cx:
        cx.execute("DELETE FROM chatfilter_log WHERE guild_id=?", (gid,))
        for log_id, v in data.items():
            cx.execute(
                "INSERT INTO chatfilter_log (guild_id,log_id,data_json) VALUES (?,?,?)",
                (gid, str(log_id), json.dumps(v)),
            )


# ── Globalchat message data ───────────────────────────────────────────────────

def load_globalchat_message_data(gid: int) -> dict:
    rows = db.query("SELECT gcmid, data_json FROM globalchat_message_data WHERE guild_id=?", (gid,))
    return {r["gcmid"]: json.loads(r["data_json"]) for r in rows}


def save_globalchat_message_data(gid: int, data: dict) -> None:
    db.ensure_guild(gid)
    with db.transaction() as cx:
        cx.execute("DELETE FROM globalchat_message_data WHERE guild_id=?", (gid,))
        for gcmid, v in data.items():
            cx.execute(
                "INSERT INTO globalchat_message_data (guild_id,gcmid,data_json) VALUES (?,?,?)",
                (gid, str(gcmid), json.dumps(v)),
            )


# ── Leveling users ────────────────────────────────────────────────────────────

# Every row keeps xp = text_xp + voice_xp (xp is the total, indexed for the leaderboard).

_LV_UPSERT = (
    "INSERT INTO leveling_users (guild_id,user_id,xp,text_xp,voice_xp,level,messages,name) "
    "VALUES (?,?,?,?,?,?,?,?) "
    "ON CONFLICT(guild_id,user_id) DO UPDATE SET "
    "xp=excluded.xp,text_xp=excluded.text_xp,voice_xp=excluded.voice_xp,"
    "level=excluded.level,messages=excluded.messages,name=excluded.name"
)

# Leaderboard sources -> column (fixed set, safe to format into SQL).
_LV_SOURCE_COL = {"total": "xp", "text": "text_xp", "voice": "voice_xp"}


def _lv_entry(r) -> dict:
    text = int(r["text_xp"] or 0)
    voice = int(r["voice_xp"] or 0)
    return {
        "xp":       text + voice,
        "text_xp":  text,
        "voice_xp": voice,
        "level":    int(r["level"] or 0),
        "messages": int(r["messages"] or 0),
        "name":     str(r["name"] or ""),
    }


def _lv_split(entry: dict) -> tuple[int, int]:
    """(text_xp, voice_xp) of an entry; a legacy entry with only ``xp`` counts as text."""
    if "text_xp" in entry or "voice_xp" in entry:
        return int(entry.get("text_xp", 0) or 0), int(entry.get("voice_xp", 0) or 0)
    return int(entry.get("xp", 0) or 0), 0


def _lv_params(gid: int, uid: str, entry: dict) -> tuple:
    text, voice = _lv_split(entry)
    return (
        gid, str(uid), text + voice, text, voice,
        int(entry.get("level", 0) or 0), int(entry.get("messages", 0) or 0),
        str(entry.get("name", "") or ""),
    )


def load_leveling_users(gid: int) -> dict:
    rows = db.query("SELECT * FROM leveling_users WHERE guild_id=?", (gid,))
    return {r["user_id"]: _lv_entry(r) for r in rows}


def save_leveling_users(gid: int, data: dict) -> None:
    db.ensure_guild(gid)
    with db.transaction() as cx:
        cx.execute("DELETE FROM leveling_users WHERE guild_id=?", (gid,))
        for uid, entry in data.items():
            cx.execute(_LV_UPSERT, _lv_params(gid, uid, entry))


def upsert_leveling_user(gid: int, uid: str, fields: dict) -> None:
    """Write one user's full entry (legacy ``xp``-only entries count as text XP)."""
    db.ensure_guild(gid)
    db.execute(_LV_UPSERT, _lv_params(gid, uid, fields))


def get_leveling_user(gid: int, uid) -> dict | None:
    """One user's entry, or None if they have none on this server."""
    rows = db.query(
        "SELECT * FROM leveling_users WHERE guild_id=? AND user_id=?", (gid, str(uid)),
    )
    return _lv_entry(rows[0]) if rows else None


def add_leveling_xp(
    gid: int, uid, name: str | None, *, level_for, text_xp: int = 0, voice_xp: int = 0,
    messages: int = 0,
) -> tuple[int, dict]:
    """Add XP / a message to one user in a single transaction.

    ``level_for(total_xp)`` computes the level; the stored level never goes down.
    ``name=None`` keeps the stored name. Returns (old_level, new_entry).
    """
    with db.transaction() as cx:
        r = cx.execute(
            "SELECT * FROM leveling_users WHERE guild_id=? AND user_id=?", (gid, str(uid)),
        ).fetchone()
        if r is None:
            cx.execute("INSERT OR IGNORE INTO guilds (guild_id) VALUES (?)", (int(gid),))
            old = {"xp": 0, "text_xp": 0, "voice_xp": 0, "level": 0, "messages": 0, "name": ""}
        else:
            old = _lv_entry(r)
        new = {
            "text_xp":  old["text_xp"] + int(text_xp),
            "voice_xp": old["voice_xp"] + int(voice_xp),
            "messages": old["messages"] + int(messages),
            "name":     old["name"] if name is None else str(name),
        }
        new["xp"] = new["text_xp"] + new["voice_xp"]
        new["level"] = max(old["level"], int(level_for(new["xp"])))
        cx.execute(_LV_UPSERT, _lv_params(gid, uid, new))
    return old["level"], new


def leveling_leaderboard(gid: int, source: str = "total", limit: int = 10) -> list[tuple[str, dict]]:
    """Top users by total, text or voice XP (users with 0 in that source are left out)."""
    col = _LV_SOURCE_COL.get(source, "xp")
    rows = db.query(
        f"SELECT * FROM leveling_users WHERE guild_id=? AND {col} > 0 "
        f"ORDER BY {col} DESC, user_id LIMIT ?",
        (gid, int(limit)),
    )
    return [(r["user_id"], _lv_entry(r)) for r in rows]


def leveling_rank(gid: int, uid, source: str = "total") -> int | None:
    """1-based leaderboard position (ties share a place); None without XP in that source."""
    col = _LV_SOURCE_COL.get(source, "xp")
    rows = db.query(
        f"SELECT {col} AS v FROM leveling_users WHERE guild_id=? AND user_id=?", (gid, str(uid)),
    )
    if not rows or not int(rows[0]["v"] or 0):
        return None
    ahead = db.query(
        f"SELECT COUNT(*) AS n FROM leveling_users WHERE guild_id=? AND {col} > ?",
        (gid, int(rows[0]["v"])),
    )
    return int(ahead[0]["n"]) + 1
