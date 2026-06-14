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

def load_leveling_users(gid: int) -> dict:
    rows = db.query("SELECT * FROM leveling_users WHERE guild_id=?", (gid,))
    out: dict = {}
    for r in rows:
        out[r["user_id"]] = {
            "xp":       int(r["xp"]),
            "level":    int(r["level"]),
            "messages": int(r["messages"]),
            "name":     str(r["name"] or ""),
        }
    return out


def save_leveling_users(gid: int, data: dict) -> None:
    db.ensure_guild(gid)
    with db.transaction() as cx:
        cx.execute("DELETE FROM leveling_users WHERE guild_id=?", (gid,))
        for uid, entry in data.items():
            cx.execute(
                "INSERT INTO leveling_users (guild_id,user_id,xp,level,messages,name) "
                "VALUES (?,?,?,?,?,?)",
                (
                    gid, str(uid),
                    int(entry.get("xp", 0)),
                    int(entry.get("level", 0)),
                    int(entry.get("messages", 0)),
                    str(entry.get("name", "")),
                ),
            )


def upsert_leveling_user(gid: int, uid: str, fields: dict) -> None:
    """Targeted upsert for the hot XP path — avoids a full reload."""
    db.ensure_guild(gid)
    db.execute(
        "INSERT INTO leveling_users (guild_id,user_id,xp,level,messages,name) "
        "VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(guild_id,user_id) DO UPDATE SET "
        "xp=excluded.xp,level=excluded.level,messages=excluded.messages,name=excluded.name",
        (
            gid, str(uid),
            int(fields.get("xp", 0)),
            int(fields.get("level", 0)),
            int(fields.get("messages", 0)),
            str(fields.get("name", "")),
        ),
    )
