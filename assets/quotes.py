"""Quote book - save memorable messages, post them in a quotes channel, pull up a random one.

A quote is saved on purpose (context menu "Save as quote" or /quote add), never automatically.
The quoted person, the person who saved it and moderators can remove it again.
"""
from __future__ import annotations

import datetime

import discord
from discord import app_commands
from discord.ext import commands

import assets.data as datasys
import assets.db as db
from assets.message.chatfilter import text_is_clean
import config.config as config
from reds_simple_logger import Logger

logger = Logger()

MAX_LEN = 1500
LIST_LIMIT = 10


# Mirrors config.datasys.default_data["quotes"]; kept here so a stale config.py cannot break the module.
_DEFAULTS = {"enabled": False, "channel": "", "staff_only_save": False}


# ── Config ───────────────────────────────────────────────────────────────────

def load_cfg(guild_id: int) -> dict:
    return {**_DEFAULTS, **dict(datasys.load_data(guild_id, "quotes"))}


def _quote_channel(guild: discord.Guild, cfg: dict) -> discord.TextChannel | None:
    raw = str(cfg.get("channel", "") or "")
    ch = guild.get_channel(int(raw)) if raw.isdigit() else None
    return ch if isinstance(ch, discord.TextChannel) else None


# ── Storage ──────────────────────────────────────────────────────────────────

def add_quote(guild_id: int, *, author_id: int | None, author_name: str, content: str,
              source_channel_id: int | None, source_message_id: int | None, saved_by: int) -> int:
    db.ensure_guild(guild_id)
    with db.transaction() as cx:
        qid = cx.execute(
            "SELECT COALESCE(MAX(quote_id), 0) + 1 FROM quotes WHERE guild_id=?", (guild_id,),
        ).fetchone()[0]
        cx.execute(
            "INSERT INTO quotes (guild_id,quote_id,author_id,author_name,content,"
            "source_channel_id,source_message_id,saved_by,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (guild_id, qid, str(author_id or ""), author_name[:100], content[:MAX_LEN],
             str(source_channel_id or ""), str(source_message_id or ""), str(saved_by),
             datetime.datetime.now(datetime.timezone.utc).isoformat()),
        )
    return qid


def get_quote(guild_id: int, quote_id: int):
    rows = db.query("SELECT * FROM quotes WHERE guild_id=? AND quote_id=?", (guild_id, quote_id))
    return rows[0] if rows else None


def find_by_source(guild_id: int, message_id: int):
    rows = db.query(
        "SELECT * FROM quotes WHERE guild_id=? AND source_message_id=?", (guild_id, str(message_id)),
    )
    return rows[0] if rows else None


def random_quote(guild_id: int, author_id: int | None = None):
    if author_id is None:
        rows = db.query("SELECT * FROM quotes WHERE guild_id=? ORDER BY RANDOM() LIMIT 1", (guild_id,))
    else:
        rows = db.query(
            "SELECT * FROM quotes WHERE guild_id=? AND author_id=? ORDER BY RANDOM() LIMIT 1",
            (guild_id, str(author_id)),
        )
    return rows[0] if rows else None


def list_quotes(guild_id: int, author_id: int | None = None) -> tuple[list, int]:
    where, params = "guild_id=?", [guild_id]
    if author_id is not None:
        where += " AND author_id=?"
        params.append(str(author_id))
    total = db.query(f"SELECT COUNT(*) AS n FROM quotes WHERE {where}", tuple(params))[0]["n"]
    rows = db.query(
        f"SELECT * FROM quotes WHERE {where} ORDER BY quote_id DESC LIMIT {LIST_LIMIT}", tuple(params),
    )
    return rows, total


def delete_quote(guild_id: int, quote_id: int) -> None:
    db.execute("DELETE FROM quotes WHERE guild_id=? AND quote_id=?", (guild_id, quote_id))


# ── Rendering ────────────────────────────────────────────────────────────────

def build_embed(guild: discord.Guild, row, t: dict) -> discord.Embed:
    embed = discord.Embed(
        title=t["title"].format(id=row["quote_id"]),
        description=f"“{row['content']}”",
        color=config.Discord.color,
    )
    member = guild.get_member(int(row["author_id"])) if str(row["author_id"]).isdigit() else None
    if member is not None:
        embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
    else:
        embed.set_author(name=row["author_name"] or "?")
    if row["source_channel_id"] and row["source_message_id"]:
        url = f"https://discord.com/channels/{guild.id}/{row['source_channel_id']}/{row['source_message_id']}"
        embed.add_field(name="​", value=f"[{t['jump']}]({url})", inline=False)
    saver = guild.get_member(int(row["saved_by"])) if str(row["saved_by"]).isdigit() else None
    when = (row["created_at"] or "")[:10]
    embed.set_footer(text=t["footer"].format(user=saver.display_name if saver else "?", date=when))
    return embed


