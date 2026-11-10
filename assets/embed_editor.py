"""/embed: a web editor for custom messages and embeds (like Discohook, but sent by Baxi).

``/embed`` (Manage Messages) answers with an ephemeral link. The link carries a short-lived token
bound to the server and the member; the page (``dash.py``: ``/embed/<token>``) needs the same
Discord login, lets the member pick a channel and compose messages, and posts them through
``send``. Everything is re-checked on send: the member's permissions in the chosen channel, the
bot's permissions, the chat filter (the server's own setting) and Discord's limits.

A message is either ``v1`` (text + classic embeds) or ``v2`` (Components V2: a ``LayoutView`` of
containers, text, sections, galleries, separators and link buttons; Discord forbids mixing the two).
"""
from __future__ import annotations

import re
import secrets
import time

import discord
from discord import app_commands
from discord.ext import commands

import assets.data as datasys
import config.config as config
from assets.dither_art import Plain

TTL = 30 * 60
MAX_MESSAGES = 5
MAX_EMBEDS = 10
_sessions: dict[str, dict] = {}
_URL = re.compile(r"^https?://\S+$", re.I)
_HEX = re.compile(r"^#?([0-9a-f]{6})$", re.I)


def _cleanup() -> None:
    now = time.time()
    for t in [t for t, s in _sessions.items() if s["exp"] < now]:
        _sessions.pop(t, None)


def create_session(guild_id: int, user_id: int) -> str:
    _cleanup()
    token = secrets.token_urlsafe(24)
    _sessions[token] = {"guild_id": guild_id, "user_id": user_id, "exp": time.time() + TTL, "last": 0.0}
    return token


def get_session(token: str) -> dict | None:
    s = _sessions.get(token)
    if s and s["exp"] >= time.time():
        return s
    _sessions.pop(token, None)
    return None


class EmbedError(ValueError):
    pass


def _s(v, limit: int) -> str:
    return str(v or "").strip()[:limit] if isinstance(v, (str, int, float)) else ""


def _url(v) -> str:
    v = _s(v, 2000)
    if not v:
        return ""
    if not _URL.match(v):
        raise EmbedError(f"Not a valid http(s) link: {v[:60]}")
    return v


def build_embed(raw: dict) -> discord.Embed | None:
    """Whitelist-build one embed from editor JSON; None when it is empty."""
    if not isinstance(raw, dict):
        raise EmbedError("Invalid embed.")
    m = _HEX.match(_s(raw.get("color"), 7))
    emb = Plain(
        title=_s(raw.get("title"), 256) or None,
        description=_s(raw.get("description"), 4096) or None,
        url=_url(raw.get("url")) or None,
        color=int(m.group(1), 16) if m else config.Discord.color.value,
    )
    a = raw.get("author") or {}
    if _s(a.get("name"), 256):
        emb.set_author(name=_s(a.get("name"), 256), url=_url(a.get("url")) or None, icon_url=_url(a.get("icon_url")) or None)
    f = raw.get("footer") or {}
    if _s(f.get("text"), 2048):
        emb.set_footer(text=_s(f.get("text"), 2048), icon_url=_url(f.get("icon_url")) or None)
    if _url(raw.get("image")):
        emb.set_image(url=_url(raw.get("image")))
    if _url(raw.get("thumbnail")):
        emb.set_thumbnail(url=_url(raw.get("thumbnail")))
    for fld in (raw.get("fields") or [])[:25]:
        name, value = _s(fld.get("name"), 256), _s(fld.get("value"), 1024)
        if name and value:
            emb.add_field(name=name, value=value, inline=bool(fld.get("inline")))
    if raw.get("timestamp"):
        emb.timestamp = discord.utils.utcnow()
    return emb if emb.to_dict().keys() - {"type", "color"} else None


# ── Components V2 ────────────────────────────────────────────────────────────
MAX_COMPONENTS = 40      # Discord: every component counts, nested ones too
MAX_V2_TEXT = 4000       # all text displays of one message together
_BLOCKS = ("text", "section", "gallery", "separator", "buttons")


