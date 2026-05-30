"""Pillow renderer for /mc link card images.

Image only contains: discord avatar, link icon, mc head, connector line, names.
All title/subtitle text lives in the surrounding Discord embed.
"""
from __future__ import annotations

import io
import asyncio
from typing import Literal

import aiohttp
import cairosvg
from PIL import Image, ImageDraw, ImageFont

from reds_simple_logger import Logger

logger = Logger()

_FONT_CANDIDATES_BOLD = [
    "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]

# Palette
_BG          = (24, 24, 27, 255)        # #18181b
_CARD_BORDER = (60, 60, 65, 255)
_TEXT        = (235, 235, 240, 255)
_MUTED       = (165, 165, 170, 255)
_PRIMARY     = (111, 131, 170, 255)     # #6F83AA
_SUCCESS     = (34, 197, 94, 255)
_DANGER      = (239, 68, 68, 255)
_LINE        = (75, 75, 80, 255)

_LINK_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" '
    'fill="none" stroke="{stroke}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/>'
    '<path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>'
    '</svg>'
)

CONFIRM_CANVAS = (640, 320)
STATE_CANVAS = (640, 320)


def _load_font(candidates: list[str], size: int):
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


async def _fetch_image(url: str, timeout: float = 6.0) -> Image.Image | None:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                if resp.status != 200:
                    return None
                data = await resp.read()
        return Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception as e:
        logger.error(f"[mc_link_card] image fetch failed for {url}: {e}")
        return None


