import json
import os
import re as _re
import datetime
import discord
from discord.ext import commands
from typing import Optional, Union
import config.config as config


def load_json(file: str):
    with open(file, "r", encoding="utf-8") as f:
        return json.load(f)


def load_data(
    sid: int,
    sys: str,
    bot: Optional[commands.AutoShardedBot] = None,
    dash_login: Optional[str] = None,
) -> Union[dict, list]:

    guild_data_dir = os.path.join("data", str(sid))
    if not os.path.exists(guild_data_dir):
        os.makedirs(guild_data_dir)
    json_file_path = os.path.join(guild_data_dir, "conf.json")
    if not os.path.exists(json_file_path):
        with open(json_file_path, "w", encoding="utf-8") as json_file:
            json.dump(config.datasys.default_data, json_file, indent=4)
    ticket_json_file_path = os.path.join(guild_data_dir, "tickets.json")
    if not os.path.exists(ticket_json_file_path):
        with open(ticket_json_file_path, "w", encoding="utf-8") as t_json_file:
            json.dump({}, t_json_file, indent=4)

    if sys == "globalchat_message_data":
        data: dict = load_json(f"data/{sid}/globalchat_message_data.json")
        return data

    elif sys == "chatfilter_log":
        data = load_json(f"data/{sid}/chatfilter_log.json")
        return data

    elif sys == "transcripts":
        data = load_json(f"data/{sid}/transcripts.json")
        return data

    elif sys == "users":
        data = load_json(f"data/{sid}/users.json")
        return data

    elif sys == "open_tickets":
        data = load_json(f"data/{sid}/tickets.json")
        return data
    elif sys == "stats":
        data = load_json(f"data/{sid}/stats.json")
        return data
    elif sys == "all":
        guild_data = load_json(f"data/{sid}/conf.json")
        gc_data = load_json("data/1001/conf.json")["globalchat"]
        if bot is None:
            return {}
        guild = bot.get_guild(int(sid))
        if guild is None:
            guild_info = {
                "name": "",
                "id": sid,
                "icon_url": "",
                "member_count": 0,
                "dash_login": dash_login,
            }
        else:
            guild_icon = guild.icon.url if guild.icon is not None else ""
            guild_info = {
                "name": guild.name,
                "id": guild.id,
                "icon_url": guild_icon,
                "member_count": len(guild.members),
                "dash_login": dash_login,
            }
        if str(sid) in gc_data:
            guild_gc_data = {"globalchat": gc_data[str(sid)]}
            guild_conf = {**guild_info, **guild_data, **guild_gc_data}
        else:
            guild_conf = {**guild_info, **guild_data}
        return guild_conf

    else:
        data = load_json(f"data/{sid}/conf.json")
        if sys in data:
            return data[sys]
        # Fall back to default if key missing (e.g. new features on old guilds)
        if sys in config.datasys.default_data:
            return config.datasys.default_data[sys]
        return {}


def load_lang(sid: int):
    if sid is not None and sid != 1001 and sid != 0:
        try:
            data = load_json(f"data/{sid}/conf.json")
            req_data = data["lang"]
        except FileNotFoundError:
            req_data = "en"

    else:
        req_data = "en"
    return req_data


def load_lang_file(sid: int):
    server_lang = load_lang(sid)
    data = load_json(os.path.join("lang", "lang.json"))
    return data[str(server_lang)]


def save_json(file: str, data):
    with open(file, "w") as f:
        json.dump(data, f, indent=4, ensure_ascii=True)


def save_data(sid: int, sys: str, data):
    if sys == "globalchat_message_data":
        file_path = f"data/{sid}/globalchat_message_data.json"
        save_json(file_path, data)
    elif sys == "chatfilter_log":
        file_path = f"data/{sid}/chatfilter_log.json"
        save_json(file_path, data)
    elif sys == "transcripts":
        file_path = f"data/{sid}/transcripts.json"
        save_json(file_path, data)
    elif sys == "users":
        save_json(f"data/{sid}/users.json", data)
    elif sys == "open_tickets":
        file_path = f"data/{sid}/tickets.json"
        save_json(file_path, data)
    elif sys == "stats":
        file_path = f"data/{sid}/stats.json"
        save_json(file_path, data)
    else:
        file_path = f"data/{sid}/conf.json"

        if os.path.exists(file_path):
            data_file = load_json(file_path)
        else:
            data_file = {}
        data_file[sys] = data
        save_json(file_path, data_file)


bot_instance: Optional[commands.AutoShardedBot] = None


def set_bot(bot: commands.AutoShardedBot):
    global bot_instance
    bot_instance = bot


class Server_info_return:
    def __init__(self, guild: discord.Guild):
        self.channels = guild.channels
        self.roles = guild.roles
        self.categories = guild.categories
        self.emojis = guild.emojis
        self.members = guild.members
        self.owner = guild.owner
        self.icon = guild.icon
        self.id = guild.id
        self.name = guild.name


