"""
assets/repo/tickets.py — open_tickets and transcripts.
"""
from __future__ import annotations

import json

import assets.db as db

_TICKET_PROMOTED = {
    "user_id", "supporter_id", "created_at", "status", "title", "message",
    "button_id", "transcript",
}


# ── Open tickets ──────────────────────────────────────────────────────────────

def load_open_tickets(gid: int) -> dict:
    """Return {channel_id: {...}} shape used by the bot."""
    rows = db.query("SELECT * FROM tickets WHERE guild_id=?", (gid,))
    out: dict = {}
    for r in rows:
        extra = json.loads(r["extra_json"] or "{}")
        transcript = json.loads(r["transcript_json"] or "[]")
        entry: dict = {
            "user":         r["user_id"],
            "supporterid":  r["supporter_id"],
            "created_at":   r["created_at"],
            "status":       str(r["status"] or ""),
            "title":        str(r["title"] or ""),
            "message":      str(r["message"] or ""),
            "button_id":    str(r["button_id"] or ""),
            "transcript":   transcript,
        }
        entry.update(extra)
        out[r["channel_id"]] = entry
    return out


def save_open_tickets(gid: int, data: dict) -> None:
    db.ensure_guild(gid)
    with db.transaction() as cx:
        cx.execute("DELETE FROM tickets WHERE guild_id=?", (gid,))
        for ch_id, entry in data.items():
            extra = {k: v for k, v in entry.items()
                     if k not in {"user", "supporterid", "created_at", "status",
                                  "title", "message", "button_id", "transcript"}}
            cx.execute(
                "INSERT INTO tickets "
                "(guild_id,channel_id,user_id,supporter_id,created_at,status,"
                "title,message,button_id,transcript_json,extra_json) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    gid, str(ch_id),
                    entry.get("user"),
                    entry.get("supporterid"),
                    entry.get("created_at"),
                    str(entry.get("status", "")),
                    str(entry.get("title", "")),
                    str(entry.get("message", "")),
                    str(entry.get("button_id", "")),
                    json.dumps(entry.get("transcript", [])),
                    json.dumps(extra),
                ),
            )


# ── Transcripts ───────────────────────────────────────────────────────────────

def load_transcripts(gid: int) -> dict:
    rows = db.query("SELECT transcript_id, data_json FROM transcripts WHERE guild_id=?", (gid,))
    return {r["transcript_id"]: json.loads(r["data_json"]) for r in rows}


def save_transcripts(gid: int, data: dict) -> None:
    db.ensure_guild(gid)
    with db.transaction() as cx:
        cx.execute("DELETE FROM transcripts WHERE guild_id=?", (gid,))
        for tid, v in data.items():
            cx.execute(
                "INSERT INTO transcripts (guild_id,transcript_id,data_json) VALUES (?,?,?)",
                (gid, str(tid), json.dumps(v)),
            )
