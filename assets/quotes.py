"""Quote book - save memorable messages, post them in a quotes channel, pull up a random one.

A quote is saved on purpose (context menu "Save as quote" or /quote add), never automatically.
The quoted person, the person who saved it and moderators can remove it again.
The post in the quotes channel carries reaction buttons: 😂 always, plus up to three more emojis
picked through the + button (any emoji, including the server's own).
"""
from __future__ import annotations

import asyncio
import datetime
import re

import discord
import emoji as _emoji_lib
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
    with db.transaction() as cx:
        cx.execute("DELETE FROM quote_reactions WHERE guild_id=? AND quote_id=?", (guild_id, quote_id))
        cx.execute("DELETE FROM quotes WHERE guild_id=? AND quote_id=?", (guild_id, quote_id))


def _set_post(guild_id: int, quote_id: int, channel_id: int, message_id: int) -> None:
    db.execute(
        "UPDATE quotes SET post_channel_id=?, post_message_id=? WHERE guild_id=? AND quote_id=?",
        (str(channel_id), str(message_id), guild_id, quote_id),
    )


# ── Reactions ────────────────────────────────────────────────────────────────
# An emoji is stored as a key that also fits into a custom_id:
#   "u1f602"         unicode, code points in hex joined by "-" (always the fully-qualified form)
#   "c123456789"     custom emoji of this server, by id
# quotes.reaction_order keeps the extra emojis in the order they first appeared, so buttons never
# jump around when someone takes their reaction back.

MAX_EMOJIS = 4                       # distinct emojis per quote, 😂 included (+ button makes 5 = one row)
DEFAULT_EMOJI = "😂"
# Offered first in the + menu; the server's own emojis fill the rest of the 25 options.
POPULAR = ["❤️", "🔥", "💀", "😭", "👀", "🫡", "🤯", "👍", "💯", "🤡"]
_SELECT_MAX = 25
_KEY_MAX = 80                        # custom_id limit is 100 incl. "qr:<id>:"

_CUSTOM_RE = re.compile(r"^<a?:[A-Za-z0-9_]{2,32}:(\d+)>$")
_NAME_RE = re.compile(r"^:([A-Za-z0-9_+\-]{2,40}):$")
_FULLY_QUALIFIED = _emoji_lib.STATUS["fully_qualified"]


def unicode_key(text: str) -> str:
    return "u" + "-".join(f"{ord(c):x}" for c in text)


def _key_to_unicode(key: str) -> str:
    return "".join(chr(int(h, 16)) for h in key[1:].split("-"))


DEFAULT_KEY = unicode_key(DEFAULT_EMOJI)


def _emoji_for(guild: discord.Guild, key: str) -> discord.PartialEmoji | str | None:
    """What a button shows for *key*, or None if it cannot be shown (custom emoji deleted)."""
    if key.startswith("c"):
        em = discord.utils.get(guild.emojis, id=int(key[1:]))
        return em if em is not None and em.available else None
    return _key_to_unicode(key)


def _qualified(text: str) -> str | None:
    """Exactly one real emoji → its fully-qualified form (❤ → ❤️), else None."""
    for cand in (text, text + "️", text.replace("️", "")):
        data = _emoji_lib.EMOJI_DATA.get(cand)
        if data and data["status"] == _FULLY_QUALIFIED:
            return cand
    return None


def parse_emoji(guild: discord.Guild, text: str) -> str | None:
    """Typed or pasted emoji → key. Custom emojis must belong to this server; :name: is looked up
    among the server's emojis first, then as a standard emoji alias (:fire:, :heart:)."""
    text = text.strip()
    m = _CUSTOM_RE.match(text)
    if m:
        em = discord.utils.get(guild.emojis, id=int(m.group(1)))
        return f"c{em.id}" if em is not None and em.available else None
    m = _NAME_RE.match(text)
    if m:
        name = m.group(1).lower()
        em = next((e for e in guild.emojis if e.name.lower() == name and e.available), None)
        if em is not None:
            return f"c{em.id}"
        text = _emoji_lib.emojize(text, language="alias")
    q = _qualified(text)
    if q is None or len(unicode_key(q)) > _KEY_MAX:
        return None
    return unicode_key(q)


def _order(guild_id: int, quote_id: int) -> list[str]:
    rows = db.query("SELECT reaction_order FROM quotes WHERE guild_id=? AND quote_id=?", (guild_id, quote_id))
    raw = (rows[0]["reaction_order"] if rows else "") or ""
    return [k for k in raw.split(",") if k]


