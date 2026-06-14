"""
assets/data.py — facade over the SQLite repo layer.

All public symbols and signatures are IDENTICAL to the original file-based
implementation.  Internally, load_data/save_data dispatch through the repo
registry.  load_json/save_json remain real file IO (lang/lang.json etc.).
"""
from __future__ import annotations

import copy
import datetime
import json
import os
import re as _re
from typing import Optional, Union

import discord
from discord.ext import commands

import config.config as config
import assets.db as db
import assets.repo as repo
from assets.repo import runtime as _runtime_repo

_DD = config.datasys.default_data


# ── File IO (unchanged) ───────────────────────────────────────────────────────

def load_json(file: str):
    with open(file, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(file: str, data):
    with open(file, "w") as f:
        json.dump(data, f, indent=4, ensure_ascii=True)


# ── Bot handle ────────────────────────────────────────────────────────────────

bot_instance: Optional[commands.AutoShardedBot] = None


def set_bot(bot: commands.AutoShardedBot) -> None:
    global bot_instance
    bot_instance = bot


# ── load_data ─────────────────────────────────────────────────────────────────

def load_data(
    sid: int,
    sys: str,
    bot: Optional[commands.AutoShardedBot] = None,
    dash_login: Optional[str] = None,
) -> Union[dict, list]:
    db.ensure_guild(int(sid))

    if sys == "all":
        return _load_all(int(sid), bot or bot_instance, dash_login)

    # 1001-bag keys (no gid argument)
    if repo.is_1001_key(sys):
        return repo.load_1001_key(sys)

    # Registry dispatch
    pair = repo.REGISTRY.get(sys)
    if pair is not None and pair[0] is not None:
        return pair[0](int(sid))

    # Guild-scalar keys stored on guilds row
    if sys in repo._GUILDS_SCALAR_KEYS:
        scalars = repo.load_guild_scalars(int(sid))
        return scalars.get(sys, copy.deepcopy(_DD.get(sys, {})))

    # Default fallback (new features, unknown keys)
    if sys in _DD:
        return copy.deepcopy(_DD[sys])
    return {}


def _load_all(sid: int, bot_ref, dash_login: Optional[str]) -> dict:
    if bot_ref is None:
        return {}
    guild = bot_ref.get_guild(int(sid))
    if guild is None:
        guild_info = {
            "name":         "",
            "id":           sid,
            "icon_url":     "",
            "member_count": 0,
            "dash_login":   dash_login,
        }
    else:
        guild_info = {
            "name":         guild.name,
            "id":           guild.id,
            "icon_url":     guild.icon.url if guild.icon else "",
            "member_count": len(guild.members),
            "dash_login":   dash_login,
        }

    guild_data = repo.load_full_conf(sid)

    # sticky_messages lived inline in conf.json pre-migration, so the old "all"
    # carried it. It now has its own table and is not a conf key, so re-attach it
    # here to keep "all" byte-identical (the dashboard reads data.sticky_messages).
    guild_data["sticky_messages"] = repo.load_sticky_messages(sid)

    # Merge globalchat from sid 1001
    gc_data = repo.load_globalchat()
    if str(sid) in gc_data:
        guild_gc = {"globalchat": gc_data[str(sid)]}
        return {**guild_info, **guild_data, **guild_gc}
    return {**guild_info, **guild_data}


# ── save_data ─────────────────────────────────────────────────────────────────

def save_data(sid: int, sys: str, data) -> None:
    db.ensure_guild(int(sid))

    # 1001-bag keys
    if repo.is_1001_key(sys):
        repo.save_1001_key(sys, data)
        return

    # Registry dispatch
    pair = repo.REGISTRY.get(sys)
    if pair is not None and pair[1] is not None:
        pair[1](int(sid), data)
        return

    # Guild-scalar keys — update the guilds row
    if sys in repo._GUILDS_SCALAR_KEYS:
        repo.save_guild_scalars(int(sid), {sys: data})
        return

    # Catch-all: persist in guild_misc so nothing is silently dropped
    repo._save_misc(int(sid), sys, data)


# ── Lang ──────────────────────────────────────────────────────────────────────

def load_lang(sid: int) -> str:
    if sid is not None and sid != 1001 and sid != 0:
        try:
            rows = db.query("SELECT lang FROM guilds WHERE guild_id=?", (int(sid),))
            if rows:
                return str(rows[0]["lang"] or "en")
        except Exception:
            pass
    return "en"


def load_lang_file(sid: int):
    server_lang = load_lang(sid)
    data = load_json(os.path.join("lang", "lang.json"))
    return data[str(server_lang)]


# ── Server_info_return ────────────────────────────────────────────────────────

class Server_info_return:
    def __init__(self, guild: discord.Guild):
        self.channels   = guild.channels
        self.roles      = guild.roles
        self.categories = guild.categories
        self.emojis     = guild.emojis
        self.members    = guild.members
        self.owner      = guild.owner
        self.icon       = guild.icon
        self.id         = guild.id
        self.name       = guild.name


def get_guild_data(gid: int) -> Optional[Server_info_return]:
    if bot_instance is None:
        return None
    guild = bot_instance.get_guild(gid)
    if guild is None:
        return None
    return Server_info_return(guild)


# ── Duration helpers (unchanged) ──────────────────────────────────────────────

def parse_duration(s: str) -> Optional[datetime.timedelta]:
    m = _re.fullmatch(r'(?:(\d+)w)?(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?', s.strip().lower())
    if not m or not any(m.groups()):
        return None
    td = datetime.timedelta(
        weeks=int(m.group(1) or 0),
        days=int(m.group(2) or 0),
        hours=int(m.group(3) or 0),
        minutes=int(m.group(4) or 0),
        seconds=int(m.group(5) or 0),
    )
    return td if td.total_seconds() > 0 else None


def format_duration(td: datetime.timedelta) -> str:
    total = int(td.total_seconds())
    weeks, rem = divmod(total, 604800)
    days, rem = divmod(rem, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    parts = []
    if weeks:   parts.append(f"{weeks}w")
    if days:    parts.append(f"{days}d")
    if hours:   parts.append(f"{hours}h")
    if minutes: parts.append(f"{minutes}m")
    if seconds and not (weeks or days or hours): parts.append(f"{seconds}s")
    return " ".join(parts) if parts else "0s"


# ── Temp actions ──────────────────────────────────────────────────────────────

def load_temp_actions(sid: int) -> dict:
    try:
        return repo.load_temp_actions(int(sid))
    except Exception:
        return {"bans": [], "timeouts": []}


def save_temp_actions(sid: int, data: dict) -> None:
    repo.save_temp_actions(int(sid), data)


# ── Activity ──────────────────────────────────────────────────────────────────

def update_activity(
    guild_id: int,
    *,
    channel_id: Optional[str] = None,
    channel_name: Optional[str] = None,
    user_id: Optional[str] = None,
    user_name: Optional[str] = None,
    hour: Optional[int] = None,
    member_join: bool = False,
    member_leave: bool = False,
) -> None:
    try:
        _runtime_repo.update_activity(
            int(guild_id),
            channel_id=channel_id,
            channel_name=channel_name,
            user_id=user_id,
            user_name=user_name,
            hour=hour,
            member_join=member_join,
            member_leave=member_leave,
        )
    except Exception:
        pass


# ── Mod / filter events ───────────────────────────────────────────────────────

def append_mod_event(guild_id: int, event: dict) -> None:
    try:
        repo.append_mod_event(int(guild_id), event)
    except Exception:
        pass


def append_filter_event(guild_id: int, event: dict) -> None:
    try:
        repo.append_filter_event(int(guild_id), event)
    except Exception:
        pass
