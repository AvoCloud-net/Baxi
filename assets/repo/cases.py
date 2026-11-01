"""
assets/repo/cases.py - moderation cases, notes and appeals (storage only).

A *case* is a row of `mod_events`: its `pos` is the case number (#123), running per
guild and never reused. Everything that is not a plain column (duration, warning id,
appeal state, ...) lives in `extra_json`. Notes have their own table; appeals are
items of kind `appeal` in `mod_review_queue` (see moderation.appeals for the flow).

Retention (see CASE_KEEP_DAYS / NOTE_KEEP_DAYS): cases and notes are kept one year.
"""
from __future__ import annotations

import datetime
import json

import assets.db as db

CASE_KEEP_DAYS = 365
NOTE_KEEP_DAYS = 365
APPEAL_WINDOW_DAYS = 14

# Case types that appear in BaxiInsights' moderation numbers (everything else is
# only for the case file).
INSIGHT_TYPES = ("warn", "mute", "kick", "ban")
# Types a user can appeal. An unban or unmute is already the good news.
APPEALABLE_TYPES = ("warn", "mute", "kick", "ban", "filter", "delete")

_PROMOTED = ("type", "user_id", "user_name", "mod_id", "mod_name", "reason", "timestamp")


def _now() -> datetime.datetime:
    return datetime.datetime.utcnow()


def _row_to_case(r) -> dict:
    case = {
        "no":        int(r["pos"]),
        "type":      str(r["type"] or ""),
        "user_id":   str(r["user_id"] or ""),
        "user_name": str(r["user_name"] or ""),
        "mod_id":    str(r["mod_id"] or ""),
        "mod_name":  str(r["mod_name"] or ""),
        "reason":    str(r["reason"] or ""),
        "timestamp": str(r["timestamp"] or ""),
    }
    try:
        extra = json.loads(r["extra_json"] or "{}")
    except ValueError:
        extra = {}
    for k, v in extra.items():
        case.setdefault(k, v)
    return case


# ── Case numbers ─────────────────────────────────────────────────────────────

def insert_event(gid: int, event: dict) -> int:
    """Insert one mod event and return its case number. The number comes from a per-guild
    counter that only goes up (pruning old rows never frees a number). Prunes cases older
    than CASE_KEEP_DAYS in the same transaction."""
    db.ensure_guild(gid)
    with db.transaction() as cx:
        row = cx.execute(
            "SELECT COALESCE(MAX(pos),0)+1 AS n, "
            "COALESCE((SELECT next_no FROM mod_case_counter WHERE guild_id=?),1) AS c "
            "FROM mod_events WHERE guild_id=?", (gid, gid),
        ).fetchone()
        no = max(int(row["n"]), int(row["c"]), 1)
        extra = {k: v for k, v in event.items() if k not in _PROMOTED}
        cx.execute(
            "INSERT INTO mod_events "
            "(guild_id,pos,type,user_id,user_name,mod_id,mod_name,reason,timestamp,extra_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                gid, no,
                event.get("type", ""),
                str(event.get("user_id", "")),
                str(event.get("user_name", "")),
                str(event.get("mod_id", "")),
                str(event.get("mod_name", "")),
                str(event.get("reason", "")),
                str(event.get("timestamp", "") or _now().isoformat()),
                json.dumps(extra),
            ),
        )
        cx.execute(
            "INSERT INTO mod_case_counter (guild_id,next_no) VALUES (?,?) "
            "ON CONFLICT(guild_id) DO UPDATE SET next_no=excluded.next_no",
            (gid, no + 1),
        )
        cutoff = (_now() - datetime.timedelta(days=CASE_KEEP_DAYS)).isoformat()
        cx.execute("DELETE FROM mod_events WHERE guild_id=? AND timestamp < ?", (gid, cutoff))
    return no


def counts_for_user(gid: int, uid: int | str) -> tuple[dict[str, int], str | None]:
    """({type: n} of the user's cases that are not lifted, timestamp of the latest case of any
    kind). A query, so the summary stays right beyond what the timeline list shows."""
    rows = db.query(
        "SELECT type, COUNT(*) AS n FROM mod_events WHERE guild_id=? AND user_id=? "
        "AND json_extract(extra_json,'$.lifted') IS NULL GROUP BY type", (gid, str(uid)))
    last = db.query("SELECT MAX(timestamp) AS t FROM mod_events WHERE guild_id=? AND user_id=?", (gid, str(uid)))
    return {str(r["type"]): int(r["n"]) for r in rows}, (last[0]["t"] if last else None)


