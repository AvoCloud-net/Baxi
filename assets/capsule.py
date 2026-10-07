"""Time capsules - write a message now, Baxi delivers it on a future date.

Delivery goes either to the author's DMs or into the server's capsule channel. The text is
stored only until it is delivered (or cancelled) and is deleted right after.
"""
from __future__ import annotations

import datetime
import time
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks

import assets.data as datasys
import assets.db as db
import config.config as config
from assets.message.chatfilter import text_is_clean
from assets.share import set_task_status
from reds_simple_logger import Logger

logger = Logger()

MAX_LEN = 1500
MAX_PENDING = 5                 # per user and server
MIN_DELAY = 60 * 60             # 1 hour
MAX_DELAY = 5 * 365 * 86400     # 5 years
MAX_ATTEMPTS = 7                # DM delivery retries (one per task run per day)
RETRY_AFTER = 24 * 3600
_DELIVERY_TZ = ZoneInfo("Europe/Berlin")
_DELIVERY_HOUR = 10             # custom dates arrive at 10:00 local time

_DELAYS = [
    app_commands.Choice(name="1 week", value=7),
    app_commands.Choice(name="1 month", value=30),
    app_commands.Choice(name="3 months", value=91),
    app_commands.Choice(name="6 months", value=182),
    app_commands.Choice(name="1 year", value=365),
    app_commands.Choice(name="2 years", value=730),
    app_commands.Choice(name="5 years", value=1825),
]
_TARGETS = [
    app_commands.Choice(name="To myself (DM)", value="dm"),
    app_commands.Choice(name="To this server", value="server"),
]


# Mirrors config.datasys.default_data["capsule"]; kept here so a stale config.py cannot break the module.
_DEFAULTS = {"enabled": False, "channel": ""}


# ── Config ───────────────────────────────────────────────────────────────────

def load_cfg(guild_id: int) -> dict:
    return {**_DEFAULTS, **dict(datasys.load_data(guild_id, "capsule"))}


def _capsule_channel(guild: discord.Guild, cfg: dict) -> discord.TextChannel | None:
    raw = str(cfg.get("channel", "") or "")
    ch = guild.get_channel(int(raw)) if raw.isdigit() else None
    return ch if isinstance(ch, discord.TextChannel) else None


# ── Dates ────────────────────────────────────────────────────────────────────

def parse_date(text: str) -> int | None:
    """DD.MM.YYYY or YYYY-MM-DD -> unix time at 10:00 Europe/Berlin, or None if unparseable."""
    text = text.strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d.%m.%y"):
        try:
            d = datetime.datetime.strptime(text, fmt)
        except ValueError:
            continue
        return int(d.replace(hour=_DELIVERY_HOUR, tzinfo=_DELIVERY_TZ).timestamp())
    return None


def validate_deliver_at(deliver_at: int, now: int | None = None) -> str | None:
    """None if fine, else 'too_soon' / 'too_far'."""
    now = int(now if now is not None else time.time())
    if deliver_at < now + MIN_DELAY:
        return "too_soon"
    if deliver_at > now + MAX_DELAY:
        return "too_far"
    return None


# ── Storage ──────────────────────────────────────────────────────────────────

def pending_count(guild_id: int, user_id: int) -> int:
    return db.query(
        "SELECT COUNT(*) AS n FROM time_capsules WHERE guild_id=? AND user_id=?", (guild_id, str(user_id)),
    )[0]["n"]


def add_capsule(guild_id: int, user_id: int, content: str, target: str, reveal: bool, deliver_at: int) -> int:
    db.ensure_guild(guild_id)
    cur = db.execute(
        "INSERT INTO time_capsules (guild_id,user_id,content,target,reveal,created_at,deliver_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (guild_id, str(user_id), content[:MAX_LEN], target, int(reveal), int(time.time()), deliver_at),
    )
    return int(cur.lastrowid)


def user_capsules(guild_id: int, user_id: int):
    return db.query(
        "SELECT capsule_id,target,deliver_at FROM time_capsules WHERE guild_id=? AND user_id=? "
        "ORDER BY deliver_at", (guild_id, str(user_id)),
    )


def cancel_capsule(guild_id: int, user_id: int, capsule_id: int) -> bool:
    cur = db.execute(
        "DELETE FROM time_capsules WHERE capsule_id=? AND guild_id=? AND user_id=?",
        (capsule_id, guild_id, str(user_id)),
    )
    return cur.rowcount > 0


