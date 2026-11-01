"""Birthdays - members save their birthday once, servers that turn the feature on congratulate them.

The date belongs to the user: day and month only (no year), one row for all servers
(`user_birthdays`). A user can hide it on single servers (`birthday_hidden`). The server
decides about the announcement: channel, text, an optional role for 24 hours, timezone.

`birthday_celebrations` remembers the last congratulation per server and user and holds the
role until it is due for removal. Nobody is congratulated twice on a server within
MIN_GAP_DAYS - not after a restart, and not by moving the date to "today" every day (the date
itself stays editable, typos must be fixable). Rows without a pending role are pruned after
about a year.
"""
from __future__ import annotations

import calendar
import datetime
import re
import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import discord
from discord import app_commands
from discord.ext import commands, tasks

import assets.data as datasys
import assets.db as db
import assets.idle as idle
import config.config as config
from assets.message.chatfilter import text_is_clean
from assets.share import set_task_status, admin_log
from reds_simple_logger import Logger

logger = Logger()

DEFAULT_TZ = "Europe/Vienna"
ANNOUNCE_HOUR = 9               # local time of the server; later on the day still counts (restart, late enable)
ROLE_HOURS = 24
UPCOMING_LIMIT = 10
MIN_GAP_DAYS = 300              # at most one congratulation per server in this window
_PRUNE_AFTER = 370 * 86400      # must stay longer than MIN_GAP_DAYS
_PRUNE_EVERY = 3600
_ID_CHUNK = 900                 # stays below SQLite's bound-parameter limit
_VARS = re.compile(r"\{(user|username|displayname|server)\}")

_last_prune = 0.0

# Mirrors config.datasys.default_data["birthdays"]; kept here so a stale config.py cannot break the module.
_DEFAULTS = {"enabled": False, "channel": "", "message": "", "role": "", "timezone": DEFAULT_TZ}


# ── Config ───────────────────────────────────────────────────────────────────

def load_cfg(guild_id: int) -> dict:
    return {**_DEFAULTS, **dict(datasys.load_data(guild_id, "birthdays"))}


