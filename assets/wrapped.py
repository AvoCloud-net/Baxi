"""Server Wrapped - the year of a server, once a year, on every server (no opt-in).

Timeline (constants below, Europe/Vienna):
  all year   the daily archive copies finished days of the activity blob into wrapped_days, so
             the recap covers more than the blob's 90 days; messages per user and channel are
             counted in memory and flushed every few minutes ("your favourite channel").
  1-7 Dec    quote of the year vote: a poll (assets/poll.py) in the quotes channel with the
             quotes of the year that got the most reactions (filled up with other quotes).
  15 Dec     release: the recap is computed once per server and stored; the staff channel
             (assets/staff.py, or the owner by DM) gets a preview with "Share". Share (Manage
             Server) posts the public version in a channel of their choice. /wrapped opens for
             everyone (ephemeral, personal cards).
  1 Feb      the stored recaps are deleted and /wrapped says it is over.

Every step is recorded in wrapped_state (per guild) or schema_meta (global), so a restart never
sends anything twice. Members can keep their name out of the server recap with
`/wrapped top_lists:hide`; the filter is applied when a card is shown, never baked in.

Cards follow the card image pattern (CLAUDE.md): all copy in the embed, the PNG
(assets/wrapped_card.py) holds avatars, icons, bars and the big figures.

Testing before December: console `wrapped <guild_id> [preview|vote [minutes]|status|reset]`
(assets/console.py -> admin_command). Bot admins can use /wrapped on every server before the
release.
"""
from __future__ import annotations

import asyncio
import datetime
import io
import json
import random
import time
from typing import Awaitable, Callable
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks

import assets.data as datasys
import assets.db as db
import assets.pulse as pulse
import assets.wrapped_card as card
import config.config as config
from assets.repo.runtime import load_activity
from assets.share import set_task_status
from reds_simple_logger import Logger

logger = Logger()

# ── Schedule (change here, nowhere else) ─────────────────────────────────────
TZ = ZoneInfo("Europe/Vienna")
YEAR = 2026                  # the season: bump it (and restart) to start the next one
VOTE_START = datetime.datetime(YEAR, 12, 1, 12, 0, tzinfo=TZ)
VOTE_END = datetime.datetime(YEAR, 12, 8, 0, 0, tzinfo=TZ)        # vote runs 1-7 Dec
RELEASE = datetime.datetime(YEAR, 12, 15, 12, 0, tzinfo=TZ)
CLOSE = datetime.datetime(YEAR + 1, 2, 1, 0, 0, tzinfo=TZ)        # recaps deleted, /wrapped over

VOTE_CANDIDATES = 5          # quotes in the vote
VOTE_MIN_HOURS_LEFT = 24     # no vote is started (late, after downtime) with less time left
MIN_MESSAGES = 50            # below this (and no voice, stars or quotes) there is no recap
MIN_TOP_PEOPLE = 2           # a top list row needs at least this many people
BATCH = 20                   # guilds per tick (every 5 min) for vote and release
_CACHE_TTL = 900             # resolved message/quote of the year per guild (seconds)
_KEEP_DAYS = 400             # archived days older than this are always deleted

_UTC = datetime.timezone.utc
_FLOOR = f"{YEAR}-01-01"
_UNTIL = RELEASE.astimezone(_UTC).date()          # data up to the day before the release
_META_VOTE = f"wrapped:{YEAR}:vote"
_META_RELEASE = f"wrapped:{YEAR}:release"
_META_CLOSED = f"wrapped:{YEAR}:closed"
_META_ARCHIVED = f"wrapped:{YEAR}:archived_on"
_META_CHANNELS_SINCE = f"wrapped:{YEAR}:channels_since"
_FILE = "wrapped.png"


def now_utc() -> datetime.datetime:
    return datetime.datetime.now(_UTC)


def phase(now: datetime.datetime | None = None) -> str:
    """collect -> vote -> wait -> release -> closed."""
    now = now or now_utc()
    if now >= CLOSE:
        return "closed"
    if now >= RELEASE:
        return "release"
    if now >= VOTE_END:
        return "wait"
    if now >= VOTE_START:
        return "vote"
    return "collect"


def _ts(dt: datetime.datetime) -> int:
    return int(dt.timestamp())


def collecting(now: datetime.datetime | None = None) -> bool:
    """Counting and archiving run until the release (the recap only uses data before it) and
    never after the season is closed, so nothing of the next year is stored before it starts."""
    return (now or now_utc()) < RELEASE


# ── Meta flags (global, cached) ──────────────────────────────────────────────
_meta_cache: dict[str, str | None] = {}


def _meta(key: str) -> str | None:
    if key not in _meta_cache:
        _meta_cache[key] = db.schema_meta_get(key)
    return _meta_cache[key]


def _set_meta(key: str, value: str) -> None:
    db.schema_meta_set(key, value)
    _meta_cache[key] = value


# ── Per-guild state, opt-out ─────────────────────────────────────────────────

def get_state(gid: int) -> dict:
    rows = db.query("SELECT data_json FROM wrapped_state WHERE guild_id=? AND year=?", (gid, YEAR))
    return json.loads(rows[0]["data_json"] or "{}") if rows else {}


def update_state(gid: int, **changes) -> dict:
    """Merge ``changes`` into the guild's state (None deletes a key). Atomic."""
    db.ensure_guild(gid)
    with db.transaction() as cx:
        row = cx.execute("SELECT data_json FROM wrapped_state WHERE guild_id=? AND year=?",
                         (gid, YEAR)).fetchone()
        state = json.loads(row[0] or "{}") if row else {}
        for k, v in changes.items():
            if v is None:
                state.pop(k, None)
            else:
                state[k] = v
        cx.execute("INSERT INTO wrapped_state (guild_id,year,data_json) VALUES (?,?,?) "
                   "ON CONFLICT(guild_id,year) DO UPDATE SET data_json=excluded.data_json",
                   (gid, YEAR, json.dumps(state)))
    return state


_hidden_cache: dict[int, frozenset[str]] | None = None    # whole (small) table, kept in memory


def _hidden_all() -> dict[int, frozenset[str]]:
    global _hidden_cache
    if _hidden_cache is None:
        by_guild: dict[int, set[str]] = {}
        for r in db.query("SELECT guild_id, user_id FROM wrapped_optout"):
            by_guild.setdefault(int(r["guild_id"]), set()).add(r["user_id"])
        _hidden_cache = {g: frozenset(u) for g, u in by_guild.items()}
    return _hidden_cache


def hidden_users(gid: int) -> frozenset[str]:
    return _hidden_all().get(int(gid), frozenset())


def set_hidden(gid: int, user_id: int, hidden: bool) -> None:
    """Opt out of (or back into) being named. Opting out also stops the per-channel counter for
    the member and deletes what it already counted. The entry stays after the season ends."""
    global _hidden_cache
    db.ensure_guild(gid)
    if hidden:
        with db.transaction() as cx:
            cx.execute("INSERT OR IGNORE INTO wrapped_optout (guild_id,user_id) VALUES (?,?)", (gid, str(user_id)))
            cx.execute("DELETE FROM wrapped_user_channels WHERE guild_id=? AND user_id=?", (gid, str(user_id)))
        for k in [k for k in _channel_counts if k[0] == gid and k[2] == str(user_id)]:
            _channel_counts.pop(k, None)
    else:
        db.execute("DELETE FROM wrapped_optout WHERE guild_id=? AND user_id=?", (gid, str(user_id)))
    _hidden_cache = None


# ── Collecting: daily archive + per-channel counter ──────────────────────────

def archive_days(today: datetime.date | None = None) -> int:
    """Copy finished days (UTC) of every guild's activity blob into wrapped_days. Idempotent:
    re-writes the last archived day and adds the newer ones. Returns the rows written."""
    day_now = today or now_utc().date()
    if day_now >= CLOSE.astimezone(_UTC).date() or day_now > _UNTIL + datetime.timedelta(days=7):
        return 0                      # recap data is complete / season over: nothing of the next year is stored
    # Only days before the release go in: the recap never uses later ones.
    today_key = min(day_now, _UNTIL).isoformat()
    last = {int(r["guild_id"]): r["m"] for r in db.query(
        "SELECT guild_id, MAX(day) AS m FROM wrapped_days GROUP BY guild_id")}
    written = 0
    for r in db.query("SELECT guild_id FROM activity"):
        gid = int(r["guild_id"])
        try:
            act = load_activity(gid)
        except Exception as e:
            logger.error(f"[Wrapped] archive: activity of {gid} unreadable: {e}")
            continue
        start = max(_FLOOR, last.get(gid) or _FLOOR)
        msg, voice, member = (act.get("msg_by_day") or {}, act.get("voice_by_day") or {},
                              act.get("member_by_day") or {})
        days = sorted(k for k in {*msg, *voice, *member} if start <= k < today_key)
        if not days:
            continue
        rows = [(gid, k, json.dumps(msg.get(k) or {}), json.dumps(voice.get(k) or {}),
                 json.dumps(member.get(k) or {})) for k in days]
        with db.transaction() as cx:
            cx.executemany("INSERT OR REPLACE INTO wrapped_days "
                           "(guild_id,day,msg_json,voice_json,member_json) VALUES (?,?,?,?,?)", rows)
        written += len(rows)
    # Safety net for the retention promise (privacy page): nothing older than ~13 months stays,
    # even if the schedule constants are not moved on to the next year.
    cutoff = (day_now - datetime.timedelta(days=_KEEP_DAYS)).isoformat()
    with db.transaction() as cx:
        cx.execute("DELETE FROM wrapped_days WHERE day<?", (cutoff,))
        cx.execute("DELETE FROM wrapped_user_channels WHERE year<?", (int(cutoff[:4]),))
    return written


