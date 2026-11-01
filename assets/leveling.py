"""
Per-user, per-server level system: one level, two XP sources.

- Text XP: at most once per TEXT_COOLDOWN seconds per user and server, for a message that
  passed anti-spam (events.process_message stops before XP otherwise) and whose chat-filter
  verdict allows it (``earns_xp``: removed -> no XP, borderline -> BORDERLINE_EARNS_XP).
- Voice XP: VOICE_XP_PER_MINUTE per full minute, credited by the 5-minute reconcile in
  assets/voice_activity.py (rules live there: not deafened, another non-deafened human in
  the channel, not the AFK channel, no bots).

The level comes from text_xp + voice_xp. Role rewards and announcements hang on that total.
Data: SQLite ``leveling_users`` via single-row reads/upserts (assets/repo/entities.py).

Level-up announcement ("announcement" config):
- "channel":      the configured announcement channel (skipped if none is set / found),
- "same_channel": where the XP was earned: the message's channel for text, the built-in
                  chat of the voice channel the member is in for voice (skipped if they
                  already left voice),
- "off":          none. Role rewards are given in every mode.
"""
from __future__ import annotations

import asyncio
import io
import time

import discord
from discord.ext import commands

import assets.data as datasys
import assets.idle as idle
from assets.repo import entities as lv_repo
import config.config as config
from reds_simple_logger import Logger

logger = Logger()

TEXT_COOLDOWN = 60          # seconds between two text-XP grants per user and server
# Borderline messages stay up and wait in the mod queue. Until staff decide, do they earn XP?
BORDERLINE_EARNS_XP = True
VOICE_XP_PER_MINUTE = 5
SOURCES = ("total", "text", "voice")

# ---------------------------------------------------------------------------
# XP helpers
# ---------------------------------------------------------------------------

def _xp_for_message(content: str) -> int:
    """XP granted for a single message, based on its length."""
    length = len(content.strip())
    if length < 20:
        return 8
    if length < 100:
        return 20
    if length < 300:
        return 35
    return 50


def xp_needed_for_level(level: int) -> int:
    """
    Total (cumulative) XP required to reach *level*.
    Formula: level * (level + 1) * 50
    e.g. level 1 → 100 XP, level 2 → 300 XP, level 3 → 600 XP …
    """
    return level * (level + 1) * 50


def current_level_from_xp(total_xp: int) -> int:
    """Return the level that corresponds to *total_xp*."""
    level = 0
    while xp_needed_for_level(level + 1) <= total_xp:
        level += 1
    return level


def xp_progress(total_xp: int) -> tuple[int, int, int]:
    """
    Returns (current_level, xp_into_level, xp_needed_for_next_level).
    xp_into_level / xp_needed_for_next_level gives the progress bar fraction.
    """
    level = current_level_from_xp(total_xp)
    xp_start = xp_needed_for_level(level)
    xp_next = xp_needed_for_level(level + 1)
    return level, total_xp - xp_start, xp_next - xp_start


# ---------------------------------------------------------------------------
# Text cooldown (in memory; a restart only means one early grant per user)
# ---------------------------------------------------------------------------

_last_text_xp: dict[tuple[int, int], float] = {}


def _cooldown_ready(guild_id: int, user_id: int, now: float | None = None) -> bool:
    """True (and stamps the time) if this user may earn text XP again."""
    now = time.monotonic() if now is None else now
    key = (guild_id, user_id)
    last = _last_text_xp.get(key)
    if last is not None and now - last < TEXT_COOLDOWN:
        return False
    _last_text_xp[key] = now
    if len(_last_text_xp) > 10_000:   # forget stamps that no longer block anything
        for k in [k for k, t in _last_text_xp.items() if now - t >= TEXT_COOLDOWN]:
            _last_text_xp.pop(k, None)
    return True


# ---------------------------------------------------------------------------
# Per-guild user data  (SQLite leveling_users, one row per user)
# { "xp": total, "text_xp": .., "voice_xp": .., "level": .., "messages": .., "name": .. }
# ---------------------------------------------------------------------------

_EMPTY = {"xp": 0, "text_xp": 0, "voice_xp": 0, "level": 0, "messages": 0, "name": ""}


def _load_users(guild_id: int) -> dict:
    """All users of a guild. Avoid on hot paths; use get_user_entry / leaderboard."""
    return dict(datasys.load_data(guild_id, "leveling_users"))


def get_user_entry(guild_id: int, user_id: int) -> dict:
    """Returns the leveling entry for a single user (or empty defaults)."""
    return lv_repo.get_leveling_user(guild_id, user_id) or dict(_EMPTY)