def _set_order(guild_id: int, quote_id: int, keys: list[str]) -> None:
    db.execute("UPDATE quotes SET reaction_order=? WHERE guild_id=? AND quote_id=?",
               (",".join(keys), guild_id, quote_id))


def reaction_counts(guild_id: int, quote_id: int) -> list[tuple[str, int]]:
    """(key, count) in button order: 😂 first, the rest in the order they first appeared."""
    counts = {r["emoji"]: r["n"] for r in db.query(
        "SELECT emoji, COUNT(*) AS n FROM quote_reactions WHERE guild_id=? AND quote_id=? GROUP BY emoji",
        (guild_id, quote_id),
    )}
    out = [(DEFAULT_KEY, counts.pop(DEFAULT_KEY, 0))]
    for key in _order(guild_id, quote_id):
        if key in counts:
            out.append((key, counts.pop(key)))
    out += sorted(counts.items())                              # rows without an order entry (should not happen)
    return out


def _shown(guild: discord.Guild, quote_id: int) -> list[tuple[str, int, object]]:
    return [(k, n, e) for k, n in reaction_counts(guild.id, quote_id)
            if (e := _emoji_for(guild, k)) is not None]


def _has_reacted(guild_id: int, quote_id: int, user_id: int, key: str) -> bool:
    return bool(db.query(
        "SELECT 1 AS x FROM quote_reactions WHERE guild_id=? AND quote_id=? AND emoji=? AND user_id=?",
        (guild_id, quote_id, key, str(user_id)),
    ))


def toggle_reaction(guild: discord.Guild, quote_id: int, user_id: int, key: str) -> tuple[str, bool]:
    """Returns (result, new_emoji): result is "added", "removed" or "full" (a new emoji would exceed
    MAX_EMOJIS); new_emoji is True when this call put a new emoji on the quote."""
    if _has_reacted(guild.id, quote_id, user_id, key):
        db.execute(
            "DELETE FROM quote_reactions WHERE guild_id=? AND quote_id=? AND emoji=? AND user_id=?",
            (guild.id, quote_id, key, str(user_id)),
        )
        if key != DEFAULT_KEY and not db.query(
            "SELECT 1 AS x FROM quote_reactions WHERE guild_id=? AND quote_id=? AND emoji=?",
            (guild.id, quote_id, key),
        ):
            _set_order(guild.id, quote_id, [k for k in _order(guild.id, quote_id) if k != key])
        return "removed", False
    shown = {k for k, _, _ in _shown(guild, quote_id)}
    is_new = key not in shown
    if is_new and len(shown) >= MAX_EMOJIS:
        return "full", False
    db.execute(
        "INSERT OR IGNORE INTO quote_reactions (guild_id,quote_id,emoji,user_id,created_at) VALUES (?,?,?,?,?)",
        (guild.id, quote_id, key, str(user_id), datetime.datetime.now(datetime.timezone.utc).isoformat()),
    )
    if key != DEFAULT_KEY:
        order = _order(guild.id, quote_id)
        if key not in order:
            _set_order(guild.id, quote_id, order + [key])
    return "added", is_new


def _drop_emoji(guild_id: int, quote_id: int, key: str) -> None:
    db.execute("DELETE FROM quote_reactions WHERE guild_id=? AND quote_id=? AND emoji=?", (guild_id, quote_id, key))
    _set_order(guild_id, quote_id, [k for k in _order(guild_id, quote_id) if k != key])


def build_view(guild: discord.Guild, quote_id: int) -> discord.ui.View:
    """Reaction row for a quote post. Built from the DynamicItem itself, so discord.py does not keep
    a stored view per post in memory; clicks are routed by custom_id, also after a restart."""
    view = discord.ui.View(timeout=None)
    shown = _shown(guild, quote_id)
    for key, n, em in shown:
        item = QuoteReactionButton(quote_id, key)
        item.item.emoji, item.item.label = em, str(n)
        view.add_item(item)
    if len(shown) < MAX_EMOJIS:
        item = QuoteReactionButton(quote_id, "add")
        item.item.emoji = "➕"
        view.add_item(item)
    return view


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
        msg = await channel.send(embed=build_embed(guild, row, t), view=build_view(guild, row["quote_id"]),
                                 allowed_mentions=discord.AllowedMentions.none())
    except (discord.Forbidden, discord.HTTPException) as e:
        logger.warn(f"[Quotes] could not post in {guild.id}: {e}")
        return None
    _set_post(guild.id, row["quote_id"], channel.id, msg.id)
    return channel


# ── Reaction UI ──────────────────────────────────────────────────────────────

def _t(guild_id: int) -> dict:
    return datasys.load_lang_file(guild_id)["quotes"]


