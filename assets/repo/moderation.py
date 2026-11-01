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

def append_mod_event(gid: int, event: dict) -> int:
    """Insert one mod event (= one moderation case) and return its case number.
    Numbering and retention live in assets/repo/cases.py."""
    from assets.repo import cases
    return cases.insert_event(gid, event)


def load_mod_events(gid: int) -> list:
    """The BaxiInsights view of mod_events: only warn/mute/kick/ban (the other case types -
    unban, unmute, removed messages - are for the case file and would skew the numbers)."""
    rows = db.query(
        "SELECT * FROM mod_events WHERE guild_id=? AND type IN ('warn','mute','kick','ban') ORDER BY pos", (gid,))
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
        for pos, ev in enumerate(data, 1):   # case numbers start at 1
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


# ── Moderation review queue ─────────────────────────────────────────────────────

def _review_row_to_dict(r) -> dict:
    return {
        "pos":         r["pos"],
        "user_id":     str(r["user_id"]),
        "user_name":   str(r["user_name"] or ""),
        "kind":        str(r["kind"] or ""),
        "status":      str(r["status"] or "pending"),
        "context":     json.loads(r["context_json"] or "{}"),
        "created_at":  str(r["created_at"] or ""),
        "resolved_by": str(r["resolved_by"] or ""),
        "resolved_at": str(r["resolved_at"] or ""),
    }


def add_review_item(gid: int, user_id: int, user_name: str, kind: str, context: dict | None = None) -> int:
    """Append a pending review item; returns its pos. kind: join_gate|deleted_msg|prism_flag."""
    db.ensure_guild(gid)
    now = datetime.datetime.utcnow().isoformat()
    with db.transaction() as cx:
        row = cx.execute(
            "SELECT COALESCE(MAX(pos)+1,0) as next_pos FROM mod_review_queue WHERE guild_id=?", (gid,)
        ).fetchone()
        next_pos = row["next_pos"] if row else 0
        cx.execute(
            "INSERT INTO mod_review_queue "
            "(guild_id,pos,user_id,user_name,kind,status,context_json,created_at) "
            "VALUES (?,?,?,?,?,'pending',?,?)",
            (gid, next_pos, str(user_id), str(user_name), str(kind),
             json.dumps(context or {}), now),
        )
    return next_pos


def load_review_queue(gid: int, status: str | None = None) -> list:
    """Return review items (optionally filtered by status), newest first."""
    if status:
        rows = db.query(
            "SELECT * FROM mod_review_queue WHERE guild_id=? AND status=? ORDER BY pos DESC",
            (gid, status),
        )
    else:
        rows = db.query(
            "SELECT * FROM mod_review_queue WHERE guild_id=? ORDER BY pos DESC", (gid,)
        )
    return [_review_row_to_dict(r) for r in rows]


def resolve_review_item(gid: int, pos: int, status: str, resolved_by: str = "") -> dict | None:
    """Set a review item's status (approved|rejected) and return the updated item."""
    if status not in ("approved", "rejected", "pending"):
        return None
    now = datetime.datetime.utcnow().isoformat()
    db.execute(
        "UPDATE mod_review_queue SET status=?,resolved_by=?,resolved_at=? WHERE guild_id=? AND pos=?",
        (status, str(resolved_by), now, gid, pos),
    )
    rows = db.query("SELECT * FROM mod_review_queue WHERE guild_id=? AND pos=?", (gid, pos))
    return _review_row_to_dict(rows[0]) if rows else None


def add_review_item_for_message(gid: int, user_id: int, user_name: str, kind: str,
                                context: dict, message_id: int) -> int | None:
    """Like add_review_item, but at most one item per (kind, message) - whatever its
    status, so an edited message or a second run does not ask staff twice.
    Returns the new pos, or None if the message is already in the queue."""
    db.ensure_guild(gid)
    now = datetime.datetime.utcnow().isoformat()
    ctx = {**(context or {}), "message_id": str(message_id)}
    with db.transaction() as cx:
        if cx.execute(
            "SELECT 1 FROM mod_review_queue WHERE guild_id=? AND kind=? "
            "AND json_extract(context_json,'$.message_id')=? LIMIT 1",
            (gid, str(kind), str(message_id)),
        ).fetchone():
            return None
        row = cx.execute(
            "SELECT COALESCE(MAX(pos)+1,0) as next_pos FROM mod_review_queue WHERE guild_id=?", (gid,)
        ).fetchone()
        next_pos = row["next_pos"] if row else 0
        cx.execute(
            "INSERT INTO mod_review_queue "
            "(guild_id,pos,user_id,user_name,kind,status,context_json,created_at) "
            "VALUES (?,?,?,?,?,'pending',?,?)",
            (gid, next_pos, str(user_id), str(user_name), str(kind), json.dumps(ctx), now),
        )
    return next_pos


