"""Pillow renderers for Baxi Pulse cards.

Graphics only (heatmap, bars, axis ticks). Titles, numbers and explanations live in the
surrounding Discord embed; the only text drawn here are axis labels, which the caller passes
in already localised.
"""
from __future__ import annotations

import io

from PIL import Image, ImageDraw

from assets.mc_link_card import (
    _BG, _CARD_BORDER, _LINE, _MUTED, _PRIMARY, _SUCCESS, _TEXT,
    _load_font,
)

CANVAS = (960, 560)
_USER_CANVAS = (960, 360)
_PAD = 44

# Heatmap ramp: empty cell -> brand blue -> bright highlight.
_RAMP = [(0.0, (38, 38, 44)), (0.55, _PRIMARY[:3]), (1.0, (205, 217, 240))]

_FONT_CANDIDATES = [
    "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def _ramp(x: float) -> tuple[int, int, int]:
    x = max(0.0, min(1.0, x))
    for (x0, c0), (x1, c1) in zip(_RAMP, _RAMP[1:]):
        if x <= x1:
            f = (x - x0) / (x1 - x0)
            return tuple(round(a + (b - a) * f) for a, b in zip(c0, c1))  # type: ignore[return-value]
    return _RAMP[-1][1]


def _frame(size: tuple[int, int]) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGBA", size, _BG)
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((16, 16, size[0] - 16, size[1] - 16), radius=24, outline=_CARD_BORDER, width=2)
    return img, draw


def _bars(draw: ImageDraw.ImageDraw, values: list[int], box: tuple[int, int, int, int],
          *, highlight_last: bool = False, labels: list[str] | None = None) -> None:
    """Rounded bar chart inside ``box`` = (x0, y0, x1, y1). Optional label under each bar."""
    x0, y0, x1, y1 = box
    n = max(len(values), 1)
    label_h = 22 if labels else 0
    top = max(values) if values and max(values) > 0 else 1
    slot = (x1 - x0) / n
    bar_w = max(4, min(int(slot * 0.62), 56))
    font = _load_font(_FONT_CANDIDATES, 15)
    for i, v in enumerate(values):
        h = max(4, int((y1 - y0 - label_h) * v / top)) if v > 0 else 4
        cx = x0 + slot * (i + 0.5)
        bx0, bx1 = int(cx - bar_w / 2), int(cx + bar_w / 2)
        by1 = y1 - label_h
        if v == 0:
            colour = _LINE
        elif highlight_last and i == n - 1:
            colour = _SUCCESS[:3]
        else:
            colour = _ramp(0.55 + 0.45 * v / top)
        draw.rounded_rectangle((bx0, by1 - h, bx1, by1), radius=min(5, bar_w // 2), fill=colour)
        if labels:
            tw = draw.textlength(labels[i], font=font)
            draw.text((cx - tw / 2, y1 - label_h + 5), labels[i], font=font, fill=_MUTED)


def render_heatmap_card(grid: list[list[int]], daily: list[int], peak: tuple[int, int] | None,
                        weekday_labels: list[str]) -> io.BytesIO:
    """Weekday x hour heatmap with the best slot ringed, plus a daily-volume strip below."""
    img, draw = _frame(CANVAS)
    label_font = _load_font(_FONT_CANDIDATES, 17)

    left = _PAD + 54
    right = CANVAS[0] - _PAD
    top = _PAD + 4
    gap = 4
    cell_w = (right - left - gap * 23) / 24
    cell_h = 30

    vmax = max((v for row in grid for v in row), default=0) or 1
    for wd in range(7):
        y = top + wd * (cell_h + gap)
        draw.text((_PAD, y + cell_h / 2 - 9), weekday_labels[wd], font=label_font, fill=_MUTED)
        for h in range(24):
            x = left + h * (cell_w + gap)
            # sqrt keeps quiet-but-real hours visible next to one huge peak
            colour = _ramp((grid[wd][h] / vmax) ** 0.5) if grid[wd][h] else _RAMP[0][1]
            draw.rounded_rectangle((x, y, x + cell_w, y + cell_h), radius=6, fill=colour)

    if peak is not None:
        wd, h = peak
        x = left + h * (cell_w + gap)
        y = top + wd * (cell_h + gap)
        draw.rounded_rectangle((x - 3, y - 3, x + cell_w + 3, y + cell_h + 3), radius=8, outline=_TEXT, width=3)

    axis_y = top + 7 * (cell_h + gap) + 2
    for h in range(0, 24, 3):
        x = left + h * (cell_w + gap)
        draw.text((x, axis_y), f"{h:02d}", font=label_font, fill=_MUTED)

    strip_top = axis_y + 44
    draw.line((_PAD, strip_top - 16, CANVAS[0] - _PAD, strip_top - 16), fill=_LINE, width=1)
    _bars(draw, daily, (_PAD, strip_top, CANVAS[0] - _PAD, CANVAS[1] - _PAD), highlight_last=True)

    return _to_png(img)


def render_user_card(daily: list[int], weekday_totals: list[int], weekday_labels: list[str]) -> io.BytesIO:
    """Daily bars on the left (last N days), weekday profile on the right."""
    img, draw = _frame(_USER_CANVAS)
    h = _USER_CANVAS[1]
    split = int(_USER_CANVAS[0] * 0.62)
    _bars(draw, daily, (_PAD, _PAD + 10, split - 20, h - _PAD), highlight_last=True)
    draw.line((split, _PAD + 10, split, h - _PAD), fill=_LINE, width=1)
    _bars(draw, weekday_totals, (split + 24, _PAD + 10, _USER_CANVAS[0] - _PAD, h - _PAD), labels=weekday_labels)
    return _to_png(img)


def _to_png(img: Image.Image) -> io.BytesIO:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf
