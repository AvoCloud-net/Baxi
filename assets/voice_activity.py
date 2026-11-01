"""Voice time tracking for BaxiInsights / Pulse.

Counts only how long a member sat in which voice channel (seconds per day, per user and per
channel) - no content. Sessions live in memory: joins/leaves/moves close or open them
immediately, and a 5-minute reconcile credits running sessions and repairs anything the
gateway events missed (reconnects, bot restart), so at most ~5 minutes are ever lost.

Voice XP (assets/leveling.py) rides on the same events and reconcile, with its own clock per
member so Insights keeps counting exactly as before. A member's XP clock runs only while
  - they are not deafened (self or server; muted is fine),
  - at least one other human in the same channel is not deafened either,
  - the channel is not the guild's AFK channel, and they are not a bot.
Any voice change re-checks everyone in the old and new channel (one person deafening or
leaving can stop their partner's clock). The reconcile banks the running time and turns
full minutes into XP; leftover seconds stay on the clock, also across leaves and rejoins,
until a clock has been stopped for XP_CLOCK_TTL. Only guilds with the level system on get
clocks (idle.guild_ids_with). XP clocks use time.monotonic(); Insights stays on wall time.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import discord
from discord.ext import commands, tasks

import assets.data as datasys
import assets.idle as idle
from assets.share import set_task_status
from reds_simple_logger import Logger

logger = Logger()


@dataclass
class _Session:
    channel_id: int
    channel_name: str
    user_name: str
    since: float


_sessions: dict[tuple[int, int], _Session] = {}
_Entry = tuple[str, str, str, str, int]


@dataclass
class _XpClock:
    since: float | None = None       # start of the current XP-eligible stretch (None = stopped)
    carry: float = 0.0               # eligible seconds not yet turned into XP
    stopped_at: float | None = None  # when it last stopped (for the cleanup)


_xp: dict[tuple[int, int], _XpClock] = {}
XP_CLOCK_TTL = 3600   # a clock stopped this long is dropped with its leftover seconds


def _eligible(member: discord.Member, channel) -> bool:
    """Bots do not count, and neither does the guild's AFK channel."""
    if member.bot or channel is None:
        return False
    afk = member.guild.afk_channel
    return afk is None or channel.id != afk.id


def _deaf(state) -> bool:
    return state is None or bool(state.self_deaf or state.deaf)


def _xp_eligible(member: discord.Member, channel, state=None) -> bool:
    """May this member earn voice XP in ``channel`` right now? ``state`` defaults to member.voice."""
    if not _eligible(member, channel) or _deaf(state if state is not None else member.voice):
        return False
    return any(m.id != member.id and not m.bot and not _deaf(m.voice) for m in channel.members)


def _xp_set(key: tuple[int, int], on: bool, now: float) -> None:
    """Start or stop a member's XP clock (stopping banks the elapsed time into carry)."""
    c = _xp.get(key)
    if on:
        if c is None:
            _xp[key] = _XpClock(since=now)
        elif c.since is None:
            c.since, c.stopped_at = now, None
    elif c is not None and c.since is not None:
        c.carry += max(0.0, now - c.since)
        c.since, c.stopped_at = None, now


def _xp_sync_channel(channel, now: float) -> None:
    for m in channel.members:
        _xp_set((m.guild.id, m.id), _xp_eligible(m, channel), now)


