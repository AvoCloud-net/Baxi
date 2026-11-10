"""Baxi news posts: the look of every announcement the bot admin sends.

One Components V2 container in the brand colour, like a news card: a banner (the given image,
else the dither banner), the title, the text (``▼ // Heading`` sections) and a version footer.
The admin dashboard writes the text as plain Markdown; a line starting with ``#`` becomes a
section heading. Discord allows 4000 characters of text per V2 message, hence the body cap.
"""
from __future__ import annotations

import re

import discord

import config.config as config
from assets import dither_art

_HEADING = re.compile(r"^\s*#{1,3}\s+(.*\S)\s*$")
_IMAGE_URL = re.compile(r"^https://\S+$")


def format_body(text: str) -> str:
    """'# Event time' -> '### ▼ // Event time'; everything else stays as written."""
    out = []
    for line in text.strip().splitlines():
        m = _HEADING.match(line)
        out.append(f"### ▼ // {m.group(1)}" if m else line)
    return "\n".join(out)[:3500]


def valid_image(url: str) -> bool:
    return not url or bool(_IMAGE_URL.match(url)) and len(url) <= 512


def build(title: str, text: str, image_url: str = "") -> discord.ui.LayoutView:
    """The news card as a Components V2 view: ``channel.send(view=build(...))`` (no content/embeds)."""
    banner = discord.ui.MediaGallery(discord.MediaGalleryItem(image_url or dither_art.url("wave", "banner")))
    card = discord.ui.Container(
        banner,
        discord.ui.TextDisplay(f"# {title[:200]}"),
        discord.ui.Separator(),
        discord.ui.TextDisplay(format_body(text)),
        discord.ui.TextDisplay(f"-# Baxi {config.Discord.version} · avocloud.net"),
        accent_colour=config.Discord.color,
    )
    view = discord.ui.LayoutView(timeout=None)
    view.add_item(card)
    return view
