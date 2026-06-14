"""
assets/repo/social.py — social platform mappers (twitter, youtube_videos, tiktok, instagram)
and livestream.
"""
from __future__ import annotations

import json

import assets.db as db
import config.config as config

_DD = config.datasys.default_data

_SOCIAL_PLATFORMS = ("twitter", "youtube_videos", "tiktok", "instagram")
_PROMOTED = ["channel_id", "username", "display_name", "profile_image_url", "alert_channel"]


# ── Social (shared loader/saver pattern) ──────────────────────────────────────

def load_social(gid: int, platform: str) -> dict:
    default = dict(_DD[platform])
    hdr = db.query(
        "SELECT * FROM cfg_social WHERE guild_id=? AND platform=?", (gid, platform)
    )
    if not hdr:
        return default
    h = hdr[0]
    rows = db.query(
        "SELECT * FROM cfg_social_channel WHERE guild_id=? AND platform=? ORDER BY pos",
        (gid, platform),
    )
    channels = []
    for r in rows:
        extra = json.loads(r["extra_json"] or "{}")
        ch: dict = {}
        for k in _PROMOTED:
            if r[k] is not None:
                ch[k] = r[k]
        ch.update(extra)
        channels.append(ch)
    return {
        "enabled":       bool(h["enabled"]),
        "alert_channel": str(h["alert_channel"] or ""),
        "ping_role":     str(h["ping_role"] or ""),
        "channels":      channels,
    }


def save_social(gid: int, platform: str, data: dict) -> None:
    db.ensure_guild(gid)
    with db.transaction() as cx:
        cx.execute(
            "INSERT INTO cfg_social (guild_id,platform,enabled,alert_channel,ping_role) "
            "VALUES (?,?,?,?,?) "
            "ON CONFLICT(guild_id,platform) DO UPDATE SET "
            "enabled=excluded.enabled,alert_channel=excluded.alert_channel,"
            "ping_role=excluded.ping_role",
            (
                gid, platform,
                int(bool(data.get("enabled", False))),
                str(data.get("alert_channel", "")),
                str(data.get("ping_role", "")),
            ),
        )
        cx.execute(
            "DELETE FROM cfg_social_channel WHERE guild_id=? AND platform=?", (gid, platform)
        )
        for pos, ch in enumerate(data.get("channels", [])):
            promoted_vals = {k: ch.get(k) for k in _PROMOTED}
            extra = {k: v for k, v in ch.items() if k not in _PROMOTED}
            cx.execute(
                "INSERT INTO cfg_social_channel "
                "(guild_id,platform,pos,channel_id,username,display_name,"
                "profile_image_url,alert_channel,extra_json) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    gid, platform, pos,
                    promoted_vals.get("channel_id"),
                    promoted_vals.get("username"),
                    promoted_vals.get("display_name"),
                    promoted_vals.get("profile_image_url"),
                    promoted_vals.get("alert_channel"),
                    json.dumps(extra),
                ),
            )


# Per-platform convenience shims (called from REGISTRY)

def load_twitter(gid: int) -> dict:
    return load_social(gid, "twitter")

def save_twitter(gid: int, data: dict) -> None:
    save_social(gid, "twitter", data)

def load_youtube_videos(gid: int) -> dict:
    return load_social(gid, "youtube_videos")

def save_youtube_videos(gid: int, data: dict) -> None:
    save_social(gid, "youtube_videos", data)

def load_tiktok(gid: int) -> dict:
    return load_social(gid, "tiktok")

def save_tiktok(gid: int, data: dict) -> None:
    save_social(gid, "tiktok", data)

def load_instagram(gid: int) -> dict:
    return load_social(gid, "instagram")

def save_instagram(gid: int, data: dict) -> None:
    save_social(gid, "instagram", data)


# ── Livestream ────────────────────────────────────────────────────────────────

_LS_DEF = _DD["livestream"]
_LS_PROMOTED = [
    "platform", "login", "display_name", "channel_id", "message_id", "profile_image_url",
]


def load_livestream(gid: int) -> dict:
    rows = db.query("SELECT * FROM cfg_livestream WHERE guild_id=?", (gid,))
    if not rows:
        return dict(_LS_DEF)
    r = rows[0]
    sr = db.query(
        "SELECT * FROM cfg_livestream_streamer WHERE guild_id=? ORDER BY pos", (gid,)
    )
    streamers = []
    for s in sr:
        extra = json.loads(s["extra_json"] or "{}")
        streamer: dict = {}
        for k in _LS_PROMOTED:
            if s[k] is not None:
                streamer[k] = s[k]
        streamer.update(extra)
        streamers.append(streamer)
    return {
        "enabled":     bool(r["enabled"]),
        "streamers":   streamers,
        "category_id": str(r["category_id"] or ""),
    }


def save_livestream(gid: int, data: dict) -> None:
    db.ensure_guild(gid)
    with db.transaction() as cx:
        cx.execute(
            "INSERT INTO cfg_livestream (guild_id,enabled,category_id) VALUES (?,?,?) "
            "ON CONFLICT(guild_id) DO UPDATE SET enabled=excluded.enabled,category_id=excluded.category_id",
            (gid, int(bool(data.get("enabled", False))), str(data.get("category_id", ""))),
        )
        cx.execute("DELETE FROM cfg_livestream_streamer WHERE guild_id=?", (gid,))
        for pos, s in enumerate(data.get("streamers", [])):
            extra = {k: v for k, v in s.items() if k not in _LS_PROMOTED}
            cx.execute(
                "INSERT INTO cfg_livestream_streamer "
                "(guild_id,pos,platform,login,display_name,channel_id,"
                "message_id,profile_image_url,extra_json) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    gid, pos,
                    s.get("platform"),
                    s.get("login"),
                    s.get("display_name"),
                    s.get("channel_id"),
                    s.get("message_id"),
                    s.get("profile_image_url"),
                    json.dumps(extra),
                ),
            )
