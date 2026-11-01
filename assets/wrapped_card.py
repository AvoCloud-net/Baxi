"""Pillow renderers for the Server Wrapped cards.

Graphics only: avatars, Lucide icons, bars and the big figures that identify a card (like the
rank card). Every word (titles, labels, names, explanations) lives in the Discord embed that
assets/wrapped.py builds around the image. The only text drawn here are axis ticks and figures,
which the caller passes in already formatted.

Four layouts, 640 x 320, drawn at 4x and downsampled with LANCZOS:
  figures   - avatar (or server icon) left, up to three icon + figure rows right
  bars      - one bar chart with a highlighted bar (hours of the day, months)
  podium    - one or two rows of up to three avatars with a rank badge (top lists)
  spotlight - one or two spots: avatar (or a big icon) with an icon + figure beside it

The async helpers fetch the avatars first (falling back to a placeholder when the CDN fails),
then render in a thread. They return io.BytesIO; the caller wraps it in discord.File.
"""
from __future__ import annotations

import asyncio
import io

import cairosvg
from PIL import Image, ImageDraw

from assets.mc_link_card import (
    _BG, _CARD_BORDER, _LINE, _MUTED, _PRIMARY, _SUCCESS, _TEXT,
    _circle_crop, _fetch_image, _placeholder, _to_bytes,
)
from PIL import ImageFont
from reds_simple_logger import Logger

logger = Logger()

CANVAS = (640, 320)
_SS = 4

# DejaVu in the places distros put it (Fedora, Debian/Ubuntu and the Docker images based on
# them, Alpine, Arch), then the bare file name (Pillow also searches the system font folders).
_FONT_BOLD = [
    "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "DejaVuSans-Bold.ttf",
]
_FONT_MONO = [
    "/usr/share/fonts/dejavu-sans-mono-fonts/DejaVuSansMono-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSansMono-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSansMono-Bold.ttf",
    "DejaVuSansMono-Bold.ttf",
    *_FONT_BOLD,
]
_font_warned = False


def _load_font(candidates: list[str], size: int):
    """First font that loads; the font bundled with Pillow if none does (logged once)."""
    global _font_warned
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    if not _font_warned:
        _font_warned = True
        logger.warn("[Wrapped] no DejaVu font found - cards use Pillow's built-in font. "
                    "Install fonts-dejavu-core (Debian) / ttf-dejavu (Alpine) / dejavu-sans-fonts (Fedora).")
    try:
        return ImageFont.load_default(size)
    except TypeError:          # Pillow < 10.1: only the tiny bitmap font exists
        return ImageFont.load_default()

# Colour per icon: text things in the brand colour, voice in the voice colour of the rank card.
COLOR_TEXT = _PRIMARY
COLOR_VOICE = _SUCCESS


def _mix(a: tuple, b: tuple, f: float) -> tuple:
    """a blended towards b by f (0 = a, 1 = b), opaque. Keeps every shade inside the palette."""
    return tuple(round(x + (y - x) * f) for x, y in zip(a[:3], b[:3])) + (255,)


_BAR_DIM = _mix(_PRIMARY, _BG, 0.55)     # ordinary bars; the highlighted one is _PRIMARY
_DISC = _mix(_PRIMARY, _BG, 0.78)        # background disc behind a big icon