def delete_case(gid: int, no: int) -> None:
    """Drop a case whose action failed after the number was taken. The number is not reused."""
    db.execute("DELETE FROM mod_events WHERE guild_id=? AND pos=?", (gid, no))


def get_case(gid: int, no: int) -> dict | None:
    rows = db.query("SELECT * FROM mod_events WHERE guild_id=? AND pos=?", (gid, no))
    return _row_to_case(rows[0]) if rows else None


def cases_for_user(gid: int, uid: int | str, limit: int = 500) -> list[dict]:
    """A user's cases in this guild, newest first."""
    rows = db.query(
        "SELECT * FROM mod_events WHERE guild_id=? AND user_id=? ORDER BY pos DESC LIMIT ?",
        (gid, str(uid), limit),
    )
    return [_row_to_case(r) for r in rows]


def recent_case(gid: int, uid: int | str, types: tuple[str, ...], within_s: int) -> dict | None:
    """The newest case of one of *types* for this user in the last *within_s* seconds."""
    since = (_now() - datetime.timedelta(seconds=within_s)).isoformat()
    marks = ",".join("?" * len(types))
    rows = db.query(
        f"SELECT * FROM mod_events WHERE guild_id=? AND user_id=? AND type IN ({marks}) "
        f"AND timestamp >= ? ORDER BY pos DESC LIMIT 1",
        (gid, str(uid), *types, since),
    )
    return _row_to_case(rows[0]) if rows else None


def update_case(gid: int, no: int, changes: dict) -> bool:
    """Merge *changes* into a case's extra data (a None value removes the key)."""
    with db.transaction() as cx:
        row = cx.execute("SELECT extra_json FROM mod_events WHERE guild_id=? AND pos=?", (gid, no)).fetchone()
        if not row:
            return False
        extra = json.loads(row["extra_json"] or "{}")
        for k, v in changes.items():
            if v is None:
                extra.pop(k, None)
            else:
                extra[k] = v
        cx.execute("UPDATE mod_events SET extra_json=? WHERE guild_id=? AND pos=?",
                   (json.dumps(extra), gid, no))
    return True


def lift_warn_cases(gid: int, warn_id: str | None = None, user_id: str | None = None) -> int:
    """Mark the warn case(s) of a removed warning as lifted (by warning id, or all of a user's)."""
    if warn_id:
        cond, arg = "json_extract(extra_json,'$.warn_id')=?", str(warn_id)
    elif user_id:
        cond, arg = "user_id=?", str(user_id)
    else:
        return 0
    return db.execute(
        f"UPDATE mod_events SET extra_json=json_set(extra_json,'$.lifted','1') "
        f"WHERE guild_id=? AND type='warn' AND {cond} AND json_extract(extra_json,'$.lifted') IS NULL",
        (gid, arg)).rowcount


def user_guilds_with_cases(uid: int | str, since: str) -> list[int]:
    """Guilds where this user has a case newer than *since* (ISO, UTC)."""
    rows = db.query(
        "SELECT DISTINCT guild_id FROM mod_events WHERE user_id=? AND timestamp >= ? "
        "AND type IN ('warn','mute','kick','ban','filter','delete')",
        (str(uid), since),
    )
    return [int(r["guild_id"]) for r in rows]


def chatfilter_message(log_id: str) -> str:
    """The text of a chat-filter log entry (the log is kept under the global id 1001)."""
    rows = db.query("SELECT data_json FROM chatfilter_log WHERE guild_id=1001 AND log_id=?", (str(log_id),))
    return str(json.loads(rows[0]["data_json"]).get("message", "")) if rows else ""


def filter_hits(gid: int, uid: int | str) -> list[dict]:
    """Chat-filter hits (filter_events, no message text) of a user, newest first."""
    rows = db.query(
        "SELECT data_json FROM filter_events WHERE guild_id=? AND json_extract(data_json,'$.user_id')=? "
        "ORDER BY pos DESC LIMIT 200", (gid, str(uid)),
    )
    return [json.loads(r["data_json"]) for r in rows]