async def _publish(guild: discord.Guild, row, cfg: dict, t: dict) -> discord.TextChannel | None:
    """Post into the configured quotes channel. Returns the channel on success."""
    channel = _quote_channel(guild, cfg)
    if channel is None:
        return None
    try:
        await channel.send(embed=build_embed(guild, row, t), allowed_mentions=discord.AllowedMentions.none())
    except (discord.Forbidden, discord.HTTPException) as e:
        logger.warn(f"[Quotes] could not post in {guild.id}: {e}")
        return None
    return channel


# ── Commands ─────────────────────────────────────────────────────────────────

def quote_commands(bot: commands.AutoShardedBot):
    def _t(guild_id: int) -> dict:
        return datasys.load_lang_file(guild_id)["quotes"]

    async def _say(interaction: discord.Interaction, text: str, *, ok: bool = False):
        await interaction.followup.send(
            embed=discord.Embed(
                description=text,
                color=config.Discord.success_color if ok else config.Discord.danger_color,
            ),
            ephemeral=True,
        )

    async def _gate(interaction: discord.Interaction, t: dict) -> dict | None:
        """Enabled + save permission. Sends the reason and returns None if blocked."""
        cfg = load_cfg(interaction.guild.id)
        if not cfg["enabled"]:
            await _say(interaction, f"{config.Icons.cross} {t['disabled']}")
            return None
        if cfg["staff_only_save"] and not interaction.user.guild_permissions.manage_messages:
            await _say(interaction, f"{config.Icons.cross} {t['no_permission']}")
            return None
        return cfg

    async def _store_and_announce(interaction: discord.Interaction, t: dict, cfg: dict, **fields):
        qid = add_quote(interaction.guild.id, saved_by=interaction.user.id, **fields)
        row = get_quote(interaction.guild.id, qid)
        channel = await _publish(interaction.guild, row, cfg, t)
        if channel is not None:
            await _say(interaction, f"{config.Icons.check} " + t["saved_in"].format(id=qid, channel=channel.mention), ok=True)
        elif str(cfg.get("channel", "") or "").isdigit():
            await _say(interaction, f"{config.Icons.check} " + t["saved"].format(id=qid) + " " +
                       t["post_failed"], ok=True)
        else:
            await _say(interaction, f"{config.Icons.check} " + t["saved"].format(id=qid), ok=True)

    @bot.tree.context_menu(name="Save as quote")
    @app_commands.guild_only()
    async def save_quote_ctx(interaction: discord.Interaction, message: discord.Message):
        await interaction.response.defer(ephemeral=True)
        t = _t(interaction.guild.id)
        cfg = await _gate(interaction, t)
        if cfg is None:
            return
        if message.author.bot:
            return await _say(interaction, f"{config.Icons.cross} {t['bot_message']}")
        text = (message.content or "").strip()
        if not text:
            return await _say(interaction, f"{config.Icons.cross} {t['empty_message']}")
        if len(text) > MAX_LEN:
            return await _say(interaction, f"{config.Icons.cross} " + t["too_long"].format(max=MAX_LEN))
        existing = find_by_source(interaction.guild.id, message.id)
        if existing:
            return await _say(interaction, f"{config.Icons.alert} " + t["duplicate"].format(id=existing["quote_id"]))
        await _store_and_announce(
            interaction, t, cfg,
            author_id=message.author.id, author_name=message.author.display_name, content=text,
            source_channel_id=message.channel.id, source_message_id=message.id,
        )

    group = app_commands.Group(name="quote", description="Quote book of this server", guild_only=True)

    @group.command(name="add", description="Save a quote by typing it in")
    @app_commands.describe(text="What was said", member="Who said it (if they are on this server)",
                           name="Who said it (if they are not a member)")
    async def quote_add(interaction: discord.Interaction, text: app_commands.Range[str, 1, MAX_LEN],
                        member: discord.Member | None = None, name: app_commands.Range[str, 1, 60] | None = None):
        await interaction.response.defer(ephemeral=True)
        t = _t(interaction.guild.id)
        cfg = await _gate(interaction, t)
        if cfg is None:
            return
        if member is None and not name:
            return await _say(interaction, f"{config.Icons.cross} {t['author_required']}")
        if member is not None and member.bot:
            return await _say(interaction, f"{config.Icons.cross} {t['bot_message']}")
        if not await text_is_clean(interaction.guild.id, interaction.channel_id or 0, interaction.user.id, text):
            return await _say(interaction, f"{config.Icons.cross} {t['filtered']}")
        await _store_and_announce(
            interaction, t, cfg,
            author_id=member.id if member else None,
            author_name=member.display_name if member else str(name),
            content=text.strip(), source_channel_id=None, source_message_id=None,
        )

    @group.command(name="random", description="Show a random quote")
    @app_commands.describe(member="Only quotes by this member")
    async def quote_random(interaction: discord.Interaction, member: discord.Member | None = None):
        await interaction.response.defer()
        t = _t(interaction.guild.id)
        if not load_cfg(interaction.guild.id)["enabled"]:
            return await _say(interaction, f"{config.Icons.cross} {t['disabled']}")
        row = random_quote(interaction.guild.id, member.id if member else None)
        if row is None:
            text = t["none_user"].format(user=member.display_name) if member else t["none"]
            return await _say(interaction, text)
        await interaction.followup.send(embed=build_embed(interaction.guild, row, t),
                                        allowed_mentions=discord.AllowedMentions.none())

    @group.command(name="show", description="Show a quote by its number")
    async def quote_show(interaction: discord.Interaction, number: app_commands.Range[int, 1, 10_000_000]):
        await interaction.response.defer()
        t = _t(interaction.guild.id)
        if not load_cfg(interaction.guild.id)["enabled"]:
            return await _say(interaction, f"{config.Icons.cross} {t['disabled']}")
        row = get_quote(interaction.guild.id, number)
        if row is None:
            return await _say(interaction, t["not_found"].format(id=number))
        await interaction.followup.send(embed=build_embed(interaction.guild, row, t),
                                        allowed_mentions=discord.AllowedMentions.none())

    @group.command(name="list", description="List the newest quotes")
    @app_commands.describe(member="Only quotes by this member")
    async def quote_list(interaction: discord.Interaction, member: discord.Member | None = None):
        await interaction.response.defer(ephemeral=True)
        t = _t(interaction.guild.id)
        if not load_cfg(interaction.guild.id)["enabled"]:
            return await _say(interaction, f"{config.Icons.cross} {t['disabled']}")
        rows, total = list_quotes(interaction.guild.id, member.id if member else None)
        if not rows:
            text = t["none_user"].format(user=member.display_name) if member else t["none"]
            return await _say(interaction, text)
        lines = []
        for r in rows:
            snippet = r["content"].replace("\n", " ")
            snippet = snippet[:90] + "…" if len(snippet) > 90 else snippet
            lines.append(f"`#{r['quote_id']}` **{discord.utils.escape_markdown(r['author_name'] or '?')}**: {discord.utils.escape_markdown(snippet)}")
        embed = discord.Embed(
            title=t["list_title_user"].format(user=member.display_name) if member else t["list_title"],
            description="\n".join(lines),
            color=config.Discord.color,
        )
        if total > len(rows):
            embed.set_footer(text=t["list_more"].format(n=len(rows), total=total))
        await interaction.followup.send(embed=embed, ephemeral=True)

    @group.command(name="remove", description="Remove a quote (your own, one you saved, or any with Manage Messages)")
    async def quote_remove(interaction: discord.Interaction, number: app_commands.Range[int, 1, 10_000_000]):
        await interaction.response.defer(ephemeral=True)
        t = _t(interaction.guild.id)
        row = get_quote(interaction.guild.id, number)
        if row is None:
            return await _say(interaction, t["not_found"].format(id=number))
        uid = str(interaction.user.id)
        if uid not in (row["author_id"], row["saved_by"]) and not interaction.user.guild_permissions.manage_messages:
            return await _say(interaction, f"{config.Icons.cross} {t['remove_denied']}")
        delete_quote(interaction.guild.id, number)
        await _say(interaction, f"{config.Icons.check} " + t["removed"].format(id=number), ok=True)

    bot.tree.add_command(group)
