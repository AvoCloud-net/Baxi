import os
import datetime
from typing import Optional, Union

import discord
from discord.ext import commands
from reds_simple_logger import Logger

import assets.data as datasys
import assets.trust as sentinel
import config.config as config

logger = Logger()


async def add_warning(
    guild_id: int,
    user: discord.Member,
    moderator: Union[discord.Member, discord.User, discord.ClientUser, None],
    reason: str,
    bot: commands.AutoShardedBot,
    channel: Optional[Union[discord.TextChannel, discord.abc.Messageable]] = None,
) -> dict:
    warnings: dict = dict(datasys.load_data(guild_id, "warnings"))
    warn_config: dict = dict(datasys.load_data(guild_id, "warn_config"))
    lang = datasys.load_lang_file(guild_id)

    warn_id = os.urandom(4).hex()
    user_key = str(user.id)

    if user_key not in warnings:
        warnings[user_key] = []

    warn_entry = {
        "id": warn_id,
        "reason": reason,
        "mod": str(moderator.name) if moderator else "System",
        "mod_id": int(moderator.id) if moderator else 0,
        "date": str(datetime.date.today()),
    }

    warnings[user_key].append(warn_entry)
    datasys.save_data(guild_id, "warnings", warnings)

    # Prism: record warning event
    try:
        account_age = (datetime.date.today() - user.created_at.date()).days
        sentinel.record_event(
            user_id=user.id,
            user_name=user.name,
            event_type="warning",
            guild_id=guild_id,
            reason=reason,
            account_age_days=account_age,
        )
    except Exception as _prism_err:
        logger.error(f"[Prism] Hook error in add_warning: {_prism_err}")

    warn_count = len(warnings[user_key])

    # Send warning embed
    if channel is not None:
        embed = discord.Embed(
            title=f"{config.Icons.alert} {lang['commands']['admin']['warn']['title']}",
            description=str(lang["commands"]["admin"]["warn"]["success"]).format(
                user=user.mention, reason=reason, count=warn_count
            ),
            color=config.Discord.warn_color,
        )
        embed.set_footer(text="Baxi · avocloud.net")
        await channel.send(embed=embed)

    # Escalation
    await _check_escalation(user, warn_count, warn_config, lang, channel, bot)

    return warn_entry


async def remove_warning(guild_id: int, user_id: int, warn_id: str) -> bool:
    warnings: dict = dict(datasys.load_data(guild_id, "warnings"))
    user_key = str(user_id)

    if user_key not in warnings:
        return False

    for i, warn in enumerate(warnings[user_key]):
        if warn["id"] == warn_id:
            warnings[user_key].pop(i)
            if len(warnings[user_key]) == 0:
                del warnings[user_key]
            datasys.save_data(guild_id, "warnings", warnings)
            return True

    return False


def get_warnings(guild_id: int, user_id: int) -> list:
    warnings: dict = dict(datasys.load_data(guild_id, "warnings"))
    return warnings.get(str(user_id), [])


async def _check_escalation(
    user: discord.Member,
    warn_count: int,
    warn_config: dict,
    lang: dict,
    channel: Optional[Union[discord.TextChannel, discord.abc.Messageable]],
    bot: commands.AutoShardedBot,
):
    mute_at = int(warn_config.get("mute_at", 3))
    kick_at = int(warn_config.get("kick_at", 5))
    ban_at = int(warn_config.get("ban_at", 7))
    mute_duration = int(warn_config.get("mute_duration", 600))

    try:
        if warn_count >= ban_at:
            await user.ban(reason=f"Auto-ban: {warn_count} warnings reached")
            if channel:
                embed = discord.Embed(
                    title=f"{config.Icons.people_crossed} AUTO BAN // {user.name} // {warn_count} WARNINGS",
                    description=str(lang["commands"]["admin"]["warn"]["escalation_ban"]).format(
                        user=user.mention, count=warn_count
                    ),
                    color=config.Discord.danger_color,
                )
                embed.set_footer(text="Baxi · avocloud.net")
                await channel.send(embed=embed)

        elif warn_count >= kick_at:
            await user.kick(reason=f"Auto-kick: {warn_count} warnings reached")
            if channel:
                embed = discord.Embed(
                    title=f"{config.Icons.people_crossed} AUTO KICK // {user.name} // {warn_count} WARNINGS",
                    description=str(lang["commands"]["admin"]["warn"]["escalation_kick"]).format(
                        user=user.mention, count=warn_count
                    ),
                    color=config.Discord.danger_color,
                )
                embed.set_footer(text="Baxi · avocloud.net")
                await channel.send(embed=embed)

        elif warn_count >= mute_at:
            duration_minutes = mute_duration // 60
            await user.timeout(
                discord.utils.utcnow() + datetime.timedelta(seconds=mute_duration)
            )
            if channel:
                embed = discord.Embed(
                    title=f"{config.Icons.alert} AUTO MUTE // {user.name} // {warn_count} WARNINGS",
                    description=str(lang["commands"]["admin"]["warn"]["escalation_mute"]).format(
                        user=user.mention, duration=duration_minutes, count=warn_count
                    ),
                    color=config.Discord.warn_color,
                )
                embed.set_footer(text="Baxi · avocloud.net")
                await channel.send(embed=embed)

    except discord.Forbidden:
        logger.error(f"Warning escalation: Missing permissions for {user.name} in {user.guild.name}")
    except Exception as e:
        logger.error(f"Warning escalation error: {e}")