_channel_counts: dict[tuple[int, int, str, str], int] = {}


def count_message(message: discord.Message) -> None:
    """Hot path: one dict increment, flushed by the task."""
    if message.guild is None or message.author.bot or message.webhook_id is not None:
        return
    if not collecting() or str(message.author.id) in hidden_users(message.guild.id):
        return
    key = (message.guild.id, YEAR, str(message.author.id), str(message.channel.id))
    _channel_counts[key] = _channel_counts.get(key, 0) + 1


def _write_channel_counts(batch: dict[tuple[int, int, str, str], int]) -> None:
    for gid in {k[0] for k in batch}:
        db.ensure_guild(gid)
    with db.transaction() as cx:
        cx.executemany(
            "INSERT INTO wrapped_user_channels (guild_id,year,user_id,channel_id,count) VALUES (?,?,?,?,?) "
            "ON CONFLICT(guild_id,year,user_id,channel_id) DO UPDATE SET count=count+excluded.count",
            [(*k, n) for k, n in batch.items()])
    if _meta(_META_CHANNELS_SINCE) is None:
        _set_meta(_META_CHANNELS_SINCE, now_utc().date().isoformat())


async def flush_channel_counts() -> int:
    """Write the counted messages. The dict is swapped on the loop thread, so a message
    counted while the write runs lands in the next batch instead of getting lost."""
    global _channel_counts
    if not _channel_counts:
        return 0
    batch, _channel_counts = _channel_counts, {}
    try:
        await asyncio.to_thread(_write_channel_counts, batch)
    except Exception as e:
        logger.error(f"[Wrapped] channel count flush failed: {e}")
        for k, n in batch.items():   # keep them for the next try
            _channel_counts[k] = _channel_counts.get(k, 0) + n
        return 0
    return len(batch)


# ── Aggregation (sync, runs in a thread) ─────────────────────────────────────

def _days(gid: int, until: datetime.date) -> tuple[dict, dict, dict]:
    """(msg, voice, member) per UTC day key in [YEAR-01-01, until): archive + live blob."""
    until_key = until.isoformat()
    msg: dict = {}
    voice: dict = {}
    member: dict = {}
    for r in db.query("SELECT day, msg_json, voice_json, member_json FROM wrapped_days "
                      "WHERE guild_id=? AND day>=? AND day<?", (gid, _FLOOR, until_key)):
        msg[r["day"]] = json.loads(r["msg_json"] or "{}")
        voice[r["day"]] = json.loads(r["voice_json"] or "{}")
        member[r["day"]] = json.loads(r["member_json"] or "{}")
    act = load_activity(gid)
    for target, live in ((msg, act.get("msg_by_day")), (voice, act.get("voice_by_day")),
                         (member, act.get("member_by_day"))):
        for k, v in (live or {}).items():
            if _FLOOR <= k < until_key:
                target[k] = v      # the live blob is the newest copy of a day
    return msg, voice, member


def _local(day: datetime.date, tracker_hour: int, tz: ZoneInfo) -> datetime.datetime:
    """A tracker bucket (UTC date, Vienna hour) as local time in ``tz`` (see pulse._local_slot)."""
    vienna_day = day + datetime.timedelta(days=1) if tracker_hour < pulse._tracker_offset_hours(day) else day
    return datetime.datetime(vienna_day.year, vienna_day.month, vienna_day.day, tracker_hour, 30,
                             tzinfo=pulse._TRACKER_TZ).astimezone(tz)


def _top(d: dict[str, dict], key: str, n: int = 10, minimum: int = 1) -> list[list]:
    items = sorted(((uid, v) for uid, v in d.items() if v.get(key, 0) >= minimum),
                   key=lambda x: (-x[1][key], x[0]))
    return [[uid, v.get("name") or uid, v[key]] for uid, v in items[:n]]


def compute(gid: int, *, tz: ZoneInfo, until: datetime.date, joined: list[datetime.datetime],
            humans: int, state: dict) -> tuple[dict, dict[str, dict]]:
    """The server recap and the per-user part. ``joined``: joined_at of the current human members."""
    msg, voice, member = _days(gid, until)
    users: dict[str, dict] = {}

    def user(uid: str, name: str | None) -> dict:
        u = users.setdefault(uid, {"name": name or uid, "msgs": 0, "voice": 0, "days": {}})
        if name:
            u["name"] = name
        return u

    hours = [0] * 24
    weekdays = [0] * 7
    local_days: dict[str, int] = {}
    total = 0
    data_days = []
    for k in sorted(msg):
        day = msg[k] or {}
        n = int(day.get("total", 0))
        if n <= 0:
            continue
        data_days.append(k)
        total += n
        d = datetime.date.fromisoformat(k)
        for h, cnt in (day.get("by_hour") or {}).items():
            try:
                loc = _local(d, int(h), tz)
            except (ValueError, OverflowError):
                continue
            hours[loc.hour] += int(cnt)
            weekdays[loc.weekday()] += int(cnt)
            lk = loc.date().isoformat()
            local_days[lk] = local_days.get(lk, 0) + int(cnt)
        for uid, uv in (day.get("by_user") or {}).items():
            u = user(uid, uv.get("name"))
            c = int(uv.get("count", 0))
            u["msgs"] += c
            u["days"][k] = u["days"].get(k, 0) + c

    voice_total = 0
    for k in sorted(voice):
        day = voice[k] or {}
        secs = int(day.get("total", 0))
        if secs > 0:
            data_days.append(k)
        voice_total += secs
        for uid, uv in (day.get("by_user") or {}).items():
            user(uid, uv.get("name"))["voice"] += int(uv.get("secs", 0))

    joins = sum(int((member[k] or {}).get("joins", 0)) for k in member)
    leaves = sum(int((member[k] or {}).get("leaves", 0)) for k in member)
    member_days = [k for k in member if (member[k] or {}).get("joins") or (member[k] or {}).get("leaves")]

    join_months = [0] * 12
    for j in joined:
        if j is None:
            continue
        loc = j.astimezone(tz)
        if loc.year == YEAR and loc.date() < until:
            join_months[loc.month - 1] += 1

    busiest = max(local_days.items(), key=lambda kv: (kv[1], kv[0])) if local_days else None

    # Starboard (IDs only; the message is fetched when the card is shown).
    star_rows = db.query(
        "SELECT message_id, channel_id, author_id, stars FROM starboard_entries "
        "WHERE guild_id=? AND message_created_at>=? AND message_created_at<? AND stars>0 "
        "ORDER BY stars DESC, message_created_at ASC", (gid, _FLOOR, until.isoformat()))
    stars = [[r["message_id"], r["channel_id"], r["author_id"], int(r["stars"])] for r in star_rows]

    # Quotes of the year and their reactions.
    quote_rows = db.query(
        "SELECT quote_id, author_id, author_name FROM quotes WHERE guild_id=? AND created_at>=? AND created_at<?",
        (gid, _FLOOR, until.isoformat()))
    reactions = {int(r["quote_id"]): int(r["n"]) for r in db.query(
        "SELECT quote_id, COUNT(*) AS n FROM quote_reactions WHERE guild_id=? GROUP BY quote_id", (gid,))}
    quoted: dict[str, dict] = {}
    for r in quote_rows:
        aid = str(r["author_id"] or "")
        if not aid:
            continue
        q = quoted.setdefault(aid, {"name": r["author_name"] or aid, "n": 0, "best": None, "best_r": -1})
        q["n"] += 1
        rc = reactions.get(int(r["quote_id"]), 0)
        if rc > q["best_r"] or (rc == q["best_r"] and int(r["quote_id"]) > (q["best"] or 0)):
            q["best"], q["best_r"] = int(r["quote_id"]), rc

    # Favourite channel per user (counted since the counter exists).
    fav: dict[str, tuple[str, int]] = {}
    for r in db.query("SELECT user_id, channel_id, count FROM wrapped_user_channels WHERE guild_id=? AND year=?",
                      (gid, YEAR)):
        if int(r["count"]) > fav.get(r["user_id"], ("", 0))[1]:
            fav[r["user_id"]] = (r["channel_id"], int(r["count"]))

    ranking = [uid for uid, _name, _n in _top(users, "msgs", n=len(users))]
    rank = {uid: i + 1 for i, uid in enumerate(ranking)}

    per_user: dict[str, dict] = {}
    best_star: dict[str, list] = {}
    for mid, cid, aid, n in stars:      # stars are sorted: the first per author is their best
        best_star.setdefault(str(aid), [mid, cid, n])
    for uid in set(users) | set(quoted) | set(best_star):
        u = users.get(uid, {"msgs": 0, "voice": 0, "days": {}})
        q = quoted.get(uid)
        days = u["days"]
        busy = max(days.items(), key=lambda kv: (kv[1], kv[0])) if days else None
        mon: dict[str, int] = {}
        for k, c in days.items():
            mon[k[:7]] = mon.get(k[:7], 0) + c
        per_user[uid] = {
            "msgs": u["msgs"], "voice": u["voice"], "rank": rank.get(uid), "ranked": len(ranking),
            "active_days": sum(1 for c in days.values() if c > 0),
            "busy_day": list(busy) if busy else None, "months": mon,
            "channel": list(fav[uid]) if uid in fav else None,
            "star": best_star.get(uid),
            "quoted": q["n"] if q else 0,
            "best_quote": q["best"] if q else None,
        }

    result = {
        "year": YEAR, "until": until.isoformat(),
        "first_day": min(data_days + member_days) if (data_days or member_days) else None,
        "messages": total, "voice_secs": voice_total,
        "active_users": sum(1 for u in users.values() if u["msgs"] > 0 or u["voice"] >= 60),
        "hours": hours, "weekdays": weekdays,
        "busiest_day": list(busiest) if busiest else None,
        "joins": joins, "leaves": leaves, "new_members": sum(join_months), "join_months": join_months,
        "humans": humans,
        "top_text": _top(users, "msgs"), "top_voice": _top(users, "voice", minimum=60),
        "stars": stars[:15],
        "quotes_total": len(quote_rows),
        "top_quoted": [[aid, v["name"], v["n"]] for aid, v in
                       sorted(quoted.items(), key=lambda x: (-x[1]["n"], x[0]))[:10]],
        "qoty": _quote_of_year(gid, state, reactions, {int(r["quote_id"]) for r in quote_rows}),
        "channels_since": _meta(_META_CHANNELS_SINCE),
    }
    return result, per_user