def update_pending_for_message(gid: int, kind: str, message_id: int, changes: dict) -> bool:
    """Merge *changes* into the context of the pending item for this message (an
    edited message re-checked). False if there is no pending item."""
    with db.transaction() as cx:
        row = cx.execute(
            "SELECT pos, context_json FROM mod_review_queue WHERE guild_id=? AND kind=? AND status='pending' "
            "AND json_extract(context_json,'$.message_id')=? LIMIT 1",
            (gid, str(kind), str(message_id)),
        ).fetchone()
        if not row:
            return False
        ctx = {**json.loads(row["context_json"] or "{}"), **changes}
        cx.execute("UPDATE mod_review_queue SET context_json=? WHERE guild_id=? AND pos=?",
                   (json.dumps(ctx), gid, row["pos"]))
    return True


def close_pending_for_message(gid: int, kind: str, message_id: int) -> bool:
    """Close the pending item for this message as 'expired' (no action, no label) and
    drop its excerpt - e.g. the author edited it into something harmless."""
    now = datetime.datetime.utcnow().isoformat()
    cur = db.execute(
        "UPDATE mod_review_queue SET status='expired',resolved_by='',resolved_at=?, "
        "context_json=json_set(context_json,'$.excerpt','') "
        "WHERE guild_id=? AND kind=? AND status='pending' AND json_extract(context_json,'$.message_id')=?",
        (now, gid, str(kind), str(message_id)),
    )
    return cur.rowcount > 0


def claim_review_item(gid: int, pos: int, status: str, resolved_by: str = "") -> bool:
    """Atomically move a *pending* item to *status*. False if someone else (or the
    expiry) got there first - the caller must not act then."""
    now = datetime.datetime.utcnow().isoformat()
    cur = db.execute(
        "UPDATE mod_review_queue SET status=?,resolved_by=?,resolved_at=? "
        "WHERE guild_id=? AND pos=? AND status='pending'",
        (str(status), str(resolved_by), now, gid, pos),
    )
    return cur.rowcount == 1


def release_review_item(gid: int, pos: int) -> None:
    """Undo claim_review_item when the action failed: the item is pending again."""
    db.execute(
        "UPDATE mod_review_queue SET status='pending',resolved_by='',resolved_at='' WHERE guild_id=? AND pos=?",
        (gid, pos),
    )


def blank_review_excerpt(gid: int, pos: int) -> None:
    """Drop the message text of a closed item (it is only needed while staff decide)."""
    db.execute(
        "UPDATE mod_review_queue SET context_json=json_set(context_json,'$.excerpt','') "
        "WHERE guild_id=? AND pos=? AND json_extract(context_json,'$.excerpt') IS NOT NULL",
        (gid, pos),
    )


def pending_review_summary(gid: int, kinds: tuple[str, ...]) -> tuple[dict[str, int], dict | None]:
    """({kind: pending count}, newest pending item) over *kinds* - for the staff notice."""
    marks = ",".join("?" * len(kinds))
    rows = db.query(
        f"SELECT kind, COUNT(*) AS n, MAX(pos) AS newest FROM mod_review_queue "
        f"WHERE guild_id=? AND status='pending' AND kind IN ({marks}) GROUP BY kind",
        (gid, *kinds),
    )
    counts = {str(r["kind"]): int(r["n"]) for r in rows}
    if not counts:
        return {}, None
    newest = max(int(r["newest"]) for r in rows)
    item = db.query("SELECT * FROM mod_review_queue WHERE guild_id=? AND pos=?", (gid, newest))
    return counts, (_review_row_to_dict(item[0]) if item else None)


def prune_closed_reviews(older_than: str) -> int:
    """Delete items closed (decided or expired) before *older_than* (ISO, UTC)."""
    cur = db.execute(
        "DELETE FROM mod_review_queue WHERE status!='pending' AND resolved_at!='' AND resolved_at < ?",
        (older_than,),
    )
    return cur.rowcount


def expire_review_items(kind: str, older_than: str) -> dict[int, int]:
    """Close pending items of *kind* created before *older_than* (ISO, UTC) as
    'expired'. Returns {guild_id: number expired}; empty (one indexed query) when
    nothing is due."""
    due = db.query(
        "SELECT guild_id, COUNT(*) AS n FROM mod_review_queue "
        "WHERE status='pending' AND kind=? AND created_at < ? GROUP BY guild_id",
        (str(kind), older_than),
    )
    if not due:
        return {}
    now = datetime.datetime.utcnow().isoformat()
    db.execute(
        "UPDATE mod_review_queue SET status='expired',resolved_by='',resolved_at=?, "
        "context_json=json_set(context_json,'$.excerpt','') "
        "WHERE status='pending' AND kind=? AND created_at < ?",
        (now, str(kind), older_than),
    )
    return {int(r["guild_id"]): int(r["n"]) for r in due}
