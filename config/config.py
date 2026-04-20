import discord


class Discord:
    shard_count = 4
    prefix = "b?"
    color         = discord.Color.from_rgb(147, 51, 234)   # #9333ea -  Purple (avocloud primary)
    danger_color  = discord.Color.from_rgb(239, 68, 68)    # #ef4444 -  Red
    warn_color    = discord.Color.from_rgb(245, 158, 11)   # #f59e0b -  Amber
    success_color = discord.Color.from_rgb(34, 197, 94)    # #22c55e -  Green
    info_color    = discord.Color.from_rgb(59, 130, 246)   # #3b82f6 -  Blue
    version = "7.0.0"


class Web:
    web_folder = "assets/dash/web"
    static_folder = "assets/dash/static"
    port = 1637
    host = "0.0.0.0"
    url = "baxi.avocloud.net"


class Chatfilter:
    chatfilter_url = "http://solyra.avocloud.net:1652/chatfilter"
    ai_url = "https://owui.avocloud.net/api/chat/completions"
    feedback_file_path = "data/ai_feedback.json"
    feedback_max_entries = 15  # FIFO cap on admin-corrected few-shot examples
    phishing_list_url = "https://raw.githubusercontent.com/Discord-AntiScam/scam-links/main/list.txt"
    phishing_list_source = "https://github.com/Discord-AntiScam/scam-links"


class Icons:
    # --- Commands (Discord custom emojis) ---
    search             = "<:search:1492977251271049318> "
    alert              = "<:alert:1397005510409981982>"
    info               = "<:info:1492977239409688586>"
    people_crossed     = "<:usercross:1492977256694546593>"
    questionmark       = "<:question:1492977250008825998>"
    messageexclamation = "<:messageexclamation:1492977241171427419>"
    user               = "<:user:1492977255608094820>"
    message            = "<:message:1492977240256938116>"
    stats              = "<:stats:1492977254463049780>"
    trophy             = "<:trophy:1492978643646026006>"
    check              = "<:check:1492987072250908794>"   # ✅
    cross              = "<:x_:1492987102353166587>"   # ❌
    celebrate          = "<:celebrate:1492987070841491707>"   # 🎉
    robot              = "<:robot:1492987089011081246>"   # 🤖
    mute               = "<:messagemute:1492987084686884904>"   # 🔇
    shield             = "<:shield:1492987092601540809>"   # 🛡️
    health             = "<:hearth:1492987077690790079>"   # ❤️
    medal              = "<:medal:1492987080412758187>"   # 🥇
    pin                = "<:pin:1492987085936660674>"   # 📌
    thumbsup           = "<:thumbsup:1492987096699244674>"   # 👍
    thumbsdown         = "<:thumbsdown:1492987094799483042>"   # 👎
    fire               = "<:fire:1492987074389872660>"   # 🔥
    trash              = "<:trash:1492987098071044197>"   # 🗑️
    hand               = "<:hand:1492987076080304128>"   # 🖐️
    up                 = "<:up:1493702235295580210>"      # ⬆️
    bulb               = "<:bulb:1494045091818377268>"    # 💡

    # --- Web (SVG strings) ---
    share              = '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-share-icon lucide-share"><path d="M12 2v13"/><path d="m16 6-4-4-4 4"/><path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8"/></svg>'
    web_check          = '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-check-icon lucide-check"><path d="M20 6 9 17l-5-5"/></svg>'
    web_cross          = '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-x-icon lucide-x"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>'   # ❌
    web_alert          = '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-triangle-alert-icon lucide-triangle-alert"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>'   # ⚠️
    web_info           = '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-info-icon lucide-info"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>'   # ℹ️
    web_user           = '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-info-icon lucide-info"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>'   # 👤
    web_stats          = '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-chart-column-increasing-icon lucide-chart-column-increasing"><path d="M13 17V9"/><path d="M18 17V5"/><path d="M3 3v16a2 2 0 0 0 2 2h16"/><path d="M8 17v-3"/></svg>'   # 📊
    web_trophy         = '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-trophy-icon lucide-trophy"><path d="M10 14.66v1.626a2 2 0 0 1-.976 1.696A5 5 0 0 0 7 21.978"/><path d="M14 14.66v1.626a2 2 0 0 0 .976 1.696A5 5 0 0 1 17 21.978"/><path d="M18 9h1.5a1 1 0 0 0 0-5H18"/><path d="M4 22h16"/><path d="M6 9a6 6 0 0 0 12 0V3a1 1 0 0 0-1-1H7a1 1 0 0 0-1 1z"/><path d="M6 9H4.5a1 1 0 0 1 0-5H6"/></svg>'   # 🏆
    web_kick           = '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-user-minus-icon lucide-user-minus"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><line x1="22" x2="16" y1="11" y2="11"/></svg>'   # 👟
    web_ban            = '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-user-x-icon lucide-user-x"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><line x1="17" x2="22" y1="8" y2="13"/><line x1="22" x2="17" y1="8" y2="13"/></svg>'   # 🔨
    web_mute           = '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-message-square-off-icon lucide-message-square-off"><path d="M19 19H6.828a2 2 0 0 0-1.414.586l-2.202 2.202A.7.7 0 0 1 2 21.286V5a2 2 0 0 1 1.184-1.826"/><path d="m2 2 20 20"/><path d="M8.656 3H20a2 2 0 0 1 2 2v11.344"/></svg>'   # 🔇
    web_shield         = '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-shield-icon lucide-shield"><path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/></svg>'   # 🛡️
    web_health         = '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-heart-icon lucide-heart"><path d="M2 9.5a5.5 5.5 0 0 1 9.591-3.676.56.56 0 0 0 .818 0A5.49 5.49 0 0 1 22 9.5c0 2.29-1.5 4-3 5.5l-5.492 5.313a2 2 0 0 1-3 .019L5 15c-1.5-1.5-3-3.2-3-5.5"/></svg>'   # ❤️
    web_pin            = '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-pin-icon lucide-pin"><path d="M12 17v5"/><path d="M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V7a1 1 0 0 1 1-1 2 2 0 0 0 0-4H8a2 2 0 0 0 0 4 1 1 0 0 1 1 1z"/></svg>'   # 📌
    web_thumbsup       = '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-thumbs-up-icon lucide-thumbs-up"><path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a3.13 3.13 0 0 1 3 3.88Z"/><path d="M7 10v12"/></svg>'   # 👍
    web_thumbsdown     = '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-thumbs-down-icon lucide-thumbs-down"><path d="M9 18.12 10 14H4.17a2 2 0 0 1-1.92-2.56l2.33-8A2 2 0 0 1 6.5 2H20a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-2.76a2 2 0 0 0-1.79 1.11L12 22a3.13 3.13 0 0 1-3-3.88Z"/><path d="M17 14V2"/></svg>'  # 👎
    web_fire           = '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-flame-icon lucide-flame"><path d="M12 3q1 4 4 6.5t3 5.5a1 1 0 0 1-14 0 5 5 0 0 1 1-3 1 1 0 0 0 5 0c0-2-1.5-3-1.5-5q0-2 2.5-4"/></svg>'   # 🔥
    web_trash          = '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-trash2-icon lucide-trash-2"><path d="M10 11v6"/><path d="M14 11v6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>'   # 🗑️