class _Budget:
    def __init__(self) -> None:
        self.components = 0
        self.chars = 0
        self.texts: list[str] = []

    def add(self, n: int = 1) -> None:
        self.components += n
        if self.components > MAX_COMPONENTS:
            raise EmbedError(f"A Components V2 message holds at most {MAX_COMPONENTS} components "
                             "(every block, button and picture counts).")

    def text(self, v, limit: int = 4000) -> str:
        t = _s(v, limit)
        self.chars += len(t)
        if self.chars > MAX_V2_TEXT:
            raise EmbedError(f"All text of one Components V2 message together may hold at most {MAX_V2_TEXT} characters.")
        if t:
            self.texts.append(t)
        return t


def _link_button(b, budget: _Budget) -> discord.ui.Button | None:
    if not isinstance(b, dict):
        return None
    label, url = _s(b.get("label"), 80), _url(b.get("url"))
    if not label or not url:
        return None
    budget.texts.append(label)
    return discord.ui.Button(style=discord.ButtonStyle.link, label=label, url=url)


def _build_block(raw, budget: _Budget):
    """One non-container block, or None when it is empty."""
    if not isinstance(raw, dict):
        raise EmbedError("Invalid block.")
    kind = raw.get("type")
    if kind == "text":
        t = budget.text(raw.get("content"))
        if not t:
            return None
        budget.add()
        return discord.ui.TextDisplay(t)
    if kind == "separator":
        budget.add()
        return discord.ui.Separator(visible=bool(raw.get("divider", True)),
                                    spacing=discord.SeparatorSpacing.large if raw.get("large") else discord.SeparatorSpacing.small)
    if kind == "gallery":
        items = []
        for it in (raw.get("items") or [])[:10]:
            u = _url(it.get("url") if isinstance(it, dict) else "")
            if u:
                items.append(discord.MediaGalleryItem(u, description=_s(it.get("description"), 1024) or None))
        if not items:
            return None
        budget.add()
        return discord.ui.MediaGallery(*items)
    if kind == "buttons":
        btns = [b for b in (_link_button(x, budget) for x in (raw.get("buttons") or [])[:5]) if b]
        if not btns:
            return None
        budget.add(1 + len(btns))
        return discord.ui.ActionRow(*btns)
    if kind == "section":
        t = budget.text(raw.get("content"))
        as_button = raw.get("accessory") == "button"
        img = "" if as_button else _url(raw.get("image"))
        btn = _link_button(raw.get("button"), budget) if as_button else None
        if not t:
            return None
        if img:
            budget.add(3)
            return discord.ui.Section(t, accessory=discord.ui.Thumbnail(img, description=_s(raw.get("description"), 1024) or None))
        if btn:
            budget.add(3)
            return discord.ui.Section(t, accessory=btn)
        budget.add()   # a section needs an accessory; without one it is plain text
        return discord.ui.TextDisplay(t)
    raise EmbedError("Unknown block type.")


def build_layout(raw_items) -> tuple[discord.ui.LayoutView | None, str]:
    """Whitelist-build a Components V2 view from editor JSON -> (view, all text for the filter)."""
    if not isinstance(raw_items, list):
        raise EmbedError("Invalid components.")
    budget = _Budget()
    view = discord.ui.LayoutView(timeout=None)
    for raw in raw_items[:100]:
        if isinstance(raw, dict) and raw.get("type") == "container":
            m = _HEX.match(_s(raw.get("color"), 7))
            children = [c for c in (_build_block(x, budget) for x in (raw.get("children") or [])[:100]) if c]
            if not children:
                continue
            budget.add()
            view.add_item(discord.ui.Container(*children, accent_colour=int(m.group(1), 16) if m else None,
                                               spoiler=bool(raw.get("spoiler"))))
        else:
            block = _build_block(raw, budget)
            if block is not None:
                view.add_item(block)
    return (view if view.children else None), "\n".join(budget.texts)


# ── v1 + parsing ─────────────────────────────────────────────────────────────
def texts_of(content: str, embeds: list[discord.Embed]) -> str:
    parts = [content]
    for e in embeds:
        parts += [e.title or "", e.description or "", e.author.name or "", e.footer.text or ""]
        parts += [x for fl in e.fields for x in (fl.name, fl.value)]
    return "\n".join(p for p in parts if p)


def parse_messages(payload) -> list[dict]:
    """-> [{"content", "embeds", "view", "text"}]; ``view`` is set for v2 messages only."""
    msgs = payload.get("messages") if isinstance(payload, dict) else None
    if not isinstance(msgs, list) or not msgs:
        raise EmbedError("Nothing to send.")
    if len(msgs) > MAX_MESSAGES:
        raise EmbedError(f"At most {MAX_MESSAGES} messages at once.")
    out = []
    for i, m in enumerate(msgs, 1):
        if not isinstance(m, dict):
            raise EmbedError(f"Message {i} is invalid.")
        if m.get("mode") == "v2":
            view, text = build_layout(m.get("components"))
            if view is None:
                raise EmbedError(f"Message {i} is empty.")
            out.append({"content": "", "embeds": [], "view": view, "text": text})
            continue
        content = _s(m.get("content"), 2000)
        embeds = [e for e in (build_embed(r) for r in (m.get("embeds") or [])[:MAX_EMBEDS]) if e]
        if not content and not embeds:
            raise EmbedError(f"Message {i} is empty.")
        if sum(len(e) for e in embeds) > 6000:
            raise EmbedError(f"Message {i}: all embeds together may hold at most 6000 characters.")
        out.append({"content": content, "embeds": embeds, "view": None, "text": texts_of(content, embeds)})
    return out


def sendable_channels(guild: discord.Guild, member: discord.Member) -> list[discord.TextChannel]:
    need = ("view_channel", "send_messages", "embed_links")
    res = []
    for ch in guild.text_channels:
        mine, theirs = ch.permissions_for(guild.me), ch.permissions_for(member)
        if all(getattr(mine, p) and getattr(theirs, p) for p in need):
            res.append(ch)
    return res


async def send(guild: discord.Guild, member: discord.Member, channel_id: int, payload) -> list[str]:
    """Post the messages; returns the jump URLs. Raises EmbedError with a message for the user."""
    from assets.message.chatfilter import text_is_clean
    if not member.guild_permissions.manage_messages:
        raise EmbedError("You need the Manage Messages permission.")
    channel = guild.get_channel(channel_id)
    if channel not in sendable_channels(guild, member):
        raise EmbedError("Pick a channel where both you and Baxi can send messages and embeds.")
    messages = parse_messages(payload)
    for m in messages:
        if not await text_is_clean(guild.id, channel.id, member.id, m["text"]):
            raise EmbedError("The chat filter of this server blocked the text.")
    mentions = (discord.AllowedMentions(everyone=True, roles=True, users=True)
                if member.guild_permissions.mention_everyone else discord.AllowedMentions(everyone=False, roles=False, users=True))
    urls = []
    for m in messages:
        try:
            if m["view"] is not None:
                sent = await channel.send(view=m["view"], allowed_mentions=mentions)
            else:
                sent = await channel.send(content=m["content"] or None, embeds=m["embeds"], allowed_mentions=mentions)
        except discord.HTTPException as e:
            raise EmbedError(f"Discord refused the message: {e.text[:150]}")
        urls.append(sent.jump_url)
    return urls


def embed_commands(bot: commands.AutoShardedBot):
    @bot.tree.command(name="embed", description="Open the editor for custom messages (Components V2 and embeds)")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.checks.has_permissions(manage_messages=True)
    async def embed_cmd(interaction: discord.Interaction):
        token = create_session(interaction.guild_id, interaction.user.id)
        link = f"https://{config.Web.url}/embed/{token}"
        e = discord.Embed(
            title="Message editor",
            description=f"[Open the editor]({link})\nLog in with Discord if asked. The link is only for you and works for 30 minutes.",
            color=config.Discord.color,
        )
        await interaction.response.send_message(embed=e, ephemeral=True)