def due_capsules(now: int | None = None):
    return db.query(
        "SELECT * FROM time_capsules WHERE deliver_at<=? ORDER BY deliver_at LIMIT 100",
        (int(now if now is not None else time.time()),),
    )


def _delete(capsule_id: int) -> None:
    db.execute("DELETE FROM time_capsules WHERE capsule_id=?", (capsule_id,))


def _retry_later(capsule_id: int) -> None:
    db.execute(
        "UPDATE time_capsules SET attempts=attempts+1, deliver_at=? WHERE capsule_id=?",
        (int(time.time()) + RETRY_AFTER, capsule_id),
    )


# ── Delivery ─────────────────────────────────────────────────────────────────

def build_embed(row, t: dict, *, author: discord.abc.User | None, guild_name: str) -> discord.Embed:
    embed = discord.Embed(
        title=t["delivery_title"],
        description=f"“{row['content']}”",
        color=config.Discord.color,
    )
    sealed = f"<t:{row['created_at']}:D>"
    if row["target"] == "server" and row["reveal"] and author is not None:
        embed.set_author(name=author.display_name, icon_url=author.display_avatar.url)
        embed.add_field(name=t["sealed_by"], value=t["sealed_by_value"].format(user=author.mention, date=sealed), inline=False)
    elif row["target"] == "server":
        embed.add_field(name=t["sealed_by"], value=t["sealed_anonymous"].format(date=sealed), inline=False)
    else:
        embed.add_field(name=t["sealed_by"], value=t["sealed_self"].format(date=sealed, server=guild_name), inline=False)
    embed.set_footer(text=t["footer"])
    return embed


async def deliver(bot: commands.AutoShardedBot, row) -> bool:
    """Try to deliver one capsule. True = done (delete it), False = try again later."""
    guild = bot.get_guild(row["guild_id"])
    t = datasys.load_lang_file(row["guild_id"])["capsule"]
    uid = int(row["user_id"])

    if row["target"] == "dm":
        try:
            user = bot.get_user(uid) or await bot.fetch_user(uid)
        except discord.NotFound:
            return True                                  # account is gone - nothing to deliver to
        embed = build_embed(row, t, author=user, guild_name=guild.name if guild else "?")
        try:
            await user.send(embed=embed)
        except discord.Forbidden:
            return row["attempts"] >= MAX_ATTEMPTS       # DMs closed: retry daily, then give up
        except discord.HTTPException:
            return False
        return True

    if guild is None:
        return row["attempts"] >= MAX_ATTEMPTS           # bot offline for / removed from this guild
    channel = _capsule_channel(guild, load_cfg(guild.id))
    if channel is None:
        return row["attempts"] >= MAX_ATTEMPTS
    # Public delivery months later: run today's filter on it, never post what it would block.
    if not await text_is_clean(guild.id, channel.id, uid, row["content"]):
        logger.warn(f"[Capsule] #{row['capsule_id']} blocked by chatfilter at delivery in {guild.id}")
        return True
    author = guild.get_member(uid)
    try:
        await channel.send(
            embed=build_embed(row, t, author=author, guild_name=guild.name),
            allowed_mentions=discord.AllowedMentions.none(),
        )
    except (discord.Forbidden, discord.HTTPException):
        return row["attempts"] >= MAX_ATTEMPTS
    return True


class CapsuleTask:
    """Delivers due capsules (checked every 5 minutes; restart-safe because state is in the DB)."""

    def __init__(self, bot: commands.AutoShardedBot):
        self.bot = bot

    @tasks.loop(minutes=5)
    async def tick(self):
        try:
            set_task_status("Capsule", "running", "Delivering due capsules...")
            delivered = 0
            for row in due_capsules():
                try:
                    if await deliver(self.bot, row):
                        _delete(row["capsule_id"])
                        delivered += 1
                    else:
                        _retry_later(row["capsule_id"])
                except Exception as e:
                    logger.error(f"[Capsule] delivery error #{row['capsule_id']}: {e}")
                    _retry_later(row["capsule_id"])
            set_task_status("Capsule", "ok", f"{delivered} capsule(s) delivered")
        except Exception as e:
            logger.error(f"[Capsule] Error in tick: {e}")
            set_task_status("Capsule", "error", f"Error: {e}")

    @tick.before_loop
    async def _before(self):
        await self.bot.wait_until_ready()


