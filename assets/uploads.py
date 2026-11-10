"""Image uploads for the web tools (/embed editor, admin news): checked, re-named, served by
the existing ``/attachments/<name>`` route so Discord can fetch them."""
from __future__ import annotations

import io
import os
import secrets

from PIL import Image

import config.config as config

MAX_BYTES = 8 * 1024 * 1024
_EXT = {"PNG": "png", "JPEG": "jpg", "GIF": "gif", "WEBP": "webp"}
DIR = "attachments"


class UploadError(ValueError):
    pass


def save_image(data: bytes) -> str:
    """Validate the bytes as a PNG/JPEG/GIF/WebP image, store them under a random name and
    return the public URL. The extension comes from the detected format, never from the client."""
    if not data:
        raise UploadError("No file received.")
    if len(data) > MAX_BYTES:
        raise UploadError("The image is larger than 8 MB.")
    try:
        with Image.open(io.BytesIO(data)) as im:
            fmt = im.format
            if fmt not in _EXT:
                raise UploadError("Only PNG, JPG, GIF and WebP images are allowed.")
            if im.width * im.height > 40_000_000:
                raise UploadError("The image is too large (pixels).")
            im.verify()
    except UploadError:
        raise
    except Exception:
        raise UploadError("That file is not a valid image.")
    os.makedirs(DIR, exist_ok=True)
    name = f"up_{secrets.token_urlsafe(12)}.{_EXT[fmt]}"
    with open(os.path.join(DIR, name), "wb") as f:
        f.write(data)
    return f"https://{config.Web.url}/attachments/{name}"
