"""Advancement icons for the DiscordGate event bridge.

`index.json` maps the vanilla advancement description (lower case) to a PNG in
this folder. The plugin sends title + description in the event text, so the
description is what we match on.
"""
import io
import json
import os
import re

_DIR = os.path.dirname(__file__)
_index: dict[str, str] | None = None


def _load() -> dict[str, str]:
    global _index
    if _index is None:
        try:
            with open(os.path.join(_DIR, "index.json"), encoding="utf-8") as f:
                _index = json.load(f)
        except (OSError, ValueError):
            _index = {}
    return _index


def find_icon(text: str) -> str | None:
    """Path of the icon whose advancement description occurs in `text`, else None."""
    flat = re.sub(r"[*_`]", "", text).lower()
    best = None
    for desc, rel in _load().items():
        if desc in flat and (best is None or len(desc) > len(best[0])):
            best = (desc, rel)
    if best is None:
        return None
    path = os.path.join(_DIR, best[1])
    return path if os.path.isfile(path) else None


def render_icon(path: str, scale: int = 5) -> io.BytesIO:
    """Pixel-art upscale (nearest neighbour) so Discord shows it large and crisp."""
    from PIL import Image
    with Image.open(path) as im:
        big = im.convert("RGBA").resize((im.width * scale, im.height * scale), Image.NEAREST)
    buf = io.BytesIO()
    big.save(buf, "PNG")
    buf.seek(0)
    return buf
