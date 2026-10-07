"""Starboard with throwbacks.

Messages that collect enough star reactions are copied into a board channel. Once a week Baxi
resurfaces an old favourite ("Throwback") - preferably one from around a year ago.

Only IDs are stored in the database. The text of a starred message lives in the board post on
Discord, so deleting the original (or the board post) removes it for good.
"""
from __future__ import annotations

import asyncio
import datetime
import random
import time
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks

import assets.data as datasys
import assets.db as db
import config.config as config
from assets.share import set_task_status
from reds_simple_logger import Logger

logger = Logger()

_THROWBACK_TZ = ZoneInfo("Europe/Berlin")
_THROWBACK_WEEKDAY = 6          # Sunday
_THROWBACK_HOUR = 18
_CFG_TTL = 30.0                 # seconds; reaction events must not hit SQLite every time
_MIN_AGE_DAYS = 60              # fallback pool for throwbacks: at least this old

_cfg_cache: dict[int, tuple[float, dict]] = {}
_locks: dict[tuple[int, int], asyncio.Lock] = {}


# Mirrors config.datasys.default_data["starboard"]; kept here so a stale config.py cannot break the module.
_DEFAULTS = {"enabled": False, "channel": "", "emoji": "⭐", "threshold": 3, "self_star": False,
             "ignore_nsfw": True, "throwback": True, "last_throwback": ""}


# ── Config ───────────────────────────────────────────────────────────────────

def load_cfg(guild_id: int, *, fresh: bool = False) -> dict:
    now = time.monotonic()
    hit = _cfg_cache.get(guild_id)
    if hit and not fresh and now - hit[0] < _CFG_TTL:
        return hit[1]
    cfg = {**_DEFAULTS, **dict(datasys.load_data(guild_id, "starboard"))}
    _cfg_cache[guild_id] = (now, cfg)
    return cfg


def _board_channel(guild: discord.Guild, cfg: dict) -> discord.TextChannel | None:
    raw = str(cfg.get("channel", "") or "")
    ch = guild.get_channel(int(raw)) if raw.isdigit() else None
    return ch if isinstance(ch, discord.TextChannel) else None


# ── Storage ──────────────────────────────────────────────────────────────────

def get_entry(guild_id: int, message_id: int):
    rows = db.query(
        "SELECT * FROM starboard_entries WHERE guild_id=? AND message_id=?", (guild_id, str(message_id)),
    )
    return rows[0] if rows else None


def _save_entry(guild_id: int, message: discord.Message, stars: int, board_message_id: int) -> None:
    db.ensure_guild(guild_id)
    db.execute(
        "INSERT INTO starboard_entries "
        "(guild_id,message_id,channel_id,author_id,stars,board_message_id,message_created_at) "
        "VALUES (?,?,?,?,?,?,?) ON CONFLICT(guild_id,message_id) DO UPDATE SET "
        "stars=excluded.stars,board_message_id=excluded.board_message_id",
        (guild_id, str(message.id), str(message.channel.id), str(message.author.id), stars,
         str(board_message_id), message.created_at.isoformat()),
    )


def _delete_entry(guild_id: int, message_id: str) -> None:
    db.execute("DELETE FROM starboard_entries WHERE guild_id=? AND message_id=?", (guild_id, str(message_id)))


def random_entry(guild_id: int):
    rows = db.query(
        "SELECT * FROM starboard_entries WHERE guild_id=? AND board_message_id!='' ORDER BY RANDOM() LIMIT 1",
        (guild_id,),
    )
    return rows[0] if rows else None


