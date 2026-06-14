"""
assets/repo/engagement.py — giveaways, polls, suggestion_votes, flag_quiz_active.
"""
from __future__ import annotations

import json

import assets.db as db

_GIVEAWAY_PROMOTED = {"channel_id", "reward", "winner_count", "end_time",
                      "host_id", "ended", "image_url", "winner_message"}
_POLL_PROMOTED = {"question", "answers", "show_votes", "image_url",
                  "channel_id", "end_time", "closed", "user_votes"}


# ── Giveaways ─────────────────────────────────────────────────────────────────

def load_giveaways(gid: int) -> dict:
    rows = db.query("SELECT * FROM giveaways WHERE guild_id=?", (gid,))
    out: dict = {}
    for r in rows:
        extra = json.loads(r["extra_json"] or "{}")
        part_rows = db.query(
            "SELECT user_id FROM giveaway_participant WHERE guild_id=? AND message_id=? ORDER BY pos",
            (gid, r["message_id"]),
        )
        participants = [int(p["user_id"]) for p in part_rows]
        entry: dict = {
            "channel_id":     str(r["channel_id"] or ""),
            "reward":         str(r["reward"] or ""),
            "winner_count":   int(r["winner_count"] or 1),
            "end_time":       int(r["end_time"] or 0),
            "host_id":        int(r["host_id"] or 0),
            "ended":          bool(r["ended"]),
            "image_url":      r["image_url"],
            "winner_message": str(r["winner_message"] or ""),
            "participants":   participants,
        }
        entry.update(extra)
        out[r["message_id"]] = entry
    return out


def save_giveaways(gid: int, data: dict) -> None:
    db.ensure_guild(gid)
    with db.transaction() as cx:
        cx.execute("DELETE FROM giveaway_participant WHERE guild_id=?", (gid,))
        cx.execute("DELETE FROM giveaways WHERE guild_id=?", (gid,))
        for msg_id, entry in data.items():
            extra = {k: v for k, v in entry.items()
                     if k not in _GIVEAWAY_PROMOTED and k != "participants"}
            cx.execute(
                "INSERT INTO giveaways "
                "(guild_id,message_id,channel_id,reward,winner_count,end_time,"
                "host_id,ended,image_url,winner_message,extra_json) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    gid, str(msg_id),
                    str(entry.get("channel_id", "")),
                    str(entry.get("reward", "")),
                    int(entry.get("winner_count", 1)),
                    int(entry.get("end_time", 0)),
                    int(entry.get("host_id", 0)),
                    int(bool(entry.get("ended", False))),
                    entry.get("image_url"),
                    str(entry.get("winner_message", "")),
                    json.dumps(extra),
                ),
            )
            for pos, uid in enumerate(entry.get("participants", [])):
                cx.execute(
                    "INSERT INTO giveaway_participant (guild_id,message_id,pos,user_id) VALUES (?,?,?,?)",
                    (gid, str(msg_id), pos, str(uid)),
                )


# ── Polls ─────────────────────────────────────────────────────────────────────

def load_polls(gid: int) -> dict:
    rows = db.query("SELECT * FROM polls WHERE guild_id=?", (gid,))
    out: dict = {}
    for r in rows:
        extra = json.loads(r["extra_json"] or "{}")
        vote_rows = db.query(
            "SELECT user_id, choice FROM poll_vote WHERE guild_id=? AND message_id=?",
            (gid, r["message_id"]),
        )
        user_votes = {v["user_id"]: int(v["choice"]) for v in vote_rows}
        answers = json.loads(r["answers_json"] or "[]")
        entry: dict = {
            "question":   str(r["question"] or ""),
            "answers":    answers,
            "show_votes": bool(r["show_votes"]),
            "image_url":  r["image_url"],
            "channel_id": str(r["channel_id"] or ""),
            "end_time":   float(r["end_time"]) if r["end_time"] is not None else None,
            "closed":     bool(r["closed"]),
            "user_votes": user_votes,
        }
        entry.update(extra)
        out[r["message_id"]] = entry
    return out


def save_polls(gid: int, data: dict) -> None:
    db.ensure_guild(gid)
    with db.transaction() as cx:
        cx.execute("DELETE FROM poll_vote WHERE guild_id=?", (gid,))
        cx.execute("DELETE FROM polls WHERE guild_id=?", (gid,))
        for msg_id, entry in data.items():
            extra = {k: v for k, v in entry.items() if k not in _POLL_PROMOTED}
            cx.execute(
                "INSERT INTO polls "
                "(guild_id,message_id,question,answers_json,show_votes,image_url,"
                "channel_id,end_time,closed,extra_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    gid, str(msg_id),
                    str(entry.get("question", "")),
                    json.dumps(entry.get("answers", [])),
                    int(bool(entry.get("show_votes", True))),
                    entry.get("image_url"),
                    str(entry.get("channel_id", "")),
                    entry.get("end_time"),
                    int(bool(entry.get("closed", False))),
                    json.dumps(extra),
                ),
            )
            for uid, choice in entry.get("user_votes", {}).items():
                cx.execute(
                    "INSERT INTO poll_vote (guild_id,message_id,user_id,choice) VALUES (?,?,?,?)",
                    (gid, str(msg_id), str(uid), str(choice)),
                )


# ── Suggestion votes ──────────────────────────────────────────────────────────

def load_suggestion_votes(gid: int) -> dict:
    rows = db.query("SELECT suggestion_id, data_json FROM suggestion_votes WHERE guild_id=?", (gid,))
    return {r["suggestion_id"]: json.loads(r["data_json"]) for r in rows}


def save_suggestion_votes(gid: int, data: dict) -> None:
    db.ensure_guild(gid)
    with db.transaction() as cx:
        cx.execute("DELETE FROM suggestion_votes WHERE guild_id=?", (gid,))
        for sid, v in data.items():
            cx.execute(
                "INSERT INTO suggestion_votes (guild_id,suggestion_id,data_json) VALUES (?,?,?)",
                (gid, str(sid), json.dumps(v)),
            )


# ── Flag quiz active ──────────────────────────────────────────────────────────

def load_flag_quiz_active(gid: int) -> dict:
    rows = db.query("SELECT data_json FROM flag_quiz_active WHERE guild_id=?", (gid,))
    if not rows:
        return {}
    return json.loads(rows[0]["data_json"] or "{}")


def save_flag_quiz_active(gid: int, data: dict) -> None:
    db.ensure_guild(gid)
    db.execute(
        "INSERT INTO flag_quiz_active (guild_id,data_json) VALUES (?,?) "
        "ON CONFLICT(guild_id) DO UPDATE SET data_json=excluded.data_json",
        (gid, json.dumps(data)),
    )
