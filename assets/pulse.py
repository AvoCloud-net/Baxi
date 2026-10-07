"""Baxi Pulse - community activity analytics, built on the BaxiInsights counters.

Reads the per-guild ``activity`` blob (``msg_by_day`` / ``member_by_day``, 90 days, counts
only - never message content) and turns it into:

* a weekday x hour heatmap in the guild's own timezone,
* a "best time to post" recommendation (the busiest slot),
* period-over-period deltas, top channels / members, activity streak,
* a weekly recap that Baxi can post on its own.

No new tracking: everything here is derived from data Baxi already keeps.
"""
from __future__ import annotations

import asyncio
import datetime
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo, available_timezones

import discord
from discord.ext import commands, tasks

import assets.data as datasys
import assets.pulse_card as pulse_card
import config.config as config
from assets.share import set_task_status
from reds_simple_logger import Logger

logger = Logger()

# The activity tracker files messages under the *UTC date* with the *Vienna hour*
# (assets/events.py: ``datetime.now(_VIENNA).hour``). Both facts are needed to recover the
# real local time of a message.
_TRACKER_TZ = ZoneInfo("Europe/Vienna")
_UTC = datetime.timezone.utc

MIN_DAYS_FOR_REPORT = 3
MAX_WINDOW_DAYS = 90
_TZ_FALLBACK = "Europe/Berlin"


# Mirrors config.datasys.default_data["pulse"]; kept here so a stale config.py cannot break the module.
_DEFAULTS = {"enabled": False, "channel": "", "weekday": 0, "hour": 18,
             "timezone": "Europe/Berlin", "show_members": True, "last_recap": ""}


# ── Config ───────────────────────────────────────────────────────────────────

def load_cfg(guild_id: int) -> dict:
    stored = dict(datasys.load_data(guild_id, "pulse"))
    return {**_DEFAULTS, **stored}


def resolve_tz(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or _TZ_FALLBACK)
    except Exception:
        return ZoneInfo(_TZ_FALLBACK)


def is_valid_timezone(name: str) -> bool:
    return name in available_timezones()


# ── Report ───────────────────────────────────────────────────────────────────

