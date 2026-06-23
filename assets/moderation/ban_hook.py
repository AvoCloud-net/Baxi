"""Ban → network safety list bridge.

Fires for ANY ban in a guild (Baxi's own command, Discord's native ban, or another mod
bot), so the safety list is not limited to one command. A ban is a deliberate, heavy
moderation action, so it qualifies as the human-gated signal the list is built on.

Only contributes when the guild participates (`prism_enabled`). Stores a coarse fact only
(user id + category + who/why) — no behavioral data. Opt-out is respected by `flag_user`.
"""
from __future__ import annotations

import discord
from discord.ext import commands
from reds_simple_logger import Logger

import assets.data as datasys
import assets.trust as safety

logger = Logger()


async def handle_ban(guild: discord.Guild, user: discord.abc.User, bot: commands.AutoShardedBot) -> None:
    # Respect guild participation.
    try:
        if datasys.load_data(guild.id, "prism_enabled") is False:
            return
    except Exception:
        return

    actor_name, reason = await _lookup_ban_actor(guild, user)
    try:
        safety.flag_user(
            user_id=user.id,
            category="other",                       # coarse; mods can refine later
            guild_id=guild.id,
            moderator_name=actor_name or "unknown",
            reason=(reason or "")[:200],
        )
    except Exception as e:
        logger.error(f"[Safety] ban_hook flag failed: {e}")


async def _lookup_ban_actor(guild: discord.Guild, user: discord.abc.User) -> tuple[str, str]:
    """Best-effort: find who issued the ban and why, from the audit log."""
    me = guild.me
    if me is None or not me.guild_permissions.view_audit_log:
        return "", ""
    try:
        async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.ban):
            if entry.target is not None and entry.target.id == user.id:
                actor = entry.user.name if entry.user else ""
                return actor, (entry.reason or "")
    except discord.Forbidden:
        return "", ""
    except Exception as e:
        logger.error(f"[Safety] ban audit lookup error: {e}")
    return "", ""
