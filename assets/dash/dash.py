import quart
from quart import redirect, url_for, Markup, session
from assets.data import load_data, save_data
import assets.data as datasys
from quart import render_template, send_from_directory, abort
from discord.ext import commands
import discord
import aiohttp
import config.auth as auth
from typing import Optional
from assets.livestream import twitch_api, youtube_api, tiktok_api
from quart_discord import DiscordOAuth2Session, requires_authorization, Unauthorized
from datetime import datetime
from zoneinfo import ZoneInfo

_VIENNA = ZoneInfo("Europe/Vienna")
import random
import re
from typing import cast
import config.config as config
from assets.buttons import TicketView
import time
import json
import os
import asyncio
import assets.share as share


def get_feature_adoption() -> dict:
    """Calculate what percentage of all servers use each feature."""
    data_dir = "data"
    counts = {
        "chatfilter": 0,
        "ticket": 0,
        "antispam": 0,
        "welcomer": 0,
        "livestream": 0,
        "custom_commands": 0,
        "globalchat": 0,
        "stats_channels": 0,
        "auto_roles": 0,
    }
    try:
        guild_dirs = [
            d for d in os.listdir(data_dir)
            if os.path.isdir(os.path.join(data_dir, d)) and d.isdigit() and d != "1001"
        ]
    except FileNotFoundError:
        return {k: 0 for k in counts}

    total = len(guild_dirs)
    if total == 0:
        return {k: 0 for k in counts}

    gc_enabled_guilds: set = set()
    try:
        with open(os.path.join(data_dir, "1001", "conf.json"), "r", encoding="utf-8") as f:
            gc_data = json.load(f)
        for gid, gc_conf in gc_data.get("globalchat", {}).items():
            if gc_conf.get("enabled", False):
                gc_enabled_guilds.add(gid)
    except Exception:
        pass

    for guild_id in guild_dirs:
        conf_path = os.path.join(data_dir, guild_id, "conf.json")
        if not os.path.exists(conf_path):
            continue
        try:
            with open(conf_path, "r", encoding="utf-8") as f:
                conf = json.load(f)
        except Exception:
            continue
        if conf.get("chatfilter", {}).get("enabled", False):
            counts["chatfilter"] += 1
        if conf.get("ticket", {}).get("enabled", False):
            counts["ticket"] += 1
        if conf.get("antispam", {}).get("enabled", False):
            counts["antispam"] += 1
        if conf.get("welcomer", {}).get("enabled", False):
            counts["welcomer"] += 1
        if conf.get("livestream", {}).get("enabled", False):
            counts["livestream"] += 1
        if conf.get("custom_commands"):
            counts["custom_commands"] += 1
        if guild_id in gc_enabled_guilds:
            counts["globalchat"] += 1
        if conf.get("stats_channels", {}).get("enabled", False):
            counts["stats_channels"] += 1
        if conf.get("auto_roles", {}).get("enabled", False):
            counts["auto_roles"] += 1

    return {k: round(v / total * 100) for k, v in counts.items()}


