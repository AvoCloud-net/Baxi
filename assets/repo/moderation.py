"""
assets/repo/moderation.py — warnings, mod_events, filter_events.

Config mappers for chatfilter/warn/antispam/serverlog live in config_simple.py.
"""
from __future__ import annotations

import datetime
import json

import assets.db as db

_INSIGHTS_MAX_DAYS = 90


# ── Warnings ──────────────────────────────────────────────────────────────────

def load_warnings(gid: int) -> dict:
    """Return {user_id_str: [{id,reason,mod,mod_id,date}, ...]} for the guild."""
    rows = db.query(
        "SELECT * FROM warnings WHERE guild_id=? ORDER BY user_id, pos", (gid,)
    )
    out: dict[str, list] = {}
    for r in rows:
        out.setdefault(r["user_id"], []).append({
            "id":     r["id"],
            "reason": r["reason"],
            "mod":    r["mod"],
            "mod_id": r["mod_id"],
            "date":   r["date"],
        })
    return out


def save_warnings(gid: int, data: dict) -> None:
    db.ensure_guild(gid)
    with db.transaction() as cx:
        cx.execute("DELETE FROM warnings WHERE guild_id=?", (gid,))
        for uid, lst in data.items():
            for pos, w in enumerate(lst):
                cx.execute(
                    "INSERT INTO warnings (id,guild_id,user_id,reason,mod,mod_id,date,pos) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (
                        w["id"], gid, str(uid),
                        w.get("reason", ""),
                        w.get("mod", ""),
                        int(w.get("mod_id", 0) or 0),
                        w.get("date", ""),
                        pos,
                    ),
                )


def add_warning(gid: int, uid: str, warn: dict) -> None:
    """Targeted insert — adds a single warning without a full reload."""
    db.ensure_guild(gid)
    with db.transaction() as cx:
        row = cx.execute(
            "SELECT COALESCE(MAX(pos)+1,0) as next_pos FROM warnings WHERE guild_id=? AND user_id=?",
            (gid, uid),
        ).fetchone()
        next_pos = row["next_pos"] if row else 0
        cx.execute(
            "INSERT OR IGNORE INTO warnings (id,guild_id,user_id,reason,mod,mod_id,date,pos) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                warn["id"], gid, str(uid),
                warn.get("reason", ""),
                warn.get("mod", ""),
                int(warn.get("mod_id", 0) or 0),
                warn.get("date", ""),
                next_pos,
            ),
        )


def remove_warning(gid: int, uid: str, warn_id: str) -> None:
    """Targeted delete — removes one warning by id."""
    db.execute("DELETE FROM warnings WHERE guild_id=? AND user_id=? AND id=?", (gid, uid, warn_id))
    # Re-number positions so pos stays contiguous
    with db.transaction() as cx:
        rows = cx.execute(
            "SELECT id FROM warnings WHERE guild_id=? AND user_id=? ORDER BY pos",
            (gid, str(uid)),
        ).fetchall()
        for new_pos, r in enumerate(rows):
            cx.execute(
                "UPDATE warnings SET pos=? WHERE guild_id=? AND user_id=? AND id=?",
                (new_pos, gid, str(uid), r["id"]),
            )


# ── Mod events ────────────────────────────────────────────────────────────────

def append_mod_event(gid: int, event: dict) -> None:
    """Insert one mod event and prune entries older than 90 days."""
    db.ensure_guild(gid)
    _PROMOTED = ["type", "user_id", "user_name", "mod_id", "mod_name", "reason", "timestamp"]
    with db.transaction() as cx:
        row = cx.execute(
            "SELECT COALESCE(MAX(pos)+1,0) as next_pos FROM mod_events WHERE guild_id=?", (gid,)
        ).fetchone()
        next_pos = row["next_pos"] if row else 0
        extra = {k: v for k, v in event.items() if k not in _PROMOTED}
        cx.execute(
            "INSERT INTO mod_events "
            "(guild_id,pos,type,user_id,user_name,mod_id,mod_name,reason,timestamp,extra_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                gid, next_pos,
                event.get("type", ""),
                str(event.get("user_id", "")),
                str(event.get("user_name", "")),
                str(event.get("mod_id", "")),
                str(event.get("mod_name", "")),
                str(event.get("reason", "")),
                str(event.get("timestamp", "")),
                json.dumps(extra),
            ),
        )
        cutoff = (datetime.datetime.utcnow() - datetime.timedelta(days=_INSIGHTS_MAX_DAYS)).isoformat()
        cx.execute(
            "DELETE FROM mod_events WHERE guild_id=? AND timestamp < ?", (gid, cutoff)
        )


