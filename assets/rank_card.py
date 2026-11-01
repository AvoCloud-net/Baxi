"""Pillow renderer for the /rank card.

Graphics only: avatar, level number, progress bar to the next level and the text / voice
split (Lucide icons + figures). Every word (name, labels, rank, explanation) lives in the
surrounding Discord embed (assets/leveling.rank_payload).

The whole card is drawn at 4x and downsampled with LANCZOS, so bars, circles and the
avatar edge come out smooth.
"""
from __future__ import annotations

import asyncio
import io

import cairosvg
from PIL import Image, ImageDraw

from assets.mc_link_card import (
    _BG, _CARD_BORDER, _LINE, _MUTED, _PRIMARY, _SUCCESS, _TEXT,
    _circle_crop, _fetch_image, _load_font, _placeholder, _to_bytes,
)

CANVAS = (640, 320)
_SS = 4

_TEXT_COLOR = _PRIMARY    # text XP
_VOICE_COLOR = _SUCCESS   # voice XP
_LEVEL_COLOR = _MUTED     # progress bar + level icon: neutral, so it doesn't read as "text"

# (level figure, XP figure) font sizes, largest first; the first pair that fits is used.
_LEVEL_SIZES = ((64, 20), (56, 20), (48, 18), (44, 16), (38, 15), (32, 14))

_FONT_BOLD = [
    "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]
_FONT_MONO = [
    "/usr/share/fonts/dejavu-sans-mono-fonts/DejaVuSansMono-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    *_FONT_BOLD,
]

# Lucide icons (lucide.dev): message-square, mic, chevrons-up.
_ICON_SVG = {
    "text": '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
    "voice": (
        '<path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/>'
        '<path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" x2="12" y1="19" y2="22"/>'
    ),
    "level": '<path d="m17 11-5-5-5 5"/><path d="m17 18-5-5-5 5"/>',
}
_SVG_WRAP = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" '
    'fill="none" stroke="{stroke}" stroke-width="2" stroke-linecap="round" '
    'stroke-linejoin="round">{body}</svg>'
)


def _icon(name: str, size: int, color: tuple) -> Image.Image:
    svg = _SVG_WRAP.format(stroke="#%02x%02x%02x" % tuple(color[:3]), body=_ICON_SVG[name])
    png = cairosvg.svg2png(bytestring=svg.encode("utf-8"), output_width=size, output_height=size)
    return Image.open(io.BytesIO(png)).convert("RGBA")


def _bar(img: Image.Image, box: tuple[int, int, int, int],
         segments: list[tuple[float, tuple]]) -> None:
    """Pill-shaped bar: grey track, then the coloured segments (fractions of the width).

    The segments are flat rectangles side by side, clipped by one pill mask over the filled
    extent, so the bar keeps round ends and the joins stay flush.
    """
    x0, y0, x1, y1 = box
    h = y1 - y0
    ImageDraw.Draw(img).rounded_rectangle(box, radius=h // 2, fill=_LINE)
    shown = [(max(0.0, f), c) for f, c in segments if f > 0]
    total = sum(f for f, _ in shown)
    if total <= 0:
        return
    scale = 1.0 / total if total > 1 else 1.0
    width = x1 - x0
    end = x0 + max(h, int(width * total * scale))   # tiny fill: a dot, not a sliver

    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    x = float(x0)
    for i, (f, color) in enumerate(shown):
        seg_end = end if i == len(shown) - 1 else x + width * f * scale
        ld.rectangle((int(x), y0, int(seg_end), y1), fill=color)
        x = seg_end
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((x0, y0, end, y1), radius=h // 2, fill=255)
    img.paste(layer, (0, 0), mask)


def _draw(avatar: Image.Image | None, level: int, xp_into: int, xp_needed: int,
          text_xp: int, voice_xp: int) -> Image.Image:
    s = _SS
    W, H = CANVAS[0] * s, CANVAS[1] * s
    img = Image.new("RGBA", (W, H), _BG)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((16 * s, 16 * s, W - 16 * s, H - 16 * s), radius=24 * s,
                        outline=_CARD_BORDER, width=2 * s)

    # Avatar (left, vertically centred) with a hairline ring.
    av = 156
    ax, ay = 48, (CANVAS[1] - av) // 2
    if avatar is None:
        av_img = _placeholder(av * s, "?", circle=True)
    else:
        av_img = _circle_crop(avatar, av * s)
    img.alpha_composite(av_img, (ax * s, ay * s))
    d.ellipse(((ax - 4) * s, (ay - 4) * s, (ax + av + 4) * s, (ay + av + 4) * s),
              outline=_CARD_BORDER, width=2 * s)

    left = ax + av + 40          # right column
    right = CANVAS[0] - 48

    # Level: chevrons icon + big figure, XP into the level right-aligned on the same baseline.
    # Measured, so long figures (level 1000, six-digit XP) shrink instead of overlapping.
    lvl_txt = str(level)
    xp_txt = f"{xp_into:,} / {xp_needed:,}"
    lvl_x = left + 50
    for big_px, small_px in _LEVEL_SIZES:
        big = _load_font(_FONT_MONO, big_px * s)
        small = _load_font(_FONT_MONO, small_px * s)
        lvl_w = d.textlength(lvl_txt, font=big) / s
        xp_w = d.textlength(xp_txt, font=small) / s
        if lvl_x + lvl_w + 16 <= right - xp_w:
            break
    baseline = 118
    icon_px = 40
    icon_cy = baseline - big_px * 0.36          # middle of the digits
    img.alpha_composite(_icon("level", icon_px * s, _LEVEL_COLOR),
                        (left * s, int((icon_cy - icon_px / 2) * s)))
    d.text((lvl_x * s, baseline * s), lvl_txt, font=big, fill=_TEXT, anchor="ls")
    d.text((right * s, baseline * s), xp_txt, font=small, fill=_MUTED, anchor="rs")

    # Progress to the next level.
    frac = (xp_into / xp_needed) if xp_needed else 1.0
    _bar(img, (left * s, 150 * s, right * s, 172 * s), [(frac, _LEVEL_COLOR)])

    # Text / voice split of the total XP.
    total = text_xp + voice_xp
    if total > 0:
        _bar(img, (left * s, 204 * s, right * s, 214 * s),
             [(text_xp / total, _TEXT_COLOR), (voice_xp / total, _VOICE_COLOR)])
    else:
        _bar(img, (left * s, 204 * s, right * s, 214 * s), [])

    fig = _load_font(_FONT_MONO, 18 * s)
    ly = 232
    x = left
    for name, value, color in (("text", text_xp, _TEXT_COLOR), ("voice", voice_xp, _VOICE_COLOR)):
        img.alpha_composite(_icon(name, 22 * s, color), (x * s, ly * s))
        label = f"{value:,}"
        d.text(((x + 30) * s, (ly + 1) * s), label, font=fig, fill=_TEXT)
        lb = d.textbbox((0, 0), label, font=fig)
        x += 30 + (lb[2] - lb[0]) // s + 32

    return img.resize(CANVAS, Image.LANCZOS)


async def render_rank(*, avatar_url: str, level: int, xp_into: int, xp_needed: int,
                      text_xp: int, voice_xp: int) -> io.BytesIO:
    """Render the rank card. The avatar falls back to a placeholder if the CDN fails."""
    avatar = await _fetch_image(avatar_url) if avatar_url else None
    img = await asyncio.to_thread(_draw, avatar, int(level), int(xp_into), int(xp_needed),
                                  int(text_xp), int(voice_xp))
    return _to_bytes(img)