# Lucide icons (lucide.dev).
_ICON_SVG = {
    "text": '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
    "voice": (
        '<path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/>'
        '<path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" x2="12" y1="19" y2="22"/>'
    ),
    "users": (
        '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/>'
        '<path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>'
    ),
    "trophy": (
        '<path d="M6 9H4.5a2.5 2.5 0 0 1 0-5H6"/><path d="M18 9h1.5a2.5 2.5 0 0 0 0-5H18"/>'
        '<path d="M4 22h16"/><path d="M10 14.66V17c0 .55-.47.98-.97 1.21C7.85 18.75 7 20.24 7 22"/>'
        '<path d="M14 14.66V17c0 .55.47.98.97 1.21C16.15 18.75 17 20.24 17 22"/>'
        '<path d="M18 2H6v7a6 6 0 0 0 12 0V2Z"/>'
    ),
    "star": (
        '<path d="M11.525 2.295a.53.53 0 0 1 .95 0l2.31 4.679a2.123 2.123 0 0 0 1.595 1.16l5.166.756'
        'a.53.53 0 0 1 .294.904l-3.736 3.638a2.123 2.123 0 0 0-.611 1.878l.882 5.14a.53.53 0 0 1-.771.56'
        'l-4.618-2.428a2.122 2.122 0 0 0-1.973 0L6.396 21.01a.53.53 0 0 1-.77-.56l.881-5.139'
        'a2.122 2.122 0 0 0-.611-1.879L2.16 9.795a.53.53 0 0 1 .294-.906l5.165-.755'
        'a2.122 2.122 0 0 0 1.597-1.16z"/>'
    ),
    "quote": (
        '<path d="M16 3a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2 1 1 0 0 1 1 1v1a2 2 0 0 1-2 2 1 1 0 0 0-1 1v2'
        'a1 1 0 0 0 1 1 6 6 0 0 0 6-6V5a2 2 0 0 0-2-2z"/>'
        '<path d="M5 3a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2 1 1 0 0 1 1 1v1a2 2 0 0 1-2 2 1 1 0 0 0-1 1v2'
        'a1 1 0 0 0 1 1 6 6 0 0 0 6-6V5a2 2 0 0 0-2-2z"/>'
    ),
    "vote": (
        '<path d="m9 12 2 2 4-4"/><path d="M5 7c0-1.1.9-2 2-2h10a2 2 0 0 1 2 2v12H5V7Z"/>'
        '<path d="M22 19H2"/>'
    ),
    "user_plus": (
        '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/>'
        '<line x1="19" x2="19" y1="8" y2="14"/><line x1="22" x2="16" y1="11" y2="11"/>'
    ),
}
_SVG_WRAP = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" '
    'fill="none" stroke="{stroke}" stroke-width="2" stroke-linecap="round" '
    'stroke-linejoin="round">{body}</svg>'
)


def icon_color(name: str) -> tuple:
    return COLOR_VOICE if name == "voice" else COLOR_TEXT


def _icon(name: str, size: int, color: tuple) -> Image.Image:
    svg = _SVG_WRAP.format(stroke="#%02x%02x%02x" % tuple(color[:3]), body=_ICON_SVG[name])
    png = cairosvg.svg2png(bytestring=svg.encode("utf-8"), output_width=size, output_height=size)
    return Image.open(io.BytesIO(png)).convert("RGBA")


# ── chrome / pieces ──────────────────────────────────────────────────────────

def _frame() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    s = _SS
    W, H = CANVAS[0] * s, CANVAS[1] * s
    img = Image.new("RGBA", (W, H), _BG)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((16 * s, 16 * s, W - 16 * s, H - 16 * s), radius=24 * s,
                        outline=_CARD_BORDER, width=2 * s)
    return img, d


def _finish(img: Image.Image) -> io.BytesIO:
    return _to_bytes(img.resize(CANVAS, Image.LANCZOS))


def _avatar(img: Image.Image, d: ImageDraw.ImageDraw, avatar: Image.Image | None, initial: str,
            x: int, y: int, size: int) -> None:
    """Round avatar at (x, y) in 1x units with a hairline ring; placeholder when missing."""
    s = _SS
    av = _circle_crop(avatar, size * s) if avatar is not None else _placeholder(size * s, initial or "?", circle=True)
    img.alpha_composite(av, (x * s, y * s))
    d.ellipse(((x - 4) * s, (y - 4) * s, (x + size + 4) * s, (y + size + 4) * s),
              outline=_CARD_BORDER, width=2 * s)


def _icon_disc(img: Image.Image, d: ImageDraw.ImageDraw, name: str, x: int, y: int, size: int) -> None:
    """A big icon on a soft disc, used where a spot has no avatar."""
    s = _SS
    d.ellipse((x * s, y * s, (x + size) * s, (y + size) * s), fill=_DISC)
    inner = int(size * 0.46)
    off = (size - inner) // 2
    img.alpha_composite(_icon(name, inner * s, icon_color(name)), ((x + off) * s, (y + off) * s))


