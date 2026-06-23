import datetime
from typing import Optional, Union

import discord
from discord.ext import commands
from reds_simple_logger import Logger

import assets.data as datasys
import assets.repo as repo
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
    warn_config: dict = dict(datasys.load_data(guild_id, "warn_config"))
    lang = datasys.load_lang_file(guild_id)

    import os as _os
    warn_id = _os.urandom(4).hex()
    user_key = str(user.id)

    warn_entry = {
        "id": warn_id,
        "reason": reason,
        "mod": str(moderator.name) if moderator else "System",
        "mod_id": int(moderator.id) if moderator else 0,
        "date": str(datetime.date.today()),
    }

    # Targeted insert — no full reload needed for the add itself
    repo.add_warning(guild_id, user_key, warn_entry)

    # Decay: if expiry is configured, reload the user's list, prune stale
    # entries (the just-added entry is always within range), then save the
    # pruned list so expired warnings are removed from the DB.
    expiry_days = int(warn_config.get("expiry_days", 0) or 0)
    warnings: dict = dict(datasys.load_data(guild_id, "warnings"))
    if expiry_days > 0 and user_key in warnings:
        active = _active_warnings(warnings[user_key], expiry_days)
        if len(active) != len(warnings[user_key]):
            warnings[user_key] = active
            datasys.save_data(guild_id, "warnings", warnings)

    # Log mod event for BaxiInsights
    try:
        datasys.append_mod_event(guild_id, {
            "type": "warn",
            "user_id": str(user.id),
            "user_name": user.name,
            "mod_id": str(moderator.id) if moderator else "0",
            "mod_name": moderator.name if moderator else "System",
            "reason": reason,
            "timestamp": datetime.datetime.utcnow().isoformat(),
        })
    except Exception:
        pass

    # Warnings are stored per-guild only (no cross-server recording — compliance).
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
    user_key = str(user_id)
    # Verify the warning exists before attempting removal
    warnings: dict = dict(datasys.load_data(guild_id, "warnings"))
    user_warns = warnings.get(user_key, [])
    if not any(w["id"] == warn_id for w in user_warns):
        return False
    # Targeted delete — no full save needed
    repo.remove_warning(guild_id, user_key, warn_id)
    return True


def get_warnings(guild_id: int, user_id: int) -> list:
    warnings: dict = dict(datasys.load_data(guild_id, "warnings"))
    return warnings.get(str(user_id), [])


def _active_warnings(warn_list: list, expiry_days: int) -> list:
    """Return only warnings whose ``date`` falls within ``expiry_days``.

    ``expiry_days <= 0`` disables decay and returns the list unchanged.
    Entries with a missing/unparseable date are treated as active.
    """
    if expiry_days <= 0:
        return list(warn_list)

    cutoff = datetime.date.today() - datetime.timedelta(days=expiry_days)
    active = []
    for w in warn_list:
        raw = w.get("date")
        try:
            wdate = datetime.date.fromisoformat(str(raw))
        except (ValueError, TypeError):
            active.append(w)
            continue
        if wdate >= cutoff:
            active.append(w)
    return active


def _normalize_steps(warn_config: dict) -> list[dict]:
    """Return escalation steps as a sorted list of normalized dicts.

    New shape stores ``steps`` directly. Old guilds only have
    ``mute_at``/``kick_at``/``ban_at``/``mute_duration`` — synthesise an
    equivalent ladder so escalation keeps working without a data migration.
    """
    steps = warn_config.get("steps")
    if not isinstance(steps, list):
        mute_at = int(warn_config.get("mute_at", 3))
        kick_at = int(warn_config.get("kick_at", 5))
        ban_at = int(warn_config.get("ban_at", 7))
        mute_duration = int(warn_config.get("mute_duration", 600))
        steps = [
            {"warns": mute_at, "action": "timeout", "duration": mute_duration},
            {"warns": kick_at, "action": "kick"},
            {"warns": ban_at, "action": "ban"},
        ]

    normalized = []
    for s in steps:
        if not isinstance(s, dict):
            continue
        try:
            warns = int(s.get("warns", 0))
        except (ValueError, TypeError):
            continue
        if warns < 1:
            continue
        action = str(s.get("action", "notify"))
        if action not in ("notify", "timeout", "kick", "ban"):
            action = "notify"
        try:
            duration = int(s.get("duration", 0) or 0)
        except (ValueError, TypeError):
            duration = 0
        normalized.append({
            "warns": warns,
            "action": action,
            "duration": duration,
            "dm": bool(s.get("dm", False)),
        })

    normalized.sort(key=lambda s: s["warns"])
    return normalized


async def _dm_user(user: discord.Member, embed: discord.Embed) -> None:
    """Best-effort DM to the user. Silently ignores closed DMs."""
    try:
        await user.send(embed=embed)
    except (discord.Forbidden, discord.HTTPException):
        pass
    except Exception as e:
        logger.error(f"Warning escalation DM error: {e}")


async def _check_escalation(
    user: discord.Member,
    warn_count: int,
    warn_config: dict,
    lang: dict,
    channel: Optional[Union[discord.TextChannel, discord.abc.Messageable]],
    bot: commands.AutoShardedBot,
):
    if not warn_config.get("enabled", True):
        return

    steps = _normalize_steps(warn_config)
    # Fire the step whose threshold matches the current warn count exactly.
    # Warns always increment by 1, so every configured step is reachable.
    step = next((s for s in steps if s["warns"] == warn_count), None)
    if step is None:
        return

    action = step["action"]
    warn_strings = lang["commands"]["admin"]["warn"]

    try:
        if action == "ban":
            await user.ban(reason=f"Auto-ban: {warn_count} warnings reached")
            title = f"{config.Icons.people_crossed} AUTO BAN // {user.name} // {warn_count} WARNINGS"
            desc = str(warn_strings["escalation_ban"]).format(user=user.mention, count=warn_count)
            color = config.Discord.danger_color

        elif action == "kick":
            await user.kick(reason=f"Auto-kick: {warn_count} warnings reached")
            title = f"{config.Icons.people_crossed} AUTO KICK // {user.name} // {warn_count} WARNINGS"
            desc = str(warn_strings["escalation_kick"]).format(user=user.mention, count=warn_count)
            color = config.Discord.danger_color

        elif action == "timeout":
            duration = step["duration"] or 600
            duration_minutes = duration // 60
            await user.timeout(
                discord.utils.utcnow() + datetime.timedelta(seconds=duration)
            )
            title = f"{config.Icons.alert} AUTO MUTE // {user.name} // {warn_count} WARNINGS"
            desc = str(warn_strings["escalation_mute"]).format(
                user=user.mention, duration=duration_minutes, count=warn_count
            )
            color = config.Discord.warn_color

        else:  # notify — no punishment, just inform
            title = f"{config.Icons.alert} {user.name} // {warn_count} WARNINGS"
            desc = str(warn_strings.get("escalation_notify", warn_strings["escalation_mute"])).format(
                user=user.mention, count=warn_count, duration=0
            )
            color = config.Discord.warn_color

        embed = discord.Embed(title=title, description=desc, color=color)
        embed.set_footer(text="Baxi · avocloud.net")
        if channel:
            await channel.send(embed=embed)
        if step["dm"]:
            await _dm_user(user, embed)

    except discord.Forbidden:
        logger.error(f"Warning escalation: Missing permissions for {user.name} in {user.guild.name}")
    except Exception as e:
        logger.error(f"Warning escalation error: {e}")
