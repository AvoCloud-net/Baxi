"""
assets/repo/runtime.py — sticky_messages, custom_commands, audit_log,
activity, temp_actions.
"""
from __future__ import annotations

import datetime
import json

import assets.db as db

_INSIGHTS_MAX_DAYS = 90


# ── Sticky messages ───────────────────────────────────────────────────────────

def load_sticky_messages(gid: int) -> dict:
    rows = db.query("SELECT * FROM sticky_messages WHERE guild_id=?", (gid,))
    out: dict = {}
    for r in rows:
        extra = json.loads(r["extra_json"] or "{}")
        entry = {"message": r["message"], "last_message_id": r["last_message_id"]}
        entry.update(extra)
        out[r["channel_id"]] = entry
    return out


def save_sticky_messages(gid: int, data: dict) -> None:
    db.ensure_guild(gid)
    with db.transaction() as cx:
        cx.execute("DELETE FROM sticky_messages WHERE guild_id=?", (gid,))
        for ch_id, entry in data.items():
            extra = {k: v for k, v in entry.items()
                     if k not in {"message", "last_message_id"}}
            # Keep last_message_id as NULL when absent — never store the literal
            # string "None" (str(None)), which would later make int(last_id) raise
            # ValueError in the sticky re-post path and silently kill the task.
            last_mid = entry.get("last_message_id")
            last_mid = str(last_mid) if last_mid not in (None, "", "None") else None
            cx.execute(
                "INSERT INTO sticky_messages "
                "(guild_id,channel_id,message,last_message_id,extra_json) VALUES (?,?,?,?,?)",
                (
                    gid, str(ch_id),
                    str(entry.get("message", "")),
                    last_mid,
                    json.dumps(extra),
                ),
            )


# ── Custom commands ───────────────────────────────────────────────────────────

def load_custom_commands(gid: int) -> dict:
    rows = db.query("SELECT name, data_json FROM custom_commands WHERE guild_id=?", (gid,))
    return {r["name"]: json.loads(r["data_json"]) for r in rows}


def save_custom_commands(gid: int, data: dict) -> None:
    db.ensure_guild(gid)
    with db.transaction() as cx:
        cx.execute("DELETE FROM custom_commands WHERE guild_id=?", (gid,))
        for name, v in data.items():
            cx.execute(
                "INSERT INTO custom_commands (guild_id,name,data_json) VALUES (?,?,?)",
                (gid, str(name), json.dumps(v)),
            )


# ── Audit log ─────────────────────────────────────────────────────────────────

def load_audit_log(gid: int) -> list:
    rows = db.query("SELECT entry_json FROM audit_log WHERE guild_id=? ORDER BY pos", (gid,))
    return [json.loads(r["entry_json"]) for r in rows]


def save_audit_log(gid: int, data: list) -> None:
    db.ensure_guild(gid)
    with db.transaction() as cx:
        cx.execute("DELETE FROM audit_log WHERE guild_id=?", (gid,))
        for pos, entry in enumerate(data):
            cx.execute(
                "INSERT INTO audit_log (guild_id,pos,entry_json) VALUES (?,?,?)",
                (gid, pos, json.dumps(entry)),
            )


# ── Activity ──────────────────────────────────────────────────────────────────

def load_activity(gid: int) -> dict:
    rows = db.query("SELECT data_json FROM activity WHERE guild_id=?", (gid,))
    if not rows:
        return {}
    return json.loads(rows[0]["data_json"] or "{}")


def save_activity(gid: int, data: dict) -> None:
    db.ensure_guild(gid)
    db.execute(
        "INSERT INTO activity (guild_id,data_json) VALUES (?,?) "
        "ON CONFLICT(guild_id) DO UPDATE SET data_json=excluded.data_json",
        (gid, json.dumps(data)),
    )


def update_activity(
    guild_id: int,
    *,
    channel_id: str | None = None,
    channel_name: str | None = None,
    user_id: str | None = None,
    user_name: str | None = None,
    hour: int | None = None,
    member_join: bool = False,
    member_leave: bool = False,
) -> None:
    """Increment activity counters; mirrors the logic from data.py's update_activity."""
    activity = load_activity(guild_id)

    today = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    cutoff = (
        datetime.datetime.utcnow() - datetime.timedelta(days=_INSIGHTS_MAX_DAYS)
    ).strftime("%Y-%m-%d")

    if channel_id is not None:
        days = activity.setdefault("msg_by_day", {})
        for d in list(days):
            if d < cutoff:
                del days[d]
        day = days.setdefault(today, {"total": 0, "by_channel": {}, "by_user": {}, "by_hour": {}})
        day["total"] = day.get("total", 0) + 1
        ch = day["by_channel"].setdefault(
            channel_id, {"name": channel_name or channel_id, "count": 0}
        )
        ch["count"] += 1
        if channel_name:
            ch["name"] = channel_name
        if user_id:
            u = day["by_user"].setdefault(user_id, {"name": user_name or user_id, "count": 0})
            u["count"] += 1
            if user_name:
                u["name"] = user_name
        if hour is not None:
            h = str(hour)
            day["by_hour"][h] = day["by_hour"].get(h, 0) + 1

    if member_join or member_leave:
        mdays = activity.setdefault("member_by_day", {})
        for d in list(mdays):
            if d < cutoff:
                del mdays[d]
        mday = mdays.setdefault(today, {"joins": 0, "leaves": 0})
        if member_join:
            mday["joins"] = mday.get("joins", 0) + 1
        if member_leave:
            mday["leaves"] = mday.get("leaves", 0) + 1

    save_activity(guild_id, activity)


# ── Temp actions ──────────────────────────────────────────────────────────────

def load_temp_actions(gid: int) -> dict:
    ban_rows = db.query("SELECT data_json FROM temp_bans WHERE guild_id=? ORDER BY pos", (gid,))
    to_rows = db.query("SELECT data_json FROM temp_timeouts WHERE guild_id=? ORDER BY pos", (gid,))
    return {
        "bans":     [json.loads(r["data_json"]) for r in ban_rows],
        "timeouts": [json.loads(r["data_json"]) for r in to_rows],
    }


def save_temp_actions(gid: int, data: dict) -> None:
    db.ensure_guild(gid)
    with db.transaction() as cx:
        cx.execute("DELETE FROM temp_bans WHERE guild_id=?", (gid,))
        cx.execute("DELETE FROM temp_timeouts WHERE guild_id=?", (gid,))
        for pos, b in enumerate(data.get("bans", [])):
            cx.execute(
                "INSERT INTO temp_bans (guild_id,pos,data_json) VALUES (?,?,?)",
                (gid, pos, json.dumps(b)),
            )
        for pos, t in enumerate(data.get("timeouts", [])):
            cx.execute(
                "INSERT INTO temp_timeouts (guild_id,pos,data_json) VALUES (?,?,?)",
                (gid, pos, json.dumps(t)),
            )
