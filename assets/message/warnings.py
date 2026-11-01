import datetime
from typing import Optional, Union

import discord
from discord.ext import commands
from reds_simple_logger import Logger

import assets.data as datasys
import assets.repo as repo
import config.config as config
from assets.moderation import cases

logger = Logger()


def _case_footer(lang: dict, case_no: Optional[int]) -> str:
    return f"{lang['moderation']['dm']['f_case']} #{case_no} · Baxi · avocloud.net" if case_no else "Baxi · avocloud.net"


async def add_warning(
    guild_id: int,
    user: discord.Member,
    moderator: Union[discord.Member, discord.User, discord.ClientUser, None],
    reason: str,
    bot: commands.AutoShardedBot,
    channel: Optional[Union[discord.TextChannel, discord.abc.Messageable]] = None,
    extra: Optional[dict] = None,
) -> dict:
    """Warn *user*: stores the warning, opens a case (#n), tells the user by DM (with the
    Appeal button) and runs the escalation ladder. *extra* is stored on the case (e.g. the
    removed message's log_id)."""
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

    # The case (#n): shown in the DM, the channel notice and the case file.
    case_no = cases.record(guild_id, "warn", user, moderator, reason, warn_id=warn_id, **(extra or {}))
    warn_entry["case"] = case_no

    # Warnings are stored per-guild only (no cross-server recording — compliance).
    warn_count = len(warnings[user_key])

    guild = getattr(user, "guild", None)
    # Warnings Baxi gives by itself (chat filter, anti-spam) are DM'd at most once per 10 minutes.
    automatic = moderator is None or getattr(moderator, "id", None) == getattr(bot.user, "id", None)
    dm_ok = await cases.notify(guild, user, case_no, "warn", reason, throttle=automatic) if guild else False

    # Send warning embed
    if channel is not None:
        embed = discord.Embed(
            title=f"{config.Icons.alert} {lang['commands']['admin']['warn']['title']}",
            description=str(lang["commands"]["admin"]["warn"]["success"]).format(
                user=user.mention, reason=reason, count=warn_count
            ),
            color=config.Discord.warn_color,
        )
        embed.set_footer(text=_case_footer(lang, case_no))
        if not dm_ok:
            embed.add_field(name="\u200b", value=cases.dm_failed_note(lang, user, guild_id), inline=False)
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
    cases.store.lift_warn_cases(guild_id, warn_id=warn_id)   # the case file shows it as lifted
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
    gid = user.guild.id
    bot_user = bot.user
    case_no = None
    acted = False   # set once the Discord action went through (then the case stays)
    auto = lang["moderation"]["auto"]

    try:
        if action in ("ban", "kick", "timeout"):
            # Can Baxi do it at all? If not: no case, no DM (Baxi logs it, the warning stands).
            blocked = cases.can_act(user.guild, user, {"timeout": "mute"}.get(action, action), lang)
            if blocked:
                logger.error(f"Warning escalation ({action}) skipped for {user.name} in {user.guild.name}: {blocked}")
                return

        if action == "ban":
            why = str(auto["escalation_ban"]).format(count=warn_count)
            case_no = cases.record(gid, "ban", user, bot_user, why)
            await cases.notify(user.guild, user, case_no, "ban", why, permanent=True)   # before: banned users can't be reached
            await user.ban(reason=f"{why} (case #{case_no})" if case_no else why)
            acted = True
            title = f"{config.Icons.people_crossed} AUTO BAN // {user.name} // {warn_count} WARNINGS"
            desc = str(warn_strings["escalation_ban"]).format(user=user.mention, count=warn_count)
            color = config.Discord.danger_color

        elif action == "kick":
            why = str(auto["escalation_kick"]).format(count=warn_count)
            case_no = cases.record(gid, "kick", user, bot_user, why)
            await cases.notify(user.guild, user, case_no, "kick", why)
            await user.kick(reason=f"{why} (case #{case_no})" if case_no else why)
            acted = True
            title = f"{config.Icons.people_crossed} AUTO KICK // {user.name} // {warn_count} WARNINGS"
            desc = str(warn_strings["escalation_kick"]).format(user=user.mention, count=warn_count)
            color = config.Discord.danger_color

        elif action == "timeout":
            duration = step["duration"] or 600
            duration_minutes = duration // 60
            why = str(auto["escalation_mute"]).format(count=warn_count)
            case_no = cases.record(gid, "mute", user, bot_user, why, duration_s=duration)
            await user.timeout(
                discord.utils.utcnow() + datetime.timedelta(seconds=duration),
                reason=f"{why} (case #{case_no})" if case_no else why,
            )
            acted = True
            await cases.notify(user.guild, user, case_no, "mute", why, seconds=duration)
            title = f"{config.Icons.alert} AUTO MUTE // {user.name} // {warn_count} WARNINGS"
            desc = str(warn_strings["escalation_mute"]).format(
                user=user.mention, duration=duration_minutes, count=warn_count
            )
            color = config.Discord.warn_color

        else:  # notify — no punishment, just inform the team (the user already got the warning DM)
            title = f"{config.Icons.alert} {user.name} // {warn_count} WARNINGS"
            desc = str(warn_strings.get("escalation_notify", warn_strings["escalation_mute"])).format(
                user=user.mention, count=warn_count, duration=0
            )
            color = config.Discord.warn_color

        embed = discord.Embed(title=title, description=desc, color=color)
        embed.set_footer(text=_case_footer(lang, case_no))
        if channel:
            await channel.send(embed=embed)

    except discord.Forbidden:
        if not acted:
            cases.discard(gid, case_no)
        logger.error(f"Warning escalation: Missing permissions for {user.name} in {user.guild.name}")
    except Exception as e:
        if not acted:
            cases.discard(gid, case_no)
        logger.error(f"Warning escalation error: {e}")