def leaderboard(guild_id: int, source: str = "total", limit: int = 10) -> list[tuple[str, dict]]:
    return lv_repo.leveling_leaderboard(guild_id, source if source in SOURCES else "total", limit)


def rank_position(guild_id: int, user_id: int, source: str = "total") -> int | None:
    return lv_repo.leveling_rank(guild_id, user_id, source if source in SOURCES else "total")


def _add(guild_id: int, user_id: int, name: str | None, *, text_xp: int = 0, voice_xp: int = 0,
         messages: int = 0) -> tuple[int, dict]:
    return lv_repo.add_leveling_xp(
        guild_id, user_id, name, level_for=current_level_from_xp,
        text_xp=text_xp, voice_xp=voice_xp, messages=messages,
    )


# ---------------------------------------------------------------------------
# Level-up: role rewards + announcement
# ---------------------------------------------------------------------------

async def _apply_role_rewards(member: discord.Member, new_level: int, role_rewards: list) -> None:
    """Assign roles whose threshold is <= new_level to this member."""
    for reward in role_rewards:
        try:
            threshold = int(reward.get("level", 0))
            role_id = int(reward.get("role_id", 0))
            if not threshold or not role_id or new_level < threshold:
                continue
            role = member.guild.get_role(role_id)
            if role is None or role in member.roles:
                continue
            await member.add_roles(role, reason=f"Baxi Level System: reached level {new_level}")
        except Exception:
            pass


async def _on_level_up(
    bot: commands.AutoShardedBot,
    member: discord.abc.User,
    guild: discord.Guild,
    new_level: int,
    same_channel,
) -> None:
    """Role rewards + announcement. ``same_channel`` is where the XP was earned (or None)."""
    leveling_cfg: dict = dict(datasys.load_data(guild.id, "leveling"))

    role_rewards: list = leveling_cfg.get("role_rewards", [])
    if role_rewards and isinstance(member, discord.Member):
        try:
            await _apply_role_rewards(member, new_level, role_rewards)
        except Exception as exc:
            logger.error(f"[Leveling] Role reward error: {exc}")

    announcement_mode: str = leveling_cfg.get("announcement", "same_channel")
    if announcement_mode == "off":
        return
    if announcement_mode == "same_channel":
        target_channel = same_channel
    else:
        ch_id_raw = str(leveling_cfg.get("announcement_channel", "") or "")
        target_channel = bot.get_channel(int(ch_id_raw)) if ch_id_raw.isdigit() else None
    if target_channel is None:
        return

    t: dict = datasys.load_lang_file(guild.id)["leveling"]
    embed = discord.Embed(
        title=t["levelup_title"].format(level=new_level),
        description=t["levelup_desc"].format(user=member.mention, level=new_level),
        color=config.Discord.success_color,
    )
    embed.set_footer(text="Baxi · avocloud.net")
    try:
        await target_channel.send(embed=embed)
    except (discord.Forbidden, discord.HTTPException, AttributeError) as exc:
        logger.warn(f"[Leveling] Could not send level-up announcement: {exc}")


# ---------------------------------------------------------------------------
# Text XP -  called from events.process_message (after anti-spam + chat filter)
# ---------------------------------------------------------------------------

def earns_xp(verdict) -> bool:
    """May a message with this chat-filter verdict (events.ChatfilterVerdict) earn XP?"""
    if verdict is None:
        return True              # chat filter did not look at it (off, exempt, ...)
    if verdict.removed:
        return False
    if verdict.borderline:
        return BORDERLINE_EARNS_XP
    return True


async def process_xp(message: discord.Message, bot: commands.AutoShardedBot, verdict=None) -> None:
    """Count the message, award XP if the verdict and the cooldown allow, handle a level-up."""
    if message.guild is None or message.author.bot:
        return
    guild_id = message.guild.id
    if guild_id not in idle.guild_ids_with(bot, "leveling"):
        return

    earned = 0
    if earns_xp(verdict) and _cooldown_ready(guild_id, message.author.id):
        earned = _xp_for_message(message.content)
    old_level, entry = _add(guild_id, message.author.id, message.author.name,
                            text_xp=earned, messages=1)
    if entry["level"] > old_level:
        await _on_level_up(bot, message.author, message.guild, entry["level"], message.channel)


# ---------------------------------------------------------------------------
# Voice XP -  called from voice_activity's 5-minute reconcile
# ---------------------------------------------------------------------------