def _quote_of_year(gid: int, state: dict, reactions: dict[int, int], year_ids: set[int]) -> list[dict]:
    """The vote winner; without a vote (or without votes) the quotes with the most reactions,
    best first. The card takes the first one that may be shown."""
    vote = state.get("vote") or {}
    qids = vote.get("quote_ids") or []
    out: list[dict] = []
    if vote.get("message_id") and qids:
        counts = {int(r["choice"]): int(r["n"]) for r in db.query(
            "SELECT choice, COUNT(*) AS n FROM poll_vote WHERE guild_id=? AND message_id=? GROUP BY choice",
            (gid, str(vote["message_id"])))}
        # Every candidate that got votes, most votes first (then most reactions): the picker at
        # show time takes the first one that may be shown.
        order = sorted((i for i in range(len(qids)) if counts.get(i, 0) > 0),
                       key=lambda i: (-counts[i], -reactions.get(int(qids[i]), 0), i))
        out = [{"quote_id": int(qids[i]), "votes": counts[i], "via": "vote"} for i in order]
    seen = {c["quote_id"] for c in out}
    ranked = sorted(((qid, n) for qid, n in reactions.items() if qid in year_ids and n > 0 and qid not in seen),
                    key=lambda x: (-x[1], x[0]))
    return out + [{"quote_id": qid, "reactions": n, "via": "reactions"} for qid, n in ranked[:5]]


def has_content(res: dict | None) -> bool:
    if not res:
        return False
    return (res["messages"] >= MIN_MESSAGES or res["voice_secs"] >= 3600
            or bool(res["stars"]) or res["quotes_total"] > 0)


def _store(gid: int, res: dict, per_user: dict[str, dict]) -> None:
    db.ensure_guild(gid)
    user_rows = [(gid, YEAR, uid, json.dumps(v)) for uid, v in per_user.items()]   # before taking the DB lock
    result_json = json.dumps(res)
    with db.transaction() as cx:
        cx.execute("DELETE FROM wrapped_users WHERE guild_id=? AND year=?", (gid, YEAR))
        cx.executemany("INSERT INTO wrapped_users (guild_id,year,user_id,data_json) VALUES (?,?,?,?)", user_rows)
        cx.execute("INSERT INTO wrapped_results (guild_id,year,data_json,computed_at) VALUES (?,?,?,?) "
                   "ON CONFLICT(guild_id,year) DO UPDATE SET data_json=excluded.data_json, "
                   "computed_at=excluded.computed_at", (gid, YEAR, result_json, int(time.time())))


def load_result(gid: int) -> tuple[dict | None, int]:
    rows = db.query("SELECT data_json, computed_at FROM wrapped_results WHERE guild_id=? AND year=?", (gid, YEAR))
    if not rows:
        return None, 0
    return json.loads(rows[0]["data_json"]), int(rows[0]["computed_at"] or 0)


def load_user(gid: int, user_id: int) -> dict | None:
    rows = db.query("SELECT data_json FROM wrapped_users WHERE guild_id=? AND year=? AND user_id=?",
                    (gid, YEAR, str(user_id)))
    return json.loads(rows[0]["data_json"]) if rows else None


_compute_locks: dict[int, asyncio.Lock] = {}


async def ensure_result(guild: discord.Guild, *, force: bool = False) -> dict | None:
    """The stored recap, computed (once) when missing or outdated. After the release a recap from
    before the release (test run) counts as outdated; before it, one older than an hour does."""
    async with _compute_locks.setdefault(guild.id, asyncio.Lock()):
        res, at = load_result(guild.id)
        now = now_utc()
        fresh = at >= _ts(RELEASE) if now >= RELEASE else time.time() - at < 3600
        if res is not None and fresh and not force:
            return res
        until = min(now.date() + datetime.timedelta(days=1), _UNTIL)
        tz = pulse.resolve_tz(pulse.load_cfg(guild.id).get("timezone"))
        joined = [m.joined_at for m in guild.members if not m.bot]
        humans = len(joined)
        state = get_state(guild.id)

        def work():
            r, users = compute(guild.id, tz=tz, until=until, joined=joined, humans=humans, state=state)
            _store(guild.id, r, users)
            return r

        _highlight_cache.pop(guild.id, None)
        return await asyncio.to_thread(work)


# ── Formatting ───────────────────────────────────────────────────────────────

def _t(guild_id: int) -> dict:
    return datasys.load_lang_file(guild_id)["wrapped"]


def _n(value: int, t: dict) -> str:
    return f"{int(value):,}".replace(",", t["thousands_sep"])


