"""Components V2 for Baxi's own messages.

``from_embed(embed)`` turns an existing ``discord.Embed`` into a V2 card (one ``Container`` in the
embed's colour), so a call site only swaps ``embed=e`` for ``view=v2.from_embed(e)``. The look:

* title, author line, description (and fields) as text; the dither thumbnail (``dither_art``) or the
  embed's own thumbnail sits next to the head as a ``Section`` accessory, like in the embed
* image as a media gallery, footer and timestamp as small ``-#`` text

A V2 message cannot carry ``content``, ``embeds`` or polls, and Discord caps the text of one message
at 4000 characters (``TEXT_LIMIT``); longer text is trimmed (the description first). Views need a
running event loop: call this from async code.
"""
from __future__ import annotations

import discord

TEXT_LIMIT = 3900   # Discord: 4000 per message; margin for the joins


def _clip(s: str, n: int) -> str:
    return s if len(s) <= n else s[: max(0, n - 1)].rstrip() + "…"


def card_container(embed: discord.Embed, buttons: list[discord.ui.Button] | None = None,
                   extra: list[discord.ui.Item] | None = None) -> discord.ui.Container:
    """The V2 card of an embed (see the module doc). ``buttons`` (link buttons) go in a row inside it,
    ``extra`` items (e.g. ready-made ``ActionRow``s with a select or buttons) are appended."""
    from assets import dither_art

    head: list[str] = []
    if embed.author and embed.author.name:
        head.append(f"-# {embed.author.name}")
    if embed.title:
        head.append(f"## [{embed.title}]({embed.url})" if embed.url else f"## {embed.title}")
    fields = [f"**{f.name}**\n{f.value}" if f.name and f.name != "\u200b" else f.value
              for f in embed.fields if f.name or f.value]
    foot = []
    if embed.footer and embed.footer.text:
        foot.append(embed.footer.text)
    if embed.timestamp:
        foot.append(f"<t:{int(embed.timestamp.timestamp())}:f>")
    foot_text = f"-# {' · '.join(foot)}" if foot else ""

    # budget: footer and fields keep their text, the description gives way
    desc = embed.description or ""
    fixed = sum(len(x) for x in head) + sum(len(x) for x in fields) + len(foot_text)
    desc = _clip(desc, max(200, TEXT_LIMIT - fixed))
    fields = _clip("\n\n".join(fields), max(200, TEXT_LIMIT - len(desc) - sum(len(x) for x in head) - len(foot_text))) if fields else ""

    head_text = "\n".join(head + ([desc] if desc else []))
    thumb = embed.thumbnail.url or dither_art.thumbnail_url(embed)
    items: list[discord.ui.Item] = []
    if head_text and thumb:
        items.append(discord.ui.Section(head_text, accessory=discord.ui.Thumbnail(thumb)))
    elif head_text:
        items.append(discord.ui.TextDisplay(head_text))
    if fields:
        items.append(discord.ui.TextDisplay(fields))
    if embed.image.url:
        items.append(discord.ui.MediaGallery(discord.MediaGalleryItem(embed.image.url)))
    if foot_text:
        items.append(discord.ui.TextDisplay(foot_text))
    if buttons:
        items.append(discord.ui.ActionRow(*buttons[:5]))
    items.extend(extra or [])
    if not items:
        items.append(discord.ui.TextDisplay("​"))
    return discord.ui.Container(*items, accent_colour=embed.color)


def from_embed(embed: discord.Embed, buttons: list[discord.ui.Button] | None = None) -> discord.ui.LayoutView:
    """Embed -> V2 card as a ready-to-send view. ``buttons`` must be link buttons (no callbacks)."""
    view = discord.ui.LayoutView(timeout=None)
    view.add_item(card_container(embed, buttons))
    return view


class CardView(discord.ui.LayoutView):
    """A card with buttons that have callbacks (the V2 replacement for ``View`` + embed).

    Declare the buttons like this in a subclass::

        class MyView(v2.CardView):
            row = discord.ui.ActionRow()

            @row.button(label="OK")
            async def ok(self, interaction, button):
                self.set_card(new_embed)
                self.disable_buttons()
                await interaction.response.edit_message(view=self)

    ``set_card(embed)`` (re)builds the card above the button rows; send/edit with ``view=self`` only.
    """

    def __init__(self, embed: discord.Embed | None = None, *, timeout: float | None = 180.0, header: str = "") -> None:
        super().__init__(timeout=timeout)
        if embed is not None:
            self.set_card(embed, header=header)

    def set_card(self, embed: discord.Embed, *, header: str = "") -> None:
        """(Re)build the card; ``header`` is plain text above it (pings go here: V2 has no ``content``)."""
        rows = [c for c in self.children if isinstance(c, discord.ui.ActionRow)]
        self.clear_items()
        if header:
            self.add_item(discord.ui.TextDisplay(_clip(header, 500)))
        self.add_item(card_container(embed))
        for r in rows:
            self.add_item(r)

    def disable_buttons(self) -> None:
        for row in self.children:
            if isinstance(row, discord.ui.ActionRow):
                for c in row.children:
                    if isinstance(c, (discord.ui.Button, discord.ui.Select)):
                        c.disabled = True


async def edit(message: discord.Message, view: discord.ui.LayoutView) -> discord.Message:
    """Edit ``message`` into a V2 message, also when it is still a classic embed message
    (Discord needs content, embeds and attachments cleared explicitly for that switch)."""
    return await message.edit(content=None, embed=None, attachments=[], view=view)
