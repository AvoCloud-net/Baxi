"""Continuous-learning hook -  turn moderator deletions into training signal.

When a *moderator* deletes someone else's message (not the author deleting their own, and
not Baxi's own chatfilter deletion), that message is strong evidence of content the server
considers unacceptable. Rather than hard-labelling it (mods also delete off-topic/noise),
the message is queued for staff review; once confirmed it is appended to the SafeText
feedback set and folded into the next LoRA fine-tune. This keeps the local classifier
improving over time -  no external LLM involved.
"""
from __future__ import annotations

import datetime

import discord
from discord.ext import commands
from reds_simple_logger import Logger

import assets.repo as repo
from assets.share import admin_log

logger = Logger()

# How far back to scan the audit log, and the matching window for a delete entry.
_AUDIT_WINDOW_SECONDS = 8


async def handle_raw_delete(payload: discord.RawMessageDeleteEvent, bot: commands.AutoShardedBot) -> None:
    """Inspect a raw delete; if a moderator removed another member's message, enqueue it
    as a candidate training sample for the chatfilter."""
    message = payload.cached_message
    if message is None or message.guild is None:
        return  # no content cached → nothing to learn from
    if message.author.bot or not message.content.strip():
        return

    guild = message.guild
    me = guild.me
    if me is None or not me.guild_permissions.view_audit_log:
        return  # cannot attribute the deletion without audit-log access

    deleter = await _find_deleter(guild, message)
    if deleter is None:
        return  # likely the author deleted their own message → not a signal
    if deleter.id == message.author.id or (bot.user and deleter.id == bot.user.id):
        return  # self-delete or Baxi's own chatfilter action (already labelled)

    context = {
        "message": message.content[:1000],
        "author_id": str(message.author.id),
        "author_name": message.author.name,
        "deleted_by_id": str(deleter.id),
        "deleted_by_name": deleter.name,
        "channel_id": str(message.channel.id),
        "channel_name": getattr(message.channel, "name", str(message.channel.id)),
        "suggested_label": "2",   # default toxic; staff confirm/adjust on approval
        "deleted_at": datetime.datetime.utcnow().isoformat(),
    }
    try:
        repo.add_review_item(guild.id, message.author.id, message.author.name, "deleted_msg", context)
        admin_log(
            "info",
            f"Learning: queued mod-deleted message from {message.author.name} "
            f"(by {deleter.name}) @ {guild.name} for chatfilter training review",
            source="Learning",
        )
    except Exception as e:
        logger.error(f"[Learning] enqueue failed: {e}")


async def _find_deleter(guild: discord.Guild, message: discord.Message) -> discord.abc.User | None:
    """Best-effort: find who deleted *message* via the audit log."""
    now = datetime.datetime.now(datetime.timezone.utc)
    try:
        async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.message_delete):
            if entry.target is None:
                continue
            if entry.target.id != message.author.id:
                continue
            if (now - entry.created_at).total_seconds() > _AUDIT_WINDOW_SECONDS:
                continue
            extra_channel = getattr(entry.extra, "channel", None)
            if extra_channel is not None and extra_channel.id != message.channel.id:
                continue
            return entry.user
    except discord.Forbidden:
        return None
    except Exception as e:
        logger.error(f"[Learning] audit lookup error: {e}")
    return None
