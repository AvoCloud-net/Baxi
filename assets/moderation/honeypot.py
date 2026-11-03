"""Honeypot channel - catches spam bots.

Admins pick one channel; a notice in it tells people not to write there. Nobody legitimate
ever posts in it, spam bots post into every channel they can reach. Whoever writes there is
removed through the normal case flow (`cases.run_automatic`: case #, one DM, audit-log reason)
and the message is deleted. Staff (Manage Messages / Manage Server / Administrator) and bots
are ignored, so the team can look at the channel without consequences.

The ban deletes the member's messages of the last `delete_hours` hours in all channels, which
is what actually cleans up after a spam wave. Kick and mute only remove the honeypot message.
"""
from __future__ import annotations

import datetime

import discord
from discord.ext import commands

import assets.data as datasys
import config.config as config
from assets.moderation import cases
from reds_simple_logger import Logger

logger = Logger()

ACTIONS = ("ban", "kick", "mute")
MUTE_SECONDS = 24 * 3600
_DEFAULTS = {"enabled": False, "channel": "", "action": "ban", "delete_hours": 1, "panel_message_id": ""}

_busy: set[tuple[int, int]] = set()   # (guild, user) currently being handled


def load_cfg(guild_id: int) -> dict:
    cfg = {**_DEFAULTS, **dict(datasys.load_data(guild_id, "honeypot") or {})}
    if cfg["action"] not in ACTIONS:
        cfg["action"] = "ban"
    return cfg


def _is_staff(member: discord.Member) -> bool:
    p = member.guild_permissions
    return p.administrator or p.manage_guild or p.manage_messages


def notice_embed(guild: discord.Guild, cfg: dict) -> discord.Embed:
    t = datasys.load_lang_file(guild.id)["honeypot"]
    return discord.Embed(
        title=t["title"],
        description=str(t["description"]).format(action=t["action_" + cfg["action"]]),
        color=config.Discord.danger_color,
    )


async def post_notice(guild: discord.Guild, cfg: dict) -> str:
    """Post (or refresh) the warning in the honeypot channel; returns the message id."""
    raw = str(cfg.get("channel", "") or "")
    channel = guild.get_channel(int(raw)) if raw.isdigit() else None
    if not isinstance(channel, discord.TextChannel):
        return ""
    embed = notice_embed(guild, cfg)
    old = str(cfg.get("panel_message_id", "") or "")
    if old.isdigit():
        try:
            msg = await channel.fetch_message(int(old))
            await msg.edit(embed=embed)
            return str(msg.id)
        except (discord.NotFound, discord.HTTPException):
            pass
    msg = await channel.send(embed=embed)
    return str(msg.id)


async def handle(message: discord.Message, bot: commands.AutoShardedBot) -> bool:
    """True if the message was written in a honeypot channel (the caller stops processing it)."""
    guild = message.guild
    if guild is None:
        return False
    cfg = load_cfg(guild.id)
    if not cfg["enabled"] or str(message.channel.id) != str(cfg["channel"]):
        return False
    if message.author.bot or message.webhook_id is not None:
        return True
    member = message.author if isinstance(message.author, discord.Member) else guild.get_member(message.author.id)
    if member is None or _is_staff(member):
        return True

    key = (guild.id, member.id)
    try:
        await message.delete()
    except (discord.Forbidden, discord.HTTPException):
        pass
    if key in _busy:
        return True
    _busy.add(key)
    try:
        action = cfg["action"]
        reason = datasys.load_lang_file(guild.id)["moderation"]["auto"]["honeypot"]
        hours = max(0, min(168, int(cfg.get("delete_hours", 1) or 0)))

        async def perform(suffix: str) -> None:
            why = reason + suffix
            if action == "ban":
                await guild.ban(member, reason=why, delete_message_seconds=hours * 3600)
            elif action == "kick":
                await member.kick(reason=why)
            else:
                await member.timeout(discord.utils.utcnow() + datetime.timedelta(seconds=MUTE_SECONDS), reason=why)

        done = await cases.run_automatic(
            guild, member, action, reason, perform,
            seconds=MUTE_SECONDS if action == "mute" else None,
        )
        if not done:
            logger.error(f"[Honeypot] cannot {action} {member} in {guild.name} (permissions or role order)")
    except discord.HTTPException as e:
        logger.error(f"[Honeypot] {action} of {member} in {guild.name} failed: {e}")
    finally:
        _busy.discard(key)
    return True