@dataclass
class Report:
    days: int
    tz: ZoneInfo
    grid: list[list[int]]                       # [weekday 0=Mon][hour] -> messages
    daily: list[tuple[datetime.date, int]]      # one entry per day of the window, oldest first
    total: int = 0
    prev_total: int = 0
    prev_days_with_data: int = 0
    active_users: int = 0
    prev_active_users: int = 0
    joins: int = 0
    leaves: int = 0
    streak: int = 0
    days_with_data: int = 0
    top_channels: list[tuple[str, str, int]] = field(default_factory=list)   # (id, name, count)
    top_users: list[tuple[str, str, int]] = field(default_factory=list)      # (id, name, count)

    @property
    def enough_data(self) -> bool:
        return self.days_with_data >= MIN_DAYS_FOR_REPORT and self.total > 0

    @property
    def peak_cell(self) -> tuple[int, int] | None:
        """Busiest (weekday, hour) slot. The neighbouring hours count at half weight so one
        noisy hour does not win, while the slot itself stays centred on the real peak."""
        best, best_val = None, 0
        for wd in range(7):
            row = self.grid[wd]
            for h in range(24):
                val = 2 * row[h] + row[(h - 1) % 24] + row[(h + 1) % 24]
                if val > best_val:
                    best, best_val = (wd, h), val
        return best

    @property
    def peak_hour(self) -> int | None:
        by_hour = [sum(self.grid[wd][h] for wd in range(7)) for h in range(24)]
        return by_hour.index(max(by_hour)) if any(by_hour) else None

    @property
    def busiest_weekday(self) -> int | None:
        by_wd = [sum(row) for row in self.grid]
        return by_wd.index(max(by_wd)) if any(by_wd) else None

    @property
    def delta_pct(self) -> int | None:
        # A trend against a mostly-empty previous period (new server, fresh tracking) is noise.
        if self.prev_total <= 0 or self.prev_days_with_data < max(3, self.days // 2):
            return None
        return round((self.total - self.prev_total) / self.prev_total * 100)


def _tracker_offset_hours(day: datetime.date) -> int:
    """Hours Vienna is ahead of UTC on the given day (1 in winter, 2 in summer)."""
    midnight = datetime.datetime(day.year, day.month, day.day, tzinfo=_UTC)
    return int(midnight.astimezone(_TRACKER_TZ).utcoffset().total_seconds() // 3600)


def _local_slot(day: datetime.date, tracker_hour: int, tz: ZoneInfo) -> tuple[int, int]:
    """Map a tracker bucket (UTC date, Vienna hour) to (weekday, hour) in ``tz``."""
    # The UTC day starts at <offset>:00 Vienna time, so Vienna hours below the offset
    # already belong to the *next* Vienna calendar day.
    vienna_day = day + datetime.timedelta(days=1) if tracker_hour < _tracker_offset_hours(day) else day
    vienna_dt = datetime.datetime(
        vienna_day.year, vienna_day.month, vienna_day.day, tracker_hour, 30, tzinfo=_TRACKER_TZ,
    )
    local = vienna_dt.astimezone(tz)
    return local.weekday(), local.hour


def _date_key(d: datetime.date) -> str:
    return d.strftime("%Y-%m-%d")


def _sum_users(msg_days: dict, keys: list[str]) -> dict[str, dict]:
    totals: dict[str, dict] = {}
    for k in keys:
        for uid, uv in (msg_days.get(k) or {}).get("by_user", {}).items():
            entry = totals.setdefault(uid, {"name": uv.get("name", uid), "count": 0})
            entry["count"] += int(uv.get("count", 0))
            if uv.get("name"):
                entry["name"] = uv["name"]
    return totals


def build_report(guild_id: int, days: int, tz: ZoneInfo, today: datetime.date | None = None) -> Report:
    """Aggregate the last ``days`` days (plus the ``days`` before, for deltas)."""
    days = max(1, min(int(days), MAX_WINDOW_DAYS))
    today = today or datetime.datetime.now(_UTC).date()
    activity = dict(datasys.load_data(guild_id, "activity"))
    msg_days: dict = activity.get("msg_by_day", {}) or {}
    member_days: dict = activity.get("member_by_day", {}) or {}

    window = [today - datetime.timedelta(days=i) for i in range(days - 1, -1, -1)]
    prev_window = [window[0] - datetime.timedelta(days=i) for i in range(days, 0, -1)]
    keys = [_date_key(d) for d in window]
    prev_keys = [_date_key(d) for d in prev_window]

    grid = [[0] * 24 for _ in range(7)]
    daily: list[tuple[datetime.date, int]] = []
    ch_totals: dict[str, dict] = {}
    days_with_data = 0

    for d, k in zip(window, keys):
        day = msg_days.get(k) or {}
        total = int(day.get("total", 0))
        daily.append((d, total))
        if total:
            days_with_data += 1
        for h, cnt in (day.get("by_hour") or {}).items():
            try:
                wd, hr = _local_slot(d, int(h), tz)
            except (ValueError, OverflowError):
                continue
            grid[wd][hr] += int(cnt)
        for cid, cv in (day.get("by_channel") or {}).items():
            entry = ch_totals.setdefault(cid, {"name": cv.get("name", cid), "count": 0})
            entry["count"] += int(cv.get("count", 0))
            if cv.get("name"):
                entry["name"] = cv["name"]

    users = _sum_users(msg_days, keys)
    prev_users = _sum_users(msg_days, prev_keys)

    streak = 0
    for d, count in reversed(daily):
        if count <= 0:
            # Today may simply not have started yet - a quiet morning must not zero the streak.
            if streak == 0 and d == today:
                continue
            break
        streak += 1

    return Report(
        days=days,
        tz=tz,
        grid=grid,
        daily=daily,
        total=sum(c for _, c in daily),
        prev_total=sum(int((msg_days.get(k) or {}).get("total", 0)) for k in prev_keys),
        prev_days_with_data=sum(1 for k in prev_keys if int((msg_days.get(k) or {}).get("total", 0)) > 0),
        active_users=len(users),
        prev_active_users=len(prev_users),
        joins=sum(int((member_days.get(k) or {}).get("joins", 0)) for k in keys),
        leaves=sum(int((member_days.get(k) or {}).get("leaves", 0)) for k in keys),
        streak=streak,
        days_with_data=days_with_data,
        top_channels=[
            (cid, v["name"], v["count"])
            for cid, v in sorted(ch_totals.items(), key=lambda x: x[1]["count"], reverse=True)[:5]
        ],
        top_users=[
            (uid, v["name"], v["count"])
            for uid, v in sorted(users.items(), key=lambda x: x[1]["count"], reverse=True)[:5]
        ],
    )


@dataclass
class UserReport:
    days: int
    daily: list[tuple[datetime.date, int]]
    weekday: list[int]                           # messages per weekday (0=Mon)
    total: int = 0
    active_days: int = 0
    streak: int = 0
    rank: int | None = None
    ranked_users: int = 0
    server_total: int = 0

    @property
    def share_pct(self) -> float:
        return round(self.total / self.server_total * 100, 1) if self.server_total else 0.0

    @property
    def persona(self) -> str:
        """weekend / weekday / balanced - by where the user's messages fall."""
        if self.total < 10:
            return "balanced"
        weekend = (self.weekday[5] + self.weekday[6]) / self.total
        # Two of seven days; an even spread would be ~29%.
        if weekend >= 0.45:
            return "weekend"
        if weekend <= 0.15:
            return "weekday"
        return "balanced"


def build_user_report(guild_id: int, user_id: int, days: int, today: datetime.date | None = None) -> UserReport:
    days = max(1, min(int(days), MAX_WINDOW_DAYS))
    today = today or datetime.datetime.now(_UTC).date()
    activity = dict(datasys.load_data(guild_id, "activity"))
    msg_days: dict = activity.get("msg_by_day", {}) or {}

    window = [today - datetime.timedelta(days=i) for i in range(days - 1, -1, -1)]
    uid = str(user_id)
    daily: list[tuple[datetime.date, int]] = []
    weekday = [0] * 7
    server_total = 0
    for d in window:
        day = msg_days.get(_date_key(d)) or {}
        server_total += int(day.get("total", 0))
        count = int(((day.get("by_user") or {}).get(uid) or {}).get("count", 0))
        daily.append((d, count))
        weekday[d.weekday()] += count

    streak = 0
    for d, count in reversed(daily):
        if count <= 0:
            if streak == 0 and d == today:
                continue
            break
        streak += 1

    ranking = sorted(
        _sum_users(msg_days, [_date_key(d) for d in window]).items(),
        key=lambda x: x[1]["count"], reverse=True,
    )
    rank = next((i + 1 for i, (u, _) in enumerate(ranking) if u == uid), None)

    return UserReport(
        days=days,
        daily=daily,
        weekday=weekday,
        total=sum(c for _, c in daily),
        active_days=sum(1 for _, c in daily if c > 0),
        streak=streak,
        rank=rank,
        ranked_users=len(ranking),
        server_total=server_total,
    )


# ── Embeds ───────────────────────────────────────────────────────────────────

def _fmt_delta(delta: int | None) -> str:
    if delta is None:
        return ""
    arrow = "▲" if delta > 0 else ("▼" if delta < 0 else "■")
    return f"{arrow} {abs(delta)}%"


def _n(value: int, t: dict) -> str:
    return f"{value:,}".replace(",", t["thousands_sep"])


def _tz_label(tz: ZoneInfo) -> str:
    return datetime.datetime.now(tz).strftime("%Z")


def _who(guild: discord.Guild | None, uid: str, name: str) -> str:
    return f"<@{uid}>" if guild is not None and guild.get_member(int(uid)) else f"**{discord.utils.escape_markdown(name)}**"


def build_server_embed(guild: discord.Guild, report: Report, t: dict, *, recap: bool = False,
                       show_members: bool = True) -> discord.Embed:
    """Embed for a server report. All copy lives here; the heatmap PNG is graphics only."""
    title = t["recap_title" if recap else "title"].format(server=guild.name)
    if not report.enough_data:
        return discord.Embed(
            title=title,
            description=t["not_enough"].format(n=report.days_with_data),
            color=config.Discord.warn_color,
        )

    embed = discord.Embed(
        title=title,
        description=t["subtitle"].format(days=report.days, tz=_tz_label(report.tz)),
        color=config.Discord.color,
    )

    delta = _fmt_delta(report.delta_pct)
    msgs = f"**{_n(report.total, t)}**" + (f"  {delta}" if delta else "")
    embed.add_field(name=t["messages"], value=msgs, inline=True)
    embed.add_field(name=t["active_members"], value=f"**{_n(report.active_users, t)}**", inline=True)
    embed.add_field(name=t["joins_leaves"], value=f"+{report.joins} / −{report.leaves}", inline=True)

    peak = report.peak_cell
    if peak is not None:
        embed.add_field(
            name=f"{config.Icons.bulb} {t['best_time']}",
            value=t["best_time_value"].format(weekday=t["weekdays_long"][peak[0]], hour=f"{peak[1]:02d}"),
            inline=False,
        )
    if report.streak >= 2:
        embed.add_field(name=f"{config.Icons.fire} {t['streak']}", value=t["streak_value"].format(n=report.streak), inline=True)
    if report.busiest_weekday is not None:
        embed.add_field(name=t["busiest_day"], value=t["weekdays_long"][report.busiest_weekday], inline=True)

    if report.top_channels:
        embed.add_field(
            name=t["top_channels"],
            value="\n".join(
                f"`{i}.` <#{cid}> · {_n(count, t)}" for i, (cid, _name, count) in enumerate(report.top_channels[:3], 1)
            ),
            inline=False,
        )
    if show_members and report.top_users:
        embed.add_field(
            name=t["top_members"],
            value="\n".join(
                f"`{i}.` {_who(guild, uid, name)} · {_n(count, t)}"
                for i, (uid, name, count) in enumerate(report.top_users[:3], 1)
            ),
            inline=False,
        )

    embed.set_footer(text=t["footer"])
    return embed


async def server_payload(guild: discord.Guild, report: Report, t: dict, *, recap: bool = False,
                         show_members: bool = True) -> dict:
    """``send()`` kwargs (embed, plus file when the card rendered). A failing renderer
    degrades to a text-only embed instead of blocking the response."""
    embed = build_server_embed(guild, report, t, recap=recap, show_members=show_members)
    if not report.enough_data:
        return {"embed": embed}
    try:
        buf = await asyncio.to_thread(
            pulse_card.render_heatmap_card,
            report.grid, [c for _, c in report.daily], report.peak_cell, t["weekdays"],
        )
    except Exception as e:
        logger.error(f"[Pulse] heatmap render failed: {e}")
        return {"embed": embed}
    embed.set_image(url="attachment://pulse.png")
    return {"embed": embed, "file": discord.File(buf, filename="pulse.png")}


def build_user_embed(member: discord.Member, ur: UserReport, t: dict) -> discord.Embed:
    embed = discord.Embed(
        title=t["me_title"].format(user=member.display_name),
        description=t["me_subtitle"].format(days=ur.days),
        color=config.Discord.color,
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    if ur.total == 0:
        embed.description += "\n\n" + t["me_empty"]
        embed.set_footer(text=t["footer"])
        return embed
    embed.add_field(name=t["messages"], value=f"**{_n(ur.total, t)}**", inline=True)
    embed.add_field(name=t["me_active_days"], value=f"**{ur.active_days}** / {ur.days}", inline=True)
    if ur.rank:
        embed.add_field(name=t["me_rank"], value=f"**#{ur.rank}** / {ur.ranked_users}", inline=True)
    embed.add_field(name=t["me_share"], value=f"**{ur.share_pct}%**", inline=True)
    if ur.streak >= 2:
        embed.add_field(name=f"{config.Icons.fire} {t['streak']}", value=t["streak_value"].format(n=ur.streak), inline=True)
    embed.add_field(name=t["me_persona"], value=t["persona"][ur.persona], inline=True)
    embed.set_footer(text=t["footer"])
    return embed


async def user_payload(member: discord.Member, ur: UserReport, t: dict) -> dict:
    embed = build_user_embed(member, ur, t)
    if ur.total == 0:
        return {"embed": embed}
    try:
        buf = await asyncio.to_thread(
            pulse_card.render_user_card, [c for _, c in ur.daily], ur.weekday, t["weekdays"],
        )
    except Exception as e:
        logger.error(f"[Pulse] user card render failed: {e}")
        return {"embed": embed}
    embed.set_image(url="attachment://pulse_me.png")
    return {"embed": embed, "file": discord.File(buf, filename="pulse_me.png")}


# ── Weekly recap ─────────────────────────────────────────────────────────────

async def post_recap(bot: commands.AutoShardedBot, guild: discord.Guild, cfg: dict) -> bool:
    """Post the weekly recap into the configured channel. Returns True when something was sent."""
    channel_id = str(cfg.get("channel", "") or "")
    if not channel_id.isdigit():
        return False
    channel = guild.get_channel(int(channel_id))
    if not isinstance(channel, (discord.TextChannel, discord.Thread)):
        return False

    t = datasys.load_lang_file(guild.id)["pulse"]
    report = await asyncio.to_thread(build_report, guild.id, 7, resolve_tz(cfg.get("timezone")))
    if not report.enough_data:
        return False

    payload = await server_payload(guild, report, t, recap=True, show_members=bool(cfg.get("show_members", True)))
    try:
        await channel.send(**payload)
    except (discord.Forbidden, discord.HTTPException) as e:
        logger.warn(f"[Pulse] could not post recap in {guild.id}: {e}")
        return False
    return True


def recap_due(cfg: dict, now_utc: datetime.datetime | None = None) -> tuple[bool, str]:
    """(due, local_date_iso). Due once per week, from the configured weekday/hour onwards,
    so a bot restart or short downtime never skips or duplicates a recap."""
    now_utc = now_utc or datetime.datetime.now(_UTC)
    local = now_utc.astimezone(resolve_tz(cfg.get("timezone")))
    today = local.date().isoformat()
    if not cfg.get("enabled") or not str(cfg.get("channel", "") or "").isdigit():
        return False, today
    if local.weekday() != int(cfg.get("weekday", 0)) or local.hour < int(cfg.get("hour", 18)):
        return False, today
    return cfg.get("last_recap", "") != today, today


class PulseTask:
    """Posts each guild's weekly recap when it is due (checked every 10 minutes)."""

    def __init__(self, bot: commands.AutoShardedBot):
        self.bot = bot

    @tasks.loop(minutes=10)
    async def tick(self):
        try:
            set_task_status("Pulse", "running", "Checking weekly recaps...")
            posted = 0
            for guild in list(self.bot.guilds):
                try:
                    cfg = load_cfg(guild.id)
                    due, today = recap_due(cfg)
                    if not due:
                        continue
                    # Mark first: a failing channel must not be retried every 10 minutes.
                    datasys.save_data(guild.id, "pulse", {**cfg, "last_recap": today})
                    if await post_recap(self.bot, guild, cfg):
                        posted += 1
                except Exception as e:
                    logger.error(f"[Pulse] recap error @ {guild.id}: {e}")
            set_task_status("Pulse", "ok", f"{posted} recap(s) posted")
        except Exception as e:
            logger.error(f"[Pulse] Error in tick: {e}")
            set_task_status("Pulse", "error", f"Error: {e}")

    @tick.before_loop
    async def _before(self):
        await self.bot.wait_until_ready()