async def _private(interaction: discord.Interaction, text: str) -> None:
    if interaction.response.is_done():
        await interaction.followup.send(text, ephemeral=True)
    else:
        await interaction.response.send_message(text, ephemeral=True)


def _label(guild: discord.Guild, key: str) -> str:
    em = _emoji_for(guild, key)
    return str(em) if em is not None else "?"


# One lock per quote: a click updates the DB and answers with the fresh row while holding it, so two
# quick clicks can never leave an older count on the post.
_locks: dict[tuple[int, int], asyncio.Lock] = {}


def _lock(guild_id: int, quote_id: int) -> asyncio.Lock:
    return _locks.setdefault((guild_id, quote_id), asyncio.Lock())


async def _refresh_post(guild: discord.Guild, quote_id: int, channel_id: int, message_id: int) -> bool:
    channel = guild.get_channel(channel_id)
    if not isinstance(channel, discord.TextChannel):
        return False
    try:
        await channel.get_partial_message(message_id).edit(view=build_view(guild, quote_id))
    except (discord.Forbidden, discord.NotFound):
        return False
    return True


async def remove_post_buttons(guild: discord.Guild, row) -> None:
    """After /quote remove: take the buttons off the post (best effort)."""
    ch_id, msg_id = str(row["post_channel_id"] or ""), str(row["post_message_id"] or "")
    channel = guild.get_channel(int(ch_id)) if ch_id.isdigit() else None
    if isinstance(channel, discord.TextChannel) and msg_id.isdigit():
        try:
            await channel.get_partial_message(int(msg_id)).edit(view=None)
        except discord.HTTPException:
            pass


async def _add_from_menu(interaction: discord.Interaction, quote_id: int, key: str,
                         channel_id: int, message_id: int) -> None:
    """A pick from the + menu (dropdown or typed): add the reaction, update the post, close the menu."""
    await interaction.response.defer()                         # edits the private menu message below
    guild, t = interaction.guild, _t(interaction.guild.id)
    async with _lock(guild.id, quote_id):
        if get_quote(guild.id, quote_id) is None:
            result, is_new = "gone", False
        elif _has_reacted(guild.id, quote_id, interaction.user.id, key):
            result, is_new = "added", False                    # picked one they had already: nothing to do
        else:
            result, is_new = toggle_reaction(guild, quote_id, interaction.user.id, key)
        if result == "gone":
            text = t["react_gone"]
        elif result == "full":
            text = t["react_full"].format(max=MAX_EMOJIS)
        else:
            try:
                ok = await _refresh_post(guild, quote_id, channel_id, message_id)
                text = t["react_added"].format(emoji=_label(guild, key)) if ok else t["react_failed"]
            except discord.HTTPException as e:
                # Only an emoji this call just introduced can be the reason; never drop existing ones.
                if is_new and e.status == 400:
                    _drop_emoji(guild.id, quote_id, key)
                    text = t["react_invalid"]
                else:
                    text = t["react_failed"]
    await interaction.edit_original_response(content=text, view=None)


class _OtherEmojiModal(discord.ui.Modal):
    def __init__(self, t: dict, quote_id: int, channel_id: int, message_id: int):
        super().__init__(title=t["react_modal_title"], timeout=300)
        self.quote_id, self.channel_id, self.message_id = quote_id, channel_id, message_id
        self.field = discord.ui.TextInput(label=t["react_modal_label"], placeholder=t["react_modal_placeholder"],
                                          max_length=60)
        self.add_item(self.field)

    async def on_submit(self, interaction: discord.Interaction):
        key = parse_emoji(interaction.guild, str(self.field.value))
        if key is None:
            return await interaction.response.edit_message(content=_t(interaction.guild.id)["react_invalid"], view=None)
        await _add_from_menu(interaction, self.quote_id, key, self.channel_id, self.message_id)


def _menu_options(guild: discord.Guild, quote_id: int) -> list[discord.SelectOption]:
    present = {k for k, _, _ in _shown(guild, quote_id)}
    opts = [discord.SelectOption(label=e, value=unicode_key(e)) for e in POPULAR if unicode_key(e) not in present]
    # Server emojis that were used on quotes before come first, then alphabetical.
    used = {r["emoji"]: r["n"] for r in db.query(
        "SELECT emoji, COUNT(*) AS n FROM quote_reactions WHERE guild_id=? AND emoji LIKE 'c%' GROUP BY emoji",
        (guild.id,),
    )}
    customs = sorted((e for e in guild.emojis if e.available and f"c{e.id}" not in present),
                     key=lambda e: (-used.get(f"c{e.id}", 0), e.name.lower()))
    for em in customs[:_SELECT_MAX - len(opts)]:
        opts.append(discord.SelectOption(label=f":{em.name}:", value=f"c{em.id}", emoji=em))
    return opts