async def credit_voice(bot: commands.AutoShardedBot, minutes: dict[int, dict[int, int]]) -> int:
    """Credit ``{guild_id: {user_id: full_minutes}}`` as voice XP. Returns users credited.

    Guilds without the level system get nothing (the minutes are dropped, not saved up).
    """
    if not minutes:
        return 0
    enabled = idle.guild_ids_with(bot, "leveling")
    credited = 0
    for gid, users in minutes.items():
        if gid not in enabled:
            continue
        guild = bot.get_guild(gid)
        if guild is None:
            continue
        for uid, mins in users.items():
            if mins <= 0:
                continue
            member = guild.get_member(uid)
            try:
                old_level, entry = _add(gid, uid, member.name if member else None,
                                        voice_xp=mins * VOICE_XP_PER_MINUTE)
            except Exception as exc:
                logger.error(f"[Leveling] voice XP for {uid} @ {gid}: {exc}")
                continue
            credited += 1
            if entry["level"] > old_level and member is not None:
                voice = member.voice.channel if member.voice else None
                await _on_level_up(bot, member, guild, entry["level"], voice)
    return credited


# ---------------------------------------------------------------------------
# /rank: embed (all copy) + card PNG (graphics only)
# ---------------------------------------------------------------------------

def _text_bar(xp_into: int, xp_needed: int) -> str:
    filled = int((xp_into / xp_needed) * 20) if xp_needed else 20
    return "█" * filled + "░" * (20 - filled)


async def rank_payload(member: discord.abc.User, guild: discord.Guild, t: dict) -> dict:
    """``followup.send`` kwargs for a member's rank: embed always, card image if it renders."""
    entry = await asyncio.to_thread(get_user_entry, guild.id, member.id)
    pos = await asyncio.to_thread(rank_position, guild.id, member.id)
    total, text_xp, voice_xp = int(entry["xp"]), int(entry["text_xp"]), int(entry["voice_xp"])
    level, xp_into, xp_needed = xp_progress(total)
    level = max(level, int(entry.get("level", 0)))

    lines = [
        t["rank_progress"].format(into=f"{xp_into:,}", needed=f"{xp_needed:,}", next=level + 1),
        t["rank_split"].format(text=f"{text_xp:,}", voice=f"{voice_xp:,}",
                               messages=f"{int(entry['messages']):,}"),
    ]
    if pos is not None:
        lines.append(t["rank_position"].format(rank=pos))
    embed = discord.Embed(
        title=t["rank_card_title"].format(user=member.display_name, level=level),
        description="\n".join(lines),
        color=config.Discord.color,
    )
    embed.set_footer(text=t["rank_footer"])

    try:
        from assets import rank_card
        buf: io.BytesIO = await rank_card.render_rank(
            avatar_url=member.display_avatar.url, level=level,
            xp_into=xp_into, xp_needed=xp_needed, text_xp=text_xp, voice_xp=voice_xp,
        )
        file = discord.File(buf, filename="rank.png")
        embed.set_image(url="attachment://rank.png")
        return {"embed": embed, "file": file}
    except Exception as exc:
        logger.error(f"[Leveling] rank card render failed: {exc}")
        embed.add_field(name=t["progress_field"],
                        value=f"`{_text_bar(xp_into, xp_needed)}` {xp_into:,} / {xp_needed:,} XP",
                        inline=False)
        embed.set_thumbnail(url=member.display_avatar.url)
        return {"embed": embed}


def leaderboard_embed(guild: discord.Guild, t: dict, source: str = "total") -> discord.Embed:
    """Top 10 by total XP (default) or by text / voice XP only."""
    source = source if source in SOURCES else "total"
    suffix = "" if source == "total" else f"_{source}"
    title = t["leaderboard_title" + suffix].format(guild=guild.name)
    rows = leaderboard(guild.id, source, 10)
    if not rows:
        return discord.Embed(title=title, description=t["leaderboard_empty" + suffix],
                             color=config.Discord.color)

    xp_key = {"total": "xp", "text": "text_xp", "voice": "voice_xp"}[source]
    lines = []
    for i, (uid, data) in enumerate(rows):
        prefix = config.Icons.medal if i < 3 else f"`{i + 1}.`"
        member = guild.get_member(int(uid))
        name = member.display_name if member else (data.get("name") or f"User {uid}")
        lvl = max(current_level_from_xp(int(data["xp"])), int(data.get("level", 0)))
        lines.append(f"{prefix} **{name}** -  " + t["leaderboard_line" + suffix].format(
            level=lvl, xp=f"{int(data[xp_key]):,}"))
    embed = discord.Embed(title=title, description="\n".join(lines), color=config.Discord.color)
    embed.set_footer(text="Baxi · avocloud.net")
    return embed