def _fit_font(d: ImageDraw.ImageDraw, text: str, size: int, max_w: int):
    """Mono font at ``size`` (1x px), shrunk until ``text`` fits ``max_w`` (1x px)."""
    s = _SS
    while size > 14:
        font = _load_font(_FONT_MONO, size * s)
        bb = d.textbbox((0, 0), text, font=font)
        if (bb[2] - bb[0]) <= max_w * s:
            return font
        size -= 2
    return _load_font(_FONT_MONO, size * s)


def _figure(img: Image.Image, d: ImageDraw.ImageDraw, icon: str | None, text: str,
            x: int, y_center: int, size: int, max_w: int) -> None:
    """Icon + big figure, vertically centred on y_center (1x units)."""
    s = _SS
    tx = x
    if icon:
        isz = int(size * 0.8)
        img.alpha_composite(_icon(icon, isz * s, icon_color(icon)), (x * s, (y_center - isz // 2) * s))
        tx = x + isz + int(size * 0.3)
    font = _fit_font(d, text, size, max_w - (tx - x))
    bb = d.textbbox((0, 0), text, font=font)
    h = bb[3] - bb[1]
    d.text((tx * s, y_center * s - h / 2 - bb[1]), text, font=font, fill=_TEXT)


# ── layouts (sync, 1x coordinates scaled by _SS) ─────────────────────────────

def draw_figures(avatar: Image.Image | None, initial: str,
                 figures: list[tuple[str, str]]) -> io.BytesIO:
    """Avatar left; up to three (icon, figure) rows right."""
    img, d = _frame()
    av = 156
    ax, ay = 48, (CANVAS[1] - av) // 2
    _avatar(img, d, avatar, initial, ax, ay, av)
    left, right = ax + av + 44, CANVAS[0] - 44
    rows = figures[:3]
    row_h = 74 if len(rows) == 3 else 90
    top = (CANVAS[1] - row_h * len(rows)) // 2
    size = 44 if len(rows) == 3 else 52
    for i, (icon, text) in enumerate(rows):
        _figure(img, d, icon, text, left, top + row_h * i + row_h // 2, size, right - left)
    return _finish(img)


def draw_bars(values: list[int], highlight: int | None, labels: list[str | None]) -> io.BytesIO:
    """Plain bars with a 4px corner; the highlighted bar in the brand colour, the rest dimmed."""
    s = _SS
    img, d = _frame()
    x0, x1 = 48, CANVAS[0] - 48
    y0, y1 = 52, CANVAS[1] - 72          # bar area; tick labels below
    n = max(len(values), 1)
    top = max(values) if values and max(values) > 0 else 1
    slot = (x1 - x0) / n
    bar_w = max(4.0, min(slot * 0.62, 40.0))
    font = _load_font(_FONT_MONO, 14 * s)
    d.line((x0 * s, (y1 + 1) * s, x1 * s, (y1 + 1) * s), fill=_LINE, width=s)
    for i, v in enumerate(values):
        cx = x0 + slot * (i + 0.5)
        bx0, bx1 = cx - bar_w / 2, cx + bar_w / 2
        if v > 0:
            h = max(6.0, (y1 - y0) * v / top)
            color = _PRIMARY if i == highlight else _BAR_DIM
            d.rounded_rectangle((int(bx0 * s), int((y1 - h) * s), int(bx1 * s), y1 * s),
                                radius=4 * s, fill=color)
        if i < len(labels) and labels[i]:
            lab = str(labels[i])
            tw = d.textlength(lab, font=font)
            d.text((cx * s - tw / 2, (y1 + 14) * s), lab, font=font,
                   fill=_TEXT if i == highlight else _MUTED)
    return _finish(img)


def draw_podium(rows: list[tuple[str, list[tuple[Image.Image | None, str]]]]) -> io.BytesIO:
    """One or two rows: icon, then up to three avatars with a rank badge (1, 2, 3)."""
    s = _SS
    img, d = _frame()
    rows = rows[:2]
    av = 92 if len(rows) == 2 else 132
    centers = [CANVAS[1] // 2] if len(rows) == 1 else [100, 220]
    badge = 30 if len(rows) == 2 else 36
    badge_font = _load_font(_FONT_MONO, (16 if len(rows) == 2 else 19) * s)
    spacing = (CANVAS[0] - 150 - 48 - av) // 2
    for (icon, people), cy in zip(rows, centers):
        isz = 40
        img.alpha_composite(_icon(icon, isz * s, icon_color(icon)), (56 * s, (cy - isz // 2) * s))
        for rank, (avatar, initial) in enumerate(people[:3], 1):
            x = 150 + (rank - 1) * spacing
            y = cy - av // 2
            _avatar(img, d, avatar, initial, x, y, av)
            bx, by = x + av - badge + 6, y + av - badge + 6
            d.ellipse((bx * s, by * s, (bx + badge) * s, (by + badge) * s),
                      fill=_PRIMARY if rank == 1 else _LINE, outline=_BG, width=3 * s)
            lab = str(rank)
            bb = d.textbbox((0, 0), lab, font=badge_font)
            d.text(((bx + badge / 2) * s - (bb[2] - bb[0]) / 2 - bb[0],
                    (by + badge / 2) * s - (bb[3] - bb[1]) / 2 - bb[1]), lab, font=badge_font, fill=_TEXT)
    return _finish(img)


def draw_spotlight(spots: list[tuple[Image.Image | None, str | None, str, str]]) -> io.BytesIO:
    """spots: (avatar, initial, icon, figure). initial None = no person: a big icon disc instead
    of an avatar, and the figure stands alone."""
    img, d = _frame()
    spots = spots[:2]
    if len(spots) == 1:
        avatar, initial, icon, text = spots[0]
        av = 156
        ax, ay = 48, (CANVAS[1] - av) // 2
        if initial is None:
            _icon_disc(img, d, icon, ax, ay, av)
        else:
            _avatar(img, d, avatar, initial, ax, ay, av)
        left = ax + av + 44
        _figure(img, d, None if initial is None else icon, text, left, CANVAS[1] // 2, 64,
                CANVAS[0] - 44 - left)
        return _finish(img)

    half = (CANVAS[0] - 32) // 2
    av = 112
    for i, (avatar, initial, icon, text) in enumerate(spots):
        x0 = 16 + half * i
        ax = x0 + 32
        ay = (CANVAS[1] - av) // 2
        if initial is None:
            _icon_disc(img, d, icon, ax, ay, av)
        else:
            _avatar(img, d, avatar, initial, ax, ay, av)
        left = ax + av + 22
        _figure(img, d, None if initial is None else icon, text, left, CANVAS[1] // 2, 40,
                x0 + half - 20 - left)
    s = _SS
    mid = 16 + half
    d.line((mid * s, 64 * s, mid * s, (CANVAS[1] - 64) * s), fill=_LINE, width=s)
    return _finish(img)


# ── async entry points (fetch avatars, render off the loop) ──────────────────

async def _fetch_all(urls: list[str | None]) -> list[Image.Image | None]:
    async def one(url: str | None):
        return await _fetch_image(url) if url else None
    return list(await asyncio.gather(*(one(u) for u in urls)))


async def figures_card(avatar_url: str | None, initial: str, figures: list[tuple[str, str]]) -> io.BytesIO:
    (avatar,) = await _fetch_all([avatar_url])
    return await asyncio.to_thread(draw_figures, avatar, initial, figures)


async def bars_card(values: list[int], highlight: int | None, labels: list[str | None]) -> io.BytesIO:
    return await asyncio.to_thread(draw_bars, values, highlight, labels)


async def podium_card(rows: list[tuple[str, list[tuple[str | None, str]]]]) -> io.BytesIO:
    """rows: (icon, [(avatar_url, initial), ...])."""
    urls = [u for _, people in rows for u, _ in people[:3]]
    images = iter(await _fetch_all(urls))
    resolved = [(icon, [(next(images), initial) for _, initial in people[:3]]) for icon, people in rows]
    return await asyncio.to_thread(draw_podium, resolved)


async def spotlight_card(spots: list[tuple[str | None, str | None, str, str]]) -> io.BytesIO:
    """spots: (avatar_url, initial, icon, figure); initial None = no person (icon disc)."""
    images = await _fetch_all([u for u, _, _, _ in spots])
    resolved = [(img, initial, icon, text) for img, (_, initial, icon, text) in zip(images, spots)]
    return await asyncio.to_thread(draw_spotlight, resolved)
