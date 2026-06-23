"""Central enforcement -  the single place where moderation actions are applied.

Rules only *decide* (produce Verdicts); this module *acts*: it deletes the message,
sends user-facing embeds, and applies the timeout/warn/kick/ban. All effects are per-guild;
no cross-server behavioral data is recorded (removed for Discord Developer Policy compliance).
"""
from __future__ import annotations

import discord
from discord.ext import commands
from reds_simple_logger import Logger

import assets.data as datasys
import config.config as config
from assets.share import admin_log
from .verdict import Verdict

logger = Logger()


async def enforce_antispam(message: discord.Message, verdict: Verdict, bot: commands.AutoShardedBot) -> None:
    """Apply an anti-spam verdict: delete, notify, act, record."""
    assert message.guild is not None
    guild_id = message.guild.id
    lang = datasys.load_lang_file(guild_id)
    kind = (verdict.meta or {}).get("kind", "triggered")
    config_action = (verdict.meta or {}).get("config_action", "mute")

    # 1. Delete the offending message.
    if verdict.delete:
        try:
            await message.delete()
        except discord.Forbidden:
            pass
        except Exception:
            pass

    # 2. Notify channel (rate vs duplicate copy).
    try:
        embed = discord.Embed(
            title=lang["systems"]["antispam"]["title"],
            description=str(lang["systems"]["antispam"][kind]).format(user=message.author.mention),
            color=config.Discord.warn_color,
        )
        await message.channel.send(embed=embed)
    except Exception:
        pass

    # 3. Apply the configured action.
    await _apply_member_action(message, config_action, lang, bot)

    # 4. Admin log (per-guild only; no cross-server recording).
    admin_log(
        "warning",
        f"Anti-Spam: deleted message from {message.author.name} in "
        f"#{getattr(message.channel, 'name', message.channel.id)} @ {message.guild.name}",
        source="AntiSpam",
    )


async def _apply_member_action(message: discord.Message, action: str, lang: dict, bot: commands.AutoShardedBot) -> None:
    assert message.guild is not None
    member = message.guild.get_member(message.author.id)
    if member is None:
        return
    try:
        if action == "mute":
            await member.timeout(discord.utils.utcnow() + datetime.timedelta(minutes=5))
            embed = discord.Embed(
                title=lang["systems"]["antispam"]["title"],
                description=str(lang["systems"]["antispam"]["muted"]).format(user=message.author.mention),
                color=config.Discord.danger_color,
            )
            await message.channel.send(embed=embed)
        elif action == "warn":
            from assets.message.warnings import add_warning
            await add_warning(
                guild_id=message.guild.id, user=member, moderator=bot.user,
                reason="Anti-Spam", bot=bot, channel=message.channel,
            )
        elif action == "kick":
            await member.kick(reason="Anti-Spam")
        elif action == "ban":
            await member.ban(reason="Anti-Spam")
    except discord.Forbidden:
        logger.error(f"AntiSpam: Missing permissions to {action} {member.name} in {message.guild.name}")
    except Exception as e:
        logger.error(f"AntiSpam action error: {e}")
