import asyncio
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

import yt_dlp


RADIO_PRESETS: dict[str, tuple[str, str]] = {
    "oe3":      ("Hitradio Ö3", "https://orf-live.ors-shoutcast.at/oe3-q2a?player=radiothek_v1&referer=oe3.orf.at&userid=a2df900b-1c5d-4696-bdf7-a6d105c5c118&_ic2=1777325916315"),
    "kronehit": ("KroneHit",    "http://onair.krone.at/kronehit.mp3"),
    "fm4":      ("FM4",         "https://orf-live.ors.at/out/u/fm4/qsb/aac.m3u8"),
}


@dataclass
class ExtractedTrack:
    title: str
    stream_url: str
    webpage_url: str
    duration: int
    thumbnail: Optional[str]
    source_type: str   # "youtube" | "soundcloud"


_YDL_OPTS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "default_search": "ytsearch1",
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "extract_flat": False,
    "source_address": "0.0.0.0",
}


def _ydl_extract(query: str) -> dict:
    with yt_dlp.YoutubeDL(_YDL_OPTS) as ydl:
        info = ydl.extract_info(query, download=False)
        if "entries" in info:
            entries = [e for e in info["entries"] if e]
            if not entries:
                raise RuntimeError("no_results")
            info = entries[0]
        return info


async def extract_track(query: str) -> ExtractedTrack:
    """Resolve a YouTube/SoundCloud URL or search term to a streamable track."""
    info = await asyncio.to_thread(_ydl_extract, query)

    url = info.get("url")
    if not url:
        for fmt in info.get("formats", []) or []:
            if fmt.get("acodec") and fmt.get("acodec") != "none":
                url = fmt.get("url")
                if url:
                    break
    if not url:
        raise RuntimeError("no_stream_url")

    extractor = (info.get("extractor") or "").lower()
    if "soundcloud" in extractor:
        source_type = "soundcloud"
    elif "youtube" in extractor:
        source_type = "youtube"
    else:
        source_type = "youtube"

    return ExtractedTrack(
        title=info.get("title", "Unknown"),
        stream_url=url,
        webpage_url=info.get("webpage_url", info.get("original_url", query)),
        duration=int(info.get("duration") or 0),
        thumbnail=info.get("thumbnail"),
        source_type=source_type,
    )


def is_safe_radio_url(url: str) -> bool:
    """Reject obviously-broken URLs. Real check: scheme http(s) + non-empty host."""
    try:
        p = urlparse(url)
        return p.scheme in ("http", "https") and bool(p.netloc)
    except Exception:
        return False