def pick_throwback(guild_id: int, now: datetime.datetime | None = None, exclude: set[str] | None = None):
    """Prefer entries from ~1 year ago (±7 days); otherwise anything older than 60 days."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    exclude = exclude or set()
    rows = [r for r in db.query(
        "SELECT * FROM starboard_entries WHERE guild_id=? AND board_message_id!=''", (guild_id,),
    ) if r["message_id"] not in exclude and r["message_created_at"]]

    def age_days(r) -> int:
        return (now - datetime.datetime.fromisoformat(r["message_created_at"])).days

    anniversary = [r for r in rows if abs(age_days(r) - 365) <= 7]
    pool = anniversary or [r for r in rows if age_days(r) >= _MIN_AGE_DAYS]
    return random.choice(pool) if pool else None


# ── Rendering ────────────────────────────────────────────────────────────────

def _header(emoji: str, stars: int, channel: discord.abc.GuildChannel) -> str:
    return f"{emoji} **{stars}** | {channel.mention}"


def build_embed(message: discord.Message, t: dict) -> discord.Embed:
    embed = discord.Embed(
        description=(message.content or "")[:4000] or None,
        color=config.Discord.warn_color,
        timestamp=message.created_at,
    )
    embed.set_author(name=message.author.display_name, icon_url=message.author.display_avatar.url)

    images = [a for a in message.attachments if (a.content_type or "").startswith("image/")]
    if images:
        embed.set_image(url=images[0].url)
    others = [a for a in message.attachments if a not in images[:1]]
    if others:
        embed.add_field(
            name=t["attachments"],
            value="\n".join(f"[{discord.utils.escape_markdown(a.filename)}]({a.url})" for a in others[:5]),
            inline=False,
        )
    embed.add_field(name="​", value=f"[{t['jump']}]({message.jump_url})", inline=False)
    embed.set_footer(text=t["footer"])
    return embed


def _age_text(days: int, t: dict) -> str:
    if days >= 365:
        unit, n = "year", days // 365
    elif days >= 30:
        unit, n = "month", days // 30
    else:
        unit, n = "day", max(days, 1)
    return t[f"age_{unit}_{'one' if n == 1 else 'other'}"].format(n=n)


# ── Reaction handling ────────────────────────────────────────────────────────

def _lock_for(key: tuple[int, int]) -> asyncio.Lock:
    if len(_locks) > 1000:
        for k in [k for k, v in _locks.items() if not v.locked()]:
            del _locks[k]
    return _locks.setdefault(key, asyncio.Lock())


async def _count_stars(message: discord.Message, emoji: str, allow_self: bool) -> int:
    reaction = next((r for r in message.reactions if str(r.emoji) == emoji), None)
    if reaction is None:
        return 0
    count = reaction.count
    if not allow_self:
        users = [u async for u in reaction.users(limit=100)]
        if any(u.id == message.author.id for u in users):
            count -= 1
    return count


async def _sync(guild: discord.Guild, board: discord.TextChannel, message: discord.Message,
                stars: int, cfg: dict) -> None:
    entry = get_entry(guild.id, message.id)
    threshold = max(1, int(cfg.get("threshold", 3)))
    board_msg: discord.Message | None = None

    if entry and entry["board_message_id"]:
        try:
            board_msg = await board.fetch_message(int(entry["board_message_id"]))
        except discord.NotFound:
            board_msg = None

    if stars < threshold:
        if board_msg is not None:
            try:
                await board_msg.delete()
            except (discord.Forbidden, discord.HTTPException):
                pass
        if entry:
            _delete_entry(guild.id, str(message.id))
        return

    header = _header(cfg["emoji"], stars, message.channel)
    if board_msg is not None:
        if board_msg.content != header:
            await board_msg.edit(content=header)
        db.execute(
            "UPDATE starboard_entries SET stars=? WHERE guild_id=? AND message_id=?",
            (stars, guild.id, str(message.id)),
        )
        return

    t = datasys.load_lang_file(guild.id)["starboard"]
    posted = await board.send(content=header, embed=build_embed(message, t),
                              allowed_mentions=discord.AllowedMentions.none())
    _save_entry(guild.id, message, stars, posted.id)


async def on_reaction_change(bot: commands.AutoShardedBot,
                             payload: discord.RawReactionActionEvent) -> None:
    if payload.guild_id is None:
        return
    cfg = load_cfg(payload.guild_id)
    if not cfg["enabled"] or str(payload.emoji) != cfg["emoji"]:
        return
    guild = bot.get_guild(payload.guild_id)
    board = _board_channel(guild, cfg) if guild else None
    if board is None or payload.channel_id == board.id:
        return

    async with _lock_for((payload.guild_id, payload.message_id)):
        try:
            channel = guild.get_channel_or_thread(payload.channel_id)
            if channel is None:
                return
            if cfg["ignore_nsfw"] and getattr(channel, "is_nsfw", lambda: False)():
                return
            message = await channel.fetch_message(payload.message_id)
            stars = await _count_stars(message, cfg["emoji"], bool(cfg["self_star"]))
            await _sync(guild, board, message, stars, cfg)
        except (discord.NotFound, discord.Forbidden):
            return
        except Exception as e:
            logger.error(f"[Starboard] reaction error @ {payload.guild_id}: {e}")


async def on_message_delete(bot: commands.AutoShardedBot, payload: discord.RawMessageDeleteEvent) -> None:
    """Original deleted -> its board post goes too. Board post deleted -> forget the entry."""
    if payload.guild_id is None:
        return
    try:
        entry = get_entry(payload.guild_id, payload.message_id)
        if entry:
            guild = bot.get_guild(payload.guild_id)
            board = _board_channel(guild, load_cfg(payload.guild_id)) if guild else None
            if board and entry["board_message_id"]:
                try:
                    await board.get_partial_message(int(entry["board_message_id"])).delete()
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass
            _delete_entry(payload.guild_id, entry["message_id"])
            return
        db.execute(
            "DELETE FROM starboard_entries WHERE guild_id=? AND board_message_id=?",
            (payload.guild_id, str(payload.message_id)),
        )
    except Exception as e:
        logger.error(f"[Starboard] delete error: {e}")


def register(bot: commands.AutoShardedBot) -> None:
    async def _add(payload): await on_reaction_change(bot, payload)
    async def _remove(payload): await on_reaction_change(bot, payload)
    async def _delete(payload): await on_message_delete(bot, payload)
    # add_listener is additive; @bot.event would replace the handlers in events.py
    bot.add_listener(_add, "on_raw_reaction_add")
    bot.add_listener(_remove, "on_raw_reaction_remove")
    bot.add_listener(_delete, "on_raw_message_delete")


# ── Throwback ────────────────────────────────────────────────────────────────

async def post_throwback(bot: commands.AutoShardedBot, guild: discord.Guild, cfg: dict) -> bool:
    board = _board_channel(guild, cfg)
    if board is None:
        return False
    t = datasys.load_lang_file(guild.id)["starboard"]
    tried: set[str] = set()
    for _ in range(5):
        entry = pick_throwback(guild.id, exclude=tried)
        if entry is None:
            return False
        tried.add(entry["message_id"])
        try:
            source = await board.fetch_message(int(entry["board_message_id"]))
        except discord.NotFound:
            _delete_entry(guild.id, entry["message_id"])    # board post is gone -> stale entry
            continue
        except (discord.Forbidden, discord.HTTPException):
            return False
        if not source.embeds:
            continue
        days = (datetime.datetime.now(datetime.timezone.utc)
                - datetime.datetime.fromisoformat(entry["message_created_at"])).days
        try:
            await board.send(
                content=t["throwback_header"].format(age=_age_text(days, t)),
                embed=source.embeds[0],
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except (discord.Forbidden, discord.HTTPException) as e:
            logger.warn(f"[Starboard] throwback failed in {guild.id}: {e}")
            return False
        return True
    return False


def throwback_due(cfg: dict, now_utc: datetime.datetime | None = None) -> tuple[bool, str]:
    """(due, week_id). Once per ISO week, from Sunday 18:00 onwards - restart-safe."""
    now_utc = now_utc or datetime.datetime.now(datetime.timezone.utc)
    local = now_utc.astimezone(_THROWBACK_TZ)
    week = local.strftime("%G-W%V")
    if not cfg.get("enabled") or not cfg.get("throwback") or not str(cfg.get("channel", "") or "").isdigit():
        return False, week
    if local.weekday() != _THROWBACK_WEEKDAY or local.hour < _THROWBACK_HOUR:
        return False, week
    return cfg.get("last_throwback", "") != week, week


class StarboardTask:
    """Posts the weekly throwback for guilds that enabled it (checked every 30 minutes)."""

    def __init__(self, bot: commands.AutoShardedBot):
        self.bot = bot

    @tasks.loop(minutes=30)
    async def tick(self):
        try:
            set_task_status("Starboard", "running", "Checking weekly throwbacks...")
            posted = 0
            for guild in list(self.bot.guilds):
                try:
                    cfg = load_cfg(guild.id, fresh=True)
                    due, week = throwback_due(cfg)
                    if not due:
                        continue
                    # Mark first: a failing channel must not be retried every 30 minutes.
                    datasys.save_data(guild.id, "starboard", {**cfg, "last_throwback": week})
                    _cfg_cache.pop(guild.id, None)
                    if await post_throwback(self.bot, guild, cfg):
                        posted += 1
                except Exception as e:
                    logger.error(f"[Starboard] throwback error @ {guild.id}: {e}")
            set_task_status("Starboard", "ok", f"{posted} throwback(s) posted")
        except Exception as e:
            logger.error(f"[Starboard] Error in tick: {e}")
            set_task_status("Starboard", "error", f"Error: {e}")

    @tick.before_loop
    async def _before(self):
        await self.bot.wait_until_ready()


# ── Commands ─────────────────────────────────────────────────────────────────

def starboard_commands(bot: commands.AutoShardedBot):
    group = app_commands.Group(name="starboard", description="Starboard of this server", guild_only=True)

    async def _say(interaction: discord.Interaction, text: str, *, ok: bool = False):
        await interaction.followup.send(
            embed=discord.Embed(
                description=text,
                color=config.Discord.success_color if ok else config.Discord.danger_color,
            ),
            ephemeral=True,
        )

    @group.command(name="random", description="Show a random message from the starboard")
    async def starboard_random(interaction: discord.Interaction):
        await interaction.response.defer()
        t = datasys.load_lang_file(interaction.guild.id)["starboard"]
        cfg = load_cfg(interaction.guild.id, fresh=True)
        board = _board_channel(interaction.guild, cfg)
        if not cfg["enabled"] or board is None:
            return await _say(interaction, f"{config.Icons.cross} {t['disabled']}")
        for _ in range(5):
            entry = random_entry(interaction.guild.id)
            if entry is None:
                break
            try:
                source = await board.fetch_message(int(entry["board_message_id"]))
            except discord.NotFound:
                _delete_entry(interaction.guild.id, entry["message_id"])
                continue
            except (discord.Forbidden, discord.HTTPException):
                break
            if source.embeds:
                return await interaction.followup.send(
                    content=source.content, embed=source.embeds[0],
                    allowed_mentions=discord.AllowedMentions.none(),
                )
        await _say(interaction, t["none"])

    @group.command(name="throwback", description="Post a throwback to an old favourite now")
    async def starboard_throwback(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        t = datasys.load_lang_file(interaction.guild.id)["starboard"]
        if not interaction.user.guild_permissions.manage_guild:
            return await _say(interaction, f"{config.Icons.cross} {t['no_permission']}")
        cfg = load_cfg(interaction.guild.id, fresh=True)
        if not cfg["enabled"] or _board_channel(interaction.guild, cfg) is None:
            return await _say(interaction, f"{config.Icons.cross} {t['disabled']}")
        sent = await post_throwback(bot, interaction.guild, cfg)
        await _say(interaction, f"{config.Icons.check} {t['throwback_sent']}" if sent else t["throwback_none"], ok=sent)

    bot.tree.add_command(group)