def search_users(gid: int, text: str, limit: int = 8) -> list[dict]:
    """Users with cases or notes whose name contains *text* (also people who left)."""
    like = "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    rows = db.query(
        "SELECT user_id, user_name FROM mod_events WHERE guild_id=? AND user_name LIKE ? ESCAPE '\\' "
        "UNION SELECT user_id, user_name FROM mod_notes WHERE guild_id=? AND user_name LIKE ? ESCAPE '\\' "
        "LIMIT ?", (gid, like, gid, like, limit),
    )
    return [{"id": str(r["user_id"]), "name": str(r["user_name"])} for r in rows]


# ── Appeals (atomic) ─────────────────────────────────────────────────────────

def submit_appeal(gid: int, no: int, user_id: int | str, user_name: str, text: str) -> tuple[str, int | None]:
    """Create the appeal for case *no*, all in one transaction so two clicks (or the
    dashboard and the DM button) cannot both succeed. Returns (status, queue pos):
    ok | not_found | not_yours | not_appealable | lifted | expired | already."""
    now = _now()
    with db.transaction() as cx:
        row = cx.execute("SELECT * FROM mod_events WHERE guild_id=? AND pos=?", (gid, no)).fetchone()
        if not row:
            return "not_found", None
        case = _row_to_case(row)
        if case["user_id"] != str(user_id):
            return "not_yours", None
        if case["type"] not in APPEALABLE_TYPES:
            return "not_appealable", None
        if case.get("lifted"):
            return "lifted", None
        if case.get("appeal"):
            return "already", None
        try:
            when = datetime.datetime.fromisoformat(case["timestamp"])
        except ValueError:
            when = now - datetime.timedelta(days=APPEAL_WINDOW_DAYS + 1)
        if now - when > datetime.timedelta(days=APPEAL_WINDOW_DAYS):
            return "expired", None
        pos = int(cx.execute(
            "SELECT COALESCE(MAX(pos)+1,0) AS p FROM mod_review_queue WHERE guild_id=?", (gid,)
        ).fetchone()["p"])
        ctx = {
            "case_no": int(no), "case_type": case["type"], "case_reason": case["reason"],
            "case_time": case["timestamp"], "case_mod": case["mod_name"],
            "text": text,
        }
        cx.execute(
            "INSERT INTO mod_review_queue "
            "(guild_id,pos,user_id,user_name,kind,status,context_json,created_at) "
            "VALUES (?,?,?,?,'appeal','pending',?,?)",
            (gid, pos, str(user_id), str(user_name), json.dumps(ctx), now.isoformat()),
        )
        extra = json.loads(row["extra_json"] or "{}")
        extra.update({"appeal": "open", "appeal_at": now.isoformat(), "appeal_pos": pos})
        cx.execute("UPDATE mod_events SET extra_json=? WHERE guild_id=? AND pos=?",
                   (json.dumps(extra), gid, no))
    return "ok", pos


def set_review_context(gid: int, pos: int, changes: dict) -> None:
    """Merge *changes* into a queue item's context."""
    with db.transaction() as cx:
        row = cx.execute("SELECT context_json FROM mod_review_queue WHERE guild_id=? AND pos=?",
                         (gid, pos)).fetchone()
        if row:
            ctx = {**json.loads(row["context_json"] or "{}"), **changes}
            cx.execute("UPDATE mod_review_queue SET context_json=? WHERE guild_id=? AND pos=?",
                       (json.dumps(ctx), gid, pos))


# ── Notes ────────────────────────────────────────────────────────────────────

def _row_to_note(r) -> dict:
    return {
        "id": int(r["id"]), "user_id": str(r["user_id"]), "user_name": str(r["user_name"] or ""),
        "author_id": str(r["author_id"]), "author_name": str(r["author_name"] or ""),
        "text": str(r["text"] or ""), "created_at": str(r["created_at"] or ""),
    }


def add_note(gid: int, user_id: int | str, user_name: str, author_id: int | str,
             author_name: str, text: str) -> int:
    text = (text or "").strip()
    if not text:
        raise ValueError("empty note")
    db.ensure_guild(gid)
    with db.transaction() as cx:
        nid = int(cx.execute("SELECT COALESCE(MAX(id),0)+1 AS n FROM mod_notes WHERE guild_id=?",
                             (gid,)).fetchone()["n"])
        cx.execute(
            "INSERT INTO mod_notes (guild_id,id,user_id,user_name,author_id,author_name,text,created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (gid, nid, str(user_id), str(user_name), str(author_id), str(author_name), text,
             _now().isoformat()),
        )
    return nid


