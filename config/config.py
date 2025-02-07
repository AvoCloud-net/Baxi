import discord


class Discord:
    shard_count = 4
    prefix = "b?"
    color = discord.Color.from_rgb(111, 131, 170)
    danger_color = discord.Color.from_rgb(220, 53, 69)
    warn_color = discord.Color.from_rgb(255, 193, 7)
    version = "5.2"


class Web:
    web_folder = "assets/dash/web"
    static_folder = "assets/dash/static"
    port = 1637
    host = "0.0.0.0"


class Chatfilter:
    chatfilter_url = "http://solyra.avocloud.net:1652/chatfilter"
    user_url = "http://solyra.avocloud.net:1652/user"


class Icons:
    base_uri = "http://solyra.avocloud.net:1650/icon/"
    danger = base_uri + "danger.png"
    warn = base_uri + "warn.png"
    wave = base_uri + "wave.png"
    user = base_uri + "user.png"
    loading = base_uri + "loading.png"
    chatbot = base_uri + "chatbot.png"


class Globalchat:
    attachments_dir = "attachments"
    attachments_url = "http://solyra.avocloud.net:1600/attachments/"


class datasys:
    default_data = {
    "lang": "en",
    "chatfilter": {
        "enabled": False,
        "c_goodwords": [],
        "c_badwords": [],
        "bypass": []
    },
    "counting": {
        "sid": None,
        "cid": None,
        "enabled": False,
        "number": None,
        "c_goodwords": None,
        "c_badwords": None,
        "bypass": None,
        "globalchat": None,
        "last_user": None
    },
    "guessing": {
        "sid": None,
        "cid": None,
        "enabled": False,
        "number": None,
        "c_goodwords": None,
        "c_badwords": None,
        "bypass": None,
        "globalchat": None,
        "last_user": None,
        "min_value": None,
        "max_value": None
    },
    "ticket": {
        "sid": None,
        "cid": None,
        "catid": None,
        "rid": None,
        "enabled": False,
        "number": None,
        "c_goodwords": None,
        "c_badwords": None,
        "bypass": None,
        "globalchat": None,
        "last_user": None,
        "min_value": None,
        "max_value": None,
        "open_tickets": {}
    }
}