class _EmojiMenu(discord.ui.View):
    """Private menu behind ➕: a dropdown of common + server emojis, and a button for any other emoji
    (a button, not a dropdown entry, so it can be used again after closing the input)."""

    def __init__(self, guild: discord.Guild, t: dict, quote_id: int, channel_id: int, message_id: int):
        super().__init__(timeout=180)
        self.t, self.quote_id, self.channel_id, self.message_id = t, quote_id, channel_id, message_id
        select = discord.ui.Select(placeholder=t["react_pick"].format(id=quote_id),
                                   options=_menu_options(guild, quote_id))
        select.callback = self._picked
        self.select = select
        self.add_item(select)
        other = discord.ui.Button(label=t["react_other"], style=discord.ButtonStyle.secondary)
        other.callback = self._other
        self.add_item(other)

    async def _picked(self, interaction: discord.Interaction):
        await _add_from_menu(interaction, self.quote_id, self.select.values[0], self.channel_id, self.message_id)

    async def _other(self, interaction: discord.Interaction):
        await interaction.response.send_modal(_OtherEmojiModal(self.t, self.quote_id, self.channel_id, self.message_id))


class QuoteReactionButton(discord.ui.DynamicItem[discord.ui.Button],
                          template=r"qr:(?P<qid>\d+):(?P<key>add|c\d+|u[0-9a-f]+(?:-[0-9a-f]+)*)"):
    def __init__(self, quote_id: int, key: str) -> None:
        super().__init__(discord.ui.Button(custom_id=f"qr:{quote_id}:{key}", style=discord.ButtonStyle.secondary))
        self.quote_id, self.key = quote_id, key

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button,
                             match: re.Match[str]) -> "QuoteReactionButton":
        return cls(int(match["qid"]), match["key"])

    async def callback(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None or interaction.message is None:
            return
        t = _t(guild.id)
        if not load_cfg(guild.id)["enabled"]:
            return await _private(interaction, f"{config.Icons.cross} {t['disabled']}")
        if get_quote(guild.id, self.quote_id) is None:
            await _private(interaction, t["react_gone"])
            try:
                await interaction.message.edit(view=None)
            except discord.HTTPException:
                pass
            return
        async with _lock(guild.id, self.quote_id):
            if self.key == "add":
                if len(_shown(guild, self.quote_id)) < MAX_EMOJIS:
                    return await interaction.response.send_message(
                        view=_EmojiMenu(guild, t, self.quote_id, interaction.channel_id, interaction.message.id),
                        ephemeral=True,
                    )
                result = "full"                                # stale ➕ on a full quote
            else:
                result, _ = toggle_reaction(guild, self.quote_id, interaction.user.id, self.key)
            await interaction.response.edit_message(view=build_view(guild, self.quote_id))
        if result == "full":
            await interaction.followup.send(t["react_full"].format(max=MAX_EMOJIS), ephemeral=True)


# ── Commands ─────────────────────────────────────────────────────────────────

def quote_commands(bot: commands.AutoShardedBot):
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

    group = app_commands.Group(name="quote", description="Quote book", guild_only=True)

    @group.command(name="add", description="Save a quote")
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

    @group.command(name="show", description="Show a quote (by number or random)")
    @app_commands.describe(number="Quote number (leave empty for a random quote)",
                           member="Random quote by this member")
    async def quote_show(interaction: discord.Interaction,
                         number: app_commands.Range[int, 1, 10_000_000] | None = None,
                         member: discord.Member | None = None):
        await interaction.response.defer()
        t = _t(interaction.guild.id)
        if not load_cfg(interaction.guild.id)["enabled"]:
            return await _say(interaction, f"{config.Icons.cross} {t['disabled']}")
        if number is not None:
            row = get_quote(interaction.guild.id, number)
            if row is None:
                return await _say(interaction, t["not_found"].format(id=number))
        else:
            row = random_quote(interaction.guild.id, member.id if member else None)
            if row is None:
                text = t["none_user"].format(user=member.display_name) if member else t["none"]
                return await _say(interaction, text)
        await interaction.followup.send(embed=build_embed(interaction.guild, row, t),
                                        allowed_mentions=discord.AllowedMentions.none())

    @group.command(name="list", description="Newest quotes")
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

    @group.command(name="remove", description="Remove a quote")
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
        await remove_post_buttons(interaction.guild, row)
        await _say(interaction, f"{config.Icons.check} " + t["removed"].format(id=number), ok=True)

    bot.tree.add_command(group)
