"""Anti-Raid -  per-guild baseline learning + automatic raid response.

Baxi watches each guild over time and learns its *normal* rate of joins and messages
(an exponentially-weighted moving average, one baseline per guild). When the live rate
inside a short window deutlich exceeds that baseline -  a coordinated join wave or a
message flood -  the guild is put into a temporary **lockdown**:

  * invites are paused              (``guild.edit(invites_disabled=True)``)
  * verification level is raised     (``VerificationLevel.highest``)
  * the flooding channel(s) get slowmode
  * raiders (members who joined during the wave / are spamming) are timed out

State lives in memory in :data:`_state`. Detection has two entry points:

  * :meth:`AntiRaid.record_join`     -  called on every join (fast path for join waves)
  * :meth:`AntiRaid.record_message`  -  called from the moderation engine per message
                                        (returns a Verdict for raiders during lockdown)

The periodic :class:`~assets.tasks.AntiRaidTask` rolls the windows, updates the learned
baselines (only while *not* in lockdown, so a raid never poisons the baseline), detects
message floods, and lifts expired lockdowns -  restoring everything it changed.

Risk is per-guild only; nothing is stored as a cross-server user profile
(Discord Developer Policy compliance, see assets/moderation/risk.py).
"""
from __future__ import annotations

import datetime
import time
from collections import deque
from dataclasses import dataclass, field

import discord
from discord.ext import commands
from reds_simple_logger import Logger

import assets.data as datasys
import config.config as config
from assets.share import admin_log
from .verdict import Verdict, safe

logger = Logger()

# EWMA smoothing for the learned baselines. Low alpha = slow, stable baseline.
_EWMA_ALPHA = 0.1
# Spike factor at sensitivity 1.0: live rate must exceed baseline * factor to trip.
_BASE_SPIKE = 3.0
# Per-user message count inside the raid window that marks a member as a spammer.
_SPAMMER_MSGS = 6
# Crowd-control (tier-1) tuning.
_CC_FLOOR = 5         # absolute minimum msgs/window before auto mode can trip (ignore tiny channels)
_CC_AUTO_CAP = 1800   # hard safety cap (s) for an auto-duration soft slowmode that never calms


@dataclass
class GuildRaidState:
    join_times: deque[float] = field(default_factory=deque)
    msg_times:  deque[float] = field(default_factory=deque)
    msg_by_user: dict[int, deque[float]] = field(default_factory=dict)
    msg_by_channel: dict[int, deque[float]] = field(default_factory=dict)

    # Tier-1 "crowd control": soft per-channel slowmode without a lockdown.
    cc_until: dict[int, float] = field(default_factory=dict)  # channel_id -> expiry ts (auto = safety cap)
    cc_prev:  dict[int, int] = field(default_factory=dict)    # channel_id -> slowmode to restore
    # Per-channel learned "normal" message rate, for auto threshold/duration.
    cc_baseline: dict[int, float] = field(default_factory=dict)
    cc_seen:     dict[int, int] = field(default_factory=dict)  # per-channel warmup counter

    baseline_joins: float = 0.0
    baseline_msgs:  float = 0.0
    seen_ticks:     int = 0          # warmup counter before baseline is trusted

    raid_active: bool = False
    raid_until:  float = 0.0
    raid_reason: str = ""

    # Saved pre-lockdown state, restored on lift.
    prev_verification: discord.VerificationLevel | None = None
    prev_invites_disabled: bool | None = None
    prev_slowmode: dict[int, int] = field(default_factory=dict)


# guild_id -> state
_state: dict[int, GuildRaidState] = {}


def _st(guild_id: int) -> GuildRaidState:
    s = _state.get(guild_id)
    if s is None:
        s = GuildRaidState()
        _state[guild_id] = s
    return s


def _cfg(guild_id: int) -> dict | None:
    try:
        cfg = dict(datasys.load_data(guild_id, "antiraid"))
    except Exception:
        return None
    if not cfg.get("enabled", False):
        return None
    return cfg