def _hours(secs: int, t: dict) -> str:
    if secs >= 3600:
        return t["hours"].format(n=_n(round(secs / 3600), t))
    return t["minutes"].format(n=max(int(secs) // 60, 0))


def _day_ts(key: str, tz: ZoneInfo = TZ) -> str:
    d = datetime.date.fromisoformat(key)
    return f"<t:{_ts(datetime.datetime(d.year, d.month, d.day, 12, tzinfo=tz))}:D>"


def _who(guild: discord.Guild | None, uid: str, name: str) -> str:
    if guild is not None and str(uid).isdigit() and guild.get_member(int(uid)) is not None:
        return f"<@{uid}>"
    return f"**{discord.utils.escape_markdown(str(name))}**"


def _avatar_of(guild: discord.Guild | None, uid: str, name: str) -> tuple[str | None, str]:
    m = guild.get_member(int(uid)) if guild is not None and str(uid).isdigit() else None
    url = m.display_avatar.with_format("png").with_size(128).url if m is not None else None
    return url, (str(name or "?")[:1] or "?").upper()


def _guild_icon(guild: discord.Guild) -> str | None:
    return guild.icon.with_format("png").with_size(256).url if guild.icon else None


def _clip(text: str, n: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _quote_block(text: str, n: int = 500) -> str:
    return "> " + discord.utils.escape_mentions(_clip(text, n))


def _since_line(res: dict, t: dict) -> str:
    """Where the numbers start (when Baxi only has part of the year) and where they end."""
    out = []
    first = res.get("first_day")
    if first and first > f"{YEAR}-01-08":
        out.append(t["since"].format(date=_day_ts(first)))
    last = datetime.date.fromisoformat(res["until"]) - datetime.timedelta(days=1)    # "until" is exclusive
    out.append(t["until"].format(date=_day_ts(last.isoformat())))
    return "\n\n" + " ".join(out)


# ── Highlights resolved at show time (opt-out, deleted messages, chatfilter) ──
_highlight_cache: dict[int, tuple[float, frozenset, dict]] = {}


async def _clean(guild_id: int, channel_id: int, user_id: int, text: str) -> bool:
    if not text:
        return True
    from assets.message.chatfilter import text_is_clean
    return await text_is_clean(guild_id, channel_id, user_id, text)


def is_public_channel(guild: discord.Guild, channel_id) -> bool:
    """May something from this channel be shown to the whole server? Visible to @everyone (view
    and read history), not NSFW; for a thread the parent decides, and private threads never."""
    ch = guild.get_channel_or_thread(int(channel_id)) if str(channel_id).isdigit() else None
    if ch is None:
        return False
    if isinstance(ch, discord.Thread):
        if ch.is_private():
            return False
        ch = ch.parent
        if ch is None:
            return False
    try:
        perms = ch.permissions_for(guild.default_role)
        return bool(perms.view_channel and perms.read_message_history and not ch.is_nsfw())
    except Exception:
        return False


def _may_name(guild: discord.Guild, author_id, hidden: frozenset) -> bool:
    """False for opted-out members, bots and members who left (an empty id is a non-member quote)."""
    aid = str(author_id or "")
    if aid in hidden:
        return False
    if not aid.isdigit():
        return aid == ""
    m = guild.get_member(int(aid))
    return m is not None and not m.bot


async def _message_of_year(guild: discord.Guild, res: dict, hidden: frozenset) -> dict | None:
    tries = 0
    for mid, cid, aid, n in res.get("stars", []):
        if not _may_name(guild, aid, hidden) or not is_public_channel(guild, cid):
            continue
        if tries >= 6:
            break
        tries += 1
        channel = guild.get_channel_or_thread(int(cid)) if str(cid).isdigit() else None
        if channel is None or not hasattr(channel, "fetch_message"):
            continue
        try:
            msg = await channel.fetch_message(int(mid))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            continue      # deleted (or no access): take the next one
        if msg.author.bot or not await _clean(guild.id, int(cid), int(aid), msg.content):
            continue
        return {"author_id": str(aid), "name": msg.author.display_name, "stars": n,
                "url": msg.jump_url, "content": msg.content or ""}
    return None


def quote_is_showable(guild: discord.Guild, row, hidden: frozenset) -> bool:
    """A quote may be shown publicly when its author may be named and it came from a public
    channel (the source channel, or else the channel it was posted in)."""
    if not (row["content"] or "").strip() or not _may_name(guild, row["author_id"], hidden):
        return False
    return is_public_channel(guild, row["source_channel_id"]) or is_public_channel(guild, row["post_channel_id"])


async def _quote_of_year_row(guild: discord.Guild, res: dict, hidden: frozenset) -> dict | None:
    for cand in res.get("qoty", []):
        rows = db.query("SELECT * FROM quotes WHERE guild_id=? AND quote_id=?", (guild.id, int(cand["quote_id"])))
        if not rows:
            continue
        r = rows[0]
        aid = str(r["author_id"] or "")
        if not quote_is_showable(guild, r, hidden):
            continue
        if not await _clean(guild.id, int(r["source_channel_id"] or 0) if str(r["source_channel_id"]).isdigit() else 0,
                            int(aid) if aid.isdigit() else 0, r["content"]):
            continue
        return {**cand, "author_id": aid, "name": r["author_name"] or "?", "content": r["content"] or ""}
    return None


async def _highlights(guild: discord.Guild, res: dict, hidden: frozenset) -> dict:
    hit = _highlight_cache.get(guild.id)
    if hit and hit[1] == hidden and time.monotonic() - hit[0] < _CACHE_TTL:
        return hit[2]
    out = {"moty": await _message_of_year(guild, res, hidden),
           "qoty": await _quote_of_year_row(guild, res, hidden)}
    _highlight_cache[guild.id] = (time.monotonic(), hidden, out)
    return out


# ── Cards ────────────────────────────────────────────────────────────────────
# A card is an async callable returning (embed, png bytes or None). A failing renderer
# degrades to the embed alone - every figure is in the embed as well.
Card = Callable[[], Awaitable[tuple[discord.Embed, bytes | None]]]


def _card(embed: discord.Embed, render: Callable[[], Awaitable[io.BytesIO]] | None) -> Card:
    async def build():
        if render is None:
            return embed, None
        try:
            buf = await render()
            return embed, buf.getvalue()
        except Exception as e:
            logger.error(f"[Wrapped] card render failed: {type(e).__name__}: {e}")
            return embed, None
    return build


def _embed(title: str, description: str, author: str, icon: str | None = None) -> discord.Embed:
    e = discord.Embed(title=title, description=description, color=config.Discord.color)
    e.set_author(name=author, icon_url=icon)
    return e


def _peak(values: list[int]) -> int | None:
    return values.index(max(values)) if values and max(values) > 0 else None


async def server_cards(guild: discord.Guild, res: dict, t: dict, *, overview_only: bool = False) -> list[Card]:
    hidden = hidden_users(guild.id)
    tz = pulse.resolve_tz(pulse.load_cfg(guild.id).get("timezone"))
    author = t["author"].format(year=YEAR, server=guild.name)
    icon = _guild_icon(guild)
    cards: list[Card] = []

    # 1. The year in numbers.
    e = _embed(t["overview_title"], t["overview_desc"].format(year=YEAR, server=discord.utils.escape_markdown(guild.name))
               + _since_line(res, t), author, icon)
    figures = [("text", _n(res["messages"], t))]
    e.add_field(name=t["messages"], value=f"**{_n(res['messages'], t)}**", inline=True)
    if res["voice_secs"] >= 60:
        figures.append(("voice", _hours(res["voice_secs"], t)))
        e.add_field(name=t["voice"], value=f"**{_hours(res['voice_secs'], t)}**", inline=True)
    if res["active_users"]:
        figures.append(("users", _n(res["active_users"], t)))
        e.add_field(name=t["active"], value=f"**{_n(res['active_users'], t)}**", inline=True)
    initial = (guild.name[:1] or "?").upper()
    cards.append(_card(e, lambda f=figures, i=initial: card.figures_card(icon, i, f)))
    if overview_only:
        return cards

    # 2. Rhythm: hours of the day, busiest day and weekday.
    peak_hour = _peak(res["hours"])
    if res["messages"] >= MIN_MESSAGES and peak_hour is not None:
        e = _embed(t["rhythm_title"], t["rhythm_desc"], author, icon)
        if res.get("busiest_day"):
            day, n = res["busiest_day"]
            e.add_field(name=t["busiest_day"], value=t["busiest_day_value"].format(date=_day_ts(day, tz), n=_n(n, t)),
                        inline=False)
        e.add_field(name=t["peak_hour"], value=t["hour_value"].format(hour=f"{peak_hour:02d}"), inline=True)
        wd = _peak(res["weekdays"])
        if wd is not None:
            e.add_field(name=t["busiest_weekday"], value=t["weekdays"][wd], inline=True)
        hours, labels = res["hours"], [f"{h:02d}" if h % 3 == 0 else None for h in range(24)]
        cards.append(_card(e, lambda v=hours, h=peak_hour, lb=labels: card.bars_card(v, h, lb)))

    # 3. New members (current members by join month - covers the whole year).
    if res["new_members"] > 0:
        e = _embed(t["members_title"], t["members_desc"].format(n=_n(res["new_members"], t), year=YEAR,
                                                                total=_n(res["humans"], t)), author, icon)
        if res["joins"] or res["leaves"]:
            first = res.get("first_day") or _FLOOR
            e.add_field(name=t["joins_leaves"].format(date=_day_ts(first)),
                        value=f"+{_n(res['joins'], t)} / −{_n(res['leaves'], t)}", inline=False)
        months = res["join_months"]
        last = datetime.date.fromisoformat(res["until"]).month if res["until"][:4] == str(YEAR) else 12
        values = months[:last]
        labels = t["months"][:last]
        hi = _peak(values)
        cards.append(_card(e, lambda v=values, h=hi, lb=labels: card.bars_card(v, h, lb)))

    # 4. Top lists (opt-out applied here).
    top_text = [x for x in res["top_text"] if _may_name(guild, x[0], hidden)][:3]     # not opted out, still a member
    top_voice = [x for x in res["top_voice"] if _may_name(guild, x[0], hidden)][:3]
    rows = []
    e = _embed(t["top_title"], t["top_desc"], author, icon)
    if len(top_text) >= MIN_TOP_PEOPLE:
        e.add_field(name=t["top_text"], value="\n".join(
            f"`{i}.` {_who(guild, uid, name)} · {_n(n, t)}" for i, (uid, name, n) in enumerate(top_text, 1)), inline=False)
        rows.append(("text", [_avatar_of(guild, uid, name) for uid, name, _ in top_text]))
    if len(top_voice) >= MIN_TOP_PEOPLE:
        e.add_field(name=t["top_voice"], value="\n".join(
            f"`{i}.` {_who(guild, uid, name)} · {_hours(n, t)}" for i, (uid, name, n) in enumerate(top_voice, 1)),
            inline=False)
        rows.append(("voice", [_avatar_of(guild, uid, name) for uid, name, _ in top_voice]))
    if rows:
        cards.append(_card(e, lambda r=rows: card.podium_card(r)))

    hl = await _highlights(guild, res, hidden)

    # 5. Message of the year.
    moty = hl.get("moty")
    if moty:
        text = _quote_block(moty["content"]) if moty["content"] else t["moty_no_text"]
        e = _embed(t["moty_title"], t["moty_desc"].format(user=_who(guild, moty["author_id"], moty["name"]))
                   + f"\n\n{text}\n\n{t['stars'].format(n=_n(moty['stars'], t))} · [{t['jump']}]({moty['url']})",
                   author, icon)
        spot = [(*_avatar_of(guild, moty["author_id"], moty["name"]), "star", _n(moty["stars"], t))]
        cards.append(_card(e, lambda sp=spot: card.spotlight_card(sp)))

    # 6. Quotes: quote of the year + most quoted person.
    qoty = hl.get("qoty")
    most = next((x for x in res["top_quoted"] if _may_name(guild, x[0], hidden) and x[2] >= 2), None)
    if qoty or most:
        e = _embed(t["quotes_title"], t["quotes_desc"].format(n=_n(res["quotes_total"], t)), author, icon)
        spots = []
        if qoty:
            how = (t["qoty_vote"].format(n=_n(qoty["votes"], t)) if qoty["via"] == "vote"
                   else t["qoty_reactions"])
            e.add_field(name=t["qoty"], value=(_quote_block(qoty["content"], 600) + "\n"
                        + t["qoty_by"].format(user=_who(guild, qoty["author_id"], qoty["name"])) + f"\n{how}")[:1024],
                        inline=False)
            figure = qoty["votes"] if qoty["via"] == "vote" else qoty["reactions"]
            spots.append((*_avatar_of(guild, qoty["author_id"], qoty["name"]),
                          "vote" if qoty["via"] == "vote" else "quote", _n(figure, t)))
        if most:
            uid, name, n = most
            e.add_field(name=t["most_quoted"], value=t["most_quoted_value"].format(user=_who(guild, uid, name),
                                                                                  n=_n(n, t)), inline=False)
            spots.append((*_avatar_of(guild, uid, name), "quote", _n(n, t)))
        cards.append(_card(e, lambda sp=spots: card.spotlight_card(sp)))

    return cards


async def personal_cards(guild: discord.Guild, member: discord.abc.User, res: dict, me: dict | None,
                         t: dict) -> list[Card]:
    author = t["me_author"].format(year=YEAR, server=guild.name)
    icon = _guild_icon(guild)
    avatar = member.display_avatar.with_format("png").with_size(256).url
    initial = (member.display_name[:1] or "?").upper()
    tz = pulse.resolve_tz(pulse.load_cfg(guild.id).get("timezone"))
    if not me or (me["msgs"] == 0 and me["voice"] < 60 and not me["star"] and not me["quoted"]):
        e = _embed(t["me_title"], t["me_empty"].format(year=YEAR), author, icon)
        return [_card(e, None)]

    cards: list[Card] = []
    # 1. Your year.
    e = _embed(t["me_title"], t["me_desc"].format(year=YEAR, server=discord.utils.escape_markdown(guild.name))
               + _since_line(res, t), author, icon)
    figures = []
    if me["msgs"]:
        figures.append(("text", _n(me["msgs"], t)))
        e.add_field(name=t["messages"], value=f"**{_n(me['msgs'], t)}**", inline=True)
    if me["voice"] >= 60:
        figures.append(("voice", _hours(me["voice"], t)))
        e.add_field(name=t["voice"], value=f"**{_hours(me['voice'], t)}**", inline=True)
    if me.get("rank"):
        figures.append(("trophy", f"#{me['rank']}"))
        e.add_field(name=t["me_rank"], value=t["me_rank_value"].format(rank=me["rank"], total=_n(me["ranked"], t)),
                    inline=True)
    if figures:
        cards.append(_card(e, lambda f=figures: card.figures_card(avatar, initial, f)))
    else:
        cards.append(_card(e, None))

    # 2. Your rhythm: messages per month (only the months Baxi counted), busiest day, channel.
    if me["msgs"] >= 10:
        e = _embed(t["me_rhythm_title"], t["me_rhythm_desc"], author, icon)
        if me.get("busy_day"):
            day, n = me["busy_day"]
            e.add_field(name=t["me_busy_day"], value=t["busiest_day_value"].format(date=_day_ts(day, tz), n=_n(n, t)),
                        inline=False)
        e.add_field(name=t["me_active_days"], value=f"**{_n(me['active_days'], t)}**", inline=True)
        if me.get("channel"):
            cid, n = me["channel"]
            since = res.get("channels_since")
            value = t["me_channel_value"].format(channel=f"<#{cid}>", n=_n(n, t))
            if since and since > f"{YEAR}-01-08":
                value += "\n" + t["me_channel_since"].format(date=_day_ts(since))
            e.add_field(name=t["me_channel"], value=value, inline=True)
        first = (res.get("first_day") or _FLOOR)[:7]
        last = res["until"][:7] if res["until"][:4] == str(YEAR) else f"{YEAR}-12"
        keys = [f"{YEAR}-{m:02d}" for m in range(1, 13) if first <= f"{YEAR}-{m:02d}" <= last]
        values = [int(me["months"].get(k, 0)) for k in keys]
        labels = [t["months"][int(k[5:]) - 1] for k in keys]
        hi = _peak(values)
        cards.append(_card(e, lambda v=values, h=hi, lb=labels: card.bars_card(v, h, lb)))

    # 3. Your highlights: most-starred message, how often you were quoted.
    spots = []
    e = _embed(t["me_highlights_title"], t["me_highlights_desc"], author, icon)
    if me.get("star"):
        mid, cid, n = me["star"]
        url = f"https://discord.com/channels/{guild.id}/{cid}/{mid}"
        e.add_field(name=t["me_star"], value=f"{t['stars'].format(n=_n(n, t))} · [{t['jump']}]({url})", inline=False)
        spots.append((None, None, "star", _n(n, t)))
    if me.get("quoted"):
        e.add_field(name=t["me_quoted"], value=f"**{_n(me['quoted'], t)}**", inline=False)
        rows = db.query("SELECT content, source_channel_id FROM quotes WHERE guild_id=? AND quote_id=?",
                        (guild.id, int(me["best_quote"] or 0)))
        if rows and rows[0]["content"]:
            cid = int(rows[0]["source_channel_id"]) if str(rows[0]["source_channel_id"]).isdigit() else 0
            if await _clean(guild.id, cid, member.id, rows[0]["content"]):
                e.add_field(name=t["me_best_quote"], value=_quote_block(rows[0]["content"], 600)[:1024], inline=False)
        spots.append((None, None, "quote", _n(me["quoted"], t)))
    if spots:
        cards.append(_card(e, lambda sp=spots: card.spotlight_card(sp)))
    return cards


# ── Views ────────────────────────────────────────────────────────────────────

async def _say_error(interaction: discord.Interaction, t: dict) -> None:
    """The generic error text, as a follow-up (or the first response). Never raises."""
    try:
        if interaction.response.is_done():
            await interaction.followup.send(t["error"], ephemeral=True)
        else:
            await interaction.response.send_message(t["error"], ephemeral=True)
    except Exception:
        pass


class CardPager(discord.ui.View):
    """Ephemeral Back / Next through a list of cards. Only the person who opened it can click."""

    def __init__(self, cards: list[Card], owner_id: int, t: dict):
        super().__init__(timeout=600)
        self.cards, self.owner_id, self.t = cards, owner_id, t
        self.index = 0
        self._done: dict[int, tuple[discord.Embed, bytes | None]] = {}
        self.message: discord.WebhookMessage | None = None
        self.back.label, self.next.label = t["btn_back"], t["btn_next"]

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message(self.t["not_yours"], ephemeral=True)
        return False

    async def on_error(self, interaction: discord.Interaction, error: Exception, item) -> None:
        logger.error(f"[Wrapped] pager: {type(error).__name__}: {error}")
        await _say_error(interaction, self.t)

    async def page(self, index: int) -> dict:
        """send/edit kwargs for page ``index``; rendered once, then reused."""
        self.index = max(0, min(index, len(self.cards) - 1))
        if self.index not in self._done:
            self._done[self.index] = await self.cards[self.index]()
        embed, png = self._done[self.index]
        embed = embed.copy()
        if len(self.cards) > 1:
            embed.set_footer(text=self.t["footer"].format(year=YEAR, n=self.index + 1, total=len(self.cards)))
        self.back.disabled = self.index == 0
        self.next.disabled = self.index >= len(self.cards) - 1
        if len(self.cards) <= 1:
            self.clear_items()
        out: dict = {"embed": embed}
        if png is not None:
            embed.set_image(url=f"attachment://{_FILE}")
            out["files"] = [discord.File(io.BytesIO(png), filename=_FILE)]
        else:
            out["files"] = []
        return out

    async def _go(self, interaction: discord.Interaction, step: int):
        await interaction.response.defer()
        kw = await self.page(self.index + step)
        await interaction.edit_original_response(embed=kw["embed"], attachments=kw["files"], view=self)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary)
    async def back(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await self._go(interaction, -1)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.primary)
    async def next(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await self._go(interaction, 1)

    async def on_timeout(self) -> None:
        """Take the buttons off the message (best effort: the follow-up token lives 15 minutes)."""
        if self.message is not None:
            try:
                await self.message.edit(view=None)
            except Exception:
                pass


async def _send_pager(interaction: discord.Interaction, cards: list[Card], t: dict) -> None:
    pager = CardPager(cards, interaction.user.id, t)
    kw = await pager.page(0)
    send = {"embed": kw["embed"], "ephemeral": True}
    if kw["files"]:
        send["files"] = kw["files"]
    if pager.children:
        send["view"] = pager
    pager.message = await interaction.followup.send(wait=True, **send)


def _buttons(guild_id: int, t: dict, *, share: bool) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(WrappedButton("cards", guild_id, YEAR, t["btn_cards"], discord.ButtonStyle.primary))
    if share:
        view.add_item(WrappedButton("share", guild_id, YEAR, t["btn_share"], discord.ButtonStyle.secondary))
    else:
        view.add_item(WrappedButton("me", guild_id, YEAR, t["btn_me"], discord.ButtonStyle.secondary))
    return view


class WrappedButton(discord.ui.DynamicItem[discord.ui.Button],
                    template=r"wrapped:(?P<action>cards|me|share):(?P<gid>\d+):(?P<year>\d{4})"):
    """Buttons on the staff preview and the public post. Routed by custom_id, so they keep
    working after a restart."""

    def __init__(self, action: str, guild_id: int, year: int, label: str | None = None,
                 style: discord.ButtonStyle = discord.ButtonStyle.secondary):
        super().__init__(discord.ui.Button(label=label, style=style,
                                           custom_id=f"wrapped:{action}:{guild_id}:{year}"))
        self.action, self.guild_id, self.year = action, int(guild_id), int(year)

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match):
        return cls(match["action"], int(match["gid"]), int(match["year"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        t = _t(self.guild_id)
        try:
            guild = interaction.client.get_guild(self.guild_id)
            if guild is None or self.year != YEAR or phase() == "closed":
                return await interaction.response.send_message(t["over"].format(year=self.year), ephemeral=True)
            if self.action == "share":
                return await _start_share(interaction, guild, t)
            await interaction.response.defer(ephemeral=True, thinking=True)
            if self.action == "me":
                return await open_personal(interaction, guild, interaction.user)
            res = await ensure_result(guild)
            if not has_content(res):
                return await interaction.followup.send(t["nothing"].format(year=YEAR), ephemeral=True)
            await _send_pager(interaction, await server_cards(guild, res, t), t)
        except Exception as e:
            logger.error(f"[Wrapped] button {self.action} @ {self.guild_id}: {type(e).__name__}: {e}")
            await _say_error(interaction, t)


# ── Personal ─────────────────────────────────────────────────────────────────

def _is_bot_admin(user_id: int) -> bool:
    try:
        from assets.repo import load_admins
        return int(user_id) in load_admins()
    except Exception:
        return False


async def open_personal(interaction: discord.Interaction, guild: discord.Guild, user: discord.abc.User) -> None:
    """Follow-up with the personal cards (interaction already deferred, ephemeral)."""
    t = _t(guild.id)
    p = phase()
    if p == "closed":
        return await interaction.followup.send(t["over"].format(year=YEAR), ephemeral=True)
    if p != "release" and not get_state(guild.id).get("test_open") and not _is_bot_admin(user.id):
        return await interaction.followup.send(
            t["not_yet"].format(year=YEAR, date=f"<t:{_ts(RELEASE)}:D>"), ephemeral=True)
    res = await ensure_result(guild)
    if res is None:
        return await interaction.followup.send(t["nothing"].format(year=YEAR), ephemeral=True)
    me = load_user(guild.id, user.id)
    member = guild.get_member(user.id) or user
    await _send_pager(interaction, await personal_cards(guild, member, res, me, t), t)


# ── Share ────────────────────────────────────────────────────────────────────

def _can_share(guild: discord.Guild, user: discord.abc.User) -> bool:
    m = guild.get_member(user.id)
    return m is not None and (m.guild_permissions.manage_guild or guild.owner_id == m.id)


def _postable(guild: discord.Guild, channel) -> bool:
    if not isinstance(channel, discord.TextChannel):
        return False
    perms = channel.permissions_for(guild.me)
    return perms.view_channel and perms.send_messages and perms.embed_links and perms.attach_files


class _ShareView(discord.ui.View):
    """Channel pick. Inside the server a channel select; in the owner's DM (no server context
    for a channel select) a plain list of the channels Baxi can post in."""

    def __init__(self, guild: discord.Guild, user_id: int, t: dict, *, in_guild: bool):
        super().__init__(timeout=300)
        self.guild, self.user_id, self.t = guild, user_id, t
        if in_guild:
            sel = discord.ui.ChannelSelect(channel_types=[discord.ChannelType.text, discord.ChannelType.news],
                                           placeholder=t["share_placeholder"])
        else:
            channels = [c for c in guild.text_channels if _postable(guild, c)]
            public = [c for c in channels if c.permissions_for(guild.default_role).view_channel]
            ordered = (public + [c for c in channels if c not in public])[:25]
            sel = discord.ui.Select(placeholder=t["share_placeholder"], options=[
                discord.SelectOption(label=f"#{c.name}"[:100], value=str(c.id)) for c in ordered] or [
                discord.SelectOption(label="-", value="0")])
        sel.callback = self._picked
        self.select = sel
        self.add_item(sel)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user_id

    async def on_error(self, interaction: discord.Interaction, error: Exception, item) -> None:
        logger.error(f"[Wrapped] share: {type(error).__name__}: {error}")
        await _say_error(interaction, self.t)

    async def _picked(self, interaction: discord.Interaction):
        raw = self.select.values[0] if self.select.values else None
        cid = raw.id if hasattr(raw, "id") else int(raw or 0)
        channel = self.guild.get_channel(cid)
        t = self.t
        await interaction.response.defer(ephemeral=True)
        if not _can_share(self.guild, interaction.user):
            return await interaction.edit_original_response(content=t["share_no_perm"], view=None)
        if not _postable(self.guild, channel):
            return await interaction.edit_original_response(
                content=t["share_cant_post"].format(channel=f"<#{cid}>"), view=None)
        msg, why = await post_public(self.guild, channel)
        if why == "already":
            existing = next((x for x in get_state(self.guild.id).get("shares", []) if x.get("channel") == str(cid)), {})
            url = f"https://discord.com/channels/{self.guild.id}/{cid}" + (f"/{existing['message']}" if existing.get("message") else "")
            return await interaction.edit_original_response(
                content=t["share_already"].format(channel=f"<#{cid}>", url=url), view=None)
        if why == "nothing":
            return await interaction.edit_original_response(content=t["nothing"].format(year=YEAR), view=None)
        if msg is None:
            return await interaction.edit_original_response(
                content=t["share_cant_post"].format(channel=f"<#{cid}>"), view=None)
        await interaction.edit_original_response(
            content=t["share_done"].format(channel=channel.mention, url=msg.jump_url), view=None)


async def _start_share(interaction: discord.Interaction, guild: discord.Guild, t: dict) -> None:
    if not _can_share(guild, interaction.user):
        return await interaction.response.send_message(t["share_no_perm"], ephemeral=True)
    in_guild = interaction.guild is not None and interaction.guild.id == guild.id
    text = t["share_pick"] if in_guild else t["share_pick"] + "\n" + t["share_dm_hint"]
    await interaction.response.send_message(text, view=_ShareView(guild, interaction.user.id, t,
                                                                  in_guild=in_guild), ephemeral=True)


async def _first_card(guild: discord.Guild, t: dict) -> dict | None:
    res = await ensure_result(guild)
    if not has_content(res):
        return None
    cards = await server_cards(guild, res, t, overview_only=True)
    embed, png = await cards[0]()
    out: dict = {"embed": embed}
    if png is not None:
        embed.set_image(url=f"attachment://{_FILE}")
        out["file"] = discord.File(io.BytesIO(png), filename=_FILE)
    return out


def _share_change(gid: int, channel_id: int, action: str, message_id: str = "") -> dict | None:
    """One atomic change of ``shares`` in the guild's state. ``reserve`` returns the existing entry
    for that channel (and changes nothing) or None after reserving it; ``done`` fills in the
    message id; ``release`` drops the reservation again."""
    db.ensure_guild(gid)
    cid = str(channel_id)
    with db.transaction() as cx:
        row = cx.execute("SELECT data_json FROM wrapped_state WHERE guild_id=? AND year=?", (gid, YEAR)).fetchone()
        state = json.loads(row[0] or "{}") if row else {}
        shares = list(state.get("shares", []))
        found = next((x for x in shares if x.get("channel") == cid), None)
        if action == "reserve":
            stale = found is not None and not found.get("message") and time.time() - found.get("at", 0) > 300
            if found is not None and not stale:
                return found
            shares = [x for x in shares if x is not found]      # a crashed attempt (pending > 5 min) is taken over
            shares.append({"channel": cid, "message": "", "at": int(time.time())})
        elif action == "done" and found is not None:
            found["message"] = str(message_id)
        elif action == "release":
            shares = [x for x in shares if not (x.get("channel") == cid and not x.get("message"))]
        state["shares"] = shares
        cx.execute("INSERT INTO wrapped_state (guild_id,year,data_json) VALUES (?,?,?) "
                   "ON CONFLICT(guild_id,year) DO UPDATE SET data_json=excluded.data_json",
                   (gid, YEAR, json.dumps(state)))
    return None


async def post_public(guild: discord.Guild, channel: discord.TextChannel) -> tuple[discord.Message | None, str]:
    """Post the public version. Returns (message, reason); reason is "posted", "already" (the
    channel has one, or one is on its way), "nothing" (no recap yet) or "failed". The channel is
    reserved before sending, so two quick clicks cannot post twice."""
    t = _t(guild.id)
    if _share_change(guild.id, channel.id, "reserve") is not None:
        return None, "already"
    try:
        payload = await _first_card(guild, t)
        if payload is None:
            _share_change(guild.id, channel.id, "release")
            return None, "nothing"
        msg = await channel.send(content=t["public_intro"].format(year=YEAR), **payload,
                                 view=_buttons(guild.id, t, share=False),
                                 allowed_mentions=discord.AllowedMentions.none())
    except Exception as e:
        logger.warn(f"[Wrapped] public post failed in {guild.id}: {type(e).__name__}: {e}")
        _share_change(guild.id, channel.id, "release")
        return None, "failed"
    _share_change(guild.id, channel.id, "done", str(msg.id))
    return msg, "posted"


# ── Staff preview ────────────────────────────────────────────────────────────

async def send_preview(guild: discord.Guild, *, test: bool = False) -> str:
    """Preview with Share in the staff channel, or the owner's DM without one.
    Returns "channel", "dm", "empty" or "failed"."""
    from assets.staff import staff_channel
    t = _t(guild.id)
    try:
        payload = await _first_card(guild, t)
    except Exception as e:
        logger.error(f"[Wrapped] preview build failed @ {guild.id}: {type(e).__name__}: {e}")
        return "failed"
    if payload is None:
        return "empty"
    note = ("\n-# " + t["test_note"]) if test else ""
    channel = staff_channel(guild)
    try:
        if channel is not None and _postable(guild, channel):
            await channel.send(content=t["preview_intro"].format(year=YEAR) + note, **payload,
                               view=_buttons(guild.id, t, share=True),
                               allowed_mentions=discord.AllowedMentions.none())
            return "channel"
        owner = guild.owner or await guild.fetch_member(guild.owner_id)
        await owner.send(content=t["preview_dm"].format(year=YEAR, server=discord.utils.escape_markdown(guild.name))
                         + note, **payload, view=_buttons(guild.id, t, share=True))
        return "dm"
    except (discord.Forbidden, discord.HTTPException, AttributeError) as e:
        logger.warn(f"[Wrapped] preview could not be delivered @ {guild.id}: {e}")
        return "failed"


# ── Quote of the year vote ───────────────────────────────────────────────────

def vote_candidate_rows(gid: int, hidden: frozenset) -> list:
    """Quotes of the year: most reactions first, the rest (never reacted, e.g. saved before
    reactions existed) in a fixed shuffled order behind them."""
    rows = [r for r in db.query(
        "SELECT * FROM quotes WHERE guild_id=? AND created_at>=? AND created_at<?",
        (gid, _FLOOR, f"{YEAR + 1}-01-01")) if (r["content"] or "").strip() and str(r["author_id"] or "") not in hidden]
    reactions = {int(r["quote_id"]): int(r["n"]) for r in db.query(
        "SELECT quote_id, COUNT(*) AS n FROM quote_reactions WHERE guild_id=? GROUP BY quote_id", (gid,))}
    liked = sorted((r for r in rows if reactions.get(int(r["quote_id"]), 0) > 0),
                   key=lambda r: (-reactions[int(r["quote_id"])], int(r["quote_id"])))
    rest = sorted((r for r in rows if reactions.get(int(r["quote_id"]), 0) == 0), key=lambda r: int(r["quote_id"]))
    random.Random(gid * 31 + YEAR).shuffle(rest)
    return liked + rest


async def post_vote(guild: discord.Guild, *, test: bool = False, minutes: int | None = None) -> str:
    """Start the quote vote. Returns what happened ("posted", "no_channel", "too_few", "failed")."""
    from assets.poll import _make_poll_embed, build_poll_view
    t = _t(guild.id)
    qcfg = dict(datasys.load_data(guild.id, "quotes") or {})
    raw = str(qcfg.get("channel", "") or "")
    channel = guild.get_channel(int(raw)) if raw.isdigit() else None
    if not qcfg.get("enabled") or not _postable(guild, channel):
        update_state(guild.id, vote={"skipped": "no_channel", "test": test})
        return "no_channel"
    picked = []
    hidden = hidden_users(guild.id)
    for r in vote_candidate_rows(guild.id, hidden):
        if not quote_is_showable(guild, r, hidden):
            continue        # private or NSFW source, bot or former member: not for a public vote
        cid = int(r["source_channel_id"]) if str(r["source_channel_id"]).isdigit() else 0
        aid = int(r["author_id"]) if str(r["author_id"]).isdigit() else 0
        if await _clean(guild.id, cid, aid, r["content"]):
            picked.append(r)
        if len(picked) >= VOTE_CANDIDATES:
            break
    if len(picked) < 2:
        update_state(guild.id, vote={"skipped": "too_few", "test": test})
        return "too_few"

    end = time.time() + minutes * 60 if minutes else VOTE_END.timestamp()
    update_state(guild.id, vote={"started": int(time.time()), "test": test})   # mark first: never twice
    answers = [_clip(f"{r['author_name'] or '?'}: {r['content']}", 90) for r in picked]
    counts = [0] * len(answers)
    question = t["vote_question"].format(year=YEAR)
    try:
        msg = await channel.send(
            content=t["vote_intro"].format(year=YEAR, end=f"<t:{int(end)}:f>"),
            embed=_make_poll_embed(question, answers, counts, False, None, end),
            view=build_poll_view(answers, counts, False),
            allowed_mentions=discord.AllowedMentions.none())
    except (discord.Forbidden, discord.HTTPException) as e:
        logger.warn(f"[Wrapped] vote could not be posted @ {guild.id}: {e}")
        update_state(guild.id, vote={"skipped": "failed", "test": test})
        return "failed"
    polls = dict(datasys.load_data(guild.id, "polls") or {})
    polls[str(msg.id)] = {"question": question, "answers": answers, "show_votes": False, "image_url": None,
                          "channel_id": str(channel.id), "end_time": end, "user_votes": {}, "closed": False,
                          "wrapped_year": YEAR}
    datasys.save_data(guild.id, "polls", polls)
    update_state(guild.id, vote={"message_id": str(msg.id), "channel_id": str(channel.id), "end": int(end),
                                 "quote_ids": [int(r["quote_id"]) for r in picked], "test": test})
    return "posted"


# ── Task ─────────────────────────────────────────────────────────────────────

def _vote_guild_ids() -> list[int]:
    """Guilds with at least two quotes this year (one query for all guilds)."""
    return [int(r["guild_id"]) for r in db.query(
        "SELECT guild_id FROM quotes WHERE created_at>=? AND created_at<? GROUP BY guild_id HAVING COUNT(*)>=2",
        (_FLOOR, f"{YEAR + 1}-01-01"))]


def _release_guild_ids() -> set[int]:
    rows = db.query(
        "SELECT guild_id FROM wrapped_days UNION SELECT guild_id FROM activity "
        "UNION SELECT guild_id FROM quotes WHERE created_at>=? "
        "UNION SELECT guild_id FROM starboard_entries WHERE message_created_at>=?", (_FLOOR, _FLOOR))
    return {int(r["guild_id"]) for r in rows}


def _states(ids) -> dict[int, dict]:
    rows = db.query("SELECT guild_id, data_json FROM wrapped_state WHERE year=?", (YEAR,))
    wanted = set(ids)
    return {int(r["guild_id"]): json.loads(r["data_json"] or "{}") for r in rows if int(r["guild_id"]) in wanted}


_RETRY = ("failed", "error")      # preview statuses that get another try on a later tick
_MAX_TRIES = 2


def _release_todo(ids) -> list[int]:
    """Guilds still waiting for their preview: never tried, or failed and tried less than twice.
    ("sending" means a crash mid-send: not repeated, so nothing is ever posted twice.)"""
    states = _states(ids)
    out = []
    for g in sorted(ids):
        pv = states.get(g, {}).get("preview")
        if not pv or (pv.get("status") in _RETRY and int(pv.get("tries", 1)) < _MAX_TRIES):
            out.append(g)
    return out


def close_year() -> None:
    """Delete everything of YEAR that only existed for Wrapped (opt-outs stay)."""
    with db.transaction() as cx:
        for table in ("wrapped_results", "wrapped_users", "wrapped_state"):
            cx.execute(f"DELETE FROM {table} WHERE year<=?", (YEAR,))
        cx.execute("DELETE FROM wrapped_user_channels WHERE year<=?", (YEAR,))
        cx.execute("DELETE FROM wrapped_days WHERE day<?", (f"{YEAR + 1}-01-01",))


class WrappedTask:
    """Every 5 minutes: flush the channel counter, archive once a day, and run the vote,
    release and close steps when their date has come. Outside those days a tick is a few
    comparisons and returns."""

    def __init__(self, bot: commands.AutoShardedBot):
        self.bot = bot

    @tasks.loop(minutes=5)
    async def tick(self):
        try:
            await flush_channel_counts()
            today = now_utc().date().isoformat()
            if _meta(_META_ARCHIVED) != today:
                n = await asyncio.to_thread(archive_days)
                _set_meta(_META_ARCHIVED, today)
                set_task_status("Wrapped", "ok", f"Archived {n} day row(s)")
            p = phase()
            if p == "vote" and _meta(_META_VOTE) is None:
                await self._votes()
            elif p == "release" and _meta(_META_RELEASE) is None:
                await self._release()
            elif p == "closed" and _meta(_META_CLOSED) is None:
                await asyncio.to_thread(close_year)
                _set_meta(_META_CLOSED, "done")
                set_task_status("Wrapped", "ok", f"Wrapped {YEAR} closed")
        except Exception as e:
            logger.error(f"[Wrapped] Error in tick: {type(e).__name__}: {e}")
            set_task_status("Wrapped", "error", f"Error: {e}")

    async def _votes(self):
        if (VOTE_END - now_utc()).total_seconds() < VOTE_MIN_HOURS_LEFT * 3600:
            _set_meta(_META_VOTE, "done")       # too late for a fair vote
            return
        ids = [g for g in _vote_guild_ids() if self.bot.get_guild(g) is not None]
        states = _states(ids)
        todo = [g for g in ids if not (states.get(g, {}).get("vote") or {}) or states[g]["vote"].get("test")]
        for gid in todo[:BATCH]:
            try:
                result = await post_vote(self.bot.get_guild(gid))
                logger.info(f"[Wrapped] vote @ {gid}: {result}")
            except Exception as e:
                logger.error(f"[Wrapped] vote error @ {gid}: {type(e).__name__}: {e}")
                update_state(gid, vote={"skipped": "error"})
        if len(todo) <= BATCH:
            _set_meta(_META_VOTE, "done")
        set_task_status("Wrapped", "ok", f"Quote votes: {min(len(todo), BATCH)} handled")

    async def _release(self):
        ids = [g for g in _release_guild_ids() if self.bot.get_guild(g) is not None]
        todo = _release_todo(ids)
        failed = 0
        for gid in todo[:BATCH]:
            guild = self.bot.get_guild(gid)
            tries = int((get_state(gid).get("preview") or {}).get("tries", 0)) + 1
            try:
                update_state(gid, preview={"status": "sending", "tries": tries, "at": int(time.time())})   # mark first
                await ensure_result(guild, force=True)
                status = await send_preview(guild)
            except Exception as e:
                logger.error(f"[Wrapped] release error @ {gid}: {type(e).__name__}: {e}")
                status = "error"
            failed += status in _RETRY
            update_state(gid, preview={"status": status, "tries": tries, "at": int(time.time())})
            if status in _RETRY:
                logger.warn(f"[Wrapped] preview @ {gid}: {status} (try {tries} of {_MAX_TRIES})")
        if not _release_todo(ids):          # nothing left to send and nothing left to retry
            _set_meta(_META_RELEASE, "done")
        set_task_status("Wrapped", "ok" if not failed else "error",
                        f"Release: {min(len(todo), BATCH)} preview(s) handled, {failed} failed")

    @tick.before_loop
    async def _before(self):
        await self.bot.wait_until_ready()


# ── Command + registration ───────────────────────────────────────────────────

def wrapped_commands(bot: commands.AutoShardedBot) -> None:

    @bot.tree.command(name="wrapped", description=f"Your {YEAR} on this server - Baxi Wrapped")
    @app_commands.describe(top_lists="Show or hide your name in this server's Wrapped (top lists, highlights)")
    @app_commands.choices(top_lists=[
        app_commands.Choice(name="Show my name", value="show"),
        app_commands.Choice(name="Hide my name", value="hide"),
    ])
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 10.0, key=lambda i: (i.guild_id, i.user.id))
    async def wrapped_cmd(interaction: discord.Interaction, top_lists: app_commands.Choice[str] | None = None):
        await interaction.response.defer(ephemeral=True, thinking=True)
        t = _t(interaction.guild.id)
        try:
            if top_lists is not None:
                hide = top_lists.value == "hide"
                set_hidden(interaction.guild.id, interaction.user.id, hide)   # on the loop: it also edits the counter
                return await interaction.followup.send(
                    embed=discord.Embed(description=t["optout_on" if hide else "optout_off"],
                                        color=config.Discord.success_color), ephemeral=True)
            await open_personal(interaction, interaction.guild, interaction.user)
        except Exception as e:
            logger.error(f"[Wrapped] /wrapped @ {interaction.guild.id}: {type(e).__name__}: {e}")
            await interaction.followup.send(
                embed=discord.Embed(description=t["error"], color=config.Discord.danger_color), ephemeral=True)

    @wrapped_cmd.error
    async def _on_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CommandOnCooldown):
            msg = f"{config.Icons.alert} " + _t(interaction.guild_id or 0)["cooldown"].format(seconds=f"{error.retry_after:.0f}")
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
            return
        logger.error(f"[Wrapped] {error}")

    async def _on_message(message: discord.Message):
        count_message(message)

    bot.add_listener(_on_message, "on_message")


# ── Admin console (test run for one guild) ───────────────────────────────────

async def admin_command(bot, args: list[str]) -> list[str]:
    """`wrapped status` or `wrapped <guild_id> [status|preview|vote [minutes]|reset]` - returns lines to print.

    status (no id): phase, dates and the vote / preview status of every guild that has one.

    preview: compute now, open /wrapped on that server and send the staff preview (marked as a
             test; the real release still sends its own).
    vote:    post a test vote in the quotes channel, ending after <minutes> (default 10).
    reset:   forget results and state of that guild for this year (opt-outs and archive stay).
    """
    if args and args[0] == "status":
        lines = [f"phase: {phase()}  vote {VOTE_START:%d.%m. %H:%M} - {VOTE_END:%d.%m. %H:%M}, "
                 f"release {RELEASE:%d.%m.%Y %H:%M}, close {CLOSE:%d.%m.%Y}"]
        rows = db.query("SELECT guild_id, data_json FROM wrapped_state WHERE year=? ORDER BY guild_id", (YEAR,))
        counts: dict[str, int] = {}
        for r in rows:
            st = json.loads(r["data_json"] or "{}")
            pv, vt = st.get("preview") or {}, st.get("vote") or {}
            counts[pv.get("status", "-")] = counts.get(pv.get("status", "-"), 0) + 1
            if pv.get("status") in _RETRY or vt.get("skipped") in ("failed", "error"):
                lines.append(f"  {r['guild_id']}: preview {pv.get('status', '-')} (tries {pv.get('tries', 0)}), "
                             f"vote {vt.get('skipped') or ('posted' if vt.get('message_id') else '-')}")
        lines.append("previews: " + (", ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "none yet"))
        return lines
    if not args or not args[0].isdigit():
        return ["Usage: wrapped status | wrapped <guild_id> [status|preview|vote [minutes]|reset]"]
    gid, action = int(args[0]), (args[1] if len(args) > 1 else "status")
    guild = bot.get_guild(gid) if bot is not None else None
    if action == "reset":
        with db.transaction() as cx:
            for table in ("wrapped_results", "wrapped_users", "wrapped_state"):
                cx.execute(f"DELETE FROM {table} WHERE guild_id=? AND year=?", (gid, YEAR))
        _highlight_cache.pop(gid, None)
        return [f"Wrapped {YEAR} state and results of {gid} deleted."]
    if action == "status":
        res, at = load_result(gid)
        days = db.query("SELECT COUNT(*) AS n, MIN(day) AS a, MAX(day) AS b FROM wrapped_days WHERE guild_id=?", (gid,))[0]
        lines = [f"phase: {phase()}  vote {VOTE_START:%d.%m. %H:%M} - {VOTE_END:%d.%m. %H:%M}, "
                 f"release {RELEASE:%d.%m.%Y %H:%M}, close {CLOSE:%d.%m.%Y}",
                 f"archive: {days['n']} day(s) {days['a'] or '-'} .. {days['b'] or '-'}",
                 f"state: {json.dumps(get_state(gid))}"]
        pv = get_state(gid).get("preview") or {}
        lines.append(f"preview: {pv.get('status', 'not sent yet')}" + (f" (tries {pv['tries']})" if pv.get("tries") else ""))
        if res:
            lines.append(f"result ({datetime.datetime.fromtimestamp(at):%d.%m. %H:%M}): {res['messages']} msgs, "
                         f"{res['voice_secs'] // 3600} h voice, first day {res['first_day']}, "
                         f"{res['new_members']} new members, {len(res['stars'])} starred, "
                         f"{res['quotes_total']} quotes, qoty {res['qoty'][:1]}")
        return lines
    if guild is None:
        return [f"Baxi is not in guild {gid} (or the bot is not running)."]
    if action == "preview":
        update_state(gid, test_open=True)
        await ensure_result(guild, force=True)
        _highlight_cache.pop(gid, None)
        status = await send_preview(guild, test=True)
        return [f"Test preview @ {guild.name}: {status}. /wrapped is open there now."]
    if action == "vote":
        minutes = int(args[2]) if len(args) > 2 and args[2].isdigit() else 10
        return [f"Test vote @ {guild.name}: {await post_vote(guild, test=True, minutes=minutes)}"]
    return [f"Unknown action '{action}'."]
