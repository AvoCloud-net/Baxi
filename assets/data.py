import json
import os

import discord
from discord.ext import commands


def load_json(file: str):
    with open(file, "r", encoding="utf-8") as f:
        return json.load(f)


class Data_return:
    def __init__(self, data: dict):
        self.data: dict = data
        self.enabled: bool = data.get("enabled")
        self.sid: int = data.get("sid")
        self.cid: int = data.get("cid")
        self.catid: int = data.get("catid")
        self.rid: int = data.get("rid")
        self.number: int = data.get("number")
        self.c_goodwords: list = data.get("c_goodwords")
        self.c_badwords: list = data.get("c_badwords")
        self.bypass: list = data.get("bypass")
        self.globalchat: dict = data.get("globalchat")
        self.last_user: int = data.get("last_user")
        self.min_value: int = data.get("min_value")
        self.max_value: int = data.get("max_value")
        self.verify_option: int = data.get(
            "verify_option"
        )  # 0 = none, 1 = captcha, 2 = password
        self.password: str = data.get("password")

    def to_dict(self):
        return {
            "enabled": self.enabled,
            "sid": self.sid,
            "cid": self.cid,
            "catid": self.catid,
            "rid": self.rid,
            "number": self.number,
            "c_goodwords": self.c_goodwords,
            "c_badwords": self.c_badwords,
            "bypass": self.bypass,
            "globalchat": self.globalchat,
            "last_user": self.last_user,
            "min_value": self.min_value,
            "max_value": self.max_value,
            "verify_option": self.verify_option,
            "password": self.password,
        } 


def load_data(sid: int, sys: str):
    if sys == "globalchat_message_data":
        file_path = f"data/{sid}/globalchat_message_data.json"
        data = load_json(file_path)
        return data
    elif sys == "chatfilter_log":
        file_path = f"data/{sid}/chatfilter_log.json"
        data = load_json(file_path)
        return data
    elif sys == "open_tickets":
        data = load_json(f"data/{sid}/tickets.json")
        return data
    else:
        data = load_json(f"data/{sid}/conf.json")
        req_data = data[sys]
        return Data_return(req_data)


def load_lang(sid: int):
    if sid is not None:
        try:
            data = load_json(f"data/{sid}/conf.json")
            req_data = data["lang"]
        except FileNotFoundError:
            req_data = "en"

    else:
        req_data = "en"
    return req_data


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
    elif sys == "open_tickets":
        file_path = f"data/{sid}/tickets.json"
        save_json(file_path, data)
    else:
        file_path = f"data/{sid}/conf.json"

        if os.path.exists(file_path):
            data_file = load_json(file_path)
        else:
            data_file = {}

        data_file[sys] = data
        save_json(file_path, data_file)


bot_instance = None


def set_bot(bot):
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


def get_guild_data(gid: int):
    guild = bot_instance.get_guild(gid)
    return Server_info_return(guild)