def parse_duration(s: str) -> Optional[datetime.timedelta]:
    """Parse '7d', '2h30m', '1w', '30m', '10s' → timedelta. Returns None if invalid."""
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
    """Format a timedelta as a compact human-readable string like '7d 2h 30m'."""
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


def load_temp_actions(sid: int) -> dict:
    """Load temp_actions.json for a guild. Returns default if missing."""
    file_path = os.path.join("data", str(sid), "temp_actions.json")
    if not os.path.exists(file_path):
        return {"bans": [], "timeouts": []}
    try:
        return load_json(file_path)
    except Exception:
        return {"bans": [], "timeouts": []}


def save_temp_actions(sid: int, data: dict):
    guild_data_dir = os.path.join("data", str(sid))
    if not os.path.exists(guild_data_dir):
        os.makedirs(guild_data_dir)
    save_json(os.path.join(guild_data_dir, "temp_actions.json"), data)


_INSIGHTS_MAX_DAYS = 90

# ── Activity tracking ──────────────────────────────────────────────────────────

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
):
    """
    Increment aggregated activity counters for a guild.
    Stored in data/{guild_id}/activity.json — no message content, counts only.
    Automatically prunes data older than 90 days.
    """
    guild_data_dir = os.path.join("data", str(guild_id))
    if not os.path.exists(guild_data_dir):
        os.makedirs(guild_data_dir)
    path = os.path.join(guild_data_dir, "activity.json")
    try:
        activity = load_json(path) if os.path.exists(path) else {}
    except Exception:
        activity = {}

    today = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    cutoff = (datetime.datetime.utcnow() - datetime.timedelta(days=_INSIGHTS_MAX_DAYS)).strftime("%Y-%m-%d")

    # ── Message tracking ──────────────────────────────────────────────────
    if channel_id is not None:
        days = activity.setdefault("msg_by_day", {})
        # Prune old days
        for d in list(days):
            if d < cutoff:
                del days[d]
        day = days.setdefault(today, {"total": 0, "by_channel": {}, "by_user": {}, "by_hour": {}})
        day["total"] = day.get("total", 0) + 1
        ch = day["by_channel"].setdefault(channel_id, {"name": channel_name or channel_id, "count": 0})
        ch["count"] += 1
        if channel_name:
            ch["name"] = channel_name
        if user_id:
            u = day["by_user"].setdefault(user_id, {"name": user_name or user_id, "count": 0})
            u["count"] += 1
            if user_name:
                u["name"] = user_name
        if hour is not None:
            h = str(hour)
            day["by_hour"][h] = day["by_hour"].get(h, 0) + 1

    # ── Member tracking ───────────────────────────────────────────────────
    if member_join or member_leave:
        mdays = activity.setdefault("member_by_day", {})
        for d in list(mdays):
            if d < cutoff:
                del mdays[d]
        mday = mdays.setdefault(today, {"joins": 0, "leaves": 0})
        if member_join:
            mday["joins"] = mday.get("joins", 0) + 1
        if member_leave:
            mday["leaves"] = mday.get("leaves", 0) + 1

    try:
        save_json(path, activity)
    except Exception:
        pass


def _prune_events(events: list) -> list:
    """Remove events older than _INSIGHTS_MAX_DAYS days."""
    cutoff = (datetime.datetime.utcnow() - datetime.timedelta(days=_INSIGHTS_MAX_DAYS)).isoformat()
    return [e for e in events if e.get("timestamp", "9999") >= cutoff]


def append_mod_event(guild_id: int, event: dict):
    """Append a moderation event to data/{guild_id}/mod_events.json (keeps last 90 days)."""
    guild_data_dir = os.path.join("data", str(guild_id))
    if not os.path.exists(guild_data_dir):
        os.makedirs(guild_data_dir)
    path = os.path.join(guild_data_dir, "mod_events.json")
    try:
        if os.path.exists(path):
            events = load_json(path)
        else:
            events = []
        events.append(event)
        save_json(path, _prune_events(events))
    except Exception:
        pass


def append_filter_event(guild_id: int, event: dict):
    """Append a chatfilter event to data/{guild_id}/filter_events.json (keeps last 90 days)."""
    guild_data_dir = os.path.join("data", str(guild_id))
    if not os.path.exists(guild_data_dir):
        os.makedirs(guild_data_dir)
    path = os.path.join(guild_data_dir, "filter_events.json")
    try:
        if os.path.exists(path):
            events = load_json(path)
        else:
            events = []
        events.append(event)
        save_json(path, _prune_events(events))
    except Exception:
        pass


def get_guild_data(gid: int) -> Optional[Server_info_return]:
    if bot_instance is None:
        return None

    guild = bot_instance.get_guild(gid)
    if guild is None:
        return None

    return Server_info_return(guild)