def _xp_bank(now: float) -> dict[int, dict[int, int]]:
    """Move running time into carry and take out the full minutes: {guild: {user: minutes}}."""
    due: dict[int, dict[int, int]] = {}
    for key, c in list(_xp.items()):
        if c.since is not None:
            c.carry += max(0.0, now - c.since)
            c.since = now
        mins = int(c.carry // 60)
        if mins:
            c.carry -= mins * 60
            due.setdefault(key[0], {})[key[1]] = mins
        if c.since is None and (c.carry < 1 or now - (c.stopped_at or now) >= XP_CLOCK_TTL):
            del _xp[key]   # stopped with (almost) nothing left over, or stopped for long
    return due


def _leveling_guilds(bot) -> frozenset[int] | None:
    """Guilds with the level system on; None (= all) when no bot is at hand (tests)."""
    bot = bot if bot is not None else idle._bot
    return idle.guild_ids_with(bot, "leveling") if bot is not None else None


def _xp_on_voice_state(member, before, after, bot) -> None:
    gid = member.guild.id
    enabled = _leveling_guilds(bot)
    if enabled is not None and gid not in enabled:
        return
    now = time.monotonic()
    b, a = before.channel, after.channel
    # Deafen toggles, joins, leaves and moves can change who qualifies, in both channels.
    _xp_set((gid, member.id), a is not None and _xp_eligible(member, a, after), now)
    for ch in {c.id: c for c in (b, a) if c is not None}.values():
        _xp_sync_channel(ch, now)


def _xp_reconcile(bot) -> dict[int, dict[int, int]]:
    """Re-check every XP clock against the live state (repairs missed events), then bank."""
    now = time.monotonic()
    enabled = _leveling_guilds(bot)
    xp_live: set[tuple[int, int]] = set()
    for guild in bot.guilds:
        if enabled is not None and guild.id not in enabled:
            continue
        for ch in (*guild.voice_channels, *guild.stage_channels):
            for m in ch.members:
                if _xp_eligible(m, ch):
                    xp_live.add((guild.id, m.id))
    for key in list(_xp):
        if enabled is not None and key[0] not in enabled:
            del _xp[key]   # level system switched off: no clock, no carry
    for key in xp_live | set(_xp):
        _xp_set(key, key in xp_live, now)
    return _xp_bank(now)


def _take(key: tuple[int, int], now: float, out: dict[int, list[_Entry]], *, keep: bool) -> None:
    """Credit a session's elapsed time into ``out``; drop it unless ``keep``."""
    s = _sessions[key] if keep else _sessions.pop(key)
    secs = int(now - s.since)
    if secs > 0:
        out.setdefault(key[0], []).append((str(s.channel_id), s.channel_name, str(key[1]), s.user_name, secs))
        s.since += secs


def _open(member: discord.Member, channel, now: float) -> None:
    _sessions[(member.guild.id, member.id)] = _Session(channel.id, channel.name, member.name, now)


def _write(out: dict[int, list[_Entry]]) -> None:
    for gid, entries in out.items():
        datasys.add_voice_time(gid, entries)


def on_voice_state(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState,
                   bot: commands.AutoShardedBot | None = None) -> None:
    """Close the old session / open the new one on join, leave and move (+ voice XP clocks)."""
    try:
        _xp_on_voice_state(member, before, after, bot)
    except Exception as e:   # never let XP cost Insights a join or leave
        logger.error(f"[VoiceActivity] voice XP update failed: {e}")
    b, a = before.channel, after.channel
    now = time.time()
    key = (member.guild.id, member.id)
    if (b.id if b else None) == (a.id if a else None):
        return  # mute / deafen / stream toggles
    out: dict[int, list[_Entry]] = {}
    if key in _sessions:
        _take(key, now, out, keep=False)
    if _eligible(member, a):
        _open(member, a, now)
    _write(out)


def reconcile(bot: commands.AutoShardedBot) -> tuple[int, dict[int, dict[int, int]]]:
    """Credit running sessions, close stale ones, open any missed.

    Also re-checks every XP clock against the live state (repairs missed events) and banks
    them. Returns (live session count, {guild_id: {user_id: full voice-XP minutes}}).
    """
    try:
        xp_due = _xp_reconcile(bot)
    except Exception as e:   # never let XP cost Insights its reconcile
        logger.error(f"[VoiceActivity] voice XP reconcile failed: {e}")
        xp_due = {}
    now = time.time()
    live: dict[tuple[int, int], tuple[discord.abc.GuildChannel, discord.Member]] = {}
    for guild in bot.guilds:
        for ch in (*guild.voice_channels, *guild.stage_channels):
            for m in ch.members:
                if _eligible(m, ch):
                    live[(guild.id, m.id)] = (ch, m)

    out: dict[int, list[_Entry]] = {}
    for key in list(_sessions):
        cur = live.get(key)
        if cur is not None and cur[0].id == _sessions[key].channel_id:
            _take(key, now, out, keep=True)
            _sessions[key].channel_name = cur[0].name
            _sessions[key].user_name = cur[1].name
        else:
            _take(key, now, out, keep=False)
    for key, (ch, m) in live.items():
        if key not in _sessions:
            _open(m, ch, now)
    _write(out)
    return len(_sessions), xp_due


class VoiceActivityTask:
    def __init__(self, bot: commands.AutoShardedBot):
        self.bot = bot

    @tasks.loop(minutes=5)
    async def tick(self):
        try:
            n, xp_due = reconcile(self.bot)
            credited = 0
            if xp_due:
                from assets import leveling
                credited = await leveling.credit_voice(self.bot, xp_due)
            if n or credited:   # rest mode: nothing to report, no admin-log write
                set_task_status("VoiceActivity", "ok", f"{n} active voice session(s), voice XP for {credited}")
        except Exception as e:
            logger.error(f"[VoiceActivity] Error in tick: {e}")
            set_task_status("VoiceActivity", "error", f"Error: {e}")

    @tick.before_loop
    async def _before(self):
        await self.bot.wait_until_ready()