def dash_web(app: quart.Quart, bot: commands.AutoShardedBot):
    assert bot.user is not None, "Bot user None"
    app.config["DISCORD_CLIENT_ID"] = int(bot.user.id)
    app.config["DISCORD_CLIENT_SECRET"] = auth.Bot.client_secret
    app.config["DISCORD_REDIRECT_URI"] = auth.Bot.callback_url
    app.secret_key = auth.Web.secret_key

    discord_auth = DiscordOAuth2Session(app)

    @app.route("/login/")
    async def login():
        return await discord_auth.create_session(
            scope=["identify", "guilds"],
            permissions=0,
        )

    @app.route("/logout/")
    async def logout():
        discord_auth.revoke()
        return await render_template("logout.html")

    @app.route("/callback/")
    async def callback():
        try:
            await discord_auth.callback()
            session['show_intro'] = True
            return redirect(url_for("index"))
        except Exception as e:
            print(f"Error in callback route: {e}")
            return await render_template(
                "error.html", message="An unexpected error occurred during login. Please try again."
            )

    @app.errorhandler(Unauthorized)
    async def redirect_unauthorized(e):
        return redirect(url_for("welcome"))

    @app.route("/welcome/")
    async def welcome():
        stats: dict = dict(load_data(1001, "stats"))
        return await render_template(
            "welcome.html",
            stats=stats,
            version=config.Discord.version,
        )

    @app.route("/privacy/")
    async def privacy():
        return await render_template("privacy.html")

    @app.route("/terms/")
    async def terms():
        return await render_template("terms.html")

    def get_time_based_greeting(username):
        hour = datetime.now(_VIENNA).hour

        if 5 <= hour < 12:
            greetings = [
                f"Good morning, {username}",
                f"Rise and shine, {username}!",
                f"{username}, ready to conquer the day?",
                f"Fresh start for you, {username}?",
                f"Hey {username}, coffee's brewing!",
                f"{username}, let's make today count!",
                f"Morning hustle, {username}?",
                f"Greetings, early bird {username}!",
                f"{username}, the guild awaits your magic!",
                f"Sun's up, {username} – time to shine!",
            ]

        elif 12 <= hour < 17:
            greetings = [
                f"Good afternoon, {username}",
                f"Back at it, {username}?",
                f"{username}, how's the guild today?",
                f"Afternoon vibes, {username}!",
                f"{username}, productivity mode: ON?",
                f"Hey {username}, need a dashboard break?",
                f"{username}, let's tweak that guild!",
                f"Crushing goals, {username}?",
                f"{username}, the guild misses you!",
                f"Afternoon fuel for {username}!",
            ]

        elif 17 <= hour < 22:
            greetings = [
                f"Good evening, {username}",
                f"{username}, still in the grind?",
                f"Evening guild session, {username}?",
                f"{username}, time to wrap up!",
                f"Hey {username}, dinner then guild?",
                f"{username}, let's polish that guild!",
                f"Evening vibes with {username}!",
                f"{username}, guild leader extraordinaire!",
                f"Sunset checks by {username}!",
                f"{username}, the guild's nightwatch!",
            ]

        else:
            greetings = [
                f"Night owl {username}?",
                f"{username}, burning midnight oil?",
                f"Hey {username}, the guild never sleeps!",
                f"{username}, vampire mode activated!",
                f"3 AM guild updates, {username}?",
                f"{username}, the dashboard misses you!",
                f"Shhh... {username} is night-configuring!",
                f"Respect the grind, {username}!",
                f"{username}, guardian of the night guild!",
                f"Insomnia? Or guild passion, {username}?",
            ]

        return random.choice(greetings)

    @app.route("/")
    @requires_authorization
    async def index():
        try:
            chatfilter_log_id = quart.request.args.get("id_chatfilter")
            guild_login = quart.request.args.get("guild_login")
            ticket_transcript = quart.request.args.get("ticket_transcript")
            user = await discord_auth.fetch_user()
            print(f"{user.name} accessed dashboard")
            if chatfilter_log_id:
                chatfilter_log: dict = cast(dict, load_data(1001, "chatfilter_log"))
                guild = await bot.fetch_guild(chatfilter_log[str(chatfilter_log_id)]["sid"])
                audit_log_new: dict = {
                    "type": "chatfilter_log",
                    "user": user.name,
                    "success": True,
                    "time": str(datetime.now(_VIENNA).strftime("%d.%m.%Y - %H:%M")),
                    "id": chatfilter_log_id,
                }
                audit_log: list = cast(
                    list, load_data(sid=guild.id, sys="audit_log", bot=bot)
                )

                audit_log.append(audit_log_new)

                save_data(guild.id, "audit_log", audit_log)
                return redirect(url_for("chatfilter", id_chatfilter=chatfilter_log_id))

            elif guild_login:
                audit_log_new: dict = {
                    "type": "login",
                    "user": user.name,
                    "success": True,
                    "time": str(datetime.now(_VIENNA).strftime("%d.%m.%Y - %H:%M")),
                }
                audit_log: list = cast(
                    list, load_data(sid=int(guild_login), sys="audit_log", bot=bot)
                )
                audit_log.append(audit_log_new)
                save_data(int(guild_login), "audit_log", audit_log)
                return redirect(url_for("guild_manager", guild_login=guild_login))

            elif ticket_transcript:
                tickets: dict = cast(dict, load_data(1001, "transcripts"))
                guild = await bot.fetch_guild(int(tickets[str(ticket_transcript)]["guild"]))
                audit_log_new: dict = {
                    "type": "ticket_transcript",
                    "user": user.name,
                    "success": True,
                    "time": str(datetime.now(_VIENNA).strftime("%d.%m.%Y - %H:%M")),
                    "id": f"{ticket_transcript}",
                }
                audit_log: list = cast(
                    list, load_data(sid=int(guild.id), sys="audit_log", bot=bot)
                )
                audit_log.append(audit_log_new)
                save_data(int(guild.id), "audit_log", audit_log)
                return redirect(url_for("ticket_transcript", id_ticket=ticket_transcript))

            user_guilds = await discord_auth.fetch_guilds()
            user_managed_guilds = {
                str(guild.id): guild.name
                for guild in user_guilds
                if guild.permissions.manage_guild
            }

            bot_guilds = bot.guilds
            bot_guild_ids = {str(guild.id) for guild in bot_guilds}

            valid_guilds = {
                guild_id: name
                for guild_id, name in user_managed_guilds.items()
                if guild_id in bot_guild_ids
            }
            stats: dict = dict(load_data(1001, "stats"))
            show_intro = session.pop('show_intro', False)
            admins: list = list(datasys.load_data(1001, "admins"))
            is_bot_admin_user: bool = user.id in admins
            return await render_template(
                "dash_home.html",
                managed_guilds=valid_guilds,
                greeting=get_time_based_greeting(user.name),
                user=user,
                stats=stats,
                show_intro=show_intro,
                is_bot_admin=is_bot_admin_user,
            )
        except Exception as e:
            print(f"Error in index route: {e}")
            return await render_template(
                "error.html", message="An unexpected error occurred. Please try again."
            )

    @app.route("/chatfilter/")
    @requires_authorization
    async def chatfilter():
        user = await discord_auth.fetch_user()
        chatfilter_log_id = quart.request.args.get("id_chatfilter")
        chatfilter_log: dict = cast(dict, load_data(1001, "chatfilter_log"))
        try:
            requested_data: Optional[dict] = chatfilter_log.get(str(chatfilter_log_id))

            if not requested_data:
                return await render_template(
                    "error.html",
                    message="We're not sure what your ID is. Just double-check that you've copied or typed it correctly.",
                )

        except Exception:
            return await render_template(
                "error.html",
                message="We're getting an error we don't recognize. Try again. If this keeps happening, let the development team know.",
            )

        return await render_template(
            "log_request.html",
            data=requested_data,
            user=user,
            greeting=get_time_based_greeting(user.name),
        )

    @app.route("/ticket_transcript/")
    @requires_authorization
    async def ticket_transcript():
        user = await discord_auth.fetch_user()
        ticket_log_id = quart.request.args.get("id_ticket")
        ticket_log: dict = cast(dict, load_data(1001, "transcripts"))
        try:
            requested_data: Optional[dict] = ticket_log.get(str(ticket_log_id))

            if not requested_data:
                return await render_template(
                    "error.html",
                    message="We're not sure what your ID is. Just double-check that you've copied or typed it correctly.",
                )

        except Exception:
            return await render_template(
                "error.html",
                message="We're getting an error we don't recognize. Try again. If this keeps happening, let the development team know.",
            )

        return await render_template(
            "ticket_transcript.html",
            data=requested_data,
            user=user,
            greeting=get_time_based_greeting(user.name),
            attachment_url=config.Globalchat.attachments_url
        )

    @app.route("/guild/")
    @requires_authorization
    async def guild_manager():
        guild_id = quart.request.args.get("guild_login")

        if not guild_id or not guild_id.isdigit():
            return await render_template(
                "error.html", message="Invalid guild ID provided."
            )

        try:
            user = await discord_auth.fetch_user()
            guild = await bot.fetch_guild(int(guild_id))

            if not guild:
                return await render_template(
                    "error.html",
                    message="Error loading guild data.",
                )

            try:
                guild_member = await guild.fetch_member(user.id)
            except discord.NotFound:
                audit_log_new = {
                    "type": "login",
                    "user": user.name,
                    "success": False,
                    "time": str(datetime.now(_VIENNA).strftime("%d.%m.%Y - %H:%M")),
                }
                audit_log = cast(
                    list, load_data(sid=guild.id, sys="audit_log", bot=bot)
                )
                audit_log.append(audit_log_new)
                save_data(guild.id, "audit_log", audit_log)
                return await render_template(
                    "error.html",
                    message=f"You are not on the guild {guild.name} and therefore do not have the required authorisations to manage this server.",
                )

            if not guild_member.guild_permissions.manage_guild:
                audit_log_new = {
                    "type": "login",
                    "user": user.name,
                    "success": False,
                    "time": str(datetime.now(_VIENNA).strftime("%d.%m.%Y - %H:%M")),
                }
                audit_log = cast(
                    list, load_data(sid=guild.id, sys="audit_log", bot=bot)
                )
                audit_log.append(audit_log_new)
                save_data(guild.id, "audit_log", audit_log)
                return await render_template(
                    "error.html",
                    message=f"Hello {user.name}! Unfortunately, you are not authorized to manage this guild.",
                )

            guild_conf: dict = dict(
                load_data(sid=guild.id, sys="all", bot=bot, dash_login=guild_id)
            )
            globalchat: dict = dict(load_data(1001, "globalchat"))
            guild_conf["globalchat"] = (
                globalchat[str(guild.id)]
                if str(guild.id) in globalchat
                else {"enabled": False, "channel": ""}
            )
            guild_conf["guild_id"] = str(guild.id)
            guild_conf["dash_login"] = guild_id
            guild_conf["name"] = guild.name
            guild_conf["icon_url"] = str(guild.icon.url) if guild.icon else ""

            channels = await guild.fetch_channels()

            text_channels = {
                str(channel.id): channel.name
                for channel in channels
                if isinstance(channel, discord.TextChannel)
            }

            voice_channels = {
                str(channel.id): channel.name
                for channel in channels
                if isinstance(channel, discord.VoiceChannel)
            }

            roles = await guild.fetch_roles()

            roles_list = {str(role.id): role.name for role in roles}
            roles_positions = {str(role.id): role.position for role in roles}

            catrgorys_list = {
                str(cat.id): cat.name
                for cat in channels
                if isinstance(cat, discord.CategoryChannel)
            }

            assert bot.user is not None, "bot user unknown"

            guild_bot_user = await guild.fetch_member(bot.user.id)
            bot_top_role_pos: int = guild_bot_user.top_role.position
            bot_nick: str = (
                guild_bot_user.nick
                if guild_bot_user.nick is not None
                else guild_bot_user.name
            )
            try:

                tickets = dict(load_data(guild.id, "open_tickets"))
                stats = {}
                now = time.time()
                total_age = sum(now - ticket["created_at"] for ticket in tickets.values())
                avg_age_hours = (total_age / len(tickets)) / 3600 if tickets else 0
                stats["avg_ticket_age_h"] = round(avg_age_hours, 1)
                stats["open_tickets"] = len(tickets)
                stats["unanswered_tickets"] = 0 

                for ticket_id, ticket in tickets.items():
                    has_staff_reply = False
                    for message in ticket.get("transcript", []):
                        if message.get("is_staff", False):
                            has_staff_reply = True
                            break 
                    if not has_staff_reply:
                        stats["unanswered_tickets"] += 1
                
                stats["version"] = config.Discord.version
            except Exception as e:
                stats = {"members": "unable to load stats", "open_tickets": "unable to load stats", "unanswered_tickets": "unable to load stats", "version": config.Discord.version}
                print(f"Unable to load stats: {e}")
            
            return await render_template(
                "dash.html",
                data=guild_conf,
                guild=guild,
                user=user,
                channels=text_channels,
                voice_channels=voice_channels,
                categorys=catrgorys_list,
                roles=roles_list,
                roles_positions=roles_positions,
                bot_top_role_pos=bot_top_role_pos,
                nick=bot_nick,
                stats=stats,
                greeting=get_time_based_greeting(user.name),
                feature_adoption=get_feature_adoption(),
            )

        except discord.NotFound:
            return await render_template("error.html", message="Guild not found.")
        except discord.Forbidden:
            return await render_template(
                "error.html", message="Bot doesn't have access to this guild."
            )
        except Exception as e:
            print(f"Error in guild_manager: {e}")
            return await render_template(
                "error.html", message="An unexpected error occurred."
            )

    @app.route("/api/dash/save/", methods=["POST", "GET"])
    async def dash_api():
        system = quart.request.args.get("system")
        print(system)
        guild_id = quart.request.args.get("dash_login")

        if not system or not guild_id:
            return quart.jsonify({"success": False, "message": "Missing 'system' or 'guild_id' parameter."}), 400

        try:
            user = await discord_auth.fetch_user()
            guild = await bot.fetch_guild(int(guild_id))
            print(guild.name)
            print(guild.id)
            print(guild_id)

            try:
                guild_member = await guild.fetch_member(user.id)
            except discord.NotFound:
                return quart.jsonify({"success": False, "message": f"You are not on the guild {guild.name} and therefore do not have the required authorisations to manage this server."}), 403

            if not guild_member.guild_permissions.manage_guild:
                return quart.jsonify({"success": False, "message": f"Hello {user.name}! Unfortunately, you are not authorized to manage this guild."}), 403

        except discord.NotFound:
            return quart.jsonify({"success": False, "message": "Guild not found."}), 404
        except discord.Forbidden:
            return quart.jsonify({"success": False, "message": "Bot doesn't have access to this guild."}), 403
        except Exception as e:
            print(f"Error in guild_manager: {e}")
            return quart.jsonify({"success": False, "message": "An unexpected error occurred."}), 500

        if system == "chatfilter":
            data: dict = await quart.request.get_json()
            chatfilter = data.get("chatfilter")

            print(chatfilter)

            if not isinstance(chatfilter, dict):
                return quart.jsonify({"success": False, "message": "Invalid data format: 'chatfilter' must be an object."}), 400

            if chatfilter.get("system") is None or chatfilter["system"] not in [
                "SafeText",
                "AI",
            ]:
                return quart.jsonify({"success": False, "message": "Invalid or missing 'system'. Must be 'SafeText' or 'AI'."}), 400

            if chatfilter.get("enabled") is None or not isinstance(
                chatfilter["enabled"], bool
            ):
                return quart.jsonify({"success": False, "message": "'enabled' must be a boolean (true/false) and not null."}), 400

            if (
                chatfilter.get("c_goodwords") is None
                or not isinstance(chatfilter["c_goodwords"], list)
                or not all(isinstance(w, str) for w in chatfilter["c_goodwords"])
            ):
                return quart.jsonify({"success": False, "message": "'c_goodwords' must be a list of strings and not null."}), 400

            if (
                chatfilter.get("c_badwords") is None
                or not isinstance(chatfilter["c_badwords"], list)
                or not all(isinstance(w, str) for w in chatfilter["c_badwords"])
            ):
                return quart.jsonify({"success": False, "message": "'c_badwords' must be a list of strings and not null."}), 400

            if chatfilter.get("bypass") is not None and (
                not isinstance(chatfilter["bypass"], list)
                or not all(isinstance(w, str) for w in chatfilter["bypass"])
            ):
                return quart.jsonify({"success": False, "message": "'bypass' must be a list of strings or omitted."}), 400

            guild_conf: dict = cast(
                dict, load_data(sid=int(guild_id), sys="chatfilter")
            )

            # Validate ai_categories if provided
            raw_ai_cats = chatfilter.get("ai_categories")
            if raw_ai_cats is not None:
                valid_keys = {"1", "2", "3", "4", "5"}
                if (
                    not isinstance(raw_ai_cats, dict)
                    or not all(k in valid_keys and isinstance(v, bool) for k, v in raw_ai_cats.items())
                ):
                    return quart.jsonify({"success": False, "message": "'ai_categories' must be an object with keys 1–5 and boolean values."}), 400

            guild_conf.setdefault("enabled", False)
            guild_conf.setdefault("system", "")
            guild_conf.setdefault("c_goodwords", [])
            guild_conf.setdefault("c_badwords", [])
            guild_conf.setdefault("bypass", [])
            guild_conf.setdefault("ai_categories", {"1": True, "2": True, "3": True, "4": True, "5": True})

            guild_conf["enabled"] = chatfilter["enabled"]
            guild_conf["system"] = chatfilter["system"]
            guild_conf["c_goodwords"] = [
                w.strip() for w in chatfilter["c_goodwords"] if w and w.strip()
            ]
            guild_conf["c_badwords"] = [
                w.strip() for w in chatfilter["c_badwords"] if w and w.strip()
            ]
            guild_conf["bypass"] = [
                w.strip() for w in chatfilter.get("bypass", []) if w and w.strip()
            ]
            guild_conf["phishing_filter"] = bool(chatfilter.get("phishing_filter", False))
            if raw_ai_cats is not None:
                guild_conf["ai_categories"] = {
                    k: bool(raw_ai_cats.get(k, True)) for k in ("1", "2", "3", "4", "5")
                }

            print(guild_conf)

            save_data(int(guild_id), "chatfilter", guild_conf)

            user = await discord_auth.fetch_user()
            audit_log_new: dict = {
                "type": "save",
                "user": user.name,
                "success": True,
                "time": str(datetime.now(_VIENNA).strftime("%d.%m.%Y - %H:%M")),
                "sys": "chatfilter",
            }
            audit_log: list = cast(
                list, load_data(sid=int(guild_id), sys="audit_log", bot=bot)
            )
            audit_log.append(audit_log_new)
            save_data(int(guild_id), "audit_log", audit_log)

        elif system == "general":
            data: dict = await quart.request.get_json()
            general = data.get("general")

            if not isinstance(general, dict):
                return quart.jsonify({"success": False, "message": "Invalid data format: 'general' must be an object."}), 400
            if general.get("lang") is None or general["lang"] not in [
                "en",
                "de",
            ]:
                return quart.jsonify({"success": False, "message": "Invalid or missing 'lang'. Must be 'en' or 'de'."}), 400

            guild_conf_lang: str = str(load_data(sid=int(guild_id), sys="lang"))
            guild_conf_lang = general["lang"]

            assert bot.user is not None, "Bot user unknwon"
            guild_bot = await guild.fetch_member(bot.user.id)

            if str(general["nick"]).lower() != str(guild_bot.nick).lower():
                if str(general["nick"]).lower() == "" or general["nick"] is None:
                    await guild_bot.edit(nick=None)
                else:
                    await guild_bot.edit(nick=general["nick"])

            save_data(sid=int(guild_id), sys="lang", data=guild_conf_lang)

            guild_conf_terms = general.get("terms")
            print(guild_conf_terms)

            if guild_conf_terms is None:
                return quart.jsonify({"success": False, "message": "'terms' must be provided and not be null."}), 400

            if not isinstance(guild_conf_terms, bool):
                return quart.jsonify({"success": False, "message": "'terms' must be a boolean (true/false)."}), 400

            save_data(sid=int(guild_id), sys="terms", data=guild_conf_terms)

            notif_ch = str(general.get("notification_channel", "")).strip()
            if notif_ch and not notif_ch.isdigit():
                return quart.jsonify({"success": False, "message": "'notification_channel' must be a channel ID or empty."}), 400
            save_data(sid=int(guild_id), sys="notification_channel", data=notif_ch)

            user = await discord_auth.fetch_user()
            audit_log_new: dict = {
                "type": "save",
                "user": user.name,
                "success": True,
                "time": str(datetime.now(_VIENNA).strftime("%d.%m.%Y - %H:%M")),
                "sys": "general",
            }
            audit_log: list = cast(
                list, load_data(sid=int(guild_id), sys="audit_log", bot=bot)
            )
            audit_log.append(audit_log_new)
            save_data(int(guild_id), "audit_log", audit_log)

        elif system == "prism":
            data: dict = await quart.request.get_json()
            prism = data.get("prism")
            if not isinstance(prism, dict):
                return quart.jsonify({"success": False, "message": "Invalid data format: 'prism' must be an object."}), 400
            prism_enabled = prism.get("enabled", True)
            if not isinstance(prism_enabled, bool):
                return quart.jsonify({"success": False, "message": "'enabled' must be a boolean."}), 400
            save_data(sid=int(guild_id), sys="prism_enabled", data=prism_enabled)
            user = await discord_auth.fetch_user()
            audit_log_new: dict = {
                "type": "save",
                "user": user.name,
                "success": True,
                "time": str(datetime.now(_VIENNA).strftime("%d.%m.%Y - %H:%M")),
                "sys": "prism",
            }
            audit_log: list = cast(list, load_data(sid=int(guild_id), sys="audit_log", bot=bot))
            audit_log.append(audit_log_new)
            save_data(int(guild_id), "audit_log", audit_log)

        elif system == "globalchat":
            data: dict = await quart.request.get_json()
            globalchat = data.get("globalchat")

            if not isinstance(globalchat, dict):
                return quart.jsonify({"success": False, "message": "Invalid data format: 'globalchat' must be an object."}), 400

            if globalchat["enabled"] is None or not isinstance(
                globalchat["enabled"], bool
            ):
                return quart.jsonify({"success": False, "message": "'enabled' must be a boolean (true/false) and not null."}), 400

            if not isinstance(globalchat["channel"], str) or not re.fullmatch(
                r"\d{17,19}", globalchat["channel"]
            ):
                return quart.jsonify({"success": False, "message": "Channel ID does not match the Discord ID format."}), 400

            channel = await guild.fetch_channel(int(globalchat["channel"]))
            if channel is None:
                return quart.jsonify({"success": False, "message": "Selected channel unknown - ID not recognized."}), 400

            settings: dict = dict(load_data(1001, "globalchat"))

            if globalchat["enabled"] is False:
                settings.pop(str(guild.id), None)
            else:
                if str(guild.id) not in settings:
                    settings[str(guild.id)] = {}
                settings[str(guild.id)]["enabled"] = True
                settings[str(guild.id)]["channel"] = globalchat["channel"]
                settings[str(guild.id)]["gid"] = guild.id

            save_data(1001, "globalchat", settings)

            user = await discord_auth.fetch_user()
            audit_log_new: dict = {
                "type": "save",
                "user": user.name,
                "success": True,
                "time": str(datetime.now(_VIENNA).strftime("%d.%m.%Y - %H:%M")),
                "sys": "globalchat",
            }
            audit_log: list = cast(
                list, load_data(sid=int(guild_id), sys="audit_log", bot=bot)
            )
            audit_log.append(audit_log_new)
            save_data(int(guild_id), "audit_log", audit_log)

        elif system == "ticket":
            data: dict = await quart.request.get_json()
            ticket = data.get("ticket")
            print(ticket)

            if not isinstance(ticket, dict):
                return quart.jsonify({"success": False, "message": "Invalid data format: 'ticket' must be an object."}), 400
            if ticket["enabled"] is None or not isinstance(ticket["enabled"], bool):
                return quart.jsonify({"success": False, "message": "'enabled' must be a boolean (true/false) and not null."}), 400
            if not isinstance(ticket["channel"], str) or not re.fullmatch(
                r"\d{17,19}", ticket["channel"]
            ):
                return quart.jsonify({"success": False, "message": "Channel ID does not match the Discord ID format."}), 400

            if not isinstance(ticket["role"], str) or not re.fullmatch(
                r"\d{17,19}", ticket["role"]
            ):
                return quart.jsonify({"success": False, "message": "Role ID does not match the Discord ID format."}), 400

            if not isinstance(ticket["color"], str) or not bool(
                re.fullmatch(
                    r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})", ticket["color"]
                )
            ):
                return quart.jsonify({"success": False, "message": "You did not specify the color in a valid HEX format."}), 400

            bot_member_check = await guild.fetch_member(bot.user.id) # type: ignore
            bot_top_role = bot_member_check.top_role
            guild_roles_sorted = sorted(guild.roles, key=lambda r: r.position, reverse=True)
            if bot_top_role.position != guild_roles_sorted[0].position:
                return quart.jsonify({
                    "success": False,
                    "message": f"Bot role \"{bot_top_role.name}\" is not at the top of the role hierarchy. The ticket system requires the bot role to be highest so it can manage channel permissions."
                }), 403

            settings: dict = dict(load_data(guild.id, "ticket"))

            channel = await guild.fetch_channel(int(ticket["channel"]))
            if channel is None:
                return quart.jsonify({"success": False, "message": "The specified channel is unknown. Was it deleted before saving? Reload the page and try again."}), 400
            if not isinstance(channel, discord.TextChannel):
                return quart.jsonify({"success": False, "message": "The specified channel is not a text channel."}), 400

            cat = await guild.fetch_channel(int(ticket["category"]))
            if cat is None:
                return quart.jsonify({"success": False, "message": "The specified category is unknown. Was it deleted before saving? Reload the page and try again."}), 400
            if not isinstance(cat, discord.CategoryChannel):
                return quart.jsonify({"success": False, "message": "The specified category is not a category."}), 400

            settings.setdefault("enabled", False)
            settings.setdefault("channel", "")
            settings.setdefault("transcript", "")
            settings.setdefault("role", "")
            settings.setdefault("catid", "")
            settings.setdefault("color", "")
            settings.setdefault("message", "")

            if ticket["enabled"] is False:
                settings["enabled"] = False
                settings["channel"] = ""
                settings["transcript"] = ""
                settings["role"] = ""
                settings["catid"] = ""
                settings["color"] = ""
                settings["message"] = ""
            else:
                settings["enabled"] = True
                settings["channel"] = ticket["channel"]
                settings["transcript"] = ticket["channel_transcript"]
                settings["role"] = ticket["role"]
                settings["catid"] = ticket["category"]
                settings["color"] = ticket["color"]
                settings["message"] = ticket["message"]

            embed = discord.Embed(
                title=f"{config.Icons.questionmark} SYS // {guild.name} SUPPORT",
                description=ticket["message"],
                color=discord.Color.from_str(ticket["color"]),
            )

            panel_msg = await channel.send(embed=embed, view=TicketView())
            settings["panel_message_id"] = str(panel_msg.id)

            save_data(guild.id, "ticket", settings)

            user = await discord_auth.fetch_user()
            audit_log_new: dict = {
                "type": "save",
                "user": user.name,
                "success": True,
                "time": str(datetime.now(_VIENNA).strftime("%d.%m.%Y - %H:%M")),
                "sys": "ticket",
            }
            audit_log: list = cast(
                list, load_data(sid=int(guild_id), sys="audit_log", bot=bot)
            )
            audit_log.append(audit_log_new)
            save_data(int(guild_id), "audit_log", audit_log)

        elif system == "antispam":
            data: dict = await quart.request.get_json()
            antispam = data.get("antispam")

            if not isinstance(antispam, dict):
                return quart.jsonify({"success": False, "message": "Invalid data format: 'antispam' must be an object."}), 400

            if not isinstance(antispam.get("enabled"), bool):
                return quart.jsonify({"success": False, "message": "'enabled' must be a boolean."}), 400

            settings = {
                "enabled": antispam["enabled"],
                "max_messages": max(2, min(20, int(antispam.get("max_messages", 5)))),
                "interval": max(2, min(30, int(antispam.get("interval", 5)))),
                "max_duplicates": max(2, min(10, int(antispam.get("max_duplicates", 3)))),
                "action": antispam.get("action", "mute") if antispam.get("action") in ["mute", "warn", "kick", "ban"] else "mute",
            }

            save_data(int(guild_id), "antispam", settings)

            user = await discord_auth.fetch_user()
            audit_log_new: dict = {
                "type": "save",
                "user": user.name,
                "success": True,
                "time": str(datetime.now(_VIENNA).strftime("%d.%m.%Y - %H:%M")),
                "sys": "antispam",
            }
            audit_log: list = cast(
                list, load_data(sid=int(guild_id), sys="audit_log", bot=bot)
            )
            audit_log.append(audit_log_new)
            save_data(int(guild_id), "audit_log", audit_log)

        elif system == "warn_config":
            data: dict = await quart.request.get_json()
            wc = data.get("warn_config")

            if not isinstance(wc, dict):
                return quart.jsonify({"success": False, "message": "Invalid data format."}), 400

            try:
                mute_at = max(1, min(20, int(wc.get("mute_at", 3))))
                kick_at = max(1, min(30, int(wc.get("kick_at", 5))))
                ban_at = max(1, min(50, int(wc.get("ban_at", 7))))
                mute_duration = max(60, min(604800, int(wc.get("mute_duration", 600))))
            except (ValueError, TypeError):
                return quart.jsonify({"success": False, "message": "All fields must be integers."}), 400

            settings = {
                "mute_at": mute_at,
                "kick_at": kick_at,
                "ban_at": ban_at,
                "mute_duration": mute_duration,
            }
            save_data(int(guild_id), "warn_config", settings)

            user = await discord_auth.fetch_user()
            audit_log_new: dict = {
                "type": "save",
                "user": user.name,
                "success": True,
                "time": str(datetime.now(_VIENNA).strftime("%d.%m.%Y - %H:%M")),
                "sys": "warn_config",
            }
            audit_log: list = cast(
                list, load_data(sid=int(guild_id), sys="audit_log", bot=bot)
            )
            audit_log.append(audit_log_new)
            save_data(int(guild_id), "audit_log", audit_log)

        elif system == "welcomer":
            data: dict = await quart.request.get_json()
            welcomer = data.get("welcomer")

            if not isinstance(welcomer, dict):
                return quart.jsonify({"success": False, "message": "Invalid data format: 'welcomer' must be an object."}), 400

            if not isinstance(welcomer.get("enabled"), bool):
                return quart.jsonify({"success": False, "message": "'enabled' must be a boolean."}), 400

            # Validate color hex
            color = str(welcomer.get("color", "#6F83AA"))[:7]
            if not re.match(r'^#[0-9a-fA-F]{6}$', color):
                color = "#6F83AA"

            card_color = str(welcomer.get("card_color", "#1a1a2e"))[:7]
            if not re.match(r'^#[0-9a-fA-F]{6}$', card_color):
                card_color = "#1a1a2e"

            leave_color = str(welcomer.get("leave_color", "#FFC107"))[:7]
            if not re.match(r'^#[0-9a-fA-F]{6}$', leave_color):
                leave_color = "#FFC107"

            image_mode = str(welcomer.get("image_mode", "none"))
            if image_mode not in ("none", "generate"):
                image_mode = "none"

            # Check if custom bg exists
            import os
            bg_path = f"data/{guild_id}/welcomer_bg.png"
            has_custom_bg = os.path.exists(bg_path)

            # Convert channel IDs to strings for consistency with frontend
            channel_val = welcomer.get("channel", "")
            channel_str = str(channel_val) if channel_val and str(channel_val).isdigit() else ""
            
            leave_channel_val = welcomer.get("leave_channel", "")
            leave_channel_str = str(leave_channel_val) if leave_channel_val and str(leave_channel_val).isdigit() else ""
            
            settings = {
                "enabled": welcomer["enabled"],
                "channel": channel_str,
                "message": str(welcomer.get("message", ""))[:1024],
                "leave_enabled": bool(welcomer.get("leave_enabled", False)),
                "leave_channel": leave_channel_str,
                "leave_message": str(welcomer.get("leave_message", ""))[:1024],
                "color": color,
                "image_mode": image_mode,
                "card_color": card_color,
                "leave_color": leave_color,
                "has_custom_bg": has_custom_bg,
            }

            save_data(int(guild_id), "welcomer", settings)

            user = await discord_auth.fetch_user()
            audit_log_new: dict = {
                "type": "save",
                "user": user.name,
                "success": True,
                "time": str(datetime.now(_VIENNA).strftime("%d.%m.%Y - %H:%M")),
                "sys": "welcomer",
            }
            audit_log: list = cast(
                list, load_data(sid=int(guild_id), sys="audit_log", bot=bot)
            )
            audit_log.append(audit_log_new)
            save_data(int(guild_id), "audit_log", audit_log)

        elif system == "custom_commands":
            data: dict = await quart.request.get_json()
            cmd_data = data.get("custom_commands")

            if not isinstance(cmd_data, dict):
                return quart.jsonify({"success": False, "message": "Invalid data format."}), 400

            action = cmd_data.get("action")
            custom_commands: dict = dict(load_data(int(guild_id), "custom_commands"))

            if action == "add":
                trigger = str(cmd_data.get("trigger", "")).strip()
                response = str(cmd_data.get("response", "")).strip()
                embed = bool(cmd_data.get("embed", True))

                if not trigger or not response:
                    return quart.jsonify({"success": False, "message": "Trigger and response are required."}), 400

                if len(trigger) > 50:
                    return quart.jsonify({"success": False, "message": "Trigger must be 50 characters or less."}), 400

                if len(response) > 2000:
                    return quart.jsonify({"success": False, "message": "Response must be 2000 characters or less."}), 400

                if trigger.lower() in {k.lower() for k in custom_commands}:
                    return quart.jsonify({"success": False, "message": f"Command '{trigger}' already exists."}), 400

                # Embed styling fields
                embed_color = str(cmd_data.get("embed_color", ""))[:7]
                if embed_color and not re.match(r'^#[0-9a-fA-F]{6}$', embed_color):
                    embed_color = ""
                embed_title = str(cmd_data.get("embed_title", ""))[:256]
                embed_footer = str(cmd_data.get("embed_footer", ""))[:256]

                user = await discord_auth.fetch_user()
                custom_commands[trigger] = {
                    "response": response,
                    "embed": embed,
                    "embed_color": embed_color,
                    "embed_title": embed_title,
                    "embed_footer": embed_footer,
                    "created_by": str(user.name),
                    "created_by_id": int(user.id),
                    "created_at": str(datetime.now(_VIENNA).strftime("%Y-%m-%d")),
                }

            elif action == "remove":
                trigger = str(cmd_data.get("trigger", "")).strip()
                found_key = None
                for key in custom_commands:
                    if key.lower() == trigger.lower():
                        found_key = key
                        break
                if found_key is None:
                    return quart.jsonify({"success": False, "message": f"Command '{trigger}' not found."}), 404
                del custom_commands[found_key]

            else:
                return quart.jsonify({"success": False, "message": "Invalid action. Use 'add' or 'remove'."}), 400

            save_data(int(guild_id), "custom_commands", custom_commands)

            user = await discord_auth.fetch_user()
            audit_log_new: dict = {
                "type": "save",
                "user": user.name,
                "success": True,
                "time": str(datetime.now(_VIENNA).strftime("%d.%m.%Y - %H:%M")),
                "sys": "custom_commands",
            }
            audit_log: list = cast(
                list, load_data(sid=int(guild_id), sys="audit_log", bot=bot)
            )
            audit_log.append(audit_log_new)
            save_data(int(guild_id), "audit_log", audit_log)

        elif system == "livestream":
            data: dict = await quart.request.get_json()
            livestream = data.get("livestream")

            if not isinstance(livestream, dict):
                return quart.jsonify({"success": False, "message": "Invalid data format: 'livestream' must be an object."}), 400

            action = livestream.get("action", "save")

            if action == "add":
                platform = str(livestream.get("platform", "twitch")).strip().lower()
                if platform not in ("twitch", "youtube", "tiktok"):
                    return quart.jsonify({"success": False, "message": "Invalid platform. Choose twitch, youtube, or tiktok."}), 400

                login = str(livestream.get("login", "")).strip()
                if not login:
                    return quart.jsonify({"success": False, "message": "Username / channel ID is required."}), 400

                # Platform-specific input validation
                if platform == "twitch":
                    login = login.lower()
                    if not re.fullmatch(r"[a-z0-9_]{2,25}", login):
                        return quart.jsonify({"success": False, "message": "Invalid Twitch username format."}), 400
                elif platform == "youtube":
                    # Accept @handle, handle, or UCxxx channel ID
                    if not re.fullmatch(r"[@a-zA-Z0-9_.\-]{2,64}", login):
                        return quart.jsonify({"success": False, "message": "Invalid YouTube channel handle or ID."}), 400
                elif platform == "tiktok":
                    login = login.lstrip("@").lower()
                    if not re.fullmatch(r"[a-z0-9_.]{2,24}", login):
                        return quart.jsonify({"success": False, "message": "Invalid TikTok username format."}), 400

                ls_config = dict(load_data(int(guild_id), "livestream"))
                streamers = ls_config.get("streamers", [])

                if len(streamers) >= 10:
                    return quart.jsonify({"success": False, "message": "Maximum of 10 streamers reached."}), 400

                # Validate user exists on the platform and get profile info
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                    if platform == "twitch":
                        users = await twitch_api.get_users(session, [login])
                        if login not in users:
                            return quart.jsonify({"success": False, "message": f"Twitch user '{login}' not found."}), 404
                        profile = users[login]
                        display_name = profile["display_name"]
                        profile_image_url = profile.get("profile_image_url", "")
                        offline_image_url = profile.get("offline_image_url", "")
                        resolved_login = login  # Twitch login stays as-is

                    elif platform == "youtube":
                        channel_info = await youtube_api.get_channel(session, login)
                        if not channel_info:
                            return quart.jsonify({"success": False, "message": f"YouTube channel '{login}' not found. Try using the channel ID (UCxxx) or @handle."}), 404
                        resolved_login = channel_info["channel_id"]  # store channel ID
                        display_name = channel_info["display_name"]
                        profile_image_url = channel_info.get("profile_image_url", "")
                        offline_image_url = ""

                    else:  # tiktok
                        user_info = await tiktok_api.get_user_info(session, login)
                        if not user_info:
                            return quart.jsonify({"success": False, "message": f"TikTok user '{login}' not found or TikTok API unavailable."}), 404
                        resolved_login = login
                        display_name = user_info.get("display_name", login)
                        profile_image_url = user_info.get("profile_image_url", "")
                        offline_image_url = ""

                # Prevent duplicate tracking (same platform + login)
                if any(
                    s.get("login", "").lower() == resolved_login.lower()
                    and s.get("platform", "twitch") == platform
                    for s in streamers
                ):
                    return quart.jsonify({"success": False, "message": f"'{display_name}' is already being tracked on {platform}."}), 400

                # Create a text channel for this streamer
                category_id = ls_config.get("category_id", "")
                category = None
                if category_id:
                    try:
                        cat_channel = await guild.fetch_channel(int(category_id))
                        if isinstance(cat_channel, discord.CategoryChannel):
                            category = cat_channel
                    except (discord.NotFound, discord.HTTPException, ValueError):
                        pass

                lang_file = datasys.load_lang_file(int(guild_id))
                ls_lang = lang_file.get("systems", {}).get("livestream", {})
                channel_name = ls_lang.get("channel_name_offline", "\u26ab\u2502{name}").format(
                    name=display_name.lower()
                )

                try:
                    new_channel = await guild.create_text_channel(
                        name=channel_name,
                        category=category,
                        reason=f"Baxi Livestream: tracking {display_name} ({platform})",
                    )
                except discord.Forbidden:
                    return quart.jsonify({"success": False, "message": "Bot does not have permission to create channels."}), 403

                # Build initial offline embed
                if platform == "twitch":
                    profile_url = f"https://twitch.tv/{resolved_login}"
                elif platform == "youtube":
                    profile_url = f"https://www.youtube.com/channel/{resolved_login}"
                else:
                    profile_url = f"https://www.tiktok.com/@{resolved_login}"

                offline_embed = discord.Embed(
                    title=ls_lang.get("embed_offline_title", "{name} is offline").format(name=display_name),
                    description=ls_lang.get("embed_offline_description", "{name} is not streaming right now. Check back later!").format(name=display_name),
                    url=profile_url,
                    color=discord.Color.red(),
                )
                if offline_image_url:
                    offline_embed.set_image(url=offline_image_url)
                if profile_image_url:
                    offline_embed.set_thumbnail(url=profile_image_url)
                offline_embed.set_footer(text=ls_lang.get("embed_footer", "Baxi Livestream - avocloud.net"))

                msg = await new_channel.send(embed=offline_embed)

                streamer_entry = {
                    "platform": platform,
                    "login": resolved_login,
                    "display_name": display_name,
                    "channel_id": str(new_channel.id),
                    "message_id": str(msg.id),
                    "profile_image_url": profile_image_url,
                }
                streamers.append(streamer_entry)
                ls_config["streamers"] = streamers
                save_data(int(guild_id), "livestream", ls_config)

            elif action == "remove":
                login = str(livestream.get("login", "")).strip()
                platform = str(livestream.get("platform", "twitch")).strip().lower()
                if not login:
                    return quart.jsonify({"success": False, "message": "Login is required."}), 400

                ls_config = dict(load_data(int(guild_id), "livestream"))
                streamers = ls_config.get("streamers", [])
                found = None
                for s in streamers:
                    if (
                        s.get("login", "").lower() == login.lower()
                        and s.get("platform", "twitch") == platform
                    ):
                        found = s
                        break

                if not found:
                    return quart.jsonify({"success": False, "message": f"'{login}' is not being tracked on {platform}."}), 404

                # Delete the Discord channel
                channel_id = found.get("channel_id")
                if channel_id:
                    try:
                        ch = await guild.fetch_channel(int(channel_id))
                        await ch.delete(reason=f"Baxi Livestream: stopped tracking {login}")
                    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                        pass

                streamers = [
                    s for s in streamers
                    if not (s.get("login", "").lower() == login.lower() and s.get("platform", "twitch") == platform)
                ]
                ls_config["streamers"] = streamers
                save_data(int(guild_id), "livestream", ls_config)

            elif action == "save":
                if not isinstance(livestream.get("enabled"), bool):
                    return quart.jsonify({"success": False, "message": "'enabled' must be a boolean."}), 400

                ls_config = dict(load_data(int(guild_id), "livestream"))
                ls_config["enabled"] = livestream["enabled"]

                category_id = str(livestream.get("category_id", "")).strip()
                if category_id and not re.fullmatch(r"\d{17,19}", category_id):
                    return quart.jsonify({"success": False, "message": "Invalid category ID format."}), 400
                ls_config["category_id"] = category_id

                ping_role = str(livestream.get("ping_role", "")).strip()
                if ping_role and not re.fullmatch(r"\d{17,19}", ping_role):
                    return quart.jsonify({"success": False, "message": "Invalid ping role ID format."}), 400
                ls_config["ping_role"] = ping_role

                save_data(int(guild_id), "livestream", ls_config)

            user = await discord_auth.fetch_user()
            audit_log_new: dict = {
                "type": "save",
                "user": user.name,
                "success": True,
                "time": str(datetime.now(_VIENNA).strftime("%d.%m.%Y - %H:%M")),
                "sys": "livestream",
            }
            audit_log: list = cast(
                list, load_data(sid=int(guild_id), sys="audit_log", bot=bot)
            )
            audit_log.append(audit_log_new)
            save_data(int(guild_id), "audit_log", audit_log)

        elif system == "stats_channels":
            data: dict = await quart.request.get_json()
            sc_data = data.get("stats_channels")

            if not isinstance(sc_data, dict):
                return quart.jsonify({"success": False, "message": "Invalid data format: 'stats_channels' must be an object."}), 400

            if not isinstance(sc_data.get("enabled"), bool):
                return quart.jsonify({"success": False, "message": "'enabled' must be a boolean."}), 400

            category_id = str(sc_data.get("category_id", "")).strip()
            if category_id and not re.fullmatch(r"\d{17,19}", category_id):
                return quart.jsonify({"success": False, "message": "Invalid category ID format."}), 400

            allowed_stat_types = ["members", "humans", "bots", "channels", "roles"]
            sc_config = dict(load_data(int(guild_id), "stats_channels"))
            old_stats = sc_config.get("stats", {})
            new_stats = {}

            incoming_stats = sc_data.get("stats", {})
            if not isinstance(incoming_stats, dict):
                return quart.jsonify({"success": False, "message": "'stats' must be an object."}), 400

            for stat_type in allowed_stat_types:
                stat = incoming_stats.get(stat_type, {})
                if not isinstance(stat, dict):
                    stat = {}

                stat_enabled = bool(stat.get("enabled", False))
                template = str(stat.get("template", f"{stat_type.capitalize()}: {{count}}"))[:64]
                # Replace any literal \{count\} variant back to {count}
                if "{count}" not in template:
                    template = f"{stat_type.capitalize()}: {{count}}"

                old_stat = old_stats.get(stat_type, {})
                old_channel_id = old_stat.get("channel_id", "")

                if stat_enabled and not old_channel_id:
                    # Create a new voice channel for this stat
                    try:
                        category = None
                        if category_id:
                            fetched_cat = await guild.fetch_channel(int(category_id))
                            if isinstance(fetched_cat, discord.CategoryChannel):
                                category = fetched_cat

                        cached_guild = bot.get_guild(int(guild_id))
                        if cached_guild is not None:
                            _counts = {
                                "members": cached_guild.member_count or 0,
                                "humans": sum(1 for m in cached_guild.members if not m.bot),
                                "bots": sum(1 for m in cached_guild.members if m.bot),
                                "channels": len(cached_guild.channels),
                                "roles": len(cached_guild.roles),
                            }
                            initial_name = template.replace("{count}", str(_counts.get(stat_type, 0)))
                        else:
                            initial_name = template.replace("{count}", "…")
                        new_ch = await guild.create_voice_channel(
                            name=initial_name,
                            category=category,
                            reason="Baxi Stats Channel setup",
                        )
                        # Make the channel read-only for everyone
                        await new_ch.set_permissions(
                            guild.default_role,
                            connect=False,
                            view_channel=True,
                        )
                        new_stats[stat_type] = {
                            "enabled": True,
                            "channel_id": str(new_ch.id),
                            "template": template,
                        }
                    except discord.Forbidden:
                        return quart.jsonify({"success": False, "message": f"Missing permissions to create voice channel for '{stat_type}'."}), 403
                    except Exception as e:
                        return quart.jsonify({"success": False, "message": f"Could not create channel for '{stat_type}': {e}"}), 500

                elif not stat_enabled and old_channel_id:
                    # Delete the voice channel
                    try:
                        ch = await guild.fetch_channel(int(old_channel_id))
                        await ch.delete(reason="Baxi Stats Channel removed")
                    except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                        pass
                    new_stats[stat_type] = {"enabled": False, "channel_id": "", "template": template}

                else:
                    # Keep existing channel_id, just update template/enabled
                    new_stats[stat_type] = {
                        "enabled": stat_enabled,
                        "channel_id": old_channel_id,
                        "template": template,
                    }

            sc_config["enabled"] = sc_data["enabled"]
            sc_config["category_id"] = category_id
            sc_config["stats"] = new_stats
            save_data(int(guild_id), "stats_channels", sc_config)

            user = await discord_auth.fetch_user()
            audit_log_new: dict = {
                "type": "save",
                "user": user.name,
                "success": True,
                "time": str(datetime.now(_VIENNA).strftime("%d.%m.%Y - %H:%M")),
                "sys": "stats_channels",
            }
            audit_log: list = cast(
                list, load_data(sid=int(guild_id), sys="audit_log", bot=bot)
            )
            audit_log.append(audit_log_new)
            save_data(int(guild_id), "audit_log", audit_log)

        elif system == "auto_roles":
            data: dict = await quart.request.get_json()
            ar_data = data.get("auto_roles")

            if not isinstance(ar_data, dict):
                return quart.jsonify({"success": False, "message": "Invalid data format: 'auto_roles' must be an object."}), 400

            if not isinstance(ar_data.get("enabled"), bool):
                return quart.jsonify({"success": False, "message": "'enabled' must be a boolean."}), 400

            role_ids = ar_data.get("roles", [])
            if not isinstance(role_ids, list) or not all(isinstance(r, str) and re.fullmatch(r"\d{17,19}", r) for r in role_ids):
                return quart.jsonify({"success": False, "message": "'roles' must be a list of valid Discord role ID strings."}), 400

            ar_config = {"enabled": ar_data["enabled"], "roles": role_ids}
            save_data(int(guild_id), "auto_roles", ar_config)

            user = await discord_auth.fetch_user()
            audit_log_new: dict = {
                "type": "save",
                "user": user.name,
                "success": True,
                "time": str(datetime.now(_VIENNA).strftime("%d.%m.%Y - %H:%M")),
                "sys": "auto_roles",
            }
            audit_log: list = cast(
                list, load_data(sid=int(guild_id), sys="audit_log", bot=bot)
            )
            audit_log.append(audit_log_new)
            save_data(int(guild_id), "audit_log", audit_log)

        elif system == "temp_voice":
            data: dict = await quart.request.get_json()
            tv_data = data.get("temp_voice")

            if not isinstance(tv_data, dict):
                return quart.jsonify({"success": False, "message": "Invalid data format: 'temp_voice' must be an object."}), 400

            if not isinstance(tv_data.get("enabled"), bool):
                return quart.jsonify({"success": False, "message": "'enabled' must be a boolean."}), 400

            create_channel_id = str(tv_data.get("create_channel_id", "")).strip()
            if create_channel_id and not re.fullmatch(r"\d{17,19}", create_channel_id):
                return quart.jsonify({"success": False, "message": "Invalid create_channel_id format."}), 400

            category_id = str(tv_data.get("category_id", "")).strip()
            if category_id and not re.fullmatch(r"\d{17,19}", category_id):
                return quart.jsonify({"success": False, "message": "Invalid category_id format."}), 400

            name_template = str(tv_data.get("name_template", "{user}'s Channel"))[:64].strip()
            if not name_template:
                name_template = "{user}'s Channel"

            tv_config = {
                "enabled": tv_data["enabled"],
                "create_channel_id": create_channel_id,
                "category_id": category_id,
                "name_template": name_template,
            }
            save_data(int(guild_id), "temp_voice", tv_config)

            user = await discord_auth.fetch_user()
            audit_log_new: dict = {
                "type": "save",
                "user": user.name,
                "success": True,
                "time": str(datetime.now(_VIENNA).strftime("%d.%m.%Y - %H:%M")),
                "sys": "temp_voice",
            }
            audit_log: list = cast(
                list, load_data(sid=int(guild_id), sys="audit_log", bot=bot)
            )
            audit_log.append(audit_log_new)
            save_data(int(guild_id), "audit_log", audit_log)

        elif system == "verify":
            data: dict = await quart.request.get_json()
            verify = data.get("verify")

            if not isinstance(verify, dict):
                return quart.jsonify({"success": False, "message": "Invalid data format: 'verify' must be an object."}), 400

            if not isinstance(verify.get("enabled"), bool):
                return quart.jsonify({"success": False, "message": "'enabled' must be a boolean."}), 400

            verify_option = verify.get("verify_option", 0)
            if verify_option not in (0, 1, 2):
                return quart.jsonify({"success": False, "message": "'verify_option' must be 0, 1 or 2."}), 400

            rid_raw = str(verify.get("rid", "")).strip()
            if rid_raw and not re.fullmatch(r"\d{17,19}", rid_raw):
                return quart.jsonify({"success": False, "message": "Invalid role ID format."}), 400

            channel_raw = str(verify.get("channel", "")).strip()
            if channel_raw and not re.fullmatch(r"\d{17,19}", channel_raw):
                return quart.jsonify({"success": False, "message": "Invalid channel ID format."}), 400

            color = str(verify.get("color", "#9333ea"))[:7]
            if not re.match(r'^#[0-9a-fA-F]{6}$', color):
                color = "#9333ea"

            current: dict = dict(load_data(int(guild_id), "verify"))
            current.update({
                "enabled": verify["enabled"],
                "rid": rid_raw,
                "verify_option": verify_option,
                "password": str(verify.get("password", ""))[:100],
                "channel": channel_raw,
                "title": str(verify.get("title", "Verification"))[:100],
                "description": str(verify.get("description", "Click the button below to verify."))[:500],
                "color": color,
            })

            # Post / repost verification panel if requested
            if verify.get("post_panel") and channel_raw and current["enabled"]:
                try:
                    from assets.buttons import VerifyView
                    ch = await guild.fetch_channel(int(channel_raw))
                    if not isinstance(ch, discord.TextChannel):
                        return quart.jsonify({"success": False, "message": "Selected channel is not a text channel."}), 400
                    try:
                        embed_color = discord.Color.from_str(color)
                    except Exception:
                        embed_color = discord.Color.from_rgb(147, 51, 234)
                    embed = discord.Embed(
                        title=current["title"],
                        description=current["description"],
                        color=embed_color,
                    )
                    embed.set_footer(text="Baxi · Verification")
                    panel_msg = await ch.send(embed=embed, view=VerifyView())
                    current["panel_message_id"] = str(panel_msg.id)
                except discord.Forbidden:
                    return quart.jsonify({"success": False, "message": "Bot does not have permission to send messages in that channel."}), 403
                except Exception as e:
                    return quart.jsonify({"success": False, "message": f"Could not post panel: {e}"}), 500

            save_data(int(guild_id), "verify", current)

            user = await discord_auth.fetch_user()
            audit_log_new: dict = {
                "type": "save",
                "user": user.name,
                "success": True,
                "time": str(datetime.now(_VIENNA).strftime("%d.%m.%Y - %H:%M")),
                "sys": "verify",
            }
            audit_log: list = cast(list, load_data(sid=int(guild_id), sys="audit_log", bot=bot))
            audit_log.append(audit_log_new)
            save_data(int(guild_id), "audit_log", audit_log)

        elif system == "auto_slowmode":
            data: dict = await quart.request.get_json()
            asm = data.get("auto_slowmode")

            if not isinstance(asm, dict):
                return quart.jsonify({"success": False, "message": "Invalid data format: 'auto_slowmode' must be an object."}), 400

            if not isinstance(asm.get("enabled"), bool):
                return quart.jsonify({"success": False, "message": "'enabled' must be a boolean."}), 400

            try:
                settings = {
                    "enabled": asm["enabled"],
                    "threshold": max(2, min(50, int(asm.get("threshold", 10)))),
                    "interval": max(2, min(60, int(asm.get("interval", 10)))),
                    "slowmode_delay": max(1, min(21600, int(asm.get("slowmode_delay", 5)))),
                    "duration": max(10, min(3600, int(asm.get("duration", 120)))),
                }
            except (ValueError, TypeError):
                return quart.jsonify({"success": False, "message": "All numeric fields must be integers."}), 400

            save_data(int(guild_id), "auto_slowmode", settings)

            user = await discord_auth.fetch_user()
            audit_log_new: dict = {
                "type": "save",
                "user": user.name,
                "success": True,
                "time": str(datetime.now(_VIENNA).strftime("%d.%m.%Y - %H:%M")),
                "sys": "auto_slowmode",
            }
            audit_log: list = cast(list, load_data(sid=int(guild_id), sys="audit_log", bot=bot))
            audit_log.append(audit_log_new)
            save_data(int(guild_id), "audit_log", audit_log)

        elif system == "reaction_roles":
            data: dict = await quart.request.get_json()
            rr = data.get("reaction_roles")

            if not isinstance(rr, dict):
                return quart.jsonify({"success": False, "message": "Invalid data format: 'reaction_roles' must be an object."}), 400

            action = rr.get("action")
            rr_config: dict = dict(load_data(int(guild_id), "reaction_roles"))
            panels: list = rr_config.get("panels", [])

            if action == "add_panel":
                channel_id_raw = str(rr.get("channel_id", "")).strip()
                if not re.fullmatch(r"\d{17,19}", channel_id_raw):
                    return quart.jsonify({"success": False, "message": "Invalid channel ID."}), 400

                title = str(rr.get("title", "Reaction Roles"))[:100]
                description = str(rr.get("description", "React to get a role!"))[:500]
                color = str(rr.get("color", "#9333ea"))[:7]
                if not re.match(r'^#[0-9a-fA-F]{6}$', color):
                    color = "#9333ea"

                try:
                    ch = await guild.fetch_channel(int(channel_id_raw))
                    if not isinstance(ch, discord.TextChannel):
                        return quart.jsonify({"success": False, "message": "Selected channel is not a text channel."}), 400
                except discord.NotFound:
                    return quart.jsonify({"success": False, "message": "Channel not found."}), 404
                except discord.Forbidden:
                    return quart.jsonify({"success": False, "message": "Bot cannot access that channel."}), 403

                panel_data = {
                    "channel_id": channel_id_raw,
                    "message_id": "",
                    "title": title,
                    "description": description,
                    "color": color,
                    "entries": [],
                }

                from assets.message.reactionroles import build_panel_embed, build_panel_view
                embed = build_panel_embed(panel_data)
                try:
                    msg = await ch.send(embed=embed, view=build_panel_view(panel_data))
                    panel_data["message_id"] = str(msg.id)
                except discord.Forbidden:
                    return quart.jsonify({"success": False, "message": "Bot cannot send messages in that channel."}), 403

                panels.append(panel_data)
                rr_config["panels"] = panels
                save_data(int(guild_id), "reaction_roles", rr_config)

            elif action == "remove_panel":
                message_id = str(rr.get("message_id", "")).strip()
                panel_to_remove = None
                for p in panels:
                    if str(p.get("message_id", "")) == message_id:
                        panel_to_remove = p
                        break
                if panel_to_remove is None:
                    return quart.jsonify({"success": False, "message": "Panel not found."}), 404

                # Try to delete the Discord message
                try:
                    ch = await guild.fetch_channel(int(panel_to_remove["channel_id"]))
                    msg = await ch.fetch_message(int(message_id))  # type: ignore
                    await msg.delete()
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass

                panels = [p for p in panels if str(p.get("message_id", "")) != message_id]
                rr_config["panels"] = panels
                save_data(int(guild_id), "reaction_roles", rr_config)

            elif action == "add_entry":
                message_id = str(rr.get("message_id", "")).strip()
                emoji = str(rr.get("emoji", "")).strip()
                role_id_raw = str(rr.get("role_id", "")).strip()
                label = str(rr.get("label", ""))[:50]

                if not re.fullmatch(r"\d{17,19}", role_id_raw):
                    return quart.jsonify({"success": False, "message": "Invalid role ID."}), 400
                if not emoji and not label:
                    return quart.jsonify({"success": False, "message": "Provide at least an emoji or a label."}), 400

                panel = next((p for p in panels if str(p.get("message_id", "")) == message_id), None)
                if panel is None:
                    return quart.jsonify({"success": False, "message": "Panel not found."}), 404

                # Check duplicate role in same panel
                if any(str(e.get("role_id")) == role_id_raw for e in panel.get("entries", [])):
                    return quart.jsonify({"success": False, "message": "This role already has a button in this panel."}), 400

                panel.setdefault("entries", []).append({
                    "emoji": emoji,
                    "role_id": role_id_raw,
                    "label": label,
                })

                # Update the Discord message with new embed + buttons
                from assets.message.reactionroles import build_panel_embed, build_panel_view
                try:
                    ch = await guild.fetch_channel(int(panel["channel_id"]))
                    msg = await ch.fetch_message(int(message_id))  # type: ignore
                    await msg.edit(embed=build_panel_embed(panel), view=build_panel_view(panel))
                except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
                    return quart.jsonify({"success": False, "message": f"Could not update panel: {e}"}), 500

                rr_config["panels"] = panels
                save_data(int(guild_id), "reaction_roles", rr_config)

            elif action == "remove_entry":
                message_id = str(rr.get("message_id", "")).strip()
                emoji = str(rr.get("emoji", "")).strip()

                panel = next((p for p in panels if str(p.get("message_id", "")) == message_id), None)
                if panel is None:
                    return quart.jsonify({"success": False, "message": "Panel not found."}), 404

                panel["entries"] = [e for e in panel.get("entries", []) if e.get("emoji") != emoji]

                from assets.message.reactionroles import build_panel_embed, build_panel_view
                try:
                    ch = await guild.fetch_channel(int(panel["channel_id"]))
                    msg = await ch.fetch_message(int(message_id))  # type: ignore
                    await msg.edit(embed=build_panel_embed(panel), view=build_panel_view(panel))
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass

                rr_config["panels"] = panels
                save_data(int(guild_id), "reaction_roles", rr_config)

            else:
                return quart.jsonify({"success": False, "message": "Invalid action."}), 400

            user = await discord_auth.fetch_user()
            audit_log_new: dict = {
                "type": "save",
                "user": user.name,
                "success": True,
                "time": str(datetime.now(_VIENNA).strftime("%d.%m.%Y - %H:%M")),
                "sys": "reaction_roles",
            }
            audit_log: list = cast(list, load_data(sid=int(guild_id), sys="audit_log", bot=bot))
            audit_log.append(audit_log_new)
            save_data(int(guild_id), "audit_log", audit_log)

        return quart.jsonify({"success": True, "message": "Settings applied successfully."})

    @app.route("/api/dash/prism-scores/", methods=["GET"])
    @requires_authorization
    async def dash_prism_scores():
        guild_id = quart.request.args.get("guild_id") or quart.request.args.get("dash_login")
        if not guild_id:
            return quart.jsonify({"success": False, "message": "Missing guild_id parameter."}), 400
        try:
            user = await discord_auth.fetch_user()
            guild = await bot.fetch_guild(int(guild_id))
            try:
                guild_member = await guild.fetch_member(user.id)
            except discord.NotFound:
                return quart.jsonify({"success": False, "message": "Not a member of this guild."}), 403
            if not guild_member.guild_permissions.manage_guild:
                return quart.jsonify({"success": False, "message": "Unauthorized."}), 403
        except discord.NotFound:
            return quart.jsonify({"success": False, "message": "Guild not found."}), 404
        except discord.Forbidden:
            return quart.jsonify({"success": False, "message": "Bot doesn't have access to this guild."}), 403
        except Exception as e:
            return quart.jsonify({"success": False, "message": str(e)}), 500

        import assets.trust as sentinel
        prism_profiles: dict = sentinel.get_all_profiles()
        users_list: dict = dict(load_data(1001, "users"))

        seen_uids: set = set()
        result = []

        for uid, profile in prism_profiles.items():
            events = profile.get("events", [])
            if not any(str(e.get("guild_id")) == str(guild_id) for e in events):
                continue
            seen_uids.add(uid)
            user_entry = users_list.get(uid, {})
            manual_flag = user_entry.get("flagged", False) and not user_entry.get("auto_flagged", True)
            result.append({
                "uid":           uid,
                "name":          profile.get("name", uid),
                "score":         profile.get("score", 100),
                "llm_summary":   profile.get("llm_summary") or "",
                "manual_flag":   manual_flag,
                "manual_reason": user_entry.get("reason", "") if manual_flag else "",
                "opted_out":     profile.get("opted_out", False),
            })

        # Fetch all guild members once: build avatar map and member id set
        guild_member_ids: set = set()
        member_avatars: dict = {}
        try:
            async for member in guild.fetch_members(limit=None):
                mid = str(member.id)
                guild_member_ids.add(mid)
                member_avatars[mid] = str(member.display_avatar.url)
        except Exception:
            pass

        # Patch avatar_url into already-built result entries
        for entry in result:
            entry["avatar_url"] = member_avatars.get(entry["uid"], "")

        # Include manually flagged users that have no Prism events for this guild
        for uid, entry in users_list.items():
            if uid in seen_uids:
                continue
            if not entry.get("flagged", False):
                continue
            if entry.get("auto_flagged", False):
                continue
            if uid not in guild_member_ids:
                continue
            profile = prism_profiles.get(uid, {})
            result.append({
                "uid":           uid,
                "name":          entry.get("name", uid),
                "score":         profile.get("score", 100),
                "llm_summary":   profile.get("llm_summary") or "",
                "manual_flag":   True,
                "manual_reason": entry.get("reason", ""),
                "avatar_url":    member_avatars.get(uid, ""),
                "opted_out":     profile.get("opted_out", False),
            })

        # Include opted-out users that are guild members but have no events for this guild
        for uid, profile in prism_profiles.items():
            if uid in seen_uids:
                continue
            if not profile.get("opted_out", False):
                continue
            if uid not in guild_member_ids:
                continue
            seen_uids.add(uid)
            user_entry = users_list.get(uid, {})
            manual_flag = user_entry.get("flagged", False) and not user_entry.get("auto_flagged", True)
            result.append({
                "uid":           uid,
                "name":          profile.get("name", uid),
                "score":         profile.get("score", 100),
                "llm_summary":   profile.get("llm_summary") or "",
                "manual_flag":   manual_flag,
                "manual_reason": user_entry.get("reason", "") if manual_flag else "",
                "avatar_url":    member_avatars.get(uid, ""),
                "opted_out":     True,
            })

        result.sort(key=lambda u: u["score"])
        return quart.jsonify({"success": True, "users": result[:200]})

    @app.route("/api/dash/welcomer-bg/", methods=["GET", "POST", "DELETE"])  # type: ignore
    @requires_authorization
    async def welcomer_bg():
        import os
        guild_id = quart.request.args.get("guild_id") or quart.request.args.get("dash_login")

        if not guild_id:
            return quart.jsonify({"success": False, "message": "Missing guild_id parameter."}), 400

        try:
            user = await discord_auth.fetch_user()
            guild = await bot.fetch_guild(int(guild_id))
            guild_member = await guild.fetch_member(user.id)
            if not guild_member.guild_permissions.manage_guild:
                return quart.jsonify({"success": False, "message": "You don't have permission to manage this guild."}), 403
        except Exception:
            return quart.jsonify({"success": False, "message": "Authorization failed."}), 403

        bg_dir = f"data/{guild_id}"
        bg_path = f"{bg_dir}/welcomer_bg.png"

        if quart.request.method == "GET":
            if os.path.exists(bg_path):
                return await quart.send_file(bg_path, mimetype="image/png")
            return quart.jsonify({"success": False, "message": "No background image."}), 404

        elif quart.request.method == "POST":
            files = await quart.request.files
            bg_file = files.get("bg")
            if not bg_file:
                return quart.jsonify({"success": False, "message": "No file uploaded."}), 400

            # Validate file size (max 5MB)
            bg_data = bg_file.read()
            if len(bg_data) > 5 * 1024 * 1024:
                return quart.jsonify({"success": False, "message": "File too large (max 5MB)."}), 400

            os.makedirs(bg_dir, exist_ok=True)

            # Convert to PNG using Pillow for safety
            from PIL import Image
            import io
            try:
                img = Image.open(io.BytesIO(bg_data))
                img = img.convert("RGB")
                img.thumbnail((2048, 2048))
                img.save(bg_path, "PNG")
            except Exception:
                return quart.jsonify({"success": False, "message": "Invalid image file."}), 400

            # Update has_custom_bg in welcomer settings
            welcomer_data = dict(load_data(int(guild_id), "welcomer"))
            welcomer_data["has_custom_bg"] = True
            save_data(int(guild_id), "welcomer", welcomer_data)

            return quart.jsonify({"success": True, "message": "Background uploaded."})

        elif quart.request.method == "DELETE":
            if os.path.exists(bg_path):
                os.remove(bg_path)
            welcomer_data = dict(load_data(int(guild_id), "welcomer"))
            welcomer_data["has_custom_bg"] = False
            save_data(int(guild_id), "welcomer", welcomer_data)
            return quart.jsonify({"success": True, "message": "Background removed."})

    @app.route("/check/channel/perms/", methods=["POST"])
    async def check_channel_perms():
        data: dict = dict(await quart.request.get_json())
        system: str = str(data.get("system"))
        if "guild_id" in data and data["guild_id"] is not None:
            guild_id: int = int(data["guild_id"])
        else:
            guild_id: int = 0 
        
        channel_id = data.get("channel_id")
        if system != "bot_general" and system != "bot_role_position":
            if not channel_id:
                return quart.jsonify({"error": "Missing channel_id for non-general check"}), 400
            channel_id = int(channel_id)

        if not guild_id or not system:
            return quart.jsonify({"error": "Missing required fields"}), 400

        try:
            guild = await bot.fetch_guild(guild_id)
            assert bot.user is not None, "Bot user unknown"
            bot_member = await guild.fetch_member(bot.user.id)
            if not bot_member:
                bot_member = await guild.fetch_member(bot.user.id)

            if system == "bot_general":
                permissions = bot_member.guild_permissions

                required_perms = {
                    "manage_guild",
                    "manage_roles",
                    
                    "manage_channels",
                    "view_channel",
                    "read_message_history",
                    "send_messages",
                    "send_messages_in_threads",
                    "manage_messages",
                    "embed_links",
                    "attach_files",
                    "mention_everyone",
                    "add_reactions",
                    "use_external_emojis",
                    "use_external_stickers",
                    "use_application_commands",
                    
                    "kick_members",
                    "ban_members",
                    "moderate_members",
                    
                    "view_audit_log",
                    
                    "connect",
                    "speak",
                    "mute_members",
                    "move_members",
                    "stream",
                    "use_voice_activation",
                    
                    "manage_permissions",
                    "create_polls",
                }

                missing = [perm for perm in required_perms if not getattr(permissions, perm, False)]
                valid = len(missing) == 0

                return quart.jsonify({
                    "valid": valid,
                    "missing": missing if not valid else None,
                    "scope": "guild"
                })
            elif system == "bot_role_position":
                bot_roles = bot_member.roles
                if not bot_roles:
                    return quart.jsonify({"error": "Bot has no roles"}), 500

                bot_top_role = bot_member.top_role
                guild_roles = sorted(guild.roles, key=lambda r: r.position, reverse=True)
                highest_role = guild_roles[0]

                is_highest = bot_top_role.position == highest_role.position

                return quart.jsonify({
                    "is_highest": is_highest,
                    "bot_role_name": bot_top_role.name,
                    "bot_role_position": bot_top_role.position,
                    "highest_role_name": highest_role.name,
                    "total_roles": len(guild.roles),
                    "warning": not is_highest
                })
            else:
                if not channel_id:
                    return quart.jsonify({"error": "channel_id is required for this system"}), 400

                channel = await guild.fetch_channel(channel_id)
                permissions = channel.permissions_for(bot_member)

                required_perms = set()
                if system == "globalchat":
                    required_perms = {
                        "send_messages",
                        "view_channel",
                        "read_message_history",
                        "attach_files",
                        "embed_links",
                        "use_external_emojis",
                        "manage_messages",
                    }
                elif system == "ticket_button":
                    required_perms = {
                        "view_channel",
                        "read_message_history",
                        "send_messages",
                        "embed_links",
                        "use_application_commands",
                    }
                elif system == "ticket":
                    required_perms = {
                        "view_channel",
                        "read_message_history",
                        "send_messages",
                        "manage_channels",
                        "manage_permissions",
                        "embed_links",
                    }
                elif system == "ticket_transcript":
                    required_perms = {
                        "view_channel",
                        "read_message_history",
                        "send_messages",
                        "attach_files",
                        "embed_links",
                    }
                elif system == "welcomer":
                    required_perms = {
                        "view_channel",
                        "read_message_history",
                        "send_messages",
                        "embed_links",
                        "attach_files",
                    }
                elif system == "category":
                    required_perms = {
                        "view_channel",
                        "read_message_history",
                        "manage_channels",
                        "manage_permissions",
                    }
                else:
                    return quart.jsonify({"error": "Unknown system"}), 400

                if isinstance(channel, (discord.TextChannel, discord.CategoryChannel)):
                    missing = [perm for perm in required_perms if not getattr(permissions, perm, False)]
                    valid = len(missing) == 0
                else:
                    valid = False
                    missing = "Channel is not a text channel or category."

                return quart.jsonify({
                    "valid": valid,
                    "missing": missing if not valid else None,
                    "scope": "channel"
                })

        except Exception as e:
            return quart.jsonify({"error": str(e)}), 500

    @app.route("/attachments/<filename>")
    async def attachments(filename):
        if ".." in filename or filename.startswith("/"):
            return abort(400, "Ungültiger Dateiname")

        return await send_from_directory("attachments", filename)

    # ── ADMIN DASHBOARD ──────────────────────────────────────────────────────

    async def _require_bot_admin(discord_auth):
        """Returns (user, True) if user is a bot admin, else (user, False)."""
        try:
            user = await discord_auth.fetch_user()
            admins: list = list(datasys.load_data(1001, "admins"))
            return user, (user.id in admins)
        except Exception:
            return None, False

    @app.route("/admin/")
    @requires_authorization
    async def admin_dashboard():
        user, is_admin = await _require_bot_admin(discord_auth)
        if not is_admin:
            return await render_template(
                "error.html",
                message="Access denied. This page is restricted to Baxi bot admins.",
            )
        stats: dict = dict(load_data(1001, "stats"))
        return await render_template(
            "admin.html",
            user=user,
            stats=stats,
            version=config.Discord.version,
            greeting=get_time_based_greeting(user.name),
        )

    @app.route("/api/admin/data")
    @requires_authorization
    async def admin_data():
        """Returns all admin data as JSON (polled by the frontend)."""
        user, is_admin = await _require_bot_admin(discord_auth)
        if not is_admin:
            return quart.jsonify({"error": "Access denied"}), 403

        # Global stats
        stats: dict = dict(load_data(1001, "stats"))

        # Prism users
        import assets.trust as sentinel
        prism_profiles: dict = sentinel.get_all_profiles()
        users_list: dict = dict(load_data(1001, "users"))

        prism_users = []
        for uid, profile in prism_profiles.items():
            entry = users_list.get(uid, {})
            prism_users.append({
                "uid": uid,
                "name": profile.get("name", uid),
                "score": profile.get("score", 100),
                "auto_flagged": profile.get("auto_flagged", False),
                "manually_flagged": bool(entry.get("flagged", False)) and not entry.get("auto_flagged", False),
                "flag_reason": entry.get("reason", ""),
                "event_count": len(profile.get("events", [])),
                "events": profile.get("events", [])[-5:],  # last 5 events
                "first_seen": profile.get("first_seen", ""),
                "last_seen": profile.get("last_seen", ""),
                "account_age_days": profile.get("account_age_days", 0),
            })
        prism_users.sort(key=lambda u: u["score"])

        # Flagged users (manual + auto)
        flagged_users = [
            {**v, "uid": k}
            for k, v in users_list.items()
            if v.get("flagged", False)
        ]

        # Feature adoption
        feature_adoption = get_feature_adoption()

        # Bot / shard info
        shard_info = []
        if hasattr(bot, "shards"):
            for shard_id, shard in bot.shards.items():
                shard_info.append({
                    "id": shard_id,
                    "latency": round(shard.latency * 1000, 1) if shard.latency else None,
                    "closed": shard.is_closed(),
                })

        # Livestream active streamers
        active_streamers = []
        for guild in bot.guilds:
            ls_config = dict(datasys.load_data(guild.id, "livestream"))
            if not ls_config.get("enabled", False):
                continue
            for streamer in ls_config.get("streamers", []):
                was_live = False
                if share.livestream_task:
                    was_live = share.livestream_task._was_live.get(guild.id, {}).get(
                        streamer.get("login", "").lower(), False
                    )
                active_streamers.append({
                    "guild_name": guild.name,
                    "guild_id": str(guild.id),
                    "login": streamer.get("login", ""),
                    "display_name": streamer.get("display_name", ""),
                    "live": was_live,
                })

        # Guild list (all guilds bot is in)
        guild_list = sorted(
            [
                {
                    "id": str(g.id),
                    "name": g.name,
                    "member_count": g.member_count or 0,
                    "icon": str(g.icon.url) if g.icon else "",
                }
                for g in bot.guilds
            ],
            key=lambda x: x["member_count"],
            reverse=True,
        )

        return quart.jsonify({
            "stats": stats,
            "task_status": share.task_status,
            "prism_users": prism_users[:100],  # cap at 100 for payload size
            "prism_total": len(prism_users),
            "flagged_users": flagged_users,
            "feature_adoption": feature_adoption,
            "shard_info": shard_info,
            "active_streamers": active_streamers,
            "guild_list": guild_list[:50],
            "guild_total": len(bot.guilds),
            "phishing_domain_count": len(share.phishing_url_list),
        })

    @app.route("/api/admin/cf_logs")
    @requires_authorization
    async def admin_cf_logs():
        """Returns chatfilter log entries for the admin dashboard."""
        user, is_admin = await _require_bot_admin(discord_auth)
        if not is_admin:
            return quart.jsonify({"error": "Access denied"}), 403

        cf_log: dict = dict(datasys.load_data(1001, "chatfilter_log"))
        entries = list(cf_log.values())

        # Newest first — parse "DD.MM.YYYY - HH:MM" format for correct chronological order
        import datetime as _dt
        def _parse_cf_ts(ts: str):
            try:
                return _dt.datetime.strptime(ts, "%d.%m.%Y - %H:%M")
            except Exception:
                return _dt.datetime.min

        entries.sort(key=lambda e: _parse_cf_ts(e.get("timestamp", "")), reverse=True)

        # Optional filters via query params
        system_filter = quart.request.args.get("system", "").strip().lower()
        reason_filter = quart.request.args.get("reason", "").strip().lower()
        search = quart.request.args.get("search", "").strip().lower()
        limit = min(int(quart.request.args.get("limit", 200)), 5000)

        if system_filter:
            entries = [e for e in entries if (e.get("system") or "SafeText").lower() == system_filter]
        if reason_filter:
            entries = [e for e in entries if reason_filter in (e.get("reason") or "").lower()]
        if search:
            entries = [e for e in entries if (
                search in (e.get("uname") or "").lower()
                or search in (e.get("sname") or "").lower()
                or search in (e.get("message") or "").lower()
                or search in (e.get("cname") or "").lower()
            )]

        return quart.jsonify({
            "entries": entries[:limit],
            "total": len(cf_log),
            "filtered": len(entries),
        })

    @app.route("/api/admin/logs")
    @requires_authorization
    async def admin_logs():
        """Returns recent log entries + SSE stream."""
        user, is_admin = await _require_bot_admin(discord_auth)
        if not is_admin:
            return quart.jsonify({"error": "Access denied"}), 403

        offset = int(quart.request.args.get("offset", 0))
        entries = list(share.admin_log_buffer)
        total_ever = share.admin_log_total
        buffer_start = total_ever - len(entries)
        effective_offset = max(offset - buffer_start, 0)
        new_entries = entries[effective_offset:]
        return quart.jsonify({
            "entries": new_entries,
            "total": total_ever,
        })

    @app.route("/api/admin/action", methods=["POST"])
    @requires_authorization
    async def admin_action():
        """Executes an admin action from the dashboard."""
        user, is_admin = await _require_bot_admin(discord_auth)
        if not is_admin:
            return quart.jsonify({"success": False, "message": "Access denied"}), 403

        data: dict = await quart.request.get_json()
        action = data.get("action")

        share.admin_log("info", f"Admin action '{action}' triggered by {user.name}", source="AdminDash")

        if action == "flag_user":
            user_id_str = str(data.get("user_id", "")).strip()
            reason = str(data.get("reason", "")).strip()
            if not user_id_str.isdigit() or not reason:
                return quart.jsonify({"success": False, "message": "Invalid user_id or empty reason."}), 400
            try:
                target = await bot.fetch_user(int(user_id_str))
            except discord.NotFound:
                return quart.jsonify({"success": False, "message": "User not found."}), 404
            except Exception as e:
                return quart.jsonify({"success": False, "message": str(e)}), 500

            users_list: dict = dict(load_data(1001, "users"))
            import datetime as dt
            users_list[str(target.id)] = {
                "entry_date": str(dt.date.today()),
                "id": target.id,
                "name": target.name,
                "reason": reason,
                "flagged": True,
                "auto_flagged": False,
            }
            save_data(1001, "users", users_list)
            share.admin_log("warning", f"User {target.name} ({target.id}) flagged by {user.name}: {reason}", source="AdminDash")
            return quart.jsonify({"success": True, "message": f"User {target.name} flagged."})

        elif action == "deflag_user":
            user_id_str = str(data.get("user_id", "")).strip()
            if not user_id_str.isdigit():
                return quart.jsonify({"success": False, "message": "Invalid user_id."}), 400
            import assets.trust as sentinel
            users_list: dict = dict(load_data(1001, "users"))
            # Remove from users.json entirely (mirrors how auto-unflag works)
            if user_id_str in users_list:
                del users_list[user_id_str]
                save_data(1001, "users", users_list)
            # Also clear auto_flagged in trust.json so the API reflects it immediately
            sentinel.clear_flag(int(user_id_str))
            share.admin_log("success", f"User {user_id_str} deflagged by {user.name}", source="AdminDash")
            return quart.jsonify({"success": True, "message": "User deflagged."})

        elif action == "clear_prism_events":
            user_id_str = str(data.get("user_id", "")).strip()
            if not user_id_str.isdigit():
                return quart.jsonify({"success": False, "message": "Invalid user_id."}), 400
            import assets.trust as sentinel
            sentinel.clear_events(int(user_id_str))
            share.admin_log("info", f"Prism events cleared for {user_id_str} by {user.name}", source="AdminDash")
            return quart.jsonify({"success": True, "message": "Events cleared."})

        elif action == "refresh_prism_summary":
            user_id_str = str(data.get("user_id", "")).strip()
            if not user_id_str.isdigit():
                return quart.jsonify({"success": False, "message": "Invalid user_id."}), 400
            import assets.trust as sentinel
            profile = sentinel.get_profile(int(user_id_str))
            if not profile:
                return quart.jsonify({"success": False, "message": "No Prism profile found for this user."}), 404
            import asyncio as _asyncio
            loop = _asyncio.get_event_loop()
            loop.create_task(sentinel._update_user_summary(user_id_str))
            share.admin_log("info", f"Prism summary re-analysis requested for {user_id_str} by {user.name}", source="AdminDash")
            return quart.jsonify({"success": True, "message": "Re-analysis started. Refresh the profile in a few seconds."})

        elif action == "leave_server":
            guild_id_str = str(data.get("guild_id", "")).strip()
            if not guild_id_str.isdigit():
                return quart.jsonify({"success": False, "message": "Invalid guild_id."}), 400
            guild = bot.get_guild(int(guild_id_str))
            if not guild:
                return quart.jsonify({"success": False, "message": "Guild not found."}), 404
            guild_name = guild.name
            await guild.leave()
            share.admin_log("warning", f"Bot left guild {guild_name} ({guild_id_str}) — triggered by {user.name}", source="AdminDash")
            return quart.jsonify({"success": True, "message": f"Left guild {guild_name}."})

        elif action == "bulk_config":
            feature = str(data.get("feature", "")).strip()
            act = str(data.get("action_type", "")).strip()
            percent = int(data.get("percent", 100))
            valid_features = ["chatfilter", "antispam", "ticket", "auto_roles", "temp_voice", "livestream"]
            if feature not in valid_features:
                return quart.jsonify({"success": False, "message": f"Invalid feature. Valid: {valid_features}"}), 400
            if act not in ("enable", "disable"):
                return quart.jsonify({"success": False, "message": "action_type must be 'enable' or 'disable'"}), 400
            if not 1 <= percent <= 100:
                return quart.jsonify({"success": False, "message": "percent must be 1-100"}), 400

            import random as _rnd
            enable = act == "enable"
            all_guilds = list(bot.guilds)
            count = max(1, round(len(all_guilds) * percent / 100))
            target_guilds = _rnd.sample(all_guilds, count) if percent < 100 else all_guilds
            success_count = 0
            failed_count = 0
            for g in target_guilds:
                try:
                    feat_data = datasys.load_data(g.id, feature)
                    if not isinstance(feat_data, dict):
                        feat_data = {}
                    feat_data["enabled"] = enable
                    datasys.save_data(g.id, feature, feat_data)
                    success_count += 1
                except Exception:
                    failed_count += 1
            share.admin_log("warning", f"Bulk {act} '{feature}' on {success_count}/{len(target_guilds)} guilds ({percent}%) by {user.name}", source="AdminDash")
            return quart.jsonify({
                "success": True,
                "message": f"{act.capitalize()}d '{feature}' on {success_count} of {len(target_guilds)} guilds ({percent}% of {len(all_guilds)} total). Failed: {failed_count}",
            })

        elif action == "search_server":
            query = str(data.get("query", "")).strip().lower()
            if not query:
                return quart.jsonify({"success": False, "message": "Query is empty."}), 400
            results = []
            for g in bot.guilds:
                if (
                    query in g.name.lower()
                    or query in str(g.id)
                    or (g.owner_id and query in str(g.owner_id))
                ):
                    results.append({
                        "id": str(g.id),
                        "name": g.name,
                        "member_count": g.member_count or 0,
                        "owner_id": str(g.owner_id),
                        "icon": str(g.icon.url) if g.icon else "",
                        "created_at": g.created_at.strftime("%d.%m.%Y"),
                        "boost_level": g.premium_tier,
                        "boost_count": g.premium_subscription_count or 0,
                        "text_channels": len(g.text_channels),
                        "voice_channels": len(g.voice_channels),
                        "roles": len(g.roles),
                        "terms": bool(datasys.load_data(g.id, "terms")),
                        "lang": str(datasys.load_data(g.id, "lang") or "en"),
                    })
            results.sort(key=lambda x: x["member_count"], reverse=True)
            return quart.jsonify({"success": True, "results": results[:25]})

        elif action == "gc_delete":
            message_id = str(data.get("message_id", "")).strip()
            if not message_id:
                return quart.jsonify({"success": False, "message": "message_id required."}), 400
            message_data = share.globalchat_message_data.get(message_id)
            if not message_data:
                return quart.jsonify({"success": False, "message": "Message not found in cache."}), 404
            deleted = 0
            failed = 0
            for msg_entry in message_data.get("messages", []):
                try:
                    g = bot.get_guild(msg_entry["gid"])
                    if not g:
                        failed += 1
                        continue
                    ch = g.get_channel(msg_entry["channel"])
                    if not isinstance(ch, discord.TextChannel):
                        failed += 1
                        continue
                    msg = await ch.fetch_message(msg_entry["mid"])
                    await msg.delete()
                    deleted += 1
                except Exception:
                    failed += 1
            del share.globalchat_message_data[message_id]
            share.admin_log("warning", f"GC message {message_id} deleted by {user.name} — {deleted} copies removed", source="AdminDash")
            return quart.jsonify({"success": True, "message": f"Deleted {deleted} message copies. Failed: {failed}."})

        elif action == "run_task":
            _TASK_METHODS = {
                "GCDH":          "sync_globalchat_message_data",
                "UpdateStats":   "update_stats",
                "Livestream":    "check_streams",
                "StatsChannels": "update_stats_channels",
                "TempActions":   "check_temp_actions",
                "PhishingList":  "update_phishing_list",
                "TrustScore":    "recalculate_scores",
                "GarbageCollector": "collect",
            }
            task_key = str(data.get("task_key", "")).strip()
            if task_key not in _TASK_METHODS:
                return quart.jsonify({"success": False, "message": f"Unknown task: {task_key}"}), 400
            instance = share.task_instances.get(task_key)
            if not instance:
                return quart.jsonify({"success": False, "message": "Task not running (bot not ready?)"}), 503
            method_name = _TASK_METHODS[task_key]
            loop = getattr(instance, method_name)
            import asyncio as _asyncio
            _asyncio.get_event_loop().create_task(loop.coro(instance))
            share.admin_log("info", f"Task {task_key} manually triggered by {user.name}", source="AdminDash")
            return quart.jsonify({"success": True, "message": f"Task {task_key} triggered."})

        elif action == "get_prism_profile":
            import assets.trust as sentinel
            user_id_str = str(data.get("user_id", "")).strip()
            if not user_id_str.isdigit():
                return quart.jsonify({"success": False, "message": "Invalid user_id."}), 400
            profile = sentinel.get_profile(int(user_id_str))
            if not profile:
                return quart.jsonify({"success": False, "message": "No Prism profile found for this user."}), 404
            import datetime as _dt
            now = _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)
            events_detail = []
            for ev in profile.get("events", []):
                etype  = ev.get("type", "")
                weight = sentinel.EVENT_WEIGHTS.get(etype, 0)
                try:
                    ts       = _dt.datetime.fromisoformat(ev["timestamp"])
                    age_days = (now - ts).days
                    decayed  = age_days > sentinel.EVENT_DECAY_DAYS
                except Exception:
                    age_days = 0
                    decayed  = False
                events_detail.append({
                    "type":           etype,
                    "label":          sentinel.EVENT_LABELS.get(etype, etype),
                    "severity":       sentinel.get_event_severity(etype),
                    "severity_label": sentinel.SEVERITY_LABELS.get(sentinel.get_event_severity(etype), ""),
                    "weight":         weight // 2 if decayed else weight,
                    "reason":         ev.get("reason", ""),
                    "guild_id":       ev.get("guild_id", ""),
                    "timestamp":      ev.get("timestamp", ""),
                    "age_days":       age_days,
                    "decayed":        decayed,
                })
            events_detail.reverse()  # newest first
            created_at = profile.get("account_created_at", "")
            if created_at:
                try:
                    age_days_current = (now - _dt.datetime.fromisoformat(created_at)).days
                except Exception:
                    age_days_current = profile.get("account_age_days", 0)
            else:
                age_days_current = profile.get("account_age_days", 0)
            return quart.jsonify({
                "success": True,
                "profile": {
                    "uid":                  user_id_str,
                    "name":                 profile.get("name", user_id_str),
                    "score":                profile.get("score", 100),
                    "auto_flagged":         profile.get("auto_flagged", False),
                    "event_count":          len(profile.get("events", [])),
                    "first_seen":           profile.get("first_seen", ""),
                    "last_seen":            profile.get("last_seen", ""),
                    "account_age_days":     age_days_current,
                    "account_created_at":   created_at,
                    "events":               events_detail,
                    "llm_summary":          profile.get("llm_summary") or "",
                    "llm_summary_updated":  profile.get("llm_summary_updated") or "",
                    "risk_signals":         profile.get("risk_signals") or [],
                    "opted_out":            profile.get("opted_out", False),
                },
            })

        elif action == "send_notification":
            title = str(data.get("title", "")).strip()
            text  = str(data.get("text",  "")).strip()
            guild_id_str = str(data.get("guild_id", "")).strip()
            if not title or not text:
                return quart.jsonify({"success": False, "message": "Title and text are required."}), 400
            if guild_id_str and not guild_id_str.isdigit():
                return quart.jsonify({"success": False, "message": "Invalid guild_id."}), 400

            from assets.trust import _resolve_notification_channel
            target_guilds = [bot.get_guild(int(guild_id_str))] if guild_id_str else list(bot.guilds)
            target_guilds = [g for g in target_guilds if g]

            sent = 0
            failed = 0
            ts = datetime.now(_VIENNA).strftime("%d.%m.%Y %H:%M")
            for g in target_guilds:
                try:
                    channel = await _resolve_notification_channel(g)
                    if channel is None:
                        failed += 1
                        continue
                    embed = discord.Embed(
                        title=title,
                        description=text,
                        color=config.Discord.color,
                    )
                    embed.set_author(name="Avocloud.net")
                    embed.set_footer(text=f"Baxi · {ts}")
                    await channel.send(embed=embed)
                    sent += 1
                except Exception:
                    failed += 1

            scope = f"guild {guild_id_str}" if guild_id_str else f"all {len(target_guilds)} guilds"
            share.admin_log("info", f"Notification sent to {sent}/{len(target_guilds)} ({scope}) by {user.name}: \"{title}\"", source="AdminDash")
            return quart.jsonify({"success": True, "message": f"Sent to {sent} server(s). Failed: {failed}."})

        elif action == "search_user":
            query = str(data.get("query", "")).strip()
            if not query:
                return quart.jsonify({"success": False, "message": "Query is empty."}), 400

            import assets.trust as sentinel

            uid_str = None
            found_name = None

            # ── resolve uid from query ────────────────────────────────────
            if query.isdigit():
                uid_str = query
                profile = sentinel.get_profile(int(uid_str))
                if profile:
                    found_name = profile.get("name", uid_str)
                else:
                    _users_tmp: dict = dict(datasys.load_data(1001, "users"))
                    if uid_str in _users_tmp:
                        found_name = _users_tmp[uid_str].get("name", uid_str)
                    else:
                        try:
                            _fu = await bot.fetch_user(int(uid_str))
                            found_name = _fu.name
                        except Exception:
                            found_name = uid_str
            else:
                _ql = query.lower()
                for _pu, _pp in sentinel.get_all_profiles().items():
                    if _ql in _pp.get("name", "").lower():
                        uid_str, found_name = _pu, _pp.get("name", _pu)
                        break
                if not uid_str:
                    for _pu, _ud in dict(datasys.load_data(1001, "users")).items():
                        if _ql in _ud.get("name", "").lower():
                            uid_str, found_name = _pu, _ud.get("name", _pu)
                            break
                if not uid_str:
                    _cf_tmp: dict = dict(datasys.load_data(1001, "chatfilter_log"))
                    for _v in _cf_tmp.values():
                        if _ql in (_v.get("uname") or "").lower():
                            uid_str = str(_v.get("uid", ""))
                            found_name = _v.get("uname", uid_str)
                            break

            if not uid_str:
                return quart.jsonify({"success": True, "found": False})

            _su_result: dict = {"success": True, "found": True, "uid": uid_str, "name": found_name or uid_str}

            # ── Prism profile ─────────────────────────────────────────────
            _su_profile = sentinel.get_profile(int(uid_str))
            if _su_profile:
                _su_result["prism"] = {
                    "score": _su_profile.get("score", 100),
                    "event_count": len(_su_profile.get("events", [])),
                    "events": _su_profile.get("events", []),
                    "first_seen": _su_profile.get("first_seen", ""),
                    "last_seen": _su_profile.get("last_seen", ""),
                    "auto_flagged": _su_profile.get("auto_flagged", False),
                    "opted_out": _su_profile.get("opted_out", False),
                    "llm_summary": _su_profile.get("llm_summary", ""),
                    "risk_signals": _su_profile.get("risk_signals", []),
                }

            # ── Flagged user entry ────────────────────────────────────────
            _su_users: dict = dict(datasys.load_data(1001, "users"))
            if uid_str in _su_users:
                _su_fe = _su_users[uid_str]
                _su_result["flagged_entry"] = {
                    "reason": _su_fe.get("reason", ""),
                    "entry_date": _su_fe.get("entry_date", ""),
                    "auto_flagged": _su_fe.get("auto_flagged", False),
                    "flagged": _su_fe.get("flagged", False),
                }

            # ── Global bans (ba_ban / gc_ban) ─────────────────────────────
            _su_gc: dict = dict(datasys.load_data(1001, "conf"))
            _su_result["ba_ban"] = uid_str in _su_gc.get("ba_ban", {})
            _su_result["gc_ban"] = uid_str in _su_gc.get("gc_ban", {})

            # ── Chatfilter violations (global + per-guild, deduplicated) ──
            _seen_cf_ids: set = set()
            _su_violations: list = []
            for _v in dict(datasys.load_data(1001, "chatfilter_log")).values():
                if str(_v.get("uid", "")) == uid_str:
                    _vid = _v.get("id", "")
                    if _vid not in _seen_cf_ids:
                        _seen_cf_ids.add(_vid)
                        _su_violations.append(_v)
            _su_result["chatfilter_violations"] = sorted(_su_violations, key=lambda x: x.get("timestamp", ""), reverse=True)[:100]

            # ── Ticket transcripts (global) ───────────────────────────────
            _su_transcripts: list = []
            try:
                _tr_data: dict = dict(datasys.load_data(1001, "transcripts"))
                for _tid, _tr in _tr_data.items():
                    _tr_msgs = _tr.get("transcript", [])
                    _user_in_transcript = any(
                        str(_m.get("author_id", _m.get("user_id", ""))) == uid_str
                        for _m in _tr_msgs
                    )
                    if _user_in_transcript:
                        _su_transcripts.append({
                            "id": _tid,
                            "guild": _tr.get("guild", ""),
                            "title": _tr.get("title", ""),
                            "closed_by": _tr.get("closed_by", ""),
                            "closed_on": _tr.get("closed_on", ""),
                            "message_count": len(_tr_msgs),
                        })
            except Exception:
                pass
            _su_result["ticket_transcripts"] = _su_transcripts

            # ── Per-guild data (warnings, temp-actions, open tickets) ─────
            _su_warnings: list = []
            _su_temp_actions: list = []
            _su_open_tickets: list = []
            _su_data_dir = "data"
            try:
                _su_guild_dirs = [
                    d for d in os.listdir(_su_data_dir)
                    if os.path.isdir(os.path.join(_su_data_dir, d)) and d.isdigit() and d != "1001"
                ]
            except FileNotFoundError:
                _su_guild_dirs = []

            for _sg in _su_guild_dirs:
                _sg_base = os.path.join(_su_data_dir, _sg)

                # warnings
                _sg_cf = os.path.join(_sg_base, "conf.json")
                if os.path.exists(_sg_cf):
                    try:
                        with open(_sg_cf, "r", encoding="utf-8") as _fh:
                            _sc = json.load(_fh)
                        _sg_warns = _sc.get("warnings", {}).get(uid_str, [])
                        if _sg_warns:
                            _su_warnings.append({
                                "guild_id": _sg,
                                "guild_name": _sc.get("guild_name", _sg),
                                "count": len(_sg_warns),
                                "warnings": _sg_warns,
                            })
                    except Exception:
                        pass

                # temp actions
                _sg_ta = os.path.join(_sg_base, "temp_actions.json")
                if os.path.exists(_sg_ta):
                    try:
                        with open(_sg_ta, "r", encoding="utf-8") as _fh:
                            _sta = json.load(_fh)
                        for _at in ["bans", "timeouts"]:
                            for _ae in _sta.get(_at, []):
                                if str(_ae.get("user_id", "")) == uid_str:
                                    _su_temp_actions.append({
                                        "type": _at[:-1],
                                        "guild_id": _sg,
                                        "guild_name": _ae.get("guild_name", _sg),
                                        "expires_at": _ae.get("expires_at", ""),
                                        "reason": _ae.get("reason", ""),
                                        "moderator_name": _ae.get("moderator_name", ""),
                                    })
                    except Exception:
                        pass

                # open tickets
                _sg_tk = os.path.join(_sg_base, "tickets.json")
                if os.path.exists(_sg_tk):
                    try:
                        with open(_sg_tk, "r", encoding="utf-8") as _fh:
                            _stk = json.load(_fh)
                        for _ch_id, _tk in _stk.items():
                            if str(_tk.get("user", "")) == uid_str:
                                _su_open_tickets.append({
                                    "guild_id": _sg,
                                    "channel_id": _ch_id,
                                    "title": _tk.get("title", ""),
                                    "message": _tk.get("message", ""),
                                    "created_at": _tk.get("created_at", 0),
                                    "status": _tk.get("status", "open"),
                                    "message_count": len(_tk.get("transcript", [])),
                                })
                    except Exception:
                        pass

            _su_result["guild_warnings"] = _su_warnings
            _su_result["temp_actions"] = _su_temp_actions
            _su_result["open_tickets"] = _su_open_tickets

            share.admin_log("info", f"User search for '{query}' → uid={uid_str} by {user.name}", source="AdminDash")
            return quart.jsonify(_su_result)

        elif action == "delete_user_data":
            user_id_str = str(data.get("user_id", "")).strip()
            if not user_id_str.isdigit():
                return quart.jsonify({"success": False, "message": "Invalid user_id."}), 400

            import assets.trust as sentinel

            _del_items: list[str] = []
            _del_name = user_id_str

            # 1. Prism profile
            _del_profile = sentinel.get_profile(int(user_id_str))
            if _del_profile:
                _del_name = _del_profile.get("name", user_id_str)
                sentinel.delete_profile(int(user_id_str))
                _del_items.append("Prism profile")

            # 2. Flagged users entry
            _del_users: dict = dict(datasys.load_data(1001, "users"))
            if user_id_str in _del_users:
                _del_name = _del_users[user_id_str].get("name", _del_name)
                del _del_users[user_id_str]
                datasys.save_data(1001, "users", _del_users)
                _del_items.append("flagged user entry")

            # 3. Global ba_ban / gc_ban
            _del_gc: dict = json.loads(open(os.path.join("data", "1001", "conf.json"), encoding="utf-8").read())
            _del_gc_mod = False
            if user_id_str in _del_gc.get("ba_ban", {}):
                del _del_gc["ba_ban"][user_id_str]
                _del_gc_mod = True
                _del_items.append("ba_ban entry")
            if user_id_str in _del_gc.get("gc_ban", {}):
                del _del_gc["gc_ban"][user_id_str]
                _del_gc_mod = True
                _del_items.append("gc_ban entry")
            if _del_gc_mod:
                with open(os.path.join("data", "1001", "conf.json"), "w", encoding="utf-8") as _fh:
                    json.dump(_del_gc, _fh, indent=2, ensure_ascii=False)

            # 4. Global chatfilter log
            _del_cf: dict = dict(datasys.load_data(1001, "chatfilter_log"))
            _del_cf_orig = len(_del_cf)
            _del_cf = {k: v for k, v in _del_cf.items() if str(v.get("uid", "")) != user_id_str}
            if len(_del_cf) < _del_cf_orig:
                datasys.save_data(1001, "chatfilter_log", _del_cf)
                _del_items.append(f"{_del_cf_orig - len(_del_cf)} chatfilter log entries (global)")

            # 5. Per-guild: warnings, temp-actions, per-guild cf-logs, open tickets
            _del_data_dir = "data"
            try:
                _del_guild_dirs = [
                    d for d in os.listdir(_del_data_dir)
                    if os.path.isdir(os.path.join(_del_data_dir, d)) and d.isdigit() and d != "1001"
                ]
            except FileNotFoundError:
                _del_guild_dirs = []

            _del_warn_g = 0
            _del_ta_g = 0
            _del_cf_g = 0
            _del_tk_g = 0
            for _dg in _del_guild_dirs:
                _dg_base = os.path.join(_del_data_dir, _dg)

                # warnings in conf.json
                _dg_cf = os.path.join(_dg_base, "conf.json")
                if os.path.exists(_dg_cf):
                    try:
                        with open(_dg_cf, "r", encoding="utf-8") as _fh:
                            _dc = json.load(_fh)
                        if user_id_str in _dc.get("warnings", {}):
                            del _dc["warnings"][user_id_str]
                            with open(_dg_cf, "w", encoding="utf-8") as _fh:
                                json.dump(_dc, _fh, indent=2, ensure_ascii=False)
                            _del_warn_g += 1
                    except Exception:
                        pass

                # temp actions
                _dg_ta = os.path.join(_dg_base, "temp_actions.json")
                if os.path.exists(_dg_ta):
                    try:
                        with open(_dg_ta, "r", encoding="utf-8") as _fh:
                            _dta = json.load(_fh)
                        _mod_ta = False
                        for _at in ["bans", "timeouts"]:
                            _orig = _dta.get(_at, [])
                            _filt = [e for e in _orig if str(e.get("user_id", "")) != user_id_str]
                            if len(_filt) < len(_orig):
                                _dta[_at] = _filt
                                _mod_ta = True
                        if _mod_ta:
                            with open(_dg_ta, "w", encoding="utf-8") as _fh:
                                json.dump(_dta, _fh, indent=2, ensure_ascii=False)
                            _del_ta_g += 1
                    except Exception:
                        pass

                # per-guild chatfilter log
                _dg_cl = os.path.join(_dg_base, "chatfilter_log.json")
                if os.path.exists(_dg_cl):
                    try:
                        with open(_dg_cl, "r", encoding="utf-8") as _fh:
                            _dcl = json.load(_fh)
                        _dcl_orig = len(_dcl)
                        _dcl = {k: v for k, v in _dcl.items() if str(v.get("uid", "")) != user_id_str}
                        if len(_dcl) < _dcl_orig:
                            with open(_dg_cl, "w", encoding="utf-8") as _fh:
                                json.dump(_dcl, _fh, indent=2, ensure_ascii=False)
                            _del_cf_g += _dcl_orig - len(_dcl)
                    except Exception:
                        pass

                # open tickets
                _dg_tk = os.path.join(_dg_base, "tickets.json")
                if os.path.exists(_dg_tk):
                    try:
                        with open(_dg_tk, "r", encoding="utf-8") as _fh:
                            _dtk = json.load(_fh)
                        _dtk_keys = [k for k, v in _dtk.items() if str(v.get("user", "")) == user_id_str]
                        for _k in _dtk_keys:
                            del _dtk[_k]
                        if _dtk_keys:
                            with open(_dg_tk, "w", encoding="utf-8") as _fh:
                                json.dump(_dtk, _fh, indent=2, ensure_ascii=False)
                            _del_tk_g += len(_dtk_keys)
                    except Exception:
                        pass

            if _del_warn_g:
                _del_items.append(f"warnings in {_del_warn_g} server(s)")
            if _del_ta_g:
                _del_items.append(f"temp actions in {_del_ta_g} server(s)")
            if _del_cf_g:
                _del_items.append(f"{_del_cf_g} chatfilter log entries (per-server)")
            if _del_tk_g:
                _del_items.append(f"{_del_tk_g} open ticket(s)")

            # 6. DM notification in English
            _del_dm_sent = False
            try:
                _del_target = await bot.fetch_user(int(user_id_str))
                _del_ts = datetime.now(_VIENNA).strftime("%d.%m.%Y %H:%M")
                _del_embed = discord.Embed(
                    title="Your data has been deleted",
                    description=(
                        "An administrator has deleted all personal data stored about you in the Baxi system.\n\n"
                        f"**What was deleted:**\n"
                        + "\n".join(f"• {x}" for x in _del_items) if _del_items
                        else "• No data was found for your account."
                    ),
                    color=config.Discord.color,
                )
                _del_embed.add_field(name="Deleted on", value=_del_ts, inline=True)
                _del_embed.add_field(name="System", value="Baxi · Avocloud.net", inline=True)
                _del_embed.set_footer(
                    text="If you believe this was done in error, please contact the Baxi support team."
                )
                await _del_target.send(embed=_del_embed)
                _del_dm_sent = True
            except Exception:
                pass

            share.admin_log(
                "warning",
                f"All data deleted for {_del_name} ({user_id_str}) by {user.name}. "
                f"Items: {', '.join(_del_items) or 'none'}. DM sent: {_del_dm_sent}",
                source="AdminDash",
            )
            _del_summary = f"Deleted: {', '.join(_del_items) if _del_items else 'nothing found'}."
            _del_summary += " DM sent to user." if _del_dm_sent else " DM could not be sent (DMs may be disabled)."
            return quart.jsonify({"success": True, "message": _del_summary})

        elif action == "send_user_data":
            user_id_str = str(data.get("user_id", "")).strip()
            if not user_id_str.isdigit():
                return quart.jsonify({"success": False, "message": "Invalid user_id."}), 400

            import assets.trust as sentinel

            try:
                _rep_target = await bot.fetch_user(int(user_id_str))
            except discord.NotFound:
                return quart.jsonify({"success": False, "message": "User not found on Discord."}), 404
            except Exception as _e:
                return quart.jsonify({"success": False, "message": f"Could not fetch user: {_e}"}), 500

            _rep_ts = datetime.now(_VIENNA).strftime("%d.%m.%Y %H:%M")

            # Collect all data
            _rep_profile = sentinel.get_profile(int(user_id_str))
            _rep_users: dict = dict(datasys.load_data(1001, "users"))
            _rep_flagged = _rep_users.get(user_id_str)
            _rep_gc_conf: dict = json.loads(open(os.path.join("data", "1001", "conf.json"), encoding="utf-8").read())
            _rep_ba_banned = user_id_str in _rep_gc_conf.get("ba_ban", {})
            _rep_gc_banned = user_id_str in _rep_gc_conf.get("gc_ban", {})

            _rep_cf: dict = dict(datasys.load_data(1001, "chatfilter_log"))
            _rep_violations = [v for v in _rep_cf.values() if str(v.get("uid", "")) == user_id_str]
            _rep_violations.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

            _rep_transcripts: list = []
            try:
                _rep_tr_data: dict = dict(datasys.load_data(1001, "transcripts"))
                for _tid, _tr in _rep_tr_data.items():
                    if any(str(_m.get("author_id", _m.get("user_id", ""))) == user_id_str for _m in _tr.get("transcript", [])):
                        _rep_transcripts.append(_tr)
            except Exception:
                pass

            _rep_data_dir = "data"
            try:
                _rep_guild_dirs = [
                    d for d in os.listdir(_rep_data_dir)
                    if os.path.isdir(os.path.join(_rep_data_dir, d)) and d.isdigit() and d != "1001"
                ]
            except FileNotFoundError:
                _rep_guild_dirs = []

            _rep_all_warnings: list = []
            _rep_temp_actions: list = []
            _rep_open_tickets: list = []
            for _rg in _rep_guild_dirs:
                _rg_base = os.path.join(_rep_data_dir, _rg)

                _rg_cf = os.path.join(_rg_base, "conf.json")
                if os.path.exists(_rg_cf):
                    try:
                        with open(_rg_cf, "r", encoding="utf-8") as _fh:
                            _rc = json.load(_fh)
                        _rg_warns = _rc.get("warnings", {}).get(user_id_str, [])
                        if _rg_warns:
                            _rep_all_warnings.append({
                                "guild_name": _rc.get("guild_name", _rg),
                                "guild_id": _rg,
                                "warnings": _rg_warns,
                            })
                    except Exception:
                        pass

                _rg_ta = os.path.join(_rg_base, "temp_actions.json")
                if os.path.exists(_rg_ta):
                    try:
                        with open(_rg_ta, "r", encoding="utf-8") as _fh:
                            _rta = json.load(_fh)
                        for _at in ["bans", "timeouts"]:
                            for _ae in _rta.get(_at, []):
                                if str(_ae.get("user_id", "")) == user_id_str:
                                    _rep_temp_actions.append({
                                        "type": _at[:-1],
                                        "guild_name": _ae.get("guild_name", _rg),
                                        "guild_id": _rg,
                                        "expires_at": _ae.get("expires_at", ""),
                                        "reason": _ae.get("reason", ""),
                                        "moderator_name": _ae.get("moderator_name", ""),
                                    })
                    except Exception:
                        pass

                _rg_tk = os.path.join(_rg_base, "tickets.json")
                if os.path.exists(_rg_tk):
                    try:
                        with open(_rg_tk, "r", encoding="utf-8") as _fh:
                            _rtk = json.load(_fh)
                        for _ch, _tk in _rtk.items():
                            if str(_tk.get("user", "")) == user_id_str:
                                _rep_open_tickets.append({
                                    "guild_name": _rg,
                                    "guild_id": _rg,
                                    "title": _tk.get("title", ""),
                                    "message": _tk.get("message", ""),
                                    "created_at": _tk.get("created_at", 0),
                                })
                    except Exception:
                        pass

            # ── helper: safely truncate for embed field limits ────────────
            def _trunc(s: str, n: int = 950) -> str:
                return s if len(s) <= n else s[:n] + "…"

            # ── Send embeds ───────────────────────────────────────────────
            _rep_embeds: list[discord.Embed] = []

            # 1. Overview
            _ov_lines = [
                f"This is a full report of all data Baxi has stored about your account.",
                f"",
                f"**User ID:** {user_id_str}",
            ]
            if _rep_profile:
                _ov_lines += [
                    f"**Prism Trust Score:** {_rep_profile.get('score', 100)}/100",
                    f"**Prism Events:** {len(_rep_profile.get('events', []))}",
                    f"**First seen by Baxi:** {(_rep_profile.get('first_seen') or '—')[:16]}",
                    f"**Last seen by Baxi:** {(_rep_profile.get('last_seen') or '—')[:16]}",
                    f"**Auto-flagged:** {'Yes' if _rep_profile.get('auto_flagged') else 'No'}",
                    f"**Opted out of Prism:** {'Yes' if _rep_profile.get('opted_out') else 'No'}",
                ]
            if _rep_flagged and _rep_flagged.get("flagged"):
                _ov_lines.append(f"**Globally flagged:** Yes — Reason: {_rep_flagged.get('reason', '—')}")
            if _rep_ba_banned:
                _ov_lines.append("**Baxi AutoMod Ban:** Yes")
            if _rep_gc_banned:
                _ov_lines.append("**Global Chat Ban:** Yes")
            _ov_lines += [
                f"**Chatfilter violations:** {len(_rep_violations)}",
                f"**Warnings (across all servers):** {sum(len(g['warnings']) for g in _rep_all_warnings)}",
                f"**Active temp actions:** {len(_rep_temp_actions)}",
                f"**Open tickets:** {len(_rep_open_tickets)}",
                f"**Closed ticket transcripts:** {len(_rep_transcripts)}",
            ]
            _ov_embed = discord.Embed(
                title="📋 Your Data stored by Baxi",
                description="\n".join(_ov_lines),
                color=config.Discord.color,
            )
            _ov_embed.set_footer(text=f"Requested on {_rep_ts} · Avocloud.net · Baxi")
            _rep_embeds.append(_ov_embed)

            # 2. Prism events (paginated by 20)
            if _rep_profile:
                _prism_events = _rep_profile.get("events", [])
                if _rep_profile.get("llm_summary"):
                    _ai_embed = discord.Embed(
                        title="🔮 Prism AI Risk Summary",
                        description=_trunc(_rep_profile["llm_summary"], 3900),
                        color=0x9333ea,
                    )
                    _rs = _rep_profile.get("risk_signals", [])
                    if _rs:
                        _ai_embed.add_field(name="Risk Signals", value=", ".join(_rs), inline=False)
                    _rep_embeds.append(_ai_embed)

                _ev_chunks = [_prism_events[i:i+20] for i in range(0, len(_prism_events), 20)]
                for _ci, _chunk in enumerate(_ev_chunks):
                    _ev_embed = discord.Embed(
                        title=f"📊 Prism Events ({_ci*20+1}–{_ci*20+len(_chunk)} of {len(_prism_events)})",
                        color=0x6366f1,
                    )
                    for _ei, _ev in enumerate(_chunk):
                        _ev_val = (
                            f"**Severity:** {_ev.get('severity', '—')}\n"
                            f"**Reason:** {_ev.get('reason', '—')}\n"
                            f"**Server ID:** {_ev.get('guild_id', '—')}\n"
                            f"**Date:** {str(_ev.get('timestamp', '—'))[:16]}"
                        )
                        _ev_embed.add_field(
                            name=f"#{_ci*20+_ei+1} · {_ev.get('type', '—')}",
                            value=_trunc(_ev_val),
                            inline=True,
                        )
                    _rep_embeds.append(_ev_embed)

            # 3. Chatfilter violations (paginated by 10)
            if _rep_violations:
                _cf_chunks = [_rep_violations[i:i+10] for i in range(0, len(_rep_violations), 10)]
                for _ci, _chunk in enumerate(_cf_chunks):
                    _cf_embed = discord.Embed(
                        title=f"🚫 Chatfilter Violations ({_ci*10+1}–{_ci*10+len(_chunk)} of {len(_rep_violations)})",
                        color=0xef4444,
                    )
                    for _vi, _v in enumerate(_chunk):
                        _cf_val = (
                            f"**System:** {_v.get('system', '—')}\n"
                            f"**Server:** {_v.get('sname', '—')}\n"
                            f"**Channel:** #{_v.get('cname', '—')}\n"
                            f"**Reason:** {_v.get('reason') or _v.get('word', '—')}\n"
                            f"**Message:** {_trunc(_v.get('message', '—'), 200)}\n"
                            f"**Date:** {_v.get('timestamp', '—')}"
                        )
                        _cf_embed.add_field(
                            name=f"#{_ci*10+_vi+1} · {_v.get('sname', '—')}",
                            value=_trunc(_cf_val),
                            inline=False,
                        )
                    _rep_embeds.append(_cf_embed)

            # 4. Warnings per server
            if _rep_all_warnings:
                _warn_embed = discord.Embed(title="⚠️ Warnings across Servers", color=0xfbbf24)
                for _wg in _rep_all_warnings:
                    _wg_lines = []
                    for _wi, _w in enumerate(_wg["warnings"]):
                        if isinstance(_w, dict):
                            _wg_lines.append(
                                f"**#{_wi+1}** — {_w.get('reason', str(_w))}"
                                + (f" (by {_w.get('moderator', '')})" if _w.get("moderator") else "")
                                + (f" · {str(_w.get('timestamp', ''))[:10]}" if _w.get("timestamp") else "")
                            )
                        else:
                            _wg_lines.append(f"**#{_wi+1}** — {str(_w)}")
                    _warn_embed.add_field(
                        name=f"{_wg['guild_name']} ({_wg['guild_id']}) — {len(_wg['warnings'])} warning(s)",
                        value=_trunc("\n".join(_wg_lines) or "—"),
                        inline=False,
                    )
                _rep_embeds.append(_warn_embed)

            # 5. Moderation history (temp actions + bans)
            _mod_lines = []
            if _rep_ba_banned:
                _mod_lines.append("• **Baxi AutoMod Ban** — active")
            if _rep_gc_banned:
                _mod_lines.append("• **Global Chat Ban** — active")
            for _ta in _rep_temp_actions:
                _mod_lines.append(
                    f"• **{_ta['type'].capitalize()}** in {_ta['guild_name']} ({_ta['guild_id']})"
                    + (f" — Reason: {_ta['reason']}" if _ta.get("reason") else "")
                    + (f" — Expires: {_ta['expires_at'][:16]}" if _ta.get("expires_at") else "")
                    + (f" — By: {_ta['moderator_name']}" if _ta.get("moderator_name") else "")
                )
            if _mod_lines:
                _mod_embed = discord.Embed(
                    title="🔨 Moderation History",
                    description=_trunc("\n".join(_mod_lines), 3900),
                    color=0xf97316,
                )
                _rep_embeds.append(_mod_embed)

            # 6. Tickets
            _tk_lines = []
            for _ot in _rep_open_tickets:
                import datetime as _dt
                _tc = _dt.datetime.fromtimestamp(_ot.get("created_at", 0)).strftime("%d.%m.%Y") if _ot.get("created_at") else "—"
                _tk_lines.append(f"• **[Open]** {_ot.get('title', '—')} — opened {_tc}\n  _{_trunc(_ot.get('message', ''), 100)}_")
            for _tr in _rep_transcripts:
                _tk_lines.append(
                    f"• **[Closed]** {_tr.get('title', '—')}"
                    + (f" — closed by {_tr.get('closed_by', '—')}" if _tr.get("closed_by") else "")
                    + (f" on {str(_tr.get('closed_on', ''))[:10]}" if _tr.get("closed_on") else "")
                    + f" | ID: {_tr.get('id', '—')}"
                )
            if _tk_lines:
                _tk_embed = discord.Embed(
                    title="🎫 Support Tickets",
                    description=_trunc("\n".join(_tk_lines), 3900),
                    color=0x22d3ee,
                )
                _rep_embeds.append(_tk_embed)

            if not _rep_embeds:
                _rep_embeds.append(discord.Embed(
                    title="📋 Your Data stored by Baxi",
                    description="No data was found stored about your account in the Baxi system.",
                    color=config.Discord.color,
                ))

            try:
                for _emb in _rep_embeds:
                    await _rep_target.send(embed=_emb)
            except discord.Forbidden:
                return quart.jsonify({"success": False, "message": "Could not send DM — user has DMs disabled."}), 400
            except Exception as _e2:
                return quart.jsonify({"success": False, "message": f"Failed to send DM: {_e2}"}), 500

            share.admin_log(
                "info",
                f"Data report ({len(_rep_embeds)} embeds) sent to {_rep_target.name} ({user_id_str}) by {user.name}",
                source="AdminDash",
            )
            return quart.jsonify({"success": True, "message": f"Data report sent to {_rep_target.name} via DM ({len(_rep_embeds)} messages)."})

        return quart.jsonify({"success": False, "message": f"Unknown action: {action}"}), 400

    app.config["BOT_READY"] = True