class Twitch:
    api_url = "https://api.twitch.tv/helix"
    token_url = "https://id.twitch.tv/oauth2/token"
    max_checks_per_minute = 20
    check_interval_seconds = 120


class YouTube:
    check_interval_seconds = 300


class YouTubeVideos:
    check_interval_seconds = 600


class TikTok:
    check_interval_seconds = 300


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
        "system": "AI",
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
        "enabled": False,
        "channel": "",
        "transcript": "",
        "catid": "",
        "role": "",
        "color": "#9333ea",
        "message": "Click a button below to open a ticket.",
        "channel_name_template": "{button}-{user}",
        "panel_message_id": "",
        "buttons": [
            {"id": "support", "label": "Support", "emoji": "🛠️", "style": "primary"}
        ],
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
        "action": "mute",
        "whitelisted_channels": [],
        "whitelisted_roles": [],
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
    "youtube_videos": {
        "enabled": False,
        "alert_channel": "",
        "ping_role": "",
        "channels": []
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
    "notification_channel": "",
    "verify": {
        "enabled": False,
        "rid": 0,
        "verify_option": 0,
        "password": "",
        "channel": "",
        "panel_message_id": "",
        "title": "Verification",
        "description": "Click the button below to verify yourself and gain access to the server.",
        "color": "#9333ea"
    },
    "reaction_roles": {
        "panels": []
    },
    "auto_slowmode": {
        "enabled": False,
        "threshold": 10,
        "interval": 10,
        "slowmode_delay": 5,
        "duration": 120
    },
    "counting": {
        "enabled": False,
        "channel": "",
        "current_count": 0,
        "high_score": 0,
        "last_user_id": 0,
        "no_double_count": True,
        "react_correct": True,
        "react_wrong": True,
    },
    "flag_quiz": {
        "enabled": False,
        "channel": "",
        "hint_after_attempts": 3,
        "next_delay": 3,
        "points_enabled": True,
        "scores": {},
        "recent_flags": [],
    },
    "flag_quiz_active": {},
    "suggestions": {
        "enabled": False,
        "channels": [],
        "staff_role": "",
        "log_channel": "",
        "auto_forward_enabled": False,
        "auto_forward_channel": "",
        "auto_forward_threshold": 10,
    },
    "suggestion_votes": {},
    "giveaways": {},
    "leveling": {
        "enabled": False,
        "announcement": "same_channel",   # "same_channel" | "channel" | "off"
        "announcement_channel": "",
        "role_rewards": [],               # [{"level": 5, "role_id": "123..."}]
    },
    "auto_release": {
        "enabled": False,
        "channels": [],
        "ignore_bots": True,
    },
    "donations": {
        "enabled": False,
        "provider": "stripe",
        "stripe_secret_key": "",
        "stripe_webhook_secret": "",
        "paypal_client_id": "",
        "paypal_client_secret": "",
        "page_text": "Support this server!",
        "success_text": "Thank you for your donation! Your role has been assigned.",
        "log_enabled": False,
        "log_channel": "",
        "tiers": [],
    },
}