def _placeholder(size: int, label: str, *, circle: bool) -> Image.Image:
    img = Image.new("RGBA", (size, size), (*_PRIMARY[:3], 60))
    d = ImageDraw.Draw(img)
    font = _load_font(_FONT_CANDIDATES_BOLD, size // 4)
    bbox = d.textbbox((0, 0), label, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    d.text(((size - tw) / 2, (size - th) / 2 - bbox[1]), label, font=font, fill=_TEXT)
    if circle:
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
        out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        out.paste(img, (0, 0), mask)
        return out
    return img


def _circle_crop(img: Image.Image, size: int) -> Image.Image:
    img = img.resize((size, size), Image.LANCZOS).convert("RGBA")
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def _round_crop(img: Image.Image, size: int, radius: int) -> Image.Image:
    img = img.resize((size, size), Image.NEAREST).convert("RGBA")
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size, size), radius=radius, fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def _rounded_rect(draw: ImageDraw.ImageDraw, xy, radius: int, fill=None, outline=None, width: int = 1):
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def _draw_card_chrome(canvas: tuple[int, int], draw: ImageDraw.ImageDraw):
    _rounded_rect(draw, (16, 16, canvas[0] - 16, canvas[1] - 16),
                  radius=24, outline=_CARD_BORDER, width=2)


def _render_link_icon(size: int, color: tuple[int, int, int]) -> Image.Image:
    hex_color = "#%02x%02x%02x" % color
    svg = _LINK_SVG.format(stroke=hex_color)
    png_bytes = cairosvg.svg2png(
        bytestring=svg.encode("utf-8"),
        output_width=size, output_height=size,
    )
    return Image.open(io.BytesIO(png_bytes)).convert("RGBA")


def _draw_link_chain(img: Image.Image, center: tuple[int, int], color=_PRIMARY):
    cx, cy = center
    disc_r = 30
    disc = Image.new("RGBA", (disc_r * 2 + 4, disc_r * 2 + 4), (0, 0, 0, 0))
    dd = ImageDraw.Draw(disc)
    dd.ellipse((2, 2, disc_r * 2 + 2, disc_r * 2 + 2),
               fill=(color[0], color[1], color[2], 50),
               outline=(color[0], color[1], color[2], 130), width=1)
    img.alpha_composite(disc, (cx - disc_r - 2, cy - disc_r - 2))

    icon_size = 32
    icon = _render_link_icon(icon_size, color[:3])
    img.alpha_composite(icon, (cx - icon_size // 2, cy - icon_size // 2))


def _draw_label(draw: ImageDraw.ImageDraw, text: str, x_center: int, y: int):
    font = _load_font(_FONT_CANDIDATES_BOLD, 14)
    text = text.upper()
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    draw.text((x_center - tw / 2, y), text, font=font, fill=_MUTED)


def _draw_name(draw: ImageDraw.ImageDraw, text: str, x_center: int, y: int, *, max_width: int = 220):
    font = _load_font(_FONT_CANDIDATES_BOLD, 26)
    bbox = draw.textbbox((0, 0), text, font=font)
    if bbox[2] - bbox[0] > max_width:
        while text and draw.textbbox((0, 0), text + "…", font=font)[2] - draw.textbbox((0, 0), text + "…", font=font)[0] > max_width:
            text = text[:-1]
        text = text + "…"
        bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    draw.text((x_center - tw / 2, y), text, font=font, fill=_TEXT)


def _to_bytes(img: Image.Image) -> io.BytesIO:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf


async def render_confirm(
    *,
    discord_name: str,
    discord_avatar_url: str,
    mc_name: str,
    mc_uuid: str,
) -> io.BytesIO:
    canvas = CONFIRM_CANVAS
    img = Image.new("RGBA", canvas, _BG)
    draw = ImageDraw.Draw(img)
    _draw_card_chrome(canvas, draw)

    avatar_size = 130
    avatars_top = 50
    left_cx = 180
    right_cx = canvas[0] - 180

    # connector line behind avatars (drawn first so it sits below)
    line_y = avatars_top + avatar_size // 2
    draw.line(
        (left_cx + avatar_size // 2 + 6, line_y,
         right_cx - avatar_size // 2 - 6, line_y),
        fill=_LINE, width=2,
    )

    # Discord avatar (circle)
    discord_img = await _fetch_image(discord_avatar_url)
    if discord_img is None:
        discord_img = _placeholder(avatar_size, "?", circle=True)
    else:
        discord_img = _circle_crop(discord_img, avatar_size)
    img.alpha_composite(discord_img, (left_cx - avatar_size // 2, avatars_top))

    # MC head (rounded square, pixelated)
    mc_url = f"https://mc-heads.net/avatar/{mc_uuid}/128"
    mc_img = await _fetch_image(mc_url)
    if mc_img is None:
        mc_img = _placeholder(avatar_size, "MC", circle=False)
    else:
        mc_img = _round_crop(mc_img, avatar_size, radius=16)
    img.alpha_composite(mc_img, (right_cx - avatar_size // 2, avatars_top))

    # link icon center
    _draw_link_chain(img, (canvas[0] // 2, avatars_top + avatar_size // 2))

    # labels + names below
    label_y = avatars_top + avatar_size + 18
    _draw_label(draw, "Discord", left_cx, label_y)
    _draw_label(draw, "Minecraft", right_cx, label_y)

    name_y = label_y + 24
    _draw_name(draw, discord_name, left_cx, name_y, max_width=240)
    _draw_name(draw, mc_name, right_cx, name_y, max_width=240)

    return _to_bytes(img)


def _render_state(kind: Literal["success", "cancel"]) -> Image.Image:
    canvas = STATE_CANVAS
    img = Image.new("RGBA", canvas, _BG)
    draw = ImageDraw.Draw(img)
    _draw_card_chrome(canvas, draw)

    color = _SUCCESS if kind == "success" else _MUTED
    soft_alpha = 60
    soft = (color[0], color[1], color[2], soft_alpha)

    cx, cy = canvas[0] // 2, canvas[1] // 2
    r = 70

    # soft disc — draw at 4× supersample for smooth edges
    ss = 4
    disc_big = Image.new("RGBA", (r * 2 * ss, r * 2 * ss), (0, 0, 0, 0))
    dd = ImageDraw.Draw(disc_big)
    dd.ellipse((0, 0, r * 2 * ss - 1, r * 2 * ss - 1), fill=soft)
    disc = disc_big.resize((r * 2, r * 2), Image.LANCZOS)
    img.alpha_composite(disc, (cx - r, cy - r))

    # icon — supersampled lines
    icon_big_size = r * 2 * ss
    icon_layer = Image.new("RGBA", (icon_big_size, icon_big_size), (0, 0, 0, 0))
    idraw = ImageDraw.Draw(icon_layer)
    stroke_w = 10 * ss
    if kind == "success":
        # checkmark — three points
        p1 = (icon_big_size * 0.30, icon_big_size * 0.52)
        p2 = (icon_big_size * 0.46, icon_big_size * 0.66)
        p3 = (icon_big_size * 0.72, icon_big_size * 0.38)
        idraw.line([p1, p2, p3], fill=color, width=stroke_w, joint="curve")
        # round end caps via small circles
        for p in (p1, p2, p3):
            rr = stroke_w // 2
            idraw.ellipse((p[0] - rr, p[1] - rr, p[0] + rr, p[1] + rr), fill=color)
    else:
        # X — exact diagonals across center
        m = icon_big_size * 0.30
        n = icon_big_size * 0.70
        idraw.line([(m, m), (n, n)], fill=color, width=stroke_w)
        idraw.line([(m, n), (n, m)], fill=color, width=stroke_w)
        for p in ((m, m), (n, n), (m, n), (n, m)):
            rr = stroke_w // 2
            idraw.ellipse((p[0] - rr, p[1] - rr, p[0] + rr, p[1] + rr), fill=color)
    icon_small = icon_layer.resize((r * 2, r * 2), Image.LANCZOS)
    img.alpha_composite(icon_small, (cx - r, cy - r))

    return img


async def render_success() -> io.BytesIO:
    return _to_bytes(_render_state("success"))


async def render_cancel() -> io.BytesIO:
    return _to_bytes(_render_state("cancel"))