def _is_whitelisted(member: discord.Member | None, cfg: dict) -> bool:
    if member is None:
        return False
    if member.guild_permissions.manage_guild:
        return True
    wl = {str(r) for r in cfg.get("whitelisted_roles", [])}
    return bool(wl) and any(str(r.id) in wl for r in member.roles)


def _spike_threshold(baseline: float, floor: int, sensitivity: float) -> float:
    """Live count needed to trip: the larger of an absolute floor and baseline*factor."""
    factor = max(2.0, _BASE_SPIKE / max(0.25, sensitivity))
    return max(float(floor), baseline * factor)


class AntiRaid:
    """Singleton facade. Detection is pure-ish; engaging/lifting a lockdown acts on Discord."""

    # ── Recording ───────────────────────────────────────────────────────────────
    async def record_join(self, member: discord.Member, bot: commands.AutoShardedBot) -> bool:
        """Track a join; engage a raid on a join wave. Returns True if a raid is active.

        During an active lockdown the joining member is actioned per ``join_action``."""
        cfg = _cfg(member.guild.id)
        if cfg is None or member.bot:
            return False
        s = _st(member.guild.id)
        now = time.time()
        window = max(2, int(cfg.get("join_window", 10)))
        s.join_times.append(now)
        _prune(s.join_times, now, window)

        if not s.raid_active:
            floor = int(cfg.get("min_joins", 5))
            sens = float(cfg.get("sensitivity", 1.0))
            warm = s.seen_ticks >= 3
            thresh = _spike_threshold(s.baseline_joins if warm else 0.0, floor, sens)
            if len(s.join_times) >= floor and len(s.join_times) >= thresh:
                await self._engage(member.guild, cfg, bot,
                                   reason=f"Join wave: {len(s.join_times)} joins in {window}s")

        if s.raid_active:
            await self._action_raider_join(member, cfg, bot)
            return True
        return False

    async def record_message(self, message: discord.Message, ctx=None) -> Verdict:
        """Track a message; during a lockdown, flag raiders (joined during the wave or
        spamming) for delete + timeout. Returns a Verdict (safe when nothing to do)."""
        if message.guild is None:
            return safe("antiraid")
        cfg = _cfg(message.guild.id)
        if cfg is None:
            return safe("antiraid")
        s = _st(message.guild.id)
        now = time.time()
        mwin = max(2, int(cfg.get("msg_window", 10)))

        s.msg_times.append(now)
        _prune(s.msg_times, now, mwin)
        ut = s.msg_by_user.get(message.author.id)
        if ut is None:
            ut = deque()
            s.msg_by_user[message.author.id] = ut
        ut.append(now)
        _prune(ut, now, mwin)

        ct = s.msg_by_channel.get(message.channel.id)
        if ct is None:
            ct = deque()
            s.msg_by_channel[message.channel.id] = ct
        ct.append(now)
        _prune(ct, now, mwin)

        if not s.raid_active:
            # Tier-1 crowd control: slow a single busy channel, no lockdown, no punishment.
            await self._crowd_control(message.channel, s, cfg, len(ct), now)
            return safe("antiraid")

        member = message.author if isinstance(message.author, discord.Member) else None
        if _is_whitelisted(member, cfg):
            return safe("antiraid")

        # A raider = joined during/just before this lockdown, or spamming inside the window.
        joined_recently = bool(
            member and member.joined_at
            and (datetime.datetime.now(datetime.timezone.utc) - member.joined_at).total_seconds()
                < int(cfg.get("lockdown_duration", 300)) + mwin
        )
        spamming = len(ut) >= _SPAMMER_MSGS
        if not (joined_recently or spamming):
            return safe("antiraid")

        mins = int(cfg.get("actions", {}).get("timeout_minutes", 10))
        return Verdict(
            rule="antiraid",
            flagged=True,
            action="timeout" if cfg.get("actions", {}).get("timeout_spammers", True) else "delete",
            delete=True,
            reason="Anti-Raid: raider activity during lockdown",
            event_type="antiraid",
            severity="high",
            meta={"timeout_minutes": mins},
        )

    async def enforce(self, message: discord.Message, verdict: Verdict, bot: commands.AutoShardedBot) -> None:
        """Delete + timeout a raider's message (no per-message channel embed during a flood)."""
        try:
            await message.delete()
        except (discord.Forbidden, discord.HTTPException):
            pass
        if verdict.action == "timeout" and isinstance(message.author, discord.Member):
            mins = int((verdict.meta or {}).get("timeout_minutes", 10))
            try:
                await message.author.timeout(
                    discord.utils.utcnow() + datetime.timedelta(minutes=mins),
                    reason="Baxi Anti-Raid: raider during lockdown",
                )
            except (discord.Forbidden, discord.HTTPException):
                pass

    # ── Periodic tick (called by AntiRaidTask) ───────────────────────────────────
    async def tick(self, guild: discord.Guild, bot: commands.AutoShardedBot) -> None:
        cfg = _cfg(guild.id)
        s = _st(guild.id)
        now = time.time()

        # Always honour an expiring lockdown, even if the system was just disabled.
        if s.raid_active and now >= s.raid_until:
            await self._lift(guild, bot)

        # Lift soft (crowd-control) slowmodes that hit their cap/manual expiry, or whose
        # system was just disabled. Auto-duration "calm again" lifting happens further down.
        for cid, until in list(s.cc_until.items()):
            if cfg is None or now >= until:
                await self._lift_crowd_control(guild, s, cid)

        if cfg is None:
            return

        jwin = max(2, int(cfg.get("join_window", 10)))
        mwin = max(2, int(cfg.get("msg_window", 10)))
        _prune(s.join_times, now, jwin)
        _prune(s.msg_times, now, mwin)
        for uid in list(s.msg_by_user.keys()):
            _prune(s.msg_by_user[uid], now, mwin)
            if not s.msg_by_user[uid]:
                del s.msg_by_user[uid]
        for cid in list(s.msg_by_channel.keys()):
            _prune(s.msg_by_channel[cid], now, mwin)
            if not s.msg_by_channel[cid]:
                del s.msg_by_channel[cid]

        joins = len(s.join_times)
        msgs = len(s.msg_times)

        # ── Crowd control: learn per-channel "normal" rate + auto "calm again" lifting ──
        cc = cfg.get("crowd_control", {}) or {}
        if not s.raid_active and cc.get("enabled", True):
            for cid, dq in s.msg_by_channel.items():
                if cid in s.cc_until:
                    continue  # don't learn while a channel is slowed (rate is suppressed)
                cnt = len(dq)
                seen = s.cc_seen.get(cid, 0)
                if seen == 0:
                    s.cc_baseline[cid] = float(cnt)
                else:
                    s.cc_baseline[cid] += _EWMA_ALPHA * (cnt - s.cc_baseline[cid])
                s.cc_seen[cid] = seen + 1

            if str(cc.get("duration_mode", "auto")) == "auto":
                for cid in list(s.cc_until.keys()):
                    dq = s.msg_by_channel.get(cid)
                    cnt = len(dq) if dq else 0
                    base = s.cc_baseline.get(cid, 0.0)
                    # Calm = back at/below normal (20% hysteresis so it doesn't flap).
                    if cnt <= max(2.0, base * 1.2):
                        await self._lift_crowd_control(guild, s, cid)

        # Learn the baseline only when calm -  never during a raid.
        if not s.raid_active:
            if s.seen_ticks == 0:
                s.baseline_joins, s.baseline_msgs = float(joins), float(msgs)
            else:
                s.baseline_joins += _EWMA_ALPHA * (joins - s.baseline_joins)
                s.baseline_msgs += _EWMA_ALPHA * (msgs - s.baseline_msgs)
            s.seen_ticks += 1

            # Message-flood detection (join waves handled live in record_join).
            floor = int(cfg.get("min_messages", 25))
            sens = float(cfg.get("sensitivity", 1.0))
            warm = s.seen_ticks >= 3
            thresh = _spike_threshold(s.baseline_msgs if warm else 0.0, floor, sens)
            if msgs >= floor and msgs >= thresh:
                await self._engage(guild, cfg, bot,
                                   reason=f"Message flood: {msgs} msgs in {mwin}s",
                                   hot_channels=self._hot_channels(s, cfg, now, mwin))

    # ── Lockdown lifecycle ───────────────────────────────────────────────────────
    async def _engage(self, guild: discord.Guild, cfg: dict, bot: commands.AutoShardedBot,
                      reason: str, hot_channels: list[int] | None = None) -> None:
        s = _st(guild.id)
        if s.raid_active:
            s.raid_until = time.time() + int(cfg.get("lockdown_duration", 300))  # extend
            return
        s.raid_active = True
        s.raid_reason = reason
        s.raid_until = time.time() + int(cfg.get("lockdown_duration", 300))
        actions = cfg.get("actions", {})

        if actions.get("pause_invites", True):
            try:
                s.prev_invites_disabled = "INVITES_DISABLED" in guild.features
                await guild.edit(invites_disabled=True, reason="Baxi Anti-Raid lockdown")
            except (discord.Forbidden, discord.HTTPException):
                pass

        if actions.get("raise_verification", True):
            try:
                s.prev_verification = guild.verification_level
                await guild.edit(verification_level=discord.VerificationLevel.highest,
                                 reason="Baxi Anti-Raid lockdown")
            except (discord.Forbidden, discord.HTTPException):
                pass

        if actions.get("slowmode", True):
            delay = max(1, min(21600, int(actions.get("slowmode_delay", 10))))
            await self._apply_slowmode(guild, s, delay, hot_channels)

        if actions.get("timeout_spammers", True):
            await self._timeout_current_spammers(guild, cfg, s)

        await self._alert(guild, cfg, bot, engaged=True)
        admin_log("error", f"Anti-Raid: LOCKDOWN @ {guild.name} -  {reason}", source="AntiRaid")
        logger.warning(f"[AntiRaid] Lockdown engaged @ {guild.name}: {reason}")

    async def _lift(self, guild: discord.Guild, bot: commands.AutoShardedBot) -> None:
        s = _st(guild.id)
        if not s.raid_active:
            return
        s.raid_active = False

        if s.prev_invites_disabled is False:
            try:
                await guild.edit(invites_disabled=False, reason="Baxi Anti-Raid lockdown lifted")
            except (discord.Forbidden, discord.HTTPException):
                pass
        if s.prev_verification is not None:
            try:
                await guild.edit(verification_level=s.prev_verification,
                                 reason="Baxi Anti-Raid lockdown lifted")
            except (discord.Forbidden, discord.HTTPException):
                pass
        for ch_id, old in list(s.prev_slowmode.items()):
            ch = guild.get_channel(ch_id)
            if isinstance(ch, discord.TextChannel):
                try:
                    await ch.edit(slowmode_delay=old, reason="Baxi Anti-Raid lockdown lifted")
                except (discord.Forbidden, discord.HTTPException):
                    pass

        s.prev_verification = None
        s.prev_invites_disabled = None
        s.prev_slowmode.clear()

        cfg = None
        try:
            cfg = dict(datasys.load_data(guild.id, "antiraid"))
        except Exception:
            cfg = {}
        await self._alert(guild, cfg or {}, bot, engaged=False)
        admin_log("info", f"Anti-Raid: lockdown lifted @ {guild.name}", source="AntiRaid")
        logger.info(f"[AntiRaid] Lockdown lifted @ {guild.name}")

    # ── Action helpers ───────────────────────────────────────────────────────────
    async def _apply_slowmode(self, guild: discord.Guild, s: GuildRaidState, delay: int,
                              hot_channels: list[int] | None) -> None:
        """Slowmode only the channel(s) the raid is actually hitting — never the whole server.

        ``hot_channels`` comes from per-channel message counts (see :meth:`_hot_channels`).
        A join-wave lockdown has no hot channel, so nothing is slowmoded (invites +
        verification carry that defence)."""
        for cid in (hot_channels or []):
            ch = guild.get_channel(cid)
            if not isinstance(ch, discord.TextChannel):
                continue
            try:
                perms = ch.permissions_for(guild.me)
            except Exception:
                continue
            if not perms.manage_channels:
                continue
            # Take over from a soft crowd-control slowmode, preserving the *original* delay.
            if cid in s.cc_until:
                s.prev_slowmode[cid] = s.cc_prev.pop(cid, ch.slowmode_delay)
                s.cc_until.pop(cid, None)
            elif cid not in s.prev_slowmode:
                s.prev_slowmode[cid] = ch.slowmode_delay
            try:
                await ch.edit(slowmode_delay=delay, reason="Baxi Anti-Raid lockdown")
            except (discord.Forbidden, discord.HTTPException):
                s.prev_slowmode.pop(cid, None)

    def _hot_channels(self, s: GuildRaidState, cfg: dict, now: float, mwin: int) -> list[int]:
        """Channels (busiest first, capped at 5) carrying the flood. Falls back to the single
        busiest channel so a lockdown always has at least one target to slow."""
        counts: list[tuple[int, int]] = []
        for cid, dq in s.msg_by_channel.items():
            _prune(dq, now, mwin)
            if dq:
                counts.append((len(dq), cid))
        counts.sort(reverse=True)
        cc_thr = max(2, int((cfg.get("crowd_control", {}) or {}).get("threshold", 12)))
        hot = [cid for n, cid in counts if n >= cc_thr][:5]
        if not hot and counts:
            hot = [counts[0][1]]
        return hot

    # ── Crowd control (tier-1, no lockdown) ──────────────────────────────────────
    async def _crowd_control(self, channel: discord.abc.Messageable, s: GuildRaidState,
                             cfg: dict, count: int, now: float) -> None:
        """Soft-slow a single busy channel when its rate spikes — no lockdown, no punishment.
        This is the merged former 'Auto-Slowmode' feature, scoped to the hot channel only."""
        cc = cfg.get("crowd_control", {}) or {}
        if not cc.get("enabled", True):
            return
        if not isinstance(channel, discord.TextChannel):
            return
        cid = channel.id
        if cid in s.cc_until:  # already slowed
            return

        # Trip decision: manual = fixed count, auto = above the channel's learned normal.
        if str(cc.get("threshold_mode", "auto")) == "manual":
            if count < max(2, int(cc.get("threshold", 12))):
                return
        else:
            warm = s.cc_seen.get(cid, 0) >= 3
            base = s.cc_baseline.get(cid, 0.0) if warm else 0.0
            thr = _spike_threshold(base, _CC_FLOOR, float(cfg.get("sensitivity", 1.0)))
            if count < _CC_FLOOR or count < thr:
                return

        try:
            perms = channel.permissions_for(channel.guild.me)
        except Exception:
            return
        if not perms.manage_channels:
            return
        delay = max(1, min(21600, int(cc.get("slowmode_delay", 5))))
        s.cc_prev[cid] = channel.slowmode_delay
        try:
            await channel.edit(slowmode_delay=delay,
                               reason="Baxi Crowd Control: channel rate spike")
        except (discord.Forbidden, discord.HTTPException):
            s.cc_prev.pop(cid, None)
            return

        # Duration: manual = fixed seconds, auto = lift on calm (tick), capped for safety.
        if str(cc.get("duration_mode", "auto")) == "manual":
            s.cc_until[cid] = now + max(10, int(cc.get("duration", 120)))
        else:
            s.cc_until[cid] = now + _CC_AUTO_CAP
        logger.info(f"[CrowdControl] {delay}s slowmode on #{channel.name} @ {channel.guild.name} "
                    f"({count} msgs in window)")
        if str(cc.get("duration_mode", "auto")) == "manual":
            lift_note = f"It lifts automatically in **{int(cc.get('duration', 120))}s**."
        else:
            lift_note = "It lifts automatically once the channel calms down."
        try:
            embed = discord.Embed(
                title="⏱ Slowmode activated",
                description=(f"A burst of activity was detected, so a **{delay}s** slowmode was "
                            f"applied to this channel. {lift_note}"),
                color=config.Discord.warn_color,
            )
            embed.set_footer(text="Baxi · Anti-Raid · Crowd Control")
            await channel.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException):
            pass

    async def _lift_crowd_control(self, guild: discord.Guild, s: GuildRaidState, cid: int) -> None:
        s.cc_until.pop(cid, None)
        prev = s.cc_prev.pop(cid, 0)
        ch = guild.get_channel(cid)
        if isinstance(ch, discord.TextChannel):
            try:
                await ch.edit(slowmode_delay=prev, reason="Baxi Crowd Control: expired")
                logger.info(f"[CrowdControl] Lifted slowmode on #{ch.name}")
            except (discord.Forbidden, discord.HTTPException):
                pass

    async def _timeout_current_spammers(self, guild: discord.Guild, cfg: dict, s: GuildRaidState) -> None:
        mins = int(cfg.get("actions", {}).get("timeout_minutes", 10))
        until = discord.utils.utcnow() + datetime.timedelta(minutes=mins)
        for uid, times in list(s.msg_by_user.items()):
            if len(times) < _SPAMMER_MSGS:
                continue
            member = guild.get_member(uid)
            if member is None or _is_whitelisted(member, cfg):
                continue
            try:
                await member.timeout(until, reason="Baxi Anti-Raid: spammer during raid")
            except (discord.Forbidden, discord.HTTPException):
                pass

    async def _action_raider_join(self, member: discord.Member, cfg: dict,
                                  bot: commands.AutoShardedBot) -> None:
        action = str(cfg.get("join_action", "timeout"))
        if action == "none" or _is_whitelisted(member, cfg):
            return
        try:
            if action == "kick":
                await member.kick(reason="Baxi Anti-Raid: joined during raid")
            elif action == "quarantine":
                role_id = int(cfg.get("quarantine_role", 0) or 0)
                role = member.guild.get_role(role_id) if role_id else None
                if role:
                    await member.add_roles(role, reason="Baxi Anti-Raid quarantine")
            else:  # timeout
                mins = int(cfg.get("actions", {}).get("timeout_minutes", 10))
                await member.timeout(
                    discord.utils.utcnow() + datetime.timedelta(minutes=mins),
                    reason="Baxi Anti-Raid: joined during raid",
                )
        except (discord.Forbidden, discord.HTTPException):
            pass

    async def _alert(self, guild: discord.Guild, cfg: dict, bot: commands.AutoShardedBot,
                     engaged: bool) -> None:
        ch = None
        try:
            ch_id = int(cfg.get("alert_channel", 0) or 0)
            if ch_id:
                ch = guild.get_channel(ch_id)
            if ch is None:
                notif = datasys.load_data(guild.id, "notification_channel")
                if notif:
                    ch = guild.get_channel(int(notif))
        except Exception:
            ch = None
        if ch is None:
            return
        s = _st(guild.id)
        lang = datasys.load_lang_file(guild.id)
        strings = (lang.get("systems", {}) or {}).get("antiraid", {})
        try:
            if engaged:
                embed = discord.Embed(
                    title=strings.get("lockdown_title", "🛡 Anti-Raid · Lockdown"),
                    description=str(strings.get("lockdown_desc",
                        "A raid was detected and the server has been locked down.")
                        ).format(reason=s.raid_reason),
                    color=config.Discord.danger_color,
                )
                embed.add_field(name=strings.get("reason_field", "Trigger"),
                                value=s.raid_reason or "–", inline=False)
            else:
                embed = discord.Embed(
                    title=strings.get("lifted_title", "✅ Anti-Raid · Lockdown lifted"),
                    description=str(strings.get("lifted_desc",
                        "The lockdown has expired. Settings were restored.")),
                    color=config.Discord.success_color,
                )
            embed.set_footer(text="Baxi · Anti-Raid")
            await ch.send(embed=embed)
        except Exception:
            pass


def _prune(dq: deque[float], now: float, window: float) -> None:
    while dq and now - dq[0] >= window:
        dq.popleft()


# Module-level singleton used by the engine, events and the periodic task.
antiraid = AntiRaid()
