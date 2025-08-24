import discord


class Discord:
    shard_count = 4
    prefix = "b?"
    color = discord.Color.from_rgb(111, 131, 170)
    danger_color = discord.Color.from_rgb(220, 53, 69)
    warn_color = discord.Color.from_rgb(255, 193, 7)
    version = "6 - BETAs"


class Web:
    web_folder = "assets/dash/web"
    static_folder = "assets/dash/static"
    port = 1637
    host = "0.0.0.0"
    url = "baxi.avocloud.net"


class Chatfilter:
    chatfilter_url = "http://solyra.avocloud.net:1652/chatfilter"
    ai_url = "https://owui.avocloud.net/api/chat/completions"


class Icons:
    search = "<:search:1397005756481409105>"
    alert = "<:alert:1397005510409981982>"
    info = "<:info:1397005995133374524>"
    people_crossed = "<:peoplecrossed:1397007080497348638>"
    questionmark = "<:questionmark:1397349053108588714>"
    messageexclamation = "<:messageexclamation:1397349612439867432>"
    share = "<:Share:1397351564414423171>"
    user = "<:person:1397349540906008597>"
    message = "<:Message:1397352374376599695>"


class Globalchat:
    attachments_dir = "attachments"
    attachments_url = "http://solyra.avocloud.net:1600/attachments/"


class datasys:
    default_data = {
    "lang": "en",
    "guild_name": "",
    "terms": False,
    "chatfilter": {
        "enabled": False
    },
    "ticket": {
        "enabled": False
    },
    "audit_log": []
}