def notes_for_user(gid: int, uid: int | str) -> list[dict]:
    rows = db.query("SELECT * FROM mod_notes WHERE guild_id=? AND user_id=? ORDER BY id DESC",
                    (gid, str(uid)))
    return [_row_to_note(r) for r in rows]


def get_note(gid: int, nid: int) -> dict | None:
    rows = db.query("SELECT * FROM mod_notes WHERE guild_id=? AND id=?", (gid, nid))
    return _row_to_note(rows[0]) if rows else None


def delete_note(gid: int, nid: int) -> bool:
    return db.execute("DELETE FROM mod_notes WHERE guild_id=? AND id=?", (gid, nid)).rowcount > 0


# ── Retention ────────────────────────────────────────────────────────────────

def prune_old() -> tuple[int, int]:
    """Delete cases and notes past their retention in ALL guilds (the per-guild insert
    only prunes the guild it writes to). Returns (cases, notes)."""
    # first make sure every guild's counter exists, so deleting its newest rows cannot free a number
    db.execute("INSERT OR IGNORE INTO mod_case_counter (guild_id, next_no) "
               "SELECT guild_id, MAX(pos) + 1 FROM mod_events GROUP BY guild_id")
    c = db.execute("DELETE FROM mod_events WHERE timestamp < ?",
                   ((_now() - datetime.timedelta(days=CASE_KEEP_DAYS)).isoformat(),)).rowcount
    n = db.execute("DELETE FROM mod_notes WHERE created_at < ?",
                   ((_now() - datetime.timedelta(days=NOTE_KEEP_DAYS)).isoformat(),)).rowcount
    return c, n


# ── Statistics ───────────────────────────────────────────────────────────────

def actions_by_mod(gid: int, since: str) -> list[dict]:
    """[{mod_id, mod_name, counts: {type: n}}] for cases since *since*, sorted by name
    (never by volume - this is an overview, not a ranking)."""
    rows = db.query(
        "SELECT mod_id, type, COUNT(*) AS n, MAX(pos) AS last_pos FROM mod_events "
        "WHERE guild_id=? AND timestamp >= ? AND type IN ('warn','mute','kick','ban','filter','delete','unban','unmute') "
        "GROUP BY mod_id, type", (gid, since),
    )
    out: dict[str, dict] = {}
    newest: dict[str, int] = {}
    for r in rows:
        m = out.setdefault(str(r["mod_id"]), {"mod_id": str(r["mod_id"]), "mod_name": "?", "counts": {}})
        m["counts"][str(r["type"])] = int(r["n"])
        if int(r["last_pos"]) >= newest.get(m["mod_id"], -1):     # show the name they use now
            newest[m["mod_id"]] = int(r["last_pos"])
    for mid, pos in newest.items():
        name = db.query("SELECT mod_name FROM mod_events WHERE guild_id=? AND pos=?", (gid, pos))
        out[mid]["mod_name"] = str(name[0]["mod_name"] or "?") if name else "?"
    return sorted(out.values(), key=lambda m: m["mod_name"].lower())


def review_handle_seconds(gid: int, since: str) -> list[float]:
    """Seconds between creation and decision for queue items decided by a person since *since*."""
    rows = db.query(
        "SELECT created_at, resolved_at FROM mod_review_queue WHERE guild_id=? "
        "AND status IN ('approved','rejected') AND resolved_by!='' AND resolved_at >= ?", (gid, since),
    )
    out = []
    for r in rows:
        try:
            a = datetime.datetime.fromisoformat(r["created_at"])
            b = datetime.datetime.fromisoformat(r["resolved_at"])
        except (TypeError, ValueError):
            continue
        out.append(max(0.0, (b - a).total_seconds()))
    return out


def open_counts(gid: int) -> dict[str, int]:
    rows = db.query(
        "SELECT kind, COUNT(*) AS n FROM mod_review_queue WHERE guild_id=? AND status='pending' GROUP BY kind",
        (gid,),
    )
    return {str(r["kind"]): int(r["n"]) for r in rows}