def load_mod_events(gid: int) -> list:
    rows = db.query("SELECT * FROM mod_events WHERE guild_id=? ORDER BY pos", (gid,))
    result = []
    for r in rows:
        ev: dict = {
            "type":      r["type"],
            "user_id":   r["user_id"],
            "user_name": r["user_name"],
            "mod_id":    r["mod_id"],
            "mod_name":  r["mod_name"],
            "reason":    r["reason"],
            "timestamp": r["timestamp"],
        }
        extra = json.loads(r["extra_json"] or "{}")
        ev.update(extra)
        result.append(ev)
    return result


def save_mod_events(gid: int, data: list) -> None:
    db.ensure_guild(gid)
    _PROMOTED = ["type", "user_id", "user_name", "mod_id", "mod_name", "reason", "timestamp"]
    with db.transaction() as cx:
        cx.execute("DELETE FROM mod_events WHERE guild_id=?", (gid,))
        for pos, ev in enumerate(data):
            extra = {k: v for k, v in ev.items() if k not in _PROMOTED}
            cx.execute(
                "INSERT INTO mod_events "
                "(guild_id,pos,type,user_id,user_name,mod_id,mod_name,reason,timestamp,extra_json) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    gid, pos,
                    ev.get("type", ""),
                    str(ev.get("user_id", "")),
                    str(ev.get("user_name", "")),
                    str(ev.get("mod_id", "")),
                    str(ev.get("mod_name", "")),
                    str(ev.get("reason", "")),
                    str(ev.get("timestamp", "")),
                    json.dumps(extra),
                ),
            )


# ── Filter events ─────────────────────────────────────────────────────────────

def append_filter_event(gid: int, event: dict) -> None:
    """Insert one filter event and prune entries older than 90 days."""
    db.ensure_guild(gid)
    with db.transaction() as cx:
        row = cx.execute(
            "SELECT COALESCE(MAX(pos)+1,0) as next_pos FROM filter_events WHERE guild_id=?", (gid,)
        ).fetchone()
        next_pos = row["next_pos"] if row else 0
        cx.execute(
            "INSERT INTO filter_events (guild_id,pos,timestamp,data_json) VALUES (?,?,?,?)",
            (gid, next_pos, str(event.get("timestamp", "")), json.dumps(event)),
        )
        cutoff = (datetime.datetime.utcnow() - datetime.timedelta(days=_INSIGHTS_MAX_DAYS)).isoformat()
        cx.execute(
            "DELETE FROM filter_events WHERE guild_id=? AND timestamp < ?", (gid, cutoff)
        )


def load_filter_events(gid: int) -> list:
    rows = db.query("SELECT data_json FROM filter_events WHERE guild_id=? ORDER BY pos", (gid,))
    return [json.loads(r["data_json"]) for r in rows]


def save_filter_events(gid: int, data: list) -> None:
    db.ensure_guild(gid)
    with db.transaction() as cx:
        cx.execute("DELETE FROM filter_events WHERE guild_id=?", (gid,))
        for pos, ev in enumerate(data):
            cx.execute(
                "INSERT INTO filter_events (guild_id,pos,timestamp,data_json) VALUES (?,?,?,?)",
                (gid, pos, str(ev.get("timestamp", "")), json.dumps(ev)),
            )
