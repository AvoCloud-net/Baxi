"""Keeps the posted verify and ticket panels on the current look.

Panels are long-lived messages in a server's channel. When their look changes (they became
Components V2), Baxi edits the existing message on every server that has the feature on, once
at start-up: a panel that is already V2 costs one fetch and nothing else. Servers that saved
their panel in the dashboard meanwhile are already V2 (the dashboard edits the same message).
Panels whose message is gone are left alone; the delete event re-posts them.
"""
from __future__ import annotations

import asyncio

import discord
from discord.ext import commands
from reds_simple_logger import Logger

import assets.data as datasys
import assets.idle as idle
import assets.v2 as v2

logger = Logger()


async def _classic_panel(guild: discord.Guild, channel_id, message_id, me_id: int) -> discord.Message | None:
    """The panel message when it exists, is Baxi's and is still a classic (embed) message."""
    if not str(channel_id).isdigit() or not str(message_id).isdigit():
        return None
    channel = guild.get_channel(int(channel_id))
    if not isinstance(channel, discord.TextChannel):
        return None
    try:
        msg = await channel.fetch_message(int(message_id))
    except (discord.NotFound, discord.Forbidden):
        return None
    if msg.author.id != me_id or msg.flags.components_v2:
        return None
    return msg


async def _refresh_ticket(guild: discord.Guild, me_id: int) -> bool:
    from assets.buttons import build_ticket_panel, ticket_panel_embed
    cfg = dict(datasys.load_data(guild.id, "ticket"))
    msg = await _classic_panel(guild, cfg.get("channel"), cfg.get("panel_message_id"), me_id)
    if msg is None:
        return False
    view = build_ticket_panel(ticket_panel_embed(guild, cfg), cfg.get("buttons", []), cfg.get("panel_style", "buttons"))
    await v2.edit(msg, view)
    return True


async def _refresh_verify(guild: discord.Guild, me_id: int) -> bool:
    from assets.buttons import VerifyView, verify_panel_embed
    cfg = dict(datasys.load_data(guild.id, "verify"))
    msg = await _classic_panel(guild, cfg.get("channel"), cfg.get("panel_message_id"), me_id)
    if msg is None:
        return False
    await v2.edit(msg, VerifyView(verify_panel_embed(cfg)))
    return True


async def refresh_panels(bot: commands.AutoShardedBot) -> None:
    """Edit every classic verify/ticket panel into its V2 form (run once after start-up)."""
    await asyncio.sleep(15)   # let the guild cache settle
    if bot.user is None:
        return
    done = 0
    for sys_name, refresh in (("ticket", _refresh_ticket), ("verify", _refresh_verify)):
        for guild in idle.guilds_with(bot, sys_name):
            try:
                if await refresh(guild, bot.user.id):
                    done += 1
                    logger.info(f"[Panels] {sys_name} panel updated in {guild.name} ({guild.id})")
            except discord.HTTPException as e:
                logger.warn(f"[Panels] {sys_name} panel in {guild.id} not updated: {e}")
            except Exception as e:
                logger.error(f"[Panels] {sys_name} panel in {guild.id}: {type(e).__name__}: {e}")
            await asyncio.sleep(1.5)   # stay far below the edit rate limit
    logger.info(f"[Panels] panel refresh done, {done} updated")