# ── Commands ─────────────────────────────────────────────────────────────────

def capsule_commands(bot: commands.AutoShardedBot):
    group = app_commands.Group(name="capsule", description="Time capsules - a message to the future", guild_only=True)

    async def _say(interaction: discord.Interaction, text: str, *, ok: bool = False):
        await interaction.followup.send(
            embed=discord.Embed(
                description=text,
                color=config.Discord.success_color if ok else config.Discord.danger_color,
            ),
            ephemeral=True,
        )

    @group.command(name="send", description="Seal a message and have Baxi deliver it in the future")
    @app_commands.describe(
        message="What do you want to tell the future?",
        delay="Deliver after this long",
        date="...or on an exact date (DD.MM.YYYY) - overrides the delay",
        target="Where it should arrive",
        reveal="For server capsules: show who wrote it (default: yes)",
    )
    @app_commands.choices(delay=_DELAYS, target=_TARGETS)
    async def capsule_send(
        interaction: discord.Interaction,
        message: app_commands.Range[str, 1, MAX_LEN],
        delay: app_commands.Choice[int] | None = None,
        date: str | None = None,
        target: app_commands.Choice[str] | None = None,
        reveal: bool = True,
    ):
        await interaction.response.defer(ephemeral=True)
        gid = interaction.guild.id
        t = datasys.load_lang_file(gid)["capsule"]
        cfg = load_cfg(gid)
        if not cfg["enabled"]:
            return await _say(interaction, f"{config.Icons.cross} {t['disabled']}")

        kind = target.value if target else "dm"
        if kind == "server" and _capsule_channel(interaction.guild, cfg) is None:
            return await _say(interaction, f"{config.Icons.cross} {t['no_channel']}")

        if date:
            deliver_at = parse_date(date)
            if deliver_at is None:
                return await _say(interaction, f"{config.Icons.cross} {t['bad_date']}")
        elif delay:
            deliver_at = int(time.time()) + delay.value * 86400
        else:
            return await _say(interaction, f"{config.Icons.cross} {t['need_when']}")
        problem = validate_deliver_at(deliver_at)
        if problem:
            return await _say(interaction, f"{config.Icons.cross} " + t[problem])

        if pending_count(gid, interaction.user.id) >= MAX_PENDING:
            return await _say(interaction, f"{config.Icons.cross} " + t["limit"].format(max=MAX_PENDING))
        if kind == "server" and not await text_is_clean(gid, interaction.channel_id or 0, interaction.user.id, message):
            return await _say(interaction, f"{config.Icons.cross} {t['filtered']}")

        cid = add_capsule(gid, interaction.user.id, message.strip(), kind, reveal, deliver_at)
        where = t["to_server"] if kind == "server" else t["to_dm"]
        await _say(
            interaction,
            f"{config.Icons.check} " + t["sealed"].format(id=cid, when=f"<t:{deliver_at}:D>", where=where),
            ok=True,
        )

    @group.command(name="list", description="Your sealed capsules (the text stays secret)")
    async def capsule_list(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        t = datasys.load_lang_file(interaction.guild.id)["capsule"]
        rows = user_capsules(interaction.guild.id, interaction.user.id)
        if not rows:
            return await _say(interaction, t["none"])
        lines = [
            f"`#{r['capsule_id']}` · <t:{r['deliver_at']}:D> · {t['to_server'] if r['target'] == 'server' else t['to_dm']}"
            for r in rows
        ]
        await interaction.followup.send(
            embed=discord.Embed(title=t["list_title"], description="\n".join(lines), color=config.Discord.color),
            ephemeral=True,
        )

    @group.command(name="cancel", description="Cancel one of your sealed capsules")
    async def capsule_cancel(interaction: discord.Interaction, number: app_commands.Range[int, 1, 2_000_000_000]):
        await interaction.response.defer(ephemeral=True)
        t = datasys.load_lang_file(interaction.guild.id)["capsule"]
        if cancel_capsule(interaction.guild.id, interaction.user.id, number):
            await _say(interaction, f"{config.Icons.check} " + t["cancelled"].format(id=number), ok=True)
        else:
            await _say(interaction, t["not_found"].format(id=number))

    bot.tree.add_command(group)
