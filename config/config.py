import discord


class Discord:
    shard_count = 4
    prefix = "b?"
    color         = discord.Color.from_rgb(147, 51, 234)   # #9333ea — Purple (avocloud primary)
    danger_color  = discord.Color.from_rgb(239, 68, 68)    # #ef4444 — Red
    warn_color    = discord.Color.from_rgb(245, 158, 11)   # #f59e0b — Amber
    success_color = discord.Color.from_rgb(34, 197, 94)    # #22c55e — Green
    info_color    = discord.Color.from_rgb(59, 130, 246)   # #3b82f6 — Blue
    version = "6.8.4"


class Web:
    web_folder = "assets/dash/web"
    static_folder = "assets/dash/static"
    port = 1637
    host = "0.0.0.0"
    url = "baxi.avocloud.net"


class Chatfilter:
    chatfilter_url = "http://solyra.avocloud.net:1652/chatfilter"
    ai_url = "https://owui.avocloud.net/api/chat/completions"
    phishing_list_url = "https://raw.githubusercontent.com/Discord-AntiScam/scam-links/main/list.txt"
    phishing_list_source = "https://github.com/Discord-AntiScam/scam-links"


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


class Twitch:
    api_url = "https://api.twitch.tv/helix"
    token_url = "https://id.twitch.tv/oauth2/token"
    max_checks_per_minute = 20
    check_interval_seconds = 60


class Globalchat:
    attachments_dir = "attachments"
    attachments_url = "http://solyra.avocloud.net:1600/attachments/"


class datasys:
    default_data = {
    "lang": "en",
    "guild_name": "",
    "guild_id": 0,
    "owner_id": 0,
    "owner_name": "",
    "terms": False,
    "chatfilter": {
        "enabled": False,
        "phishing_filter": False,
        "ai_categories": {
            "1": True,
            "2": True,
            "3": True,
            "4": True,
            "5": True,
        }
    },
    "ticket": {
        "enabled": False
    },
    "audit_log": [],
    "warnings": {},
    "warn_config": {
        "mute_at": 3,
        "kick_at": 5,
        "ban_at": 7,
        "mute_duration": 600
    },
    "antispam": {
        "enabled": False,
        "max_messages": 5,
        "interval": 5,
        "max_duplicates": 3,
        "action": "mute"
    },
    "welcomer": {
        "enabled": False,
        "channel": 0,
        "message": "Welcome {user} to {server}!",
        "leave_enabled": False,
        "leave_channel": 0,
        "leave_message": "{user} has left {server}.",
        "color": "#9333ea",
        "image_mode": "none",
        "card_color": "#1a1a2e",
        "has_custom_bg": False,
        "leave_color": "#f59e0b"
    },
    "custom_commands": {},
    "livestream": {
        "enabled": False,
        "streamers": [],
        "category_id": ""
    },
    "stats_channels": {
        "enabled": False,
        "category_id": "",
        "stats": {
            "members":  {"enabled": False, "channel_id": "", "template": "Members: {count}"},
            "humans":   {"enabled": False, "channel_id": "", "template": "Humans: {count}"},
            "bots":     {"enabled": False, "channel_id": "", "template": "Bots: {count}"},
            "channels": {"enabled": False, "channel_id": "", "template": "Channels: {count}"},
            "roles":    {"enabled": False, "channel_id": "", "template": "Roles: {count}"}
        }
    },
    "auto_roles": {
        "enabled": False,
        "roles": []
    },
    "temp_voice": {
        "enabled": False,
        "create_channel_id": "",
        "category_id": "",
        "name_template": "{user}'s Channel"
    },
    "prism_enabled": True,
    "notification_channel": ""
}

