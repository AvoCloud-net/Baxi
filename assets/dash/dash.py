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
from assets.livestream import twitch_api
from quart_discord import DiscordOAuth2Session, requires_authorization, Unauthorized
from datetime import datetime
import random
import re
from typing import cast
import config.config as config
from assets.buttons import TicketView
import time
import json
import os


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
        return redirect(url_for("login"))

    def get_time_based_greeting(username):
        hour = datetime.now().hour

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
                    "time": str(datetime.now().strftime("%d.%m.%Y - %H:%M")),
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
                    "time": str(datetime.now().strftime("%d.%m.%Y - %H:%M")),
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
                    "time": str(datetime.now().strftime("%d.%m.%Y - %H:%M")),
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
            return await render_template(
                "dash_home.html",
                managed_guilds=valid_guilds,
                greeting=get_time_based_greeting(user.name),
                user=user,
                stats=stats,
                show_intro=show_intro
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
                    "time": str(datetime.now().strftime("%d.%m.%Y - %H:%M")),
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
                    "time": str(datetime.now().strftime("%d.%m.%Y - %H:%M")),
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

            catrgorys_list = {
                str(cat.id): cat.name
                for cat in channels
                if isinstance(cat, discord.CategoryChannel)
            }

            assert bot.user is not None, "bot user unknown"

            guild_bot_user = await guild.fetch_member(bot.user.id)
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

            guild_conf.setdefault("enabled", False)
            guild_conf.setdefault("system", "")
            guild_conf.setdefault("c_goodwords", [])
            guild_conf.setdefault("c_badwords", [])
            guild_conf.setdefault("bypass", [])

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

            print(guild_conf)

            save_data(int(guild_id), "chatfilter", guild_conf)

            user = await discord_auth.fetch_user()
            audit_log_new: dict = {
                "type": "save",
                "user": user.name,
                "success": True,
                "time": str(datetime.now().strftime("%d.%m.%Y - %H:%M")),
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

            user = await discord_auth.fetch_user()
            audit_log_new: dict = {
                "type": "save",
                "user": user.name,
                "success": True,
                "time": str(datetime.now().strftime("%d.%m.%Y - %H:%M")),
                "sys": "general",
            }
            audit_log: list = cast(
                list, load_data(sid=int(guild_id), sys="audit_log", bot=bot)
            )
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
                "time": str(datetime.now().strftime("%d.%m.%Y - %H:%M")),
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

            bot_member_check = await guild.fetch_member(bot.user.id)
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
                title=f"{config.Icons.questionmark} {guild.name} support",
                description=ticket["message"],
                color=discord.Color.from_str(ticket["color"]),
            )

            await channel.send(embed=embed, view=TicketView())

            save_data(guild.id, "ticket", settings)

            user = await discord_auth.fetch_user()
            audit_log_new: dict = {
                "type": "save",
                "user": user.name,
                "success": True,
                "time": str(datetime.now().strftime("%d.%m.%Y - %H:%M")),
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
                "time": str(datetime.now().strftime("%d.%m.%Y - %H:%M")),
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
                "time": str(datetime.now().strftime("%d.%m.%Y - %H:%M")),
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
                "time": str(datetime.now().strftime("%d.%m.%Y - %H:%M")),
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
                    "created_at": str(datetime.now().strftime("%Y-%m-%d")),
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
                "time": str(datetime.now().strftime("%d.%m.%Y - %H:%M")),
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
                login = str(livestream.get("login", "")).strip().lower()
                if not login:
                    return quart.jsonify({"success": False, "message": "Twitch username is required."}), 400
                if not re.fullmatch(r"[a-z0-9_]{2,25}", login):
                    return quart.jsonify({"success": False, "message": "Invalid Twitch username format."}), 400

                ls_config = dict(load_data(int(guild_id), "livestream"))
                streamers = ls_config.get("streamers", [])

                if len(streamers) >= 10:
                    return quart.jsonify({"success": False, "message": "Maximum of 10 streamers reached."}), 400

                if any(s.get("login", "").lower() == login for s in streamers):
                    return quart.jsonify({"success": False, "message": f"'{login}' is already being tracked."}), 400

                # Validate that the Twitch user exists
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                    users = await twitch_api.get_users(session, [login])
                if login not in users:
                    return quart.jsonify({"success": False, "message": f"Twitch user '{login}' not found."}), 404

                display_name = users[login]["display_name"]

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
                channel_name = ls_lang.get("channel_name_offline", "\U0001f534\u2502{name}").format(
                    name=display_name.lower()
                )

                try:
                    new_channel = await guild.create_text_channel(
                        name=channel_name,
                        category=category,
                        reason=f"Baxi Livestream: tracking {display_name}",
                    )
                except discord.Forbidden:
                    return quart.jsonify({"success": False, "message": "Bot does not have permission to create channels."}), 403

                # Build initial offline embed
                profile = users[login]
                offline_embed = discord.Embed(
                    title=ls_lang.get("embed_offline_title", "{name} is offline").format(name=display_name),
                    description=ls_lang.get("embed_offline_description", "{name} is not streaming right now. Check back later!").format(name=display_name),
                    url=f"https://twitch.tv/{login}",
                    color=discord.Color.red(),
                )
                if profile.get("offline_image_url"):
                    offline_embed.set_image(url=profile["offline_image_url"])
                if profile.get("profile_image_url"):
                    offline_embed.set_thumbnail(url=profile["profile_image_url"])
                offline_embed.set_footer(text=ls_lang.get("embed_footer", "Baxi Livestream - avocloud.net"))

                msg = await new_channel.send(embed=offline_embed)

                streamer_entry = {
                    "login": login,
                    "display_name": display_name,
                    "channel_id": str(new_channel.id),
                    "message_id": str(msg.id),
                    "profile_image_url": profile.get("profile_image_url", ""),
                }
                streamers.append(streamer_entry)
                ls_config["streamers"] = streamers
                save_data(int(guild_id), "livestream", ls_config)

            elif action == "remove":
                login = str(livestream.get("login", "")).strip().lower()
                if not login:
                    return quart.jsonify({"success": False, "message": "Twitch username is required."}), 400

                ls_config = dict(load_data(int(guild_id), "livestream"))
                streamers = ls_config.get("streamers", [])
                found = None
                for s in streamers:
                    if s.get("login", "").lower() == login:
                        found = s
                        break

                if not found:
                    return quart.jsonify({"success": False, "message": f"'{login}' is not being tracked."}), 404

                # Delete the channel
                channel_id = found.get("channel_id")
                if channel_id:
                    try:
                        ch = await guild.fetch_channel(int(channel_id))
                        await ch.delete(reason=f"Baxi Livestream: stopped tracking {login}")
                    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                        pass

                streamers = [s for s in streamers if s.get("login", "").lower() != login]
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
                "time": str(datetime.now().strftime("%d.%m.%Y - %H:%M")),
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
                "time": str(datetime.now().strftime("%d.%m.%Y - %H:%M")),
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
                "time": str(datetime.now().strftime("%d.%m.%Y - %H:%M")),
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
                "time": str(datetime.now().strftime("%d.%m.%Y - %H:%M")),
                "sys": "temp_voice",
            }
            audit_log: list = cast(
                list, load_data(sid=int(guild_id), sys="audit_log", bot=bot)
            )
            audit_log.append(audit_log_new)
            save_data(int(guild_id), "audit_log", audit_log)

        return quart.jsonify({"success": True, "message": "Settings applied successfully."})

    @app.route("/api/dash/welcomer-bg/", methods=["GET", "POST", "DELETE"])
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
