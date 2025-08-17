import json
import os
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

    elif sys == "all":
        guild_data = load_json(f"data/{sid}/conf.json")
        gc_data = load_json("data/1001/conf.json")["globalchat"]
        if bot is None:
            return {}
        guild = bot.get_guild(int(sid))
        if guild is None:
            return {}
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
        req_data = data[sys]
        return req_data


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


def get_guild_data(gid: int) -> Optional[Server_info_return]:
    if bot_instance is None:
        return None

    guild = bot_instance.get_guild(gid)
    if guild is None:
        return None

    return Server_info_return(guild)
