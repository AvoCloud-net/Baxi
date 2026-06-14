"""
Per-user, per-server level system.
Each user accumulates XP individually on each server they're active on.
Data stored in SQLite via the repo layer (leveling_users table).
"""
import discord
from discord.ext import commands

import assets.data as datasys
from assets.repo.entities import upsert_leveling_user
import config.config as config
from reds_simple_logger import Logger

logger = Logger()

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
# Per-guild user data  (SQLite leveling_users table via datasys)
# { "user_id": { "xp": 150, "level": 2, "messages": 42, "name": "username" } }
# ---------------------------------------------------------------------------

def _load_users(guild_id: int) -> dict:
    return dict(datasys.load_data(guild_id, "leveling_users"))


def _save_users(guild_id: int, data: dict) -> None:
    datasys.save_data(guild_id, "leveling_users", data)


def get_user_entry(guild_id: int, user_id: int) -> dict:
    """Returns the leveling entry for a single user (or empty defaults)."""
    users = _load_users(guild_id)
    return users.get(str(user_id), {"xp": 0, "level": 0, "messages": 0, "name": ""})


# ---------------------------------------------------------------------------
# Role-reward helper
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


# ---------------------------------------------------------------------------
# Main entry point -  called from events.process_message
# ---------------------------------------------------------------------------

async def process_xp(message: discord.Message, bot: commands.AutoShardedBot) -> None:
    """Award XP to the message author, check for level-up, fire announcements."""
    if message.guild is None or message.author.bot:
        return

    guild_id = message.guild.id
    leveling_cfg: dict = dict(datasys.load_data(guild_id, "leveling"))

    if not leveling_cfg.get("enabled", False):
        return

    earned = _xp_for_message(message.content)
    users = _load_users(guild_id)
    uid = str(message.author.id)

    entry = users.get(uid, {"xp": 0, "level": 0, "messages": 0, "name": message.author.name})
    old_level: int = int(entry.get("level", 0))
    new_xp: int = int(entry.get("xp", 0)) + earned
    new_level: int = current_level_from_xp(new_xp)

    new_messages = int(entry.get("messages", 0)) + 1
    new_name = message.author.name

    # Targeted hot-path write — avoids a full reload/save cycle
    upsert_leveling_user(guild_id, uid, {
        "xp":       new_xp,
        "level":    new_level,
        "messages": new_messages,
        "name":     new_name,
    })

    # Level-up handling
    if new_level <= old_level:
        return

    lang = datasys.load_lang_file(guild_id)
    t: dict = lang["leveling"]

    # Role rewards
    role_rewards: list = leveling_cfg.get("role_rewards", [])
    if role_rewards and isinstance(message.author, discord.Member):
        try:
            await _apply_role_rewards(message.author, new_level, role_rewards)
        except Exception as exc:
            logger.error(f"[Leveling] Role reward error: {exc}")

    # Announcement
    announcement_mode: str = leveling_cfg.get("announcement", "same_channel")
    if announcement_mode == "off":
        return

    embed = discord.Embed(
        title=t["levelup_title"].format(level=new_level),
        description=t["levelup_desc"].format(
            user=message.author.mention,
            level=new_level,
        ),
        color=config.Discord.success_color,
    )
    embed.set_footer(text="Baxi · avocloud.net")

    if announcement_mode == "same_channel":
        target_channel = message.channel
    else:
        ch_id_raw = str(leveling_cfg.get("announcement_channel", "") or "")
        if not ch_id_raw or not ch_id_raw.isdigit():
            return
        target_channel = bot.get_channel(int(ch_id_raw))
        if target_channel is None:
            return

    try:
        await target_channel.send(embed=embed)
    except (discord.Forbidden, discord.HTTPException) as exc:
        logger.warn(f"[Leveling] Could not send level-up announcement: {exc}")