def _tz(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(str(name or DEFAULT_TZ))
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(DEFAULT_TZ)


def _channel(guild: discord.Guild, cfg: dict) -> discord.TextChannel | None:
    """The configured channel, otherwise the server's system channel (works without setup)."""
    raw = str(cfg.get("channel", "") or "")
    ch = guild.get_channel(int(raw)) if raw.isdigit() else guild.system_channel
    return ch if isinstance(ch, discord.TextChannel) else None


def _role(guild: discord.Guild, cfg: dict) -> discord.Role | None:
    """The birthday role, only if Baxi is actually allowed to hand it out."""
    raw = str(cfg.get("role", "") or "")
    role = guild.get_role(int(raw)) if raw.isdigit() else None
    me = guild.me
    if role is None or me is None or role.managed or role.is_default():
        return None
    if not me.guild_permissions.manage_roles or role >= me.top_role:
        return None
    return role


# ── Dates ────────────────────────────────────────────────────────────────────

def is_valid_date(day: int, month: int) -> bool:
    """Day + month without a year. 29.02 is allowed (2000 is a leap year), 31.02 is not."""
    try:
        datetime.date(2000, month, day)
    except (ValueError, TypeError):
        return False
    return True


def celebration_date(day: int, month: int, year: int) -> datetime.date:
    """The day a birthday is celebrated in `year`: 29.02 moves to 28.02 in non-leap years."""
    if month == 2 and day == 29 and not calendar.isleap(year):
        return datetime.date(year, 2, 28)
    return datetime.date(year, month, day)


def birthdays_on(d: datetime.date) -> list[tuple[int, int]]:
    """(day, month) pairs celebrated on date `d`."""
    pairs = [(d.day, d.month)]
    if d.month == 2 and d.day == 28 and not calendar.isleap(d.year):
        pairs.append((29, 2))
    return pairs


def next_occurrence(day: int, month: int, today: datetime.date) -> datetime.date:
    this_year = celebration_date(day, month, today.year)
    return this_year if this_year >= today else celebration_date(day, month, today.year + 1)


def local_now(tz_name: str, now: float | None = None) -> datetime.datetime:
    return datetime.datetime.fromtimestamp(now if now is not None else time.time(), _tz(tz_name))


def _fmt_date(day: int, month: int, t: dict) -> str:
    return t["date"].format(day=day, month=t["months"][month - 1])


# ── Storage ──────────────────────────────────────────────────────────────────

def get_birthday(user_id: int) -> tuple[int, int] | None:
    rows = db.query("SELECT day, month FROM user_birthdays WHERE user_id=?", (str(user_id),))
    return (rows[0]["day"], rows[0]["month"]) if rows else None


def set_birthday(user_id: int, day: int, month: int) -> None:
    db.execute(
        "INSERT INTO user_birthdays (user_id,day,month) VALUES (?,?,?) "
        "ON CONFLICT(user_id) DO UPDATE SET day=excluded.day, month=excluded.month",
        (str(user_id), day, month),
    )


def remove_birthday(user_id: int) -> bool:
    """Deletes the date and every per-server hide of this user."""
    cur = db.execute("DELETE FROM user_birthdays WHERE user_id=?", (str(user_id),))
    db.execute("DELETE FROM birthday_hidden WHERE user_id=?", (str(user_id),))
    return cur.rowcount > 0


def is_hidden(guild_id: int, user_id: int) -> bool:
    return bool(db.query(
        "SELECT 1 FROM birthday_hidden WHERE guild_id=? AND user_id=?", (guild_id, str(user_id)),
    ))


def hidden_count(user_id: int) -> int:
    return db.query("SELECT COUNT(*) AS n FROM birthday_hidden WHERE user_id=?", (str(user_id),))[0]["n"]


def set_hidden(guild_id: int, user_id: int, hidden: bool) -> None:
    if not hidden:
        db.execute("DELETE FROM birthday_hidden WHERE guild_id=? AND user_id=?", (guild_id, str(user_id)))
        return
    db.ensure_guild(guild_id)
    db.execute("INSERT OR IGNORE INTO birthday_hidden (guild_id,user_id) VALUES (?,?)", (guild_id, str(user_id)))


def user_ids_on(d: datetime.date) -> list[str]:
    """Everyone whose birthday is celebrated on `d` (any server)."""
    pairs = birthdays_on(d)
    where = " OR ".join("(day=? AND month=?)" for _ in pairs)
    return [r["user_id"] for r in db.query(
        f"SELECT user_id FROM user_birthdays WHERE {where}", tuple(v for p in pairs for v in p),
    )]


def skipped_in_guild(guild_id: int, now: float | None = None) -> set[str]:
    """Users not to congratulate here now: hidden, or congratulated within MIN_GAP_DAYS."""
    since = int(now if now is not None else time.time()) - MIN_GAP_DAYS * 86400
    return {r["user_id"] for r in db.query(
        "SELECT user_id FROM birthday_hidden WHERE guild_id=? "
        "UNION SELECT user_id FROM birthday_celebrations WHERE guild_id=? AND celebrated_at>?",
        (guild_id, guild_id, since),
    )}


def claim(guild_id: int, user_id: int | str, today: str, role_id: str = "", now: float | None = None) -> bool:
    """Atomically mark (guild, user) as congratulated. False if that happened within MIN_GAP_DAYS.

    Called before sending: a failing channel must not lead to a second post on the next tick,
    and a restart in between must not repeat it. The role deadline is written in the same
    statement, so a crash after add_roles can never leave the role behind forever. A role that
    is still pending is never overwritten (see owns_role).
    """
    now = int(now if now is not None else time.time())
    until = now + ROLE_HOURS * 3600 if role_id else 0
    db.ensure_guild(guild_id)
    cur = db.execute(
        "INSERT INTO birthday_celebrations (guild_id,user_id,celebrated_on,celebrated_at,role_id,role_until) "
        "VALUES (?,?,?,?,?,?) ON CONFLICT(guild_id,user_id) DO UPDATE SET "
        "celebrated_on=excluded.celebrated_on, celebrated_at=excluded.celebrated_at, "
        "role_id=CASE WHEN birthday_celebrations.role_until>0 THEN birthday_celebrations.role_id ELSE excluded.role_id END, "
        "role_until=CASE WHEN birthday_celebrations.role_until>0 THEN birthday_celebrations.role_until ELSE excluded.role_until END "
        "WHERE birthday_celebrations.celebrated_at<=?",
        (guild_id, str(user_id), today, now, role_id, until, now - MIN_GAP_DAYS * 86400),
    )
    return cur.rowcount > 0


def owns_role(guild_id: int, user_id: int | str, role_id: str, now: float) -> bool:
    """True if the row just claimed carries this role with a fresh deadline (not an older pending one)."""
    rows = db.query(
        "SELECT role_id, role_until FROM birthday_celebrations WHERE guild_id=? AND user_id=?",
        (guild_id, str(user_id)),
    )
    return bool(rows) and rows[0]["role_id"] == role_id and rows[0]["role_until"] == int(now) + ROLE_HOURS * 3600


def due_roles(now: float | None = None):
    return db.query(
        "SELECT guild_id,user_id,role_id FROM birthday_celebrations WHERE role_until>0 AND role_until<=? LIMIT 100",
        (int(now if now is not None else time.time()),),
    )


def _role_done(guild_id: int, user_id: str) -> None:
    db.execute(
        "UPDATE birthday_celebrations SET role_id='', role_until=0 WHERE guild_id=? AND user_id=?",
        (guild_id, user_id),
    )


def prune(now: float | None = None) -> None:
    db.execute(
        "DELETE FROM birthday_celebrations WHERE role_until=0 AND celebrated_at<?",
        (int(now if now is not None else time.time()) - _PRUNE_AFTER,),
    )


# ── Announcement ─────────────────────────────────────────────────────────────

def render(template: str, member: discord.Member) -> str:
    """Fill the variables in one pass, so a name like "{server}" stays literal. Unknown braces stay."""
    values = {
        "user": member.mention,
        "username": discord.utils.escape_markdown(member.name),
        "displayname": discord.utils.escape_markdown(member.display_name),
        "server": discord.utils.escape_markdown(member.guild.name),
    }
    return _VARS.sub(lambda m: values[m.group(1)], str(template))[:2000]


def _chunks(lines: list[tuple[str, discord.Member]]) -> list[tuple[str, list[discord.Member]]]:
    """Join rendered lines into messages of at most 2000 characters, with the members each one pings."""
    out: list[tuple[str, list[discord.Member]]] = []
    text, members = "", []
    for line, member in lines:
        if text and len(text) + 1 + len(line) > 2000:
            out.append((text, members))
            text, members = "", []
        text = f"{text}\n{line}" if text else line
        members.append(member)
    if text:
        out.append((text, members))
    return out


async def _template(bot: commands.AutoShardedBot, guild: discord.Guild, channel: discord.TextChannel,
                    cfg: dict, t: dict) -> str:
    """The server's text if set and clean, otherwise the default text. The dashboard checks it on
    save too; this is the safety net for texts saved before or filters changed since."""
    custom = str(cfg.get("message", "") or "").strip()
    if not custom:
        return t["default_message"]
    if await text_is_clean(guild.id, channel.id, bot.user.id if bot.user else 0, custom):
        return custom
    logger.warn(f"[Birthdays] custom message blocked by chatfilter in {guild.id}, using the default")
    return t["default_message"]


async def celebrate_guild(bot: commands.AutoShardedBot, guild: discord.Guild, candidates: list[str],
                          now: float | None = None, *, cfg: dict | None = None) -> int:
    """Congratulate today's birthdays on one server in one message. Returns how many were congratulated."""
    now = now if now is not None else time.time()
    cfg = cfg if cfg is not None else load_cfg(guild.id)
    local = local_now(cfg["timezone"], now)
    if local.hour < ANNOUNCE_HOUR:
        return 0
    skip = skipped_in_guild(guild.id, now)
    members = [m for uid in candidates if uid not in skip
               and (m := guild.get_member(int(uid))) is not None and not m.bot]
    if not members:
        return 0
    channel = _channel(guild, cfg)
    role = _role(guild, cfg)
    if channel is None and role is None:
        return 0                                      # nowhere to post: keep it open for later today
    today = local.date().isoformat()
    role_id = str(role.id) if role else ""
    claimed = [m for m in members if claim(guild.id, m.id, today, role_id, now)]
    if not claimed:
        return 0

    if role is not None:
        for member in claimed:
            if not owns_role(guild.id, member.id, role_id, now):
                continue                              # an older role is still pending: never stack a second one
            try:
                await member.add_roles(role, reason="Birthday")
            except (discord.Forbidden, discord.HTTPException) as e:
                logger.warn(f"[Birthdays] role failed in {guild.id}: {e}")

    if channel is not None:
        t = datasys.load_lang_file(guild.id)["birthdays"]
        template = await _template(bot, guild, channel, cfg, t)
        for text, pinged in _chunks([(render(template, m), m) for m in claimed]):
            try:
                await channel.send(
                    content=text,
                    allowed_mentions=discord.AllowedMentions(users=pinged, roles=False, everyone=False),
                )
            except (discord.Forbidden, discord.HTTPException) as e:
                logger.warn(f"[Birthdays] post failed in {guild.id}: {e}")
    return len(claimed)


async def expire_roles(bot: commands.AutoShardedBot, now: float | None = None) -> int:
    """Take the birthday role back after 24 h. Runs even if the feature was switched off since."""
    removed = 0
    for row in due_roles(now):
        gid, uid = int(row["guild_id"]), row["user_id"]
        guild = bot.get_guild(gid)
        if guild is not None and guild.unavailable:
            continue                                  # outage / reconnect: no roles cached yet, try later
        role = guild.get_role(int(row["role_id"])) if guild and str(row["role_id"]).isdigit() else None
        if role is None:
            _role_done(gid, uid)                      # server or role gone: nothing to take back
            continue
        member = guild.get_member(int(uid))
        try:
            if member is None:
                member = await guild.fetch_member(int(uid))
            if role in member.roles:
                await member.remove_roles(role, reason="Birthday is over")
                removed += 1
        except discord.NotFound:
            pass                                      # left the server
        except discord.Forbidden:
            admin_log("warning", f"Birthday role {role.name} ({role.id}) could not be removed from {uid} "
                              f"@ {guild.name} ({gid}): missing permission or role above Baxi", source="Birthdays")
        except discord.HTTPException:
            continue                                  # transient: try again next tick
        _role_done(gid, uid)
    return removed


class BirthdayTask:
    """Congratulates today's birthdays and takes the role back (every 10 minutes).

    Rest-mode friendly: only guilds with the feature on, one query per local date for the
    birthdays of the day, and nothing at all when nobody is due.
    """

    def __init__(self, bot: commands.AutoShardedBot):
        self.bot = bot

    @tasks.loop(minutes=10)
    async def tick(self):
        global _last_prune
        try:
            now = time.time()
            removed = await expire_roles(self.bot, now)
            if now - _last_prune >= _PRUNE_EVERY:
                _last_prune = now
                prune(now)

            by_date: dict[datetime.date, list[str]] = {}
            posted = 0
            for guild in idle.guilds_with(self.bot, "birthdays"):
                try:
                    cfg = load_cfg(guild.id)
                    day = local_now(cfg["timezone"], now).date()
                    if day not in by_date:
                        by_date[day] = user_ids_on(day)
                    if by_date[day]:
                        posted += await celebrate_guild(self.bot, guild, by_date[day], now, cfg=cfg)
                except Exception as e:
                    logger.error(f"[Birthdays] error @ {guild.id}: {e}")
            if posted or removed:
                set_task_status("Birthdays", "ok", f"{posted} birthday(s) congratulated, {removed} role(s) removed")
        except Exception as e:
            logger.error(f"[Birthdays] Error in tick: {e}")
            set_task_status("Birthdays", "error", f"Error: {e}")

    @tick.before_loop
    async def _before(self):
        await self.bot.wait_until_ready()


# ── Commands ─────────────────────────────────────────────────────────────────

def upcoming(guild: discord.Guild, today: datetime.date, limit: int = UPCOMING_LIMIT):
    """[(date, member, day, month)] of the next birthdays on this server, hidden ones left out.
    Looks up the server's members by ID (in chunks), never the whole table."""
    ids = [str(m.id) for m in guild.members if not m.bot]
    out = []
    for i in range(0, len(ids), _ID_CHUNK):
        chunk = ids[i:i + _ID_CHUNK]
        rows = db.query(
            f"SELECT user_id, day, month FROM user_birthdays WHERE user_id IN ({','.join('?' * len(chunk))}) "
            "AND user_id NOT IN (SELECT user_id FROM birthday_hidden WHERE guild_id=?)",
            (*chunk, guild.id),
        )
        for r in rows:
            member = guild.get_member(int(r["user_id"]))
            if member is not None:
                out.append((next_occurrence(r["day"], r["month"], today), member, r["day"], r["month"]))
    out.sort(key=lambda x: (x[0], x[1].display_name.lower()))
    return out[:limit]


class _BirthdayModal(discord.ui.Modal):
    def __init__(self, t: dict, current: tuple[int, int] | None):
        super().__init__(title=t["modal_title"], timeout=300)
        self.t = t
        self.day = discord.ui.TextInput(label=t["modal_day"], placeholder="24", min_length=1, max_length=2,
                                        default=str(current[0]) if current else None)
        self.month = discord.ui.TextInput(label=t["modal_month"], placeholder="12", min_length=1, max_length=2,
                                          default=str(current[1]) if current else None)
        self.add_item(self.day)
        self.add_item(self.month)

    async def on_submit(self, interaction: discord.Interaction):
        t = self.t
        try:
            day, month = int(str(self.day.value).strip()), int(str(self.month.value).strip())
        except ValueError:
            day = month = 0
        if not is_valid_date(day, month):
            return await interaction.response.send_message(
                embed=discord.Embed(description=f"{config.Icons.cross} {t['invalid']}", color=config.Discord.danger_color),
                ephemeral=True,
            )
        set_birthday(interaction.user.id, day, month)
        text = t["saved"].format(date=_fmt_date(day, month, t))
        if month == 2 and day == 29:
            text += "\n" + t["leap_note"]
        if not load_cfg(interaction.guild.id)["enabled"]:
            text += "\n" + t["saved_disabled_here"]
        elif is_hidden(interaction.guild.id, interaction.user.id):
            text += "\n" + t["saved_hidden_here"]
        await interaction.response.send_message(
            embed=discord.Embed(description=f"{config.Icons.check} {text}", color=config.Discord.success_color),
            ephemeral=True,
        )


def birthday_commands(bot: commands.AutoShardedBot):
    group = app_commands.Group(name="birthday", description="Birthdays - Baxi congratulates you on your day",
                               guild_only=True)

    def _t(guild_id: int) -> dict:
        return datasys.load_lang_file(guild_id)["birthdays"]

    async def _say(interaction: discord.Interaction, text: str, *, ok: bool = False):
        # Everything personal (and every error) is only visible to the user.
        await interaction.response.send_message(
            embed=discord.Embed(
                description=text,
                color=config.Discord.success_color if ok else config.Discord.danger_color,
            ),
            ephemeral=True,
        )

    @group.command(name="set", description="Save your birthday (day and month, no year)")
    async def birthday_set(interaction: discord.Interaction):
        # A modal has to be the first response, so no defer here.
        await interaction.response.send_modal(_BirthdayModal(_t(interaction.guild.id), get_birthday(interaction.user.id)))

    @group.command(name="remove", description="Delete your birthday from Baxi (all servers)")
    async def birthday_remove(interaction: discord.Interaction):
        t = _t(interaction.guild.id)
        if remove_birthday(interaction.user.id):
            await _say(interaction, f"{config.Icons.check} {t['removed']}", ok=True)
        else:
            await _say(interaction, t["none_saved"])

    @group.command(name="hide", description="Hide your birthday on this server")
    async def birthday_hide(interaction: discord.Interaction):
        t = _t(interaction.guild.id)
        if get_birthday(interaction.user.id) is None:
            return await _say(interaction, t["none_saved"])
        set_hidden(interaction.guild.id, interaction.user.id, True)
        await _say(interaction, f"{config.Icons.check} {t['hidden']}", ok=True)

    @group.command(name="show", description="Show your birthday on this server again")
    async def birthday_show(interaction: discord.Interaction):
        t = _t(interaction.guild.id)
        set_hidden(interaction.guild.id, interaction.user.id, False)
        if get_birthday(interaction.user.id) is None:
            return await _say(interaction, t["none_saved"])
        await _say(interaction, f"{config.Icons.check} {t['shown']}", ok=True)

    @group.command(name="upcoming", description="The next birthdays on this server")
    async def birthday_upcoming(interaction: discord.Interaction):
        t = _t(interaction.guild.id)
        cfg = load_cfg(interaction.guild.id)
        if not cfg["enabled"]:
            return await _say(interaction, f"{config.Icons.cross} {t['disabled']}")
        today = local_now(cfg["timezone"]).date()
        rows = upcoming(interaction.guild, today)
        if not rows:
            return await _say(interaction, t["upcoming_none"])
        lines = []
        for when, member, _day, _month in rows:
            days = (when - today).days
            rel = t["today"] if days == 0 else t["tomorrow"] if days == 1 else t["in_days"].format(n=days)
            # The day it is celebrated (29.02 shows as 28.02 in non-leap years).
            lines.append(f"**{_fmt_date(when.day, when.month, t)}** · {member.mention} · {rel}")
        # Only the list itself is public; it is an embed, so nobody gets pinged.
        await interaction.response.send_message(
            embed=discord.Embed(title=t["upcoming_title"], description="\n".join(lines), color=config.Discord.color)
            .set_footer(text=t["upcoming_footer"]),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    bot.tree.add_command(group)
