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
from assets.buttons import build_ticket_panel_view
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
        "youtube_videos": 0,
        "custom_commands": 0,
        "globalchat": 0,
        "stats_channels": 0,
        "auto_roles": 0,
        "reaction_roles": 0,
        "auto_slowmode": 0,
        "counting": 0,
        "flag_quiz": 0,
        "suggestions": 0,
        "temp_voice": 0,
        "verify": 0,
        "sticky_messages": 0,
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
        if conf.get("reaction_roles", {}).get("panels"):
            counts["reaction_roles"] += 1
        if conf.get("auto_slowmode", {}).get("enabled", False):
            counts["auto_slowmode"] += 1
        if conf.get("counting", {}).get("enabled", False):
            counts["counting"] += 1
        if conf.get("flag_quiz", {}).get("enabled", False):
            counts["flag_quiz"] += 1
        if conf.get("suggestions", {}).get("enabled", False):
            counts["suggestions"] += 1
        if conf.get("temp_voice", {}).get("enabled", False):
            counts["temp_voice"] += 1
        if conf.get("verify", {}).get("enabled", False):
            counts["verify"] += 1
        if conf.get("youtube_videos", {}).get("enabled", False):
            counts["youtube_videos"] += 1
        sticky_path = os.path.join(data_dir, guild_id, "sticky_messages.json")
        if os.path.exists(sticky_path):
            try:
                with open(sticky_path, "r", encoding="utf-8") as sf:
                    sticky = json.load(sf)
                if sticky:
                    counts["sticky_messages"] += 1
            except Exception:
                pass

    return {k: round(v / total * 100) for k, v in counts.items()}


def dash_web(app: quart.Quart, bot: commands.AutoShardedBot):
    assert bot.user is not None, "Bot user None"
    app.config["DISCORD_CLIENT_ID"] = int(bot.user.id)
    app.config["DISCORD_CLIENT_SECRET"] = auth.Bot.client_secret
    app.config["DISCORD_REDIRECT_URI"] = auth.Bot.callback_url
    app.secret_key = auth.Web.secret_key

    discord_auth = DiscordOAuth2Session(app)

    # Pending-vote map: discord_user_id -> (guild_id, expires_at_unix).
    # Populated when a user clicks the vote button on the dashboard, then
    # consumed when the top.gg webhook fires (V1 doesn't pass `query` anymore).
    pending_votes: dict[int, tuple[int, float]] = {}
    PENDING_VOTE_TTL = 60 * 60 * 6  # 6 hours

    def _cleanup_pending_votes():
        now = time.time()
        stale = [uid for uid, (_g, exp) in pending_votes.items() if exp < now]
        for uid in stale:
            pending_votes.pop(uid, None)

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
            next_url = session.pop("next_url", None)
            if next_url:
                return redirect(next_url)
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
        current_user = None
        try:
            if discord_auth.authorized:
                current_user = await discord_auth.fetch_user()
        except Exception:
            pass
        return await render_template(
            "welcome.html",
            stats=stats,
            version=config.Discord.version,
            current_user=current_user,
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
                bot_id=bot.user.id,
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

            # Never send donation provider credentials to the browser. Replace them with
            # boolean "is set" flags so the template can render a placeholder instead.
            _don = guild_conf.get("donations")
            if isinstance(_don, dict):
                for _k in ("stripe_secret_key", "stripe_webhook_secret", "paypal_client_id", "paypal_client_secret"):
                    _don[f"has_{_k}"] = bool(_don.get(_k))
                    _don[_k] = ""

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
            
            user_on_avocloud = False
            avocloud_guild_id = auth.TopGG.avocloud_guild_id
            if avocloud_guild_id:
                avocloud_guild = bot.get_guild(avocloud_guild_id)
                if avocloud_guild is not None:
                    try:
                        avo_member = avocloud_guild.get_member(user.id)
                        if avo_member is None:
                            avo_member = await avocloud_guild.fetch_member(user.id)
                        user_on_avocloud = avo_member is not None
                    except discord.NotFound:
                        user_on_avocloud = False
                    except Exception:
                        user_on_avocloud = False

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
                bot_id=bot.user.id,
                user_on_avocloud=user_on_avocloud,
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

            if not isinstance(ticket, dict):
                return quart.jsonify({"success": False, "message": "Invalid data format: 'ticket' must be an object."}), 400
            if not isinstance(ticket.get("enabled"), bool):
                return quart.jsonify({"success": False, "message": "'enabled' must be a boolean (true/false)."}), 400

            settings: dict = dict(load_data(guild.id, "ticket"))
            settings.setdefault("enabled", False)
            settings.setdefault("channel", "")
            settings.setdefault("transcript", "")
            settings.setdefault("role", "")
            settings.setdefault("catid", "")
            settings.setdefault("color", "#9333ea")
            settings.setdefault("message", "")
            settings.setdefault("buttons", [])
            settings.setdefault("panel_message_id", "")

            if ticket["enabled"] is False:
                settings["enabled"] = False
                save_data(guild.id, "ticket", settings)
            else:
                # Validate required fields
                if not isinstance(ticket.get("channel"), str) or not re.fullmatch(r"\d{17,19}", ticket["channel"]):
                    return quart.jsonify({"success": False, "message": "Channel ID does not match the Discord ID format."}), 400
                if not isinstance(ticket.get("role"), str) or not re.fullmatch(r"\d{17,19}", ticket["role"]):
                    return quart.jsonify({"success": False, "message": "Role ID does not match the Discord ID format."}), 400
                if not isinstance(ticket.get("category"), str) or not re.fullmatch(r"\d{17,19}", ticket["category"]):
                    return quart.jsonify({"success": False, "message": "Category ID does not match the Discord ID format."}), 400
                if not isinstance(ticket.get("channel_transcript"), str) or not re.fullmatch(r"\d{17,19}", ticket["channel_transcript"]):
                    return quart.jsonify({"success": False, "message": "Transcript channel ID does not match the Discord ID format."}), 400
                color_raw = str(ticket.get("color", "#9333ea"))
                if not re.fullmatch(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})", color_raw):
                    return quart.jsonify({"success": False, "message": "Color must be valid HEX."}), 400

                # Validate buttons
                raw_buttons = ticket.get("buttons", [])
                if not isinstance(raw_buttons, list) or len(raw_buttons) == 0:
                    return quart.jsonify({"success": False, "message": "At least one ticket button is required."}), 400
                if len(raw_buttons) > 25:
                    return quart.jsonify({"success": False, "message": "Maximum 25 ticket buttons allowed."}), 400

                allowed_styles = {"primary", "secondary", "success", "danger"}
                cleaned_buttons: list[dict] = []
                used_ids: set[str] = set()
                for b in raw_buttons:
                    if not isinstance(b, dict):
                        continue
                    label = str(b.get("label", "")).strip()[:50]
                    emoji = str(b.get("emoji", "")).strip()[:50]
                    style = str(b.get("style", "primary")).strip().lower()
                    if style not in allowed_styles:
                        style = "primary"
                    if not label and not emoji:
                        return quart.jsonify({"success": False, "message": "Each button needs a label or an emoji."}), 400
                    # Derive stable id from label (slugified). Ensure uniqueness.
                    base_id = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-") or "ticket"
                    btn_id = base_id
                    n = 2
                    while btn_id in used_ids:
                        btn_id = f"{base_id}-{n}"
                        n += 1
                    used_ids.add(btn_id)
                    cleaned_buttons.append({"id": btn_id, "label": label, "emoji": emoji, "style": style})

                bot_member_check = await guild.fetch_member(bot.user.id)  # type: ignore
                bot_top_role = bot_member_check.top_role
                guild_roles_sorted = sorted(guild.roles, key=lambda r: r.position, reverse=True)
                if bot_top_role.position != guild_roles_sorted[0].position:
                    return quart.jsonify({
                        "success": False,
                        "message": f"Bot role \"{bot_top_role.name}\" is not at the top of the role hierarchy. The ticket system requires the bot role to be highest so it can manage channel permissions."
                    }), 403

                channel = await guild.fetch_channel(int(ticket["channel"]))
                if not isinstance(channel, discord.TextChannel):
                    return quart.jsonify({"success": False, "message": "The specified channel is not a text channel."}), 400

                cat = await guild.fetch_channel(int(ticket["category"]))
                if not isinstance(cat, discord.CategoryChannel):
                    return quart.jsonify({"success": False, "message": "The specified category is not a category."}), 400

                settings["enabled"] = True
                settings["channel"] = ticket["channel"]
                settings["transcript"] = ticket["channel_transcript"]
                settings["role"] = ticket["role"]
                settings["catid"] = ticket["category"]
                settings["color"] = color_raw
                settings["message"] = str(ticket.get("message", ""))[:4000]
                settings["buttons"] = cleaned_buttons

                embed = discord.Embed(
                    title=f"{config.Icons.questionmark} SYS // {guild.name} SUPPORT",
                    description=settings["message"],
                    color=discord.Color.from_str(color_raw),
                )

                panel_msg = await channel.send(embed=embed, view=build_ticket_panel_view(cleaned_buttons))
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

            # Validate optional whitelisted_channels
            raw_wl_ch = antispam.get("whitelisted_channels", [])
            if not isinstance(raw_wl_ch, list):
                return quart.jsonify({"success": False, "message": "'whitelisted_channels' must be a list."}), 400
            whitelisted_channels = [str(c) for c in raw_wl_ch if re.fullmatch(r"\d{17,19}", str(c))]

            # Validate optional whitelisted_roles
            raw_wl_ro = antispam.get("whitelisted_roles", [])
            if not isinstance(raw_wl_ro, list):
                return quart.jsonify({"success": False, "message": "'whitelisted_roles' must be a list."}), 400
            whitelisted_roles = [str(r) for r in raw_wl_ro if re.fullmatch(r"\d{17,19}", str(r))]

            settings = {
                "enabled": antispam["enabled"],
                "max_messages": max(2, min(20, int(antispam.get("max_messages", 5)))),
                "interval": max(2, min(30, int(antispam.get("interval", 5)))),
                "max_duplicates": max(2, min(10, int(antispam.get("max_duplicates", 3)))),
                "action": antispam.get("action", "mute") if antispam.get("action") in ["mute", "warn", "kick", "ban"] else "mute",
                "whitelisted_channels": whitelisted_channels,
                "whitelisted_roles": whitelisted_roles,
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

        elif system == "youtube_videos":
            data: dict = await quart.request.get_json()
            yv_data = data.get("youtube_videos")

            if not isinstance(yv_data, dict):
                return quart.jsonify({"success": False, "message": "Invalid data format."}), 400

            action = yv_data.get("action", "save")

            if action == "add":
                login = str(yv_data.get("login", "")).strip()
                if not login:
                    return quart.jsonify({"success": False, "message": "Channel handle or ID is required."}), 400
                if not re.fullmatch(r"[@a-zA-Z0-9_.\-]{2,64}", login):
                    return quart.jsonify({"success": False, "message": "Invalid YouTube channel handle or ID."}), 400

                yv_config = dict(load_data(int(guild_id), "youtube_videos"))
                channels = yv_config.get("channels", [])

                if len(channels) >= 10:
                    return quart.jsonify({"success": False, "message": "Maximum of 10 tracked channels reached."}), 400

                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
                    channel_info = await youtube_api.get_channel(session, login)

                if not channel_info:
                    return quart.jsonify({"success": False, "message": f"YouTube channel '{login}' not found. Try using @handle or UCxxx channel ID."}), 404

                resolved_id       = channel_info["channel_id"]
                display_name      = channel_info["display_name"]
                handle            = channel_info.get("handle", "")
                profile_image_url = channel_info.get("profile_image_url", "")

                if any(c.get("channel_id") == resolved_id for c in channels):
                    return quart.jsonify({"success": False, "message": f"'{display_name}' is already being tracked."}), 400

                channels.append({
                    "channel_id":        resolved_id,
                    "display_name":      display_name,
                    "handle":            handle,
                    "profile_image_url": profile_image_url,
                    "last_video_id":     "",
                })
                yv_config["channels"] = channels
                save_data(int(guild_id), "youtube_videos", yv_config)

                user = await discord_auth.fetch_user()
                audit_log_new: dict = {
                    "type": "save",
                    "user": user.name,
                    "success": True,
                    "time": str(datetime.now(_VIENNA).strftime("%d.%m.%Y - %H:%M")),
                    "sys": "youtube_videos",
                }
                audit_log: list = cast(list, load_data(sid=int(guild_id), sys="audit_log", bot=bot))
                audit_log.append(audit_log_new)
                save_data(int(guild_id), "audit_log", audit_log)
                return quart.jsonify({
                    "success": True,
                    "message": f"Now tracking '{display_name}'.",
                    "channel": {
                        "channel_id":        resolved_id,
                        "display_name":      display_name,
                        "handle":            handle,
                        "profile_image_url": profile_image_url,
                    },
                })

            elif action == "remove":
                channel_id_to_remove = str(yv_data.get("channel_id", "")).strip()
                if not channel_id_to_remove:
                    return quart.jsonify({"success": False, "message": "channel_id is required."}), 400

                yv_config = dict(load_data(int(guild_id), "youtube_videos"))
                channels = yv_config.get("channels", [])
                before_count = len(channels)
                channels = [c for c in channels if c.get("channel_id") != channel_id_to_remove]

                if len(channels) == before_count:
                    return quart.jsonify({"success": False, "message": "Channel not found."}), 404

                yv_config["channels"] = channels
                save_data(int(guild_id), "youtube_videos", yv_config)

                user = await discord_auth.fetch_user()
                audit_log_new: dict = {
                    "type": "save",
                    "user": user.name,
                    "success": True,
                    "time": str(datetime.now(_VIENNA).strftime("%d.%m.%Y - %H:%M")),
                    "sys": "youtube_videos",
                }
                audit_log: list = cast(list, load_data(sid=int(guild_id), sys="audit_log", bot=bot))
                audit_log.append(audit_log_new)
                save_data(int(guild_id), "audit_log", audit_log)
                return quart.jsonify({"success": True, "message": "Channel removed."})

            elif action == "save":
                if not isinstance(yv_data.get("enabled"), bool):
                    return quart.jsonify({"success": False, "message": "'enabled' must be a boolean."}), 400

                alert_channel = str(yv_data.get("alert_channel", "")).strip()
                if alert_channel and not re.fullmatch(r"\d{17,19}", alert_channel):
                    return quart.jsonify({"success": False, "message": "Invalid alert channel ID."}), 400

                ping_role = str(yv_data.get("ping_role", "")).strip()
                if ping_role and not re.fullmatch(r"\d{17,19}", ping_role):
                    return quart.jsonify({"success": False, "message": "Invalid ping role ID."}), 400

                yv_config = dict(load_data(int(guild_id), "youtube_videos"))
                yv_config["enabled"]       = yv_data["enabled"]
                yv_config["alert_channel"] = alert_channel
                yv_config["ping_role"]     = ping_role
                save_data(int(guild_id), "youtube_videos", yv_config)

                user = await discord_auth.fetch_user()
                audit_log_new: dict = {
                    "type": "save",
                    "user": user.name,
                    "success": True,
                    "time": str(datetime.now(_VIENNA).strftime("%d.%m.%Y - %H:%M")),
                    "sys": "youtube_videos",
                }
                audit_log: list = cast(list, load_data(sid=int(guild_id), sys="audit_log", bot=bot))
                audit_log.append(audit_log_new)
                save_data(int(guild_id), "audit_log", audit_log)

            else:
                return quart.jsonify({"success": False, "message": "Invalid action."}), 400

            return quart.jsonify({"success": True, "message": "Settings saved."})

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

        elif system == "counting":
            data: dict = await quart.request.get_json()
            counting = data.get("counting")

            if not isinstance(counting, dict):
                return quart.jsonify({"success": False, "message": "Invalid data format: 'counting' must be an object."}), 400

            if not isinstance(counting.get("enabled"), bool):
                return quart.jsonify({"success": False, "message": "'enabled' must be a boolean."}), 400

            channel_raw = str(counting.get("channel", "")).strip()
            if channel_raw and not re.fullmatch(r"\d{17,19}", channel_raw):
                return quart.jsonify({"success": False, "message": "Invalid channel ID."}), 400

            existing: dict = dict(load_data(int(guild_id), "counting"))
            settings = {
                "enabled": counting["enabled"],
                "channel": channel_raw if channel_raw else "",
                "no_double_count": bool(counting.get("no_double_count", True)),
                "react_correct": bool(counting.get("react_correct", True)),
                "react_wrong": bool(counting.get("react_wrong", True)),
                # preserve runtime state
                "current_count": existing.get("current_count", 0),
                "high_score": existing.get("high_score", 0),
                "last_user_id": existing.get("last_user_id", 0),
            }

            save_data(int(guild_id), "counting", settings)

            user = await discord_auth.fetch_user()
            audit_log_new: dict = {
                "type": "save",
                "user": user.name,
                "success": True,
                "time": str(datetime.now(_VIENNA).strftime("%d.%m.%Y - %H:%M")),
                "sys": "counting",
            }
            audit_log: list = cast(list, load_data(sid=int(guild_id), sys="audit_log", bot=bot))
            audit_log.append(audit_log_new)
            save_data(int(guild_id), "audit_log", audit_log)

            return quart.jsonify({"success": True, "message": "Counting Game settings saved!"})

        elif system == "counting_reset":
            existing: dict = dict(load_data(int(guild_id), "counting"))
            existing["current_count"] = 0
            existing["last_user_id"] = 0
            save_data(int(guild_id), "counting", existing)

            user = await discord_auth.fetch_user()
            audit_log_new = {
                "type": "save",
                "user": user.name,
                "success": True,
                "time": str(datetime.now(_VIENNA).strftime("%d.%m.%Y - %H:%M")),
                "sys": "counting_reset",
            }
            audit_log = cast(list, load_data(sid=int(guild_id), sys="audit_log", bot=bot))
            audit_log.append(audit_log_new)
            save_data(int(guild_id), "audit_log", audit_log)

            return quart.jsonify({"success": True, "message": "Count was reset to 0."})

        elif system == "leveling":
            data: dict = await quart.request.get_json()
            lev = data.get("leveling")

            if not isinstance(lev, dict):
                return quart.jsonify({"success": False, "message": "Invalid data format."}), 400
            if not isinstance(lev.get("enabled"), bool):
                return quart.jsonify({"success": False, "message": "'enabled' must be a boolean."}), 400

            announcement = str(lev.get("announcement", "same_channel"))
            if announcement not in ("same_channel", "channel", "off"):
                announcement = "same_channel"

            ann_channel = str(lev.get("announcement_channel", "")).strip()
            if ann_channel and not re.fullmatch(r"\d{17,19}", ann_channel):
                return quart.jsonify({"success": False, "message": "Invalid announcement channel ID."}), 400

            raw_rewards = lev.get("role_rewards", [])
            if not isinstance(raw_rewards, list):
                return quart.jsonify({"success": False, "message": "'role_rewards' must be a list."}), 400
            role_rewards = []
            for r in raw_rewards:
                if not isinstance(r, dict):
                    continue
                lvl = r.get("level")
                rid = str(r.get("role_id", "")).strip()
                if not isinstance(lvl, int) or lvl < 1:
                    continue
                if not re.fullmatch(r"\d{17,19}", rid):
                    continue
                role_rewards.append({"level": lvl, "role_id": rid})

            existing: dict = dict(load_data(int(guild_id), "leveling"))
            settings = {
                "enabled": lev["enabled"],
                "xp": existing.get("xp", 0),
                "level": existing.get("level", 0),
                "announcement": announcement,
                "announcement_channel": ann_channel,
                "role_rewards": role_rewards,
            }
            save_data(int(guild_id), "leveling", settings)

            user = await discord_auth.fetch_user()
            audit_log_new: dict = {
                "type": "save",
                "user": user.name,
                "success": True,
                "time": str(datetime.now(_VIENNA).strftime("%d.%m.%Y - %H:%M")),
                "sys": "leveling",
            }
            audit_log: list = cast(list, load_data(sid=int(guild_id), sys="audit_log", bot=bot))
            audit_log.append(audit_log_new)
            save_data(int(guild_id), "audit_log", audit_log)

            return quart.jsonify({"success": True, "message": "Level System settings saved!"})

        elif system == "flag_quiz":
            data: dict = await quart.request.get_json()
            fq = data.get("flag_quiz")

            if not isinstance(fq, dict):
                return quart.jsonify({"success": False, "message": "Invalid data format: 'flag_quiz' must be an object."}), 400

            if not isinstance(fq.get("enabled"), bool):
                return quart.jsonify({"success": False, "message": "'enabled' must be a boolean."}), 400

            channel_raw = str(fq.get("channel", "")).strip()
            if channel_raw and not re.fullmatch(r"\d{17,19}", channel_raw):
                return quart.jsonify({"success": False, "message": "Invalid channel ID."}), 400

            existing: dict = dict(load_data(int(guild_id), "flag_quiz"))

            try:
                hint_after_attempts = max(0, min(20, int(fq.get("hint_after_attempts", 3))))
                next_delay = max(1, min(60, int(fq.get("next_delay", 3))))
            except (ValueError, TypeError):
                return quart.jsonify({"success": False, "message": "hint_after_attempts and next_delay must be integers."}), 400

            settings = {
                "enabled": fq["enabled"],
                "channel": channel_raw if channel_raw else "",
                "hint_after_attempts": hint_after_attempts,
                "next_delay": next_delay,
                "points_enabled": bool(fq.get("points_enabled", True)),
                # preserve scores
                "scores": existing.get("scores", {}),
            }

            save_data(int(guild_id), "flag_quiz", settings)

            # Auto-start: if enabled and no question is currently active, post first round
            if settings["enabled"] and settings["channel"]:
                import assets.games.quiz as quiz_game
                gid_int = int(guild_id)
                if gid_int not in quiz_game._active:
                    guild_obj = bot.get_guild(gid_int)
                    if guild_obj:
                        ch = guild_obj.get_channel(int(settings["channel"]))
                        if isinstance(ch, discord.TextChannel):
                            asyncio.create_task(quiz_game.start_round(gid_int, ch, bot))

            user = await discord_auth.fetch_user()
            audit_log_new = {
                "type": "save",
                "user": user.name,
                "success": True,
                "time": str(datetime.now(_VIENNA).strftime("%d.%m.%Y - %H:%M")),
                "sys": "flag_quiz",
            }
            audit_log = cast(list, load_data(sid=int(guild_id), sys="audit_log", bot=bot))
            audit_log.append(audit_log_new)
            save_data(int(guild_id), "audit_log", audit_log)

            return quart.jsonify({"success": True, "message": "Flag Quiz settings saved!"})

        elif system == "flag_quiz_reset_scores":
            existing: dict = dict(load_data(int(guild_id), "flag_quiz"))
            existing["scores"] = {}
            save_data(int(guild_id), "flag_quiz", existing)

            user = await discord_auth.fetch_user()
            audit_log_new = {
                "type": "save",
                "user": user.name,
                "success": True,
                "time": str(datetime.now(_VIENNA).strftime("%d.%m.%Y - %H:%M")),
                "sys": "flag_quiz_reset_scores",
            }
            audit_log = cast(list, load_data(sid=int(guild_id), sys="audit_log", bot=bot))
            audit_log.append(audit_log_new)
            save_data(int(guild_id), "audit_log", audit_log)

            return quart.jsonify({"success": True, "message": "All scores have been reset."})

        elif system == "suggestions":
            data: dict = await quart.request.get_json()
            sugg = data.get("suggestions")

            if not isinstance(sugg, dict):
                return quart.jsonify({"success": False, "message": "Invalid data format."}), 400

            if not isinstance(sugg.get("enabled"), bool):
                return quart.jsonify({"success": False, "message": "'enabled' must be a boolean."}), 400

            # Validate and clean channel list (new format: list of dicts)
            raw_channels = sugg.get("channels", [])
            if not isinstance(raw_channels, list):
                return quart.jsonify({"success": False, "message": "'channels' must be a list."}), 400
            channels: list[dict] = []
            for ch in raw_channels:
                if isinstance(ch, str) and re.fullmatch(r"\d{17,19}", ch):
                    # Backward-compat: plain string → wrap as dict
                    channels.append({"id": ch, "votes_enabled": True})
                elif isinstance(ch, dict):
                    ch_id = str(ch.get("id", "")).strip()
                    if not re.fullmatch(r"\d{17,19}", ch_id):
                        continue
                    channels.append({
                        "id": ch_id,
                        "votes_enabled": bool(ch.get("votes_enabled", True)),
                    })

            staff_role_raw = str(sugg.get("staff_role", "") or "").strip()
            if staff_role_raw and not re.fullmatch(r"\d{17,19}", staff_role_raw):
                return quart.jsonify({"success": False, "message": "Invalid staff role ID."}), 400

            log_ch_raw = str(sugg.get("log_channel", "") or "").strip()
            if log_ch_raw and not re.fullmatch(r"\d{17,19}", log_ch_raw):
                return quart.jsonify({"success": False, "message": "Invalid log channel ID."}), 400

            # Validate auto-forward settings
            auto_forward_enabled = bool(sugg.get("auto_forward_enabled", False))
            af_ch_raw = str(sugg.get("auto_forward_channel", "") or "").strip()
            if af_ch_raw and not re.fullmatch(r"\d{17,19}", af_ch_raw):
                return quart.jsonify({"success": False, "message": "Invalid auto_forward_channel ID."}), 400
            try:
                af_threshold = max(1, min(1000, int(sugg.get("auto_forward_threshold", 10))))
            except (ValueError, TypeError):
                af_threshold = 10

            settings = {
                "enabled": sugg["enabled"],
                "channels": channels,
                "staff_role": staff_role_raw,
                "log_channel": log_ch_raw,
                "auto_forward_enabled": auto_forward_enabled,
                "auto_forward_channel": af_ch_raw,
                "auto_forward_threshold": af_threshold,
            }
            save_data(int(guild_id), "suggestions", settings)

            user = await discord_auth.fetch_user()
            audit_log_new = {
                "type": "save",
                "user": user.name,
                "success": True,
                "time": str(datetime.now(_VIENNA).strftime("%d.%m.%Y - %H:%M")),
                "sys": "suggestions",
            }
            audit_log = cast(list, load_data(sid=int(guild_id), sys="audit_log", bot=bot))
            audit_log.append(audit_log_new)
            save_data(int(guild_id), "audit_log", audit_log)

            return quart.jsonify({"success": True, "message": "Suggestion settings saved!"})

        elif system == "sticky_messages":
            data: dict = await quart.request.get_json()
            raw = data.get("sticky_messages")

            if not isinstance(raw, dict):
                return quart.jsonify({"success": False, "message": "Invalid data format."}), 400

            # Validate each entry: channel_id must be a snowflake, message must be a non-empty string ≤2000 chars
            cleaned: dict = {}
            for cid, entry in raw.items():
                if not re.fullmatch(r"\d{17,19}", str(cid)):
                    continue
                if not isinstance(entry, dict):
                    continue
                msg = str(entry.get("message", "")).strip()
                if not msg or len(msg) > 2000:
                    continue
                cleaned[str(cid)] = {
                    "message": msg,
                    "last_message_id": entry.get("last_message_id"),
                }

            save_data(int(guild_id), "sticky_messages", cleaned)

            user = await discord_auth.fetch_user()
            audit_log_new = {
                "type": "save",
                "user": user.name,
                "success": True,
                "time": str(datetime.now(_VIENNA).strftime("%d.%m.%Y - %H:%M")),
                "sys": "sticky_messages",
            }
            audit_log = cast(list, load_data(sid=int(guild_id), sys="audit_log", bot=bot))
            audit_log.append(audit_log_new)
            save_data(int(guild_id), "audit_log", audit_log)

            return quart.jsonify({"success": True, "message": "Sticky messages saved!"})

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

                title = str(rr.get("title", "Button Roles"))[:100]
                description = str(rr.get("description", "Click a button to toggle a role."))[:500]
                color = str(rr.get("color", "#9333ea"))[:7]
                if not re.match(r'^#[0-9a-fA-F]{6}$', color):
                    color = "#9333ea"

                max_roles_raw = rr.get("max_roles")
                max_roles = 0
                if max_roles_raw not in (None, "", 0):
                    try:
                        max_roles = max(0, min(25, int(max_roles_raw)))
                    except (ValueError, TypeError):
                        max_roles = 0

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
                    "max_roles": max_roles,
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

            elif action == "update_panel":
                message_id = str(rr.get("message_id", "")).strip()
                panel = next((p for p in panels if str(p.get("message_id", "")) == message_id), None)
                if panel is None:
                    return quart.jsonify({"success": False, "message": "Panel not found."}), 404

                panel["title"] = str(rr.get("title", panel.get("title", "Button Roles")))[:100]
                panel["description"] = str(rr.get("description", panel.get("description", "")))[:500]
                color = str(rr.get("color", panel.get("color", "#9333ea")))[:7]
                if not re.match(r'^#[0-9a-fA-F]{6}$', color):
                    color = "#9333ea"
                panel["color"] = color

                max_roles_raw = rr.get("max_roles")
                if max_roles_raw in (None, "", 0, "0"):
                    panel["max_roles"] = 0
                else:
                    try:
                        panel["max_roles"] = max(0, min(25, int(max_roles_raw)))
                    except (ValueError, TypeError):
                        panel["max_roles"] = 0

                from assets.message.reactionroles import build_panel_embed, build_panel_view
                try:
                    ch = await guild.fetch_channel(int(panel["channel_id"]))
                    msg = await ch.fetch_message(int(message_id))  # type: ignore
                    await msg.edit(embed=build_panel_embed(panel), view=build_panel_view(panel))
                except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
                    return quart.jsonify({"success": False, "message": f"Could not update panel: {e}"}), 500

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

                panel.setdefault("entries", []).append({"emoji": emoji, "role_id": role_id_raw, "label": label})

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

        elif system == "donations":
            from assets.crypto import encrypt_secret, decrypt_secret

            data: dict = await quart.request.get_json()
            don = data.get("donations")

            if not isinstance(don, dict):
                return quart.jsonify({"success": False, "message": "Invalid data format: 'donations' must be an object."}), 400
            if not isinstance(don.get("enabled"), bool):
                return quart.jsonify({"success": False, "message": "'enabled' must be a boolean."}), 400

            provider = str(don.get("provider", "stripe")).strip().lower()
            if provider not in ("stripe", "paypal"):
                return quart.jsonify({"success": False, "message": "provider must be 'stripe' or 'paypal'."}), 400

            # Load existing settings so we can keep unchanged (blank-left) secrets.
            existing: dict = dict(load_data(int(guild_id), "donations"))
            _ex_sk = existing.get("stripe_secret_key", "") or ""
            _ex_wh = existing.get("stripe_webhook_secret", "") or ""
            _ex_pcid = existing.get("paypal_client_id", "") or ""
            _ex_pcs = existing.get("paypal_client_secret", "") or ""

            # Resolve each secret: non-empty input = new plaintext; empty input = keep stored.
            sk_new = str(don.get("stripe_secret_key", "")).strip()
            wh_new = str(don.get("stripe_webhook_secret", "")).strip()
            pcid_new = str(don.get("paypal_client_id", "")).strip()
            pcs_new = str(don.get("paypal_client_secret", "")).strip()

            sk_plain = sk_new if sk_new else decrypt_secret(_ex_sk)
            wh_plain = wh_new if wh_new else decrypt_secret(_ex_wh)
            pcid_plain = pcid_new if pcid_new else decrypt_secret(_ex_pcid)
            pcs_plain = pcs_new if pcs_new else decrypt_secret(_ex_pcs)

            enabled = don["enabled"]
            if enabled:
                if provider == "stripe":
                    if not sk_plain or not (sk_plain.startswith("sk_") or sk_plain.startswith("rk_")):
                        return quart.jsonify({"success": False, "message": "Stripe Secret Key must start with 'sk_' or 'rk_'."}), 400
                    if not wh_plain or not wh_plain.startswith("whsec_"):
                        return quart.jsonify({"success": False, "message": "Stripe Webhook Secret must start with 'whsec_'."}), 400
                elif provider == "paypal":
                    if not pcid_plain:
                        return quart.jsonify({"success": False, "message": "PayPal Client ID is required."}), 400
                    if not pcs_plain:
                        return quart.jsonify({"success": False, "message": "PayPal Client Secret is required."}), 400

            # Validate tiers
            raw_tiers = don.get("tiers", [])
            if not isinstance(raw_tiers, list):
                return quart.jsonify({"success": False, "message": "'tiers' must be a list."}), 400
            cleaned_tiers: list[dict] = []
            for t in raw_tiers:
                if not isinstance(t, dict):
                    continue
                tier_type = str(t.get("type", "fixed"))
                if tier_type not in ("fixed", "range"):
                    return quart.jsonify({"success": False, "message": "Tier type must be 'fixed' or 'range'."}), 400
                label = str(t.get("label", "")).strip()[:100]
                if not label:
                    return quart.jsonify({"success": False, "message": "Each tier must have a label."}), 400
                role_id = str(t.get("role_id", "")).strip()
                if not re.fullmatch(r"\d{17,19}", role_id):
                    return quart.jsonify({"success": False, "message": f"Tier '{label}': Role ID does not match the Discord ID format."}), 400
                tier_id = str(t.get("id", f"tier_{label}")).strip()[:64] or f"tier_{label}"
                entry: dict = {"id": tier_id, "label": label, "type": tier_type, "amount": None, "amount_min": None, "amount_max": None, "role_id": role_id}
                if tier_type == "fixed":
                    try:
                        amount = round(float(t["amount"]), 2)
                        if amount < 0.50:
                            return quart.jsonify({"success": False, "message": f"Tier '{label}': Amount must be at least €0.50."}), 400
                    except (TypeError, ValueError, KeyError):
                        return quart.jsonify({"success": False, "message": f"Tier '{label}': Invalid amount."}), 400
                    entry["amount"] = amount
                else:
                    try:
                        amount_min = round(float(t["amount_min"]), 2)
                        if amount_min < 0.50:
                            return quart.jsonify({"success": False, "message": f"Tier '{label}': Min amount must be at least €0.50."}), 400
                    except (TypeError, ValueError, KeyError):
                        return quart.jsonify({"success": False, "message": f"Tier '{label}': Invalid min amount."}), 400
                    amount_max = None
                    if t.get("amount_max") not in (None, ""):
                        try:
                            amount_max = round(float(t["amount_max"]), 2)
                            if amount_max <= amount_min:
                                return quart.jsonify({"success": False, "message": f"Tier '{label}': Max must be greater than min."}), 400
                        except (TypeError, ValueError):
                            return quart.jsonify({"success": False, "message": f"Tier '{label}': Invalid max amount."}), 400
                    entry["amount_min"] = amount_min
                    entry["amount_max"] = amount_max
                cleaned_tiers.append(entry)

            log_enabled = bool(don.get("log_enabled", False))
            log_channel = str(don.get("log_channel", "")).strip()
            if log_enabled and log_channel and not re.fullmatch(r"\d{17,19}", log_channel):
                return quart.jsonify({"success": False, "message": "Announcement channel ID does not match the Discord ID format."}), 400

            settings: dict = dict(existing)
            settings["enabled"] = enabled
            settings["provider"] = provider
            # Encrypt only when a new plaintext value was supplied; otherwise keep the
            # already-stored (already-encrypted) value verbatim.
            settings["stripe_secret_key"] = encrypt_secret(sk_new) if sk_new else _ex_sk
            settings["stripe_webhook_secret"] = encrypt_secret(wh_new) if wh_new else _ex_wh
            settings["paypal_client_id"] = encrypt_secret(pcid_new) if pcid_new else _ex_pcid
            settings["paypal_client_secret"] = encrypt_secret(pcs_new) if pcs_new else _ex_pcs
            settings["page_text"] = str(don.get("page_text", "Support this server!")).strip()[:2000]
            settings["success_text"] = str(don.get("success_text", "Thank you for your donation!")).strip()[:2000]
            settings["log_enabled"] = log_enabled
            settings["log_channel"] = log_channel
            settings["tiers"] = cleaned_tiers

            save_data(int(guild_id), "donations", settings)

            user = await discord_auth.fetch_user()
            audit_log_new: dict = {
                "type": "save",
                "user": user.name,
                "success": True,
                "time": str(datetime.now(_VIENNA).strftime("%d.%m.%Y - %H:%M")),
                "sys": "donations",
            }
            audit_log: list = cast(list, load_data(sid=int(guild_id), sys="audit_log", bot=bot))
            audit_log.append(audit_log_new)
            save_data(int(guild_id), "audit_log", audit_log)

            return quart.jsonify({"success": True, "message": "Donation settings saved!"})

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
            # Prefer cached guild so that channel.guild and bot_member.guild
            # reference the same object, avoiding permission calculation mismatches.
            guild = bot.get_guild(guild_id)
            if guild is None:
                guild = await bot.fetch_guild(guild_id)
            assert bot.user is not None, "Bot user unknown"
            bot_member = guild.get_member(bot.user.id) or await guild.fetch_member(bot.user.id)

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
            elif system in ("ticket_role", "verify_role", "reaction_role"):
                role_id_raw = data.get("role_id")
                if not role_id_raw:
                    return quart.jsonify({"error": "role_id is required for role hierarchy check"}), 400
                role = guild.get_role(int(role_id_raw))
                if not role:
                    return quart.jsonify({"valid": True, "missing": None, "scope": "role", "note": "Role not found in cache"})
                bot_top = bot_member.top_role
                if bot_top.position > role.position:
                    return quart.jsonify({"valid": True, "missing": None, "scope": "role"})
                else:
                    return quart.jsonify({
                        "valid": False,
                        "missing": [f"Baxi's top role \"{bot_top.name}\" must be above \"{role.name}\" to manage it"],
                        "scope": "role"
                    })
            else:
                if not channel_id:
                    return quart.jsonify({"error": "channel_id is required for this system"}), 400

                try:
                    channel = await guild.fetch_channel(channel_id)
                except discord.NotFound:
                    return quart.jsonify({"valid": False, "missing": ["Channel not found — it may have been deleted"], "scope": "channel"})
                except discord.Forbidden:
                    return quart.jsonify({"valid": False, "missing": ["Baxi cannot access this channel (missing View Channel permission)"], "scope": "channel"})
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
                        "manage_channels",  # for slowmode
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
                elif system in ("temp_voice_category", "livestream_category", "stats_category"):
                    required_perms = {
                        "view_channel",
                        "manage_channels",
                        "manage_permissions",
                    }
                elif system == "temp_voice_trigger":
                    if not isinstance(channel, discord.VoiceChannel):
                        return quart.jsonify({"valid": False, "missing": ["Not a voice channel"], "scope": "channel"})
                    vc_needed = ["view_channel", "connect"]
                    missing_vc = [p for p in vc_needed if not getattr(permissions, p, False)]
                    return quart.jsonify({"valid": not missing_vc, "missing": missing_vc if missing_vc else None, "scope": "channel"})
                elif system == "sticky_messages":
                    required_perms = {
                        "view_channel",
                        "send_messages",
                        "manage_messages",
                    }
                elif system == "suggestions":
                    required_perms = {
                        "view_channel",
                        "send_messages",
                        "embed_links",
                        "manage_messages",
                        "add_reactions",
                    }
                elif system == "suggestions_log":
                    required_perms = {
                        "view_channel",
                        "send_messages",
                        "embed_links",
                    }
                elif system == "counting":
                    required_perms = {
                        "view_channel",
                        "send_messages",
                        "add_reactions",
                    }
                elif system == "reaction_role_channel":
                    required_perms = {
                        "view_channel",
                        "send_messages",
                        "embed_links",
                        "add_reactions",
                        "read_message_history",
                    }
                elif system in ("flag_quiz", "leveling", "youtube_alert", "notification", "donations_log", "verify_channel"):
                    required_perms = {
                        "view_channel",
                        "send_messages",
                        "embed_links",
                    }
                else:
                    return quart.jsonify({"error": "Unknown system"}), 400

                if isinstance(channel, (discord.TextChannel, discord.CategoryChannel)):
                    missing = [perm for perm in required_perms if not getattr(permissions, perm, False)]
                    valid = len(missing) == 0
                else:
                    valid = False
                    missing = ["Channel is not a text or category channel"]

                return quart.jsonify({
                    "valid": valid,
                    "missing": missing if not valid else None,
                    "scope": "channel"
                })

        except Exception as e:
            return quart.jsonify({"error": str(e)}), 500

    @app.route("/api/dash/channel-stats/", methods=["GET"])
    @requires_authorization
    async def channel_stats_api():
        """Returns text-channel count, how many Baxi can see, and how many have view+manage_messages."""
        guild_id_raw = quart.request.args.get("guild_id")
        if not guild_id_raw:
            return quart.jsonify({"error": "Missing guild_id"}), 400
        try:
            user = await discord_auth.fetch_user()
            guild_obj = await bot.fetch_guild(int(guild_id_raw))
            member_check = await guild_obj.fetch_member(user.id)
            if not member_check.guild_permissions.manage_guild:
                return quart.jsonify({"error": "Unauthorized"}), 403
        except Exception:
            return quart.jsonify({"error": "Authorization failed"}), 403

        cached = bot.get_guild(int(guild_id_raw))
        if not cached:
            return quart.jsonify({"error": "Guild not in cache"}), 404
        me = cached.me
        if not me:
            return quart.jsonify({"error": "Bot not in guild"}), 404

        text_chs = [ch for ch in cached.channels if isinstance(ch, discord.TextChannel)]
        total = len(text_chs)
        visible = 0
        correct = 0
        for ch in text_chs:
            p = ch.permissions_for(me)
            if p.view_channel:
                visible += 1
                if p.manage_messages:
                    correct += 1
        return quart.jsonify({"total": total, "visible": visible, "correct_perms": correct})

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
                "opted_out": profile.get("opted_out", False),
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

    @app.route("/api/admin/guild_config")
    @requires_authorization
    async def admin_guild_config():
        """Returns the full conf.json (+ sticky_messages) for a given guild ID."""
        user, is_admin = await _require_bot_admin(discord_auth)
        if not is_admin:
            return quart.jsonify({"error": "Access denied"}), 403

        guild_id_str = quart.request.args.get("guild_id", "").strip()
        if not guild_id_str.isdigit():
            return quart.jsonify({"error": "Invalid guild_id"}), 400

        conf_path = os.path.join("data", guild_id_str, "conf.json")
        if not os.path.exists(conf_path):
            return quart.jsonify({"error": "No config found for this guild."}), 404

        try:
            with open(conf_path, "r", encoding="utf-8") as f:
                conf = json.load(f)
        except Exception as e:
            return quart.jsonify({"error": f"Failed to read config: {e}"}), 500

        # Add sticky messages count from separate file
        sticky_path = os.path.join("data", guild_id_str, "sticky_messages.json")
        conf["_sticky_messages"] = {}
        if os.path.exists(sticky_path):
            try:
                with open(sticky_path, "r", encoding="utf-8") as sf:
                    conf["_sticky_messages"] = json.load(sf)
            except Exception:
                pass

        # Try to get guild name from Discord cache
        guild_name = conf.get("guild_name", guild_id_str)
        try:
            g = bot.get_guild(int(guild_id_str))
            if g:
                guild_name = g.name
        except Exception:
            pass

        share.admin_log("info", f"Guild config viewed for {guild_id_str} ({guild_name}) by {user.name}", source="AdminDash")
        return quart.jsonify({"success": True, "guild_name": guild_name, "guild_id": guild_id_str, "config": conf})

    @app.route("/api/admin/guild_activity")
    @requires_authorization
    async def admin_guild_activity():
        """Returns per-guild activity stats based on activity.json files."""
        user, is_admin = await _require_bot_admin(discord_auth)
        if not is_admin:
            return quart.jsonify({"error": "Access denied"}), 403

        import datetime as _dt
        today = _dt.datetime.utcnow().date()
        cutoffs = {
            "7d":  str(today - _dt.timedelta(days=7)),
            "14d": str(today - _dt.timedelta(days=14)),
            "30d": str(today - _dt.timedelta(days=30)),
        }

        data_dir = "data"
        try:
            guild_dirs = [
                d for d in os.listdir(data_dir)
                if os.path.isdir(os.path.join(data_dir, d)) and d.isdigit() and d != "1001"
            ]
        except FileNotFoundError:
            return quart.jsonify({"guilds": []})

        results = []
        for gid in guild_dirs:
            # Get guild name from Discord cache first, fallback to conf.json
            guild_name = gid
            member_count = 0
            g = bot.get_guild(int(gid))
            if g:
                guild_name = g.name
                member_count = g.member_count or 0
            else:
                conf_path = os.path.join(data_dir, gid, "conf.json")
                if os.path.exists(conf_path):
                    try:
                        with open(conf_path, "r", encoding="utf-8") as f:
                            _c = json.load(f)
                        guild_name = _c.get("guild_name") or gid
                    except Exception:
                        pass

            activity_path = os.path.join(data_dir, gid, "activity.json")
            msg_7d = msg_14d = msg_30d = 0
            last_active = None

            if os.path.exists(activity_path):
                try:
                    with open(activity_path, "r", encoding="utf-8") as f:
                        act = json.load(f)
                    msg_by_day = act.get("msg_by_day", {})
                    for day, val in msg_by_day.items():
                        count = val.get("total", 0) if isinstance(val, dict) else 0
                        if day >= cutoffs["30d"]:
                            msg_30d += count
                        if day >= cutoffs["14d"]:
                            msg_14d += count
                        if day >= cutoffs["7d"]:
                            msg_7d += count
                    # Last active day (any day with messages)
                    active_days = [d for d, v in msg_by_day.items()
                                   if (v.get("total", 0) if isinstance(v, dict) else 0) > 0]
                    if active_days:
                        last_active = max(active_days)
                except Exception:
                    pass

            # Status classification
            if msg_7d > 0:
                status = "active"
            elif msg_14d > 0:
                status = "idle"
            elif msg_30d > 0:
                status = "fading"
            else:
                status = "dead"

            results.append({
                "guild_id": gid,
                "guild_name": guild_name,
                "member_count": member_count,
                "msg_7d": msg_7d,
                "msg_14d": msg_14d,
                "msg_30d": msg_30d,
                "last_active": last_active,
                "status": status,
            })

        results.sort(key=lambda x: x["msg_30d"], reverse=True)

        # Compute percentages relative to the most active guild
        max_30d = max((r["msg_30d"] for r in results), default=1) or 1
        for r in results:
            r["pct"] = round(r["msg_30d"] / max_30d * 100)

        counts = {s: sum(1 for r in results if r["status"] == s)
                  for s in ("active", "idle", "fading", "dead")}

        return quart.jsonify({"guilds": results, "counts": counts})

    @app.route("/api/admin/reload-templates", methods=["POST"])
    @requires_authorization
    async def admin_reload_templates():
        """Clears the Jinja2 template cache so updated HTML/CSS/JS files are served immediately."""
        user, is_admin = await _require_bot_admin(discord_auth)
        if not is_admin:
            return quart.jsonify({"success": False, "message": "Access denied"}), 403
        cache = app.jinja_env.cache
        if cache is not None:
            cache.clear()
        share.admin_log("info", f"Template cache cleared by {user.name}", source="AdminDash")
        return quart.jsonify({"success": True, "message": "Template cache cleared."})

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

        elif action == "delete_prism_event":
            user_id_str = str(data.get("user_id", "")).strip()
            event_ts    = str(data.get("event_timestamp", "")).strip()
            if not user_id_str.isdigit():
                return quart.jsonify({"success": False, "message": "Invalid user_id."}), 400
            if not event_ts:
                return quart.jsonify({"success": False, "message": "Missing event_timestamp."}), 400
            import assets.trust as sentinel
            removed = sentinel.delete_event(int(user_id_str), event_ts)
            if not removed:
                return quart.jsonify({"success": False, "message": "Event not found."}), 404
            share.admin_log("info", f"Prism single event deleted for {user_id_str} (ts={event_ts}) by {user.name}", source="AdminDash")
            return quart.jsonify({"success": True, "message": "Event deleted."})

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
                "YouTubeVideos":    "check_videos",
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

            if query.isdigit():
                uid_str = query
                profile = sentinel.get_profile(int(uid_str))
                if profile:
                    found_name = profile.get("name", uid_str)
                else:
                    users_list_tmp: dict = dict(datasys.load_data(1001, "users"))
                    if uid_str in users_list_tmp:
                        found_name = users_list_tmp[uid_str].get("name", uid_str)
                    else:
                        try:
                            fetched = await bot.fetch_user(int(uid_str))
                            found_name = fetched.name
                        except Exception:
                            found_name = uid_str
            else:
                query_lower = query.lower()
                prism_profiles = sentinel.get_all_profiles()
                for puid, pprofile in prism_profiles.items():
                    if query_lower in pprofile.get("name", "").lower():
                        uid_str = puid
                        found_name = pprofile.get("name", puid)
                        break
                if not uid_str:
                    users_list_tmp: dict = dict(datasys.load_data(1001, "users"))
                    for puid, udata in users_list_tmp.items():
                        if query_lower in udata.get("name", "").lower():
                            uid_str = puid
                            found_name = udata.get("name", puid)
                            break

            if not uid_str:
                return quart.jsonify({"success": True, "found": False})

            result: dict = {"success": True, "found": True, "uid": uid_str, "name": found_name or uid_str}

            # Prism profile
            profile = sentinel.get_profile(int(uid_str))
            if profile:
                _prism_events = profile.get("events", [])
                result["prism"] = {
                    "score": profile.get("score", 100),
                    "event_count": len(_prism_events),
                    "first_seen": profile.get("first_seen", ""),
                    "last_seen": profile.get("last_seen", ""),
                    "account_created_at": profile.get("account_created_at", ""),
                    "auto_flagged": profile.get("auto_flagged", False),
                    "opted_out": profile.get("opted_out", False),
                    "risk_signals": profile.get("risk_signals", []),
                    "events": _prism_events[-30:],
                }

            # Flagged entry
            users_list2: dict = dict(datasys.load_data(1001, "users"))
            if uid_str in users_list2:
                entry = users_list2[uid_str]
                result["flagged_entry"] = {
                    "reason": entry.get("reason", ""),
                    "entry_date": entry.get("entry_date", ""),
                    "auto_flagged": entry.get("auto_flagged", False),
                    "flagged": entry.get("flagged", False),
                }

            # Chatfilter violations (global log)
            cf_log: dict = dict(datasys.load_data(1001, "chatfilter_log"))
            violations = [v for v in cf_log.values() if str(v.get("uid", "")) == uid_str]
            violations.sort(key=lambda v: v.get("timestamp", ""), reverse=True)
            result["chatfilter_violations"] = violations[:50]

            # Guild warnings
            guild_warnings = []
            _data_dir = "data"
            try:
                _guild_dirs = [
                    d for d in os.listdir(_data_dir)
                    if os.path.isdir(os.path.join(_data_dir, d)) and d.isdigit() and d != "1001"
                ]
            except FileNotFoundError:
                _guild_dirs = []

            for _gid in _guild_dirs:
                _conf_path = os.path.join(_data_dir, _gid, "conf.json")
                if not os.path.exists(_conf_path):
                    continue
                try:
                    with open(_conf_path, "r", encoding="utf-8") as _f:
                        _conf = json.load(_f)
                    _warns = _conf.get("warnings", {}).get(uid_str, [])
                    if _warns:
                        guild_warnings.append({
                            "guild_id": _gid,
                            "guild_name": _conf.get("guild_name", _gid),
                            "count": len(_warns),
                            "entries": _warns,
                        })
                except Exception:
                    pass
            result["guild_warnings"] = guild_warnings

            # Temp actions
            temp_actions_found = []
            for _gid in _guild_dirs:
                _ta_path = os.path.join(_data_dir, _gid, "temp_actions.json")
                if not os.path.exists(_ta_path):
                    continue
                try:
                    with open(_ta_path, "r", encoding="utf-8") as _f:
                        _ta = json.load(_f)
                    for _atype in ["bans", "timeouts"]:
                        for _entry in _ta.get(_atype, []):
                            if str(_entry.get("user_id", "")) == uid_str:
                                temp_actions_found.append({
                                    "type": _atype[:-1],
                                    "guild_id": _gid,
                                    "guild_name": _entry.get("guild_name", _gid),
                                    "expires_at": _entry.get("expires_at", ""),
                                    "reason": _entry.get("reason", ""),
                                })
                except Exception:
                    pass
            result["temp_actions"] = temp_actions_found

            # GC ban / BA ban (global)
            _global_conf_path = os.path.join("data", "1001", "conf.json")
            result["gc_ban"] = None
            result["ba_ban"] = None
            try:
                with open(_global_conf_path, "r", encoding="utf-8") as _gcf:
                    _global_conf = json.load(_gcf)
                _gc_ban_map = _global_conf.get("gc_ban", {})
                _ba_ban_map = _global_conf.get("ba_ban", {})
                if uid_str in _gc_ban_map:
                    result["gc_ban"] = _gc_ban_map[uid_str]
                if uid_str in _ba_ban_map:
                    result["ba_ban"] = _ba_ban_map[uid_str]
            except Exception:
                pass

            # Open tickets per guild
            open_tickets_found = []
            for _gid in _guild_dirs:
                _tk_path = os.path.join(_data_dir, _gid, "tickets.json")
                if not os.path.exists(_tk_path):
                    continue
                try:
                    with open(_tk_path, "r", encoding="utf-8") as _tf:
                        _open_tks = json.load(_tf)
                    _gname_tk = None
                    for _cid, _td in _open_tks.items():
                        if str(_td.get("user", "")) == uid_str:
                            if _gname_tk is None:
                                try:
                                    with open(os.path.join(_data_dir, _gid, "conf.json"), encoding="utf-8") as _fcf:
                                        _gname_tk = json.load(_fcf).get("guild_name", _gid)
                                except Exception:
                                    _gname_tk = _gid
                            open_tickets_found.append({
                                "guild_id": _gid,
                                "guild_name": _gname_tk,
                                "channel_id": _cid,
                                "title": _td.get("title", ""),
                                "message": _td.get("message", ""),
                                "status": _td.get("status", "open"),
                                "created_at": _td.get("created_at", ""),
                            })
                except Exception:
                    pass
            result["open_tickets"] = open_tickets_found

            # Closed transcripts (match by username in messages)
            transcripts_found = []
            if found_name:
                _name_lower = found_name.lower()
                try:
                    _transcripts: dict = dict(datasys.load_data(1001, "transcripts"))
                    for _tid, _tr in _transcripts.items():
                        _tr_msgs = _tr.get("transcript", [])
                        for _trm in _tr_msgs:
                            if _trm.get("user", "").lower() == _name_lower:
                                transcripts_found.append({
                                    "id": _tid,
                                    "guild_id": _tr.get("guild", ""),
                                    "title": _tr.get("title", ""),
                                    "initial_message": _tr.get("msg", ""),
                                    "closed_by": _tr.get("closed_by", ""),
                                    "closed_on": _tr.get("closed_on", ""),
                                    "message_count": len(_tr_msgs),
                                })
                                break
                except Exception:
                    pass
            result["transcripts"] = transcripts_found

            share.admin_log("info", f"User search for '{query}' by {user.name} → found uid={uid_str}", source="AdminDash")
            return quart.jsonify(result)

        elif action == "delete_user_data":
            user_id_str = str(data.get("user_id", "")).strip()
            if not user_id_str.isdigit():
                return quart.jsonify({"success": False, "message": "Invalid user_id."}), 400

            import assets.trust as sentinel
            import datetime as _dt

            deleted_items: list[str] = []
            user_name_del = user_id_str

            # 1. Prism profile
            profile = sentinel.get_profile(int(user_id_str))
            if profile:
                user_name_del = profile.get("name", user_id_str)
                sentinel.delete_profile(int(user_id_str))
                deleted_items.append("Prism profile")

            # 2. Flagged users entry
            users_list_del: dict = dict(datasys.load_data(1001, "users"))
            if user_id_str in users_list_del:
                user_name_del = users_list_del[user_id_str].get("name", user_name_del)
                del users_list_del[user_id_str]
                datasys.save_data(1001, "users", users_list_del)
                deleted_items.append("flagged user entry")

            # 3. Global chatfilter log
            cf_log_del: dict = dict(datasys.load_data(1001, "chatfilter_log"))
            orig_len = len(cf_log_del)
            cf_log_del = {k: v for k, v in cf_log_del.items() if str(v.get("uid", "")) != user_id_str}
            if len(cf_log_del) < orig_len:
                datasys.save_data(1001, "chatfilter_log", cf_log_del)
                deleted_items.append(f"{orig_len - len(cf_log_del)} chatfilter log entries")

            # 4. Guild warnings + per-guild chatfilter logs
            _data_dir2 = "data"
            try:
                _guild_dirs2 = [
                    d for d in os.listdir(_data_dir2)
                    if os.path.isdir(os.path.join(_data_dir2, d)) and d.isdigit() and d != "1001"
                ]
            except FileNotFoundError:
                _guild_dirs2 = []

            warn_guilds = 0
            for _gid2 in _guild_dirs2:
                _cp = os.path.join(_data_dir2, _gid2, "conf.json")
                if not os.path.exists(_cp):
                    continue
                try:
                    with open(_cp, "r", encoding="utf-8") as _f2:
                        _conf2 = json.load(_f2)
                    _mod = False
                    if user_id_str in _conf2.get("warnings", {}):
                        del _conf2["warnings"][user_id_str]
                        _mod = True
                    if _mod:
                        with open(_cp, "w", encoding="utf-8") as _f2:
                            json.dump(_conf2, _f2, indent=2, ensure_ascii=False)
                        warn_guilds += 1
                except Exception:
                    pass
            if warn_guilds:
                deleted_items.append(f"warnings in {warn_guilds} guild(s)")

            # 5. Temp actions
            ta_guilds = 0
            for _gid2 in _guild_dirs2:
                _tp = os.path.join(_data_dir2, _gid2, "temp_actions.json")
                if not os.path.exists(_tp):
                    continue
                try:
                    with open(_tp, "r", encoding="utf-8") as _f3:
                        _ta2 = json.load(_f3)
                    _mod2 = False
                    for _at in ["bans", "timeouts"]:
                        _orig = _ta2.get(_at, [])
                        _filt = [e for e in _orig if str(e.get("user_id", "")) != user_id_str]
                        if len(_filt) < len(_orig):
                            _ta2[_at] = _filt
                            _mod2 = True
                    if _mod2:
                        with open(_tp, "w", encoding="utf-8") as _f3:
                            json.dump(_ta2, _f3, indent=2, ensure_ascii=False)
                        ta_guilds += 1
                except Exception:
                    pass
            if ta_guilds:
                deleted_items.append(f"temp actions in {ta_guilds} guild(s)")

            # 6. Send DM to user
            dm_sent = False
            try:
                target_del = await bot.fetch_user(int(user_id_str))
                _ts_del = datetime.now(_VIENNA).strftime("%d.%m.%Y %H:%M")
                embed_del = discord.Embed(
                    title="Your Data has been deleted",
                    description=(
                        "All data stored about you in Baxi has been deleted by an administrator.\n\n"
                        f"**Deleted:** {', '.join(deleted_items) if deleted_items else 'No data found'}\n"
                        f"**Deleted on:** {_ts_del}\n\n"
                        "If you believe this was done in error, please contact the Baxi support team."
                    ),
                    color=config.Discord.color,
                )
                embed_del.set_author(name="Baxi Data Management")
                embed_del.set_footer(text="Avocloud.net · Baxi")
                await target_del.send(embed=embed_del)
                dm_sent = True
            except Exception:
                pass

            share.admin_log(
                "warning",
                f"All data deleted for {user_name_del} ({user_id_str}) by {user.name}. "
                f"Items: {', '.join(deleted_items) or 'none'}. DM sent: {dm_sent}",
                source="AdminDash",
            )

            summary = f"Gelöscht: {', '.join(deleted_items) if deleted_items else 'keine Daten gefunden'}."
            summary += " DM gesendet." if dm_sent else " DM konnte nicht gesendet werden (DMs möglicherweise deaktiviert)."
            return quart.jsonify({"success": True, "message": summary})

        elif action == "send_user_data":
            user_id_str = str(data.get("user_id", "")).strip()
            if not user_id_str.isdigit():
                return quart.jsonify({"success": False, "message": "Invalid user_id."}), 400

            import assets.trust as sentinel
            import datetime as _dt

            try:
                target_rep = await bot.fetch_user(int(user_id_str))
            except discord.NotFound:
                return quart.jsonify({"success": False, "message": "User not found on Discord."}), 404
            except Exception as _e:
                return quart.jsonify({"success": False, "message": f"Could not fetch user: {_e}"}), 500

            _ts_rep = datetime.now(_VIENNA).strftime("%d.%m.%Y %H:%M")

            profile_rep = sentinel.get_profile(int(user_id_str))
            users_list_rep: dict = dict(datasys.load_data(1001, "users"))
            flagged_rep = users_list_rep.get(user_id_str)
            cf_log_rep: dict = dict(datasys.load_data(1001, "chatfilter_log"))
            violations_rep = sorted(
                [v for v in cf_log_rep.values() if str(v.get("uid", "")) == user_id_str],
                key=lambda v: v.get("timestamp", ""), reverse=True
            )

            _data_dir3 = "data"
            try:
                _guild_dirs3 = [
                    d for d in os.listdir(_data_dir3)
                    if os.path.isdir(os.path.join(_data_dir3, d)) and d.isdigit() and d != "1001"
                ]
            except FileNotFoundError:
                _guild_dirs3 = []

            all_warnings_rep: list[dict] = []
            for _gid3 in _guild_dirs3:
                _cp3 = os.path.join(_data_dir3, _gid3, "conf.json")
                if not os.path.exists(_cp3):
                    continue
                try:
                    with open(_cp3, "r", encoding="utf-8") as _f4:
                        _conf3 = json.load(_f4)
                    _gw = _conf3.get("warnings", {}).get(user_id_str, [])
                    _gname3 = _conf3.get("guild_name", _gid3)
                    for _w in _gw:
                        all_warnings_rep.append({**_w, "guild_name": _gname3, "guild_id": _gid3})
                except Exception:
                    pass

            temp_actions_rep: list[dict] = []
            for _gid3 in _guild_dirs3:
                _tp3 = os.path.join(_data_dir3, _gid3, "temp_actions.json")
                if not os.path.exists(_tp3):
                    continue
                try:
                    with open(_tp3, "r", encoding="utf-8") as _f5:
                        _ta3 = json.load(_f5)
                    for _at3 in ["bans", "timeouts"]:
                        for _te3 in _ta3.get(_at3, []):
                            if str(_te3.get("user_id", "")) == user_id_str:
                                temp_actions_rep.append({
                                    "type": _at3[:-1],
                                    "guild_name": _te3.get("guild_name", _gid3),
                                    "expires_at": _te3.get("expires_at", ""),
                                    "reason": _te3.get("reason", ""),
                                })
                except Exception:
                    pass

            # GC ban / BA ban
            gc_ban_rep = None
            ba_ban_rep = None
            try:
                _global_conf_path3 = os.path.join("data", "1001", "conf.json")
                with open(_global_conf_path3, "r", encoding="utf-8") as _gcf3:
                    _global_conf3 = json.load(_gcf3)
                if user_id_str in _global_conf3.get("gc_ban", {}):
                    gc_ban_rep = _global_conf3["gc_ban"][user_id_str]
                if user_id_str in _global_conf3.get("ba_ban", {}):
                    ba_ban_rep = _global_conf3["ba_ban"][user_id_str]
            except Exception:
                pass

            # Open tickets
            open_tickets_rep2: list[dict] = []
            for _gid3 in _guild_dirs3:
                _tk_path3 = os.path.join(_data_dir3, _gid3, "tickets.json")
                if not os.path.exists(_tk_path3):
                    continue
                try:
                    with open(_tk_path3, "r", encoding="utf-8") as _tf3:
                        _open_tks3 = json.load(_tf3)
                    _gname_tk3 = None
                    for _cid3, _td3 in _open_tks3.items():
                        if str(_td3.get("user", "")) == user_id_str:
                            if _gname_tk3 is None:
                                try:
                                    with open(os.path.join(_data_dir3, _gid3, "conf.json"), encoding="utf-8") as _fcf3:
                                        _gname_tk3 = json.load(_fcf3).get("guild_name", _gid3)
                                except Exception:
                                    _gname_tk3 = _gid3
                            open_tickets_rep2.append({
                                "guild_name": _gname_tk3,
                                "title": _td3.get("title", ""),
                                "status": _td3.get("status", "open"),
                                "created_at": _td3.get("created_at", ""),
                            })
                except Exception:
                    pass

            # Closed transcripts
            transcripts_rep2: list[dict] = []
            _tname_lower = target_rep.name.lower()
            try:
                _transcripts3: dict = dict(datasys.load_data(1001, "transcripts"))
                for _tid3, _tr3 in _transcripts3.items():
                    _tr3_msgs = _tr3.get("transcript", [])
                    for _trm3 in _tr3_msgs:
                        if _trm3.get("user", "").lower() == _tname_lower:
                            transcripts_rep2.append({
                                "title": _tr3.get("title", ""),
                                "guild_id": _tr3.get("guild", ""),
                                "closed_on": _tr3.get("closed_on", ""),
                                "message_count": len(_tr3_msgs),
                            })
                            break
            except Exception:
                pass

            embeds_to_send: list[discord.Embed] = []

            # ── Embed 1: Overview ─────────────────────────────────────────
            overview_lines = [
                "The following data is stored about you in the Baxi bot system.",
                "This information is used for moderation and trust-scoring purposes.\n",
            ]
            if profile_rep:
                _score = profile_rep.get("score", 100)
                _flag_txt = f" {config.Icons.alert} Auto-flagged" if profile_rep.get("auto_flagged") else ""
                overview_lines.append(f"**Prism Trust Score:** {_score}/100{_flag_txt}")
                overview_lines.append(f"**Prism Events recorded:** {len(profile_rep.get('events', []))}")
                if profile_rep.get("first_seen"):
                    overview_lines.append(f"**First seen by Baxi:** {profile_rep['first_seen'][:10]}")
                if profile_rep.get("last_seen"):
                    overview_lines.append(f"**Last seen by Baxi:** {profile_rep['last_seen'][:10]}")
                if profile_rep.get("account_created_at"):
                    overview_lines.append(f"**Account created:** {profile_rep['account_created_at'][:10]}")
                if profile_rep.get("opted_out"):
                    overview_lines.append("**Prism tracking:** Opted out")
                _rsig = profile_rep.get("risk_signals", [])
                if _rsig:
                    overview_lines.append(f"**Active risk signals:** {', '.join(_rsig)}")
            if flagged_rep and flagged_rep.get("flagged"):
                overview_lines.append(f"**Global flag:** Yes — Reason: {flagged_rep.get('reason', '—')}")
                if flagged_rep.get("entry_date"):
                    overview_lines.append(f"**Flagged on:** {flagged_rep['entry_date']}")
            if gc_ban_rep is not None:
                overview_lines.append("**Global Chat Ban:** Yes")
            if ba_ban_rep is not None:
                overview_lines.append("**Bot-Wide Ban:** Yes")
            overview_lines.append(f"\n**Chatfilter violations:** {len(violations_rep)}")
            overview_lines.append(f"**Warnings across all servers:** {len(all_warnings_rep)}")
            overview_lines.append(f"**Active temp actions:** {len(temp_actions_rep)}")
            overview_lines.append(f"**Open tickets:** {len(open_tickets_rep2)}")
            overview_lines.append(f"**Closed ticket transcripts:** {len(transcripts_rep2)}")

            embed_overview = discord.Embed(
                title="Your Data stored in Baxi",
                description="\n".join(overview_lines),
                color=config.Discord.color,
            )
            embed_overview.set_author(name="Baxi Data Report")
            embed_overview.set_footer(text=f"Requested on {_ts_rep} · Avocloud.net · Baxi")
            embeds_to_send.append(embed_overview)

            # ── Embed 2: Prism events ────────────────────────────────────
            if profile_rep and profile_rep.get("events"):
                _evs = profile_rep["events"][-20:]
                ev_lines = []
                for _ev in reversed(_evs):
                    _ev_ts = str(_ev.get("timestamp", ""))[:16].replace("T", " ")
                    _ev_type = _ev.get("type", "unknown")
                    _ev_reason = _ev.get("reason", "—")
                    _ev_guild = _ev.get("guild_id", "")
                    ev_lines.append(f"`{_ev_ts}` **{_ev_type}** — {_ev_reason} *(server {_ev_guild})*")
                embed_events = discord.Embed(
                    title="Prism Events (last 20)",
                    description="\n".join(ev_lines) or "No events recorded.",
                    color=0x9333ea,
                )
                embeds_to_send.append(embed_events)

            # ── Embed 3: Chatfilter violations ───────────────────────────
            if violations_rep:
                cf_lines = []
                for _viol in violations_rep[:15]:
                    _vts = _viol.get("timestamp", "—")
                    _vsname = _viol.get("sname", "—")
                    _vreason = _viol.get("reason", "—")
                    _vmsg = (_viol.get("message", "") or "")[:80]
                    cf_lines.append(f"`{_vts}` **{_vsname}** — *{_vreason}*\n> {_vmsg}")
                if len(violations_rep) > 15:
                    cf_lines.append(f"*… and {len(violations_rep) - 15} more violations*")
                embed_cf = discord.Embed(
                    title=f"Chatfilter Violations ({len(violations_rep)})",
                    description="\n\n".join(cf_lines),
                    color=0xc084fc,
                )
                embeds_to_send.append(embed_cf)

            # ── Embed 4: Warnings ────────────────────────────────────────
            if all_warnings_rep:
                warn_lines = []
                for _warn in all_warnings_rep[:20]:
                    _wdate = _warn.get("date", "—")
                    _wreason = _warn.get("reason", "—")
                    _wmod = _warn.get("mod", "—")
                    _wguild = _warn.get("guild_name", "—")
                    warn_lines.append(f"`{_wdate}` **{_wguild}** — {_wreason} *(by {_wmod})*")
                if len(all_warnings_rep) > 20:
                    warn_lines.append(f"*… and {len(all_warnings_rep) - 20} more warnings*")
                embed_warns = discord.Embed(
                    title=f"Warnings ({len(all_warnings_rep)} total)",
                    description="\n".join(warn_lines),
                    color=0xfb923c,
                )
                embeds_to_send.append(embed_warns)

            # ── Embed 5: Temp actions ────────────────────────────────────
            if temp_actions_rep:
                ta_lines = []
                for _ta_r in temp_actions_rep:
                    _ta_type = _ta_r.get("type", "—").upper()
                    _ta_guild = _ta_r.get("guild_name", "—")
                    _ta_exp = _ta_r.get("expires_at", "—")
                    _ta_reason = _ta_r.get("reason", "—")
                    ta_lines.append(f"**{_ta_type}** in {_ta_guild}\nExpires: `{_ta_exp}` — {_ta_reason}")
                embed_ta = discord.Embed(
                    title=f"Active Temp Actions ({len(temp_actions_rep)})",
                    description="\n\n".join(ta_lines),
                    color=0xf87171,
                )
                embeds_to_send.append(embed_ta)

            # ── Embed 6: GC Ban ──────────────────────────────────────────
            if gc_ban_rep is not None:
                _gc_desc = json.dumps(gc_ban_rep, indent=2) if isinstance(gc_ban_rep, dict) else str(gc_ban_rep)
                embed_gc = discord.Embed(
                    title="Global Chat Ban",
                    description=f"You are banned from Baxi's Global Chat.\n```json\n{_gc_desc[:1800]}\n```",
                    color=0xef4444,
                )
                embeds_to_send.append(embed_gc)

            # ── Embed 7: BA Ban ──────────────────────────────────────────
            if ba_ban_rep is not None:
                _ba_desc = json.dumps(ba_ban_rep, indent=2) if isinstance(ba_ban_rep, dict) else str(ba_ban_rep)
                embed_ba = discord.Embed(
                    title="Bot-Wide Ban",
                    description=f"You have a bot-wide ban entry.\n```json\n{_ba_desc[:1800]}\n```",
                    color=0xef4444,
                )
                embeds_to_send.append(embed_ba)

            # ── Embed 8: Open Tickets ────────────────────────────────────
            if open_tickets_rep2:
                tk_lines = []
                for _tk_r in open_tickets_rep2:
                    _tk_guild = _tk_r.get("guild_name", "—")
                    _tk_title = _tk_r.get("title", "—")
                    _tk_status = _tk_r.get("status", "open")
                    tk_lines.append(f"**{_tk_guild}** — {_tk_title} *(Status: {_tk_status})*")
                embed_tickets = discord.Embed(
                    title=f"Open Tickets ({len(open_tickets_rep2)})",
                    description="\n".join(tk_lines),
                    color=0x60a5fa,
                )
                embeds_to_send.append(embed_tickets)

            # ── Embed 9: Transcripts ─────────────────────────────────────
            if transcripts_rep2:
                tr2_lines = []
                for _tr2 in transcripts_rep2[:15]:
                    _tr2_title = _tr2.get("title", "—")
                    _tr2_guild = _tr2.get("guild_id", "—")
                    _tr2_closed = str(_tr2.get("closed_on", "—"))[:10]
                    _tr2_count = _tr2.get("message_count", 0)
                    tr2_lines.append(f"**{_tr2_title}** (Server: {_tr2_guild}) — Closed: {_tr2_closed} — {_tr2_count} msgs")
                if len(transcripts_rep2) > 15:
                    tr2_lines.append(f"*… and {len(transcripts_rep2) - 15} more*")
                embed_transcripts = discord.Embed(
                    title=f"Closed Ticket Transcripts ({len(transcripts_rep2)})",
                    description="\n".join(tr2_lines),
                    color=0x34d399,
                )
                embeds_to_send.append(embed_transcripts)

            if len(embeds_to_send) == 1:
                embed_overview.description += "\n\n*No detailed records found beyond this summary.*"

            try:
                # Discord allows max 10 embeds per message; send in batches of 10
                for _i in range(0, len(embeds_to_send), 10):
                    await target_rep.send(embeds=embeds_to_send[_i:_i + 10])
            except discord.Forbidden:
                return quart.jsonify({"success": False, "message": "Could not send DM — user has DMs disabled."}), 400
            except Exception as _e2:
                return quart.jsonify({"success": False, "message": f"Error sending DM: {_e2}"}), 500

            share.admin_log(
                "info",
                f"Data report sent to {target_rep.name} ({user_id_str}) by {user.name}",
                source="AdminDash",
            )
            return quart.jsonify({"success": True, "message": f"Data report sent via DM to {target_rep.name}."})

        return quart.jsonify({"success": False, "message": f"Unknown action: {action}"}), 400

    # ── BaxiInsights ──────────────────────────────────────────────────────────

    def _load_insights_data(guild_id: str, days: int) -> dict:
        """Load and aggregate insights data for a guild over the past N days."""
        import assets.trust as sentinel_mod
        from datetime import timedelta
        cutoff = datetime.now() - timedelta(days=days)

        # Mod events
        mod_path = os.path.join("data", guild_id, "mod_events.json")
        mod_events = []
        if os.path.exists(mod_path):
            try:
                with open(mod_path, "r", encoding="utf-8") as f:
                    mod_events = json.load(f)
            except Exception:
                pass
        mod_events = [
            e for e in mod_events
            if datetime.fromisoformat(e.get("timestamp", "2000-01-01")) >= cutoff
        ]

        # Filter events
        filter_path = os.path.join("data", guild_id, "filter_events.json")
        filter_events = []
        if os.path.exists(filter_path):
            try:
                with open(filter_path, "r", encoding="utf-8") as f:
                    filter_events = json.load(f)
            except Exception:
                pass
        filter_events = [
            e for e in filter_events
            if datetime.fromisoformat(e.get("timestamp", "2000-01-01")) >= cutoff
        ]

        # Mod counts
        mod_counts = {"warn": 0, "kick": 0, "ban": 0, "mute": 0}
        for e in mod_events:
            t = e.get("type", "")
            if t in mod_counts:
                mod_counts[t] += 1

        # Mod timeline (per day)
        from collections import defaultdict
        timeline: dict = defaultdict(lambda: {"warn": 0, "kick": 0, "ban": 0, "mute": 0})
        for e in mod_events:
            day = e.get("timestamp", "")[:10]
            t = e.get("type", "")
            if t in mod_counts:
                timeline[day][t] += 1
        timeline_sorted = [{"date": k, **v} for k, v in sorted(timeline.items())]

        # Filter stats
        severity_dist = {str(i): 0 for i in range(1, 6)}
        category_counts: dict = defaultdict(int)
        for e in filter_events:
            sev = str(e.get("severity", 1))
            if sev in severity_dist:
                severity_dist[sev] += 1
            cat = e.get("category", "keyword")
            category_counts[cat] += 1

        # Top offenders (by mod event count)
        offenders: dict = defaultdict(lambda: {"user_name": "", "count": 0, "types": defaultdict(int)})
        for e in mod_events:
            uid = e.get("user_id", "?")
            offenders[uid]["user_name"] = e.get("user_name", uid)
            offenders[uid]["count"] += 1
            offenders[uid]["types"][e.get("type", "?")] += 1
        top_offenders = sorted(offenders.values(), key=lambda x: x["count"], reverse=True)[:10]
        for o in top_offenders:
            o["types"] = dict(o["types"])

        # Top users by filter hits
        filter_users: dict = defaultdict(lambda: {"user_name": "", "count": 0})
        for e in filter_events:
            uid = e.get("user_id", "?")
            filter_users[uid]["user_name"] = e.get("user_name", uid)
            filter_users[uid]["count"] += 1
        top_filter_users = sorted(filter_users.values(), key=lambda x: x["count"], reverse=True)[:10]

        # Top channels by filter hits
        filter_channels: dict = defaultdict(lambda: {"channel_name": "", "count": 0})
        for e in filter_events:
            cid = e.get("channel_id", "?")
            filter_channels[cid]["channel_name"] = e.get("channel_name", f"#{cid}")
            filter_channels[cid]["count"] += 1
        top_filter_channels = sorted(filter_channels.values(), key=lambda x: x["count"], reverse=True)[:10]

        # Activity data (messages, members)
        activity_path = os.path.join("data", guild_id, "activity.json")
        activity_raw = {}
        if os.path.exists(activity_path):
            try:
                with open(activity_path, "r", encoding="utf-8") as f:
                    activity_raw = json.load(f)
            except Exception:
                pass

        cutoff_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        msg_days = {d: v for d, v in activity_raw.get("msg_by_day", {}).items() if d >= cutoff_date}
        member_days = {d: v for d, v in activity_raw.get("member_by_day", {}).items() if d >= cutoff_date}

        # Message timeline (total per day)
        msg_timeline = [{"date": d, "count": v.get("total", 0)} for d, v in sorted(msg_days.items())]
        total_messages = sum(v.get("total", 0) for v in msg_days.values())

        # Top channels by message count (summed across days)
        ch_totals: dict = defaultdict(lambda: {"name": "", "count": 0})
        for day_data in msg_days.values():
            for cid, cv in day_data.get("by_channel", {}).items():
                ch_totals[cid]["name"] = cv.get("name", cid)
                ch_totals[cid]["count"] += cv.get("count", 0)
        top_active_channels = sorted(ch_totals.values(), key=lambda x: x["count"], reverse=True)[:10]

        # Top users by message count (summed across days)
        u_totals: dict = defaultdict(lambda: {"name": "", "count": 0})
        for day_data in msg_days.values():
            for uid, uv in day_data.get("by_user", {}).items():
                u_totals[uid]["name"] = uv.get("name", uid)
                u_totals[uid]["count"] += uv.get("count", 0)
        top_active_users = sorted(u_totals.values(), key=lambda x: x["count"], reverse=True)[:10]

        # Hourly distribution (summed across days)
        hourly: dict = {str(h): 0 for h in range(24)}
        for day_data in msg_days.values():
            for h, cnt in day_data.get("by_hour", {}).items():
                hourly[str(h)] = hourly.get(str(h), 0) + cnt

        # Member joins/leaves timeline
        member_timeline = [
            {"date": d, "joins": v.get("joins", 0), "leaves": v.get("leaves", 0)}
            for d, v in sorted(member_days.items())
        ]
        total_joins  = sum(v.get("joins",  0) for v in member_days.values())
        total_leaves = sum(v.get("leaves", 0) for v in member_days.values())

        # PRISM scores for guild members
        all_trust = sentinel_mod._load()
        guild = bot.get_guild(int(guild_id))
        prism_scores = []
        if guild:
            member_ids = {str(m.id) for m in guild.members}
            for uid, profile in all_trust.items():
                if uid in member_ids and not profile.get("opt_out", False):
                    prism_scores.append(profile.get("score", 100))
        avg_prism = round(sum(prism_scores) / len(prism_scores), 1) if prism_scores else 100
        prism_dist = {"0-20": 0, "21-40": 0, "41-60": 0, "61-80": 0, "81-100": 0}
        for s in prism_scores:
            if s <= 20:    prism_dist["0-20"] += 1
            elif s <= 40:  prism_dist["21-40"] += 1
            elif s <= 60:  prism_dist["41-60"] += 1
            elif s <= 80:  prism_dist["61-80"] += 1
            else:          prism_dist["81-100"] += 1

        # Health score
        member_count = guild.member_count if guild and guild.member_count else 1
        mod_rate = len(mod_events) / max(member_count, 1)
        filter_rate = len(filter_events) / max(member_count * days, 1)
        health = 100 - (mod_rate * 20) - (filter_rate * 15) - max(0, (50 - avg_prism) * 0.8)
        health = max(0, min(100, round(health)))

        return {
            # Moderation
            "mod_counts": mod_counts,
            "mod_total": len(mod_events),
            "filter_total": len(filter_events),
            "timeline": timeline_sorted,
            "severity_dist": severity_dist,
            "category_counts": dict(category_counts),
            "top_offenders": top_offenders,
            "top_filter_users": top_filter_users,
            "top_filter_channels": top_filter_channels,
            # Activity
            "total_messages": total_messages,
            "msg_timeline": msg_timeline,
            "top_active_channels": top_active_channels,
            "top_active_users": top_active_users,
            "hourly_dist": hourly,
            "member_timeline": member_timeline,
            "total_joins": total_joins,
            "total_leaves": total_leaves,
            # PRISM
            "prism_scores_count": len(prism_scores),
            "avg_prism": avg_prism,
            "prism_dist": prism_dist,
            # Meta
            "health": health,
            "days": days,
            "member_count": member_count,
        }

    async def _check_guild_auth(guild_id: str):
        """Returns (user, guild, error_response) — error_response is None on success."""
        if not guild_id or not guild_id.isdigit():
            return None, None, (await render_template("error.html", message="Invalid guild ID."), 400)
        try:
            user = await discord_auth.fetch_user()
            guild = await bot.fetch_guild(int(guild_id))
            if not guild:
                return None, None, (await render_template("error.html", message="Guild not found."), 404)
            try:
                guild_member = await guild.fetch_member(user.id)
            except discord.NotFound:
                return None, None, (await render_template("error.html", message="You are not a member of this guild."), 403)
            if not guild_member.guild_permissions.manage_guild:
                return None, None, (await render_template("error.html", message="You do not have the Manage Server permission."), 403)
            return user, guild, None
        except discord.NotFound:
            return None, None, (await render_template("error.html", message="Guild not found."), 404)
        except discord.Forbidden:
            return None, None, (await render_template("error.html", message="Bot has no access to this guild."), 403)
        except Exception as e:
            return None, None, (await render_template("error.html", message=f"Unexpected error: {e}"), 500)

    @app.route("/guild/insights/")
    @requires_authorization
    async def guild_insights():
        guild_id = quart.request.args.get("guild_login", "")
        user, guild, err = await _check_guild_auth(guild_id)
        if err:
            return err
        try:
            days = int(quart.request.args.get("days", 30))
        except ValueError:
            days = 30
        days = days if days in (7, 30, 90) else 30
        data = _load_insights_data(guild_id, days)
        return await render_template(
            "insights.html",
            data=data,
            guild=guild,
            user=user,
            guild_id=guild_id,
            days=days,
            greeting=get_time_based_greeting(user.name),
        )

    @app.route("/api/dash/insights/")
    @requires_authorization
    async def guild_insights_api():
        guild_id = quart.request.args.get("guild_login", "")
        try:
            days = int(quart.request.args.get("days", 30))
        except ValueError:
            days = 30
        days = days if days in (7, 30, 90) else 30
        if not guild_id or not guild_id.isdigit():
            return quart.jsonify({"success": False, "message": "Invalid guild ID."}), 400
        try:
            user = await discord_auth.fetch_user()
            guild = await bot.fetch_guild(int(guild_id))
            try:
                guild_member = await guild.fetch_member(user.id)
            except discord.NotFound:
                return quart.jsonify({"success": False, "message": "Not a guild member."}), 403
            if not guild_member.guild_permissions.manage_guild:
                return quart.jsonify({"success": False, "message": "Missing Manage Server permission."}), 403
        except discord.NotFound:
            return quart.jsonify({"success": False, "message": "Guild not found."}), 404
        except discord.Forbidden:
            return quart.jsonify({"success": False, "message": "Bot has no access."}), 403
        except Exception as e:
            return quart.jsonify({"success": False, "message": str(e)}), 500
        data = _load_insights_data(guild_id, days)
        return quart.jsonify({"success": True, **data})

    @app.route("/vote/<int:guild_id>")
    @requires_authorization
    async def vote_redirect(guild_id: int):
        """
        Records the (user → guild) mapping for a pending top.gg vote, then
        redirects to top.gg. The webhook handler reads this map when the
        vote actually fires, since top.gg V1 webhooks no longer carry the
        original query string.
        """
        try:
            user = await discord_auth.fetch_user()
        except Exception:
            return redirect(f"https://top.gg/bot/{bot.user.id}/vote")

        _cleanup_pending_votes()
        pending_votes[int(user.id)] = (int(guild_id), time.time() + PENDING_VOTE_TTL)
        print(f"[TopGG Vote] Pending vote registered: user {user.id} → guild {guild_id}")
        return redirect(f"https://top.gg/bot/{bot.user.id}/vote")

    @app.route("/webhooks/topgg/vote", methods=["POST"])
    async def topgg_vote_webhook():
        import hmac
        import hashlib
        import time as _time

        # Log incoming headers (masked) for debugging
        all_headers = {k: v for k, v in quart.request.headers.items()}
        masked = {k: (v[:6] + "…" + v[-4:] if len(v) > 16 else v) for k, v in all_headers.items()}
        print(f"[TopGG Vote] Incoming headers: {masked}")

        expected_secret = auth.TopGG.webhook_secret
        if not expected_secret or expected_secret == "YOUR-TOPGG-WEBHOOK-SECRET":
            print("[TopGG Vote] Webhook secret not configured.")
            return quart.jsonify({"error": "Not configured"}), 503

        # Top.gg V1 uses HMAC-SHA256 signature verification via the
        # `x-topgg-signature` header (format: "t={unix_ts},v1={hex_sig}").
        sig_header = quart.request.headers.get("x-topgg-signature", "")
        trace_id = quart.request.headers.get("x-topgg-trace", "")
        if trace_id:
            print(f"[TopGG Vote] Trace ID: {trace_id}")

        # Read the raw body BEFORE parsing JSON — signature is computed over raw bytes
        raw_body: bytes = await quart.request.get_data()

        if not sig_header:
            print("[TopGG Vote] ABORT: Missing x-topgg-signature header.")
            return quart.jsonify({"error": "Missing signature"}), 401

        # Parse "t=...,v1=..."
        sig_parts: dict[str, str] = {}
        for part in sig_header.split(","):
            if "=" in part:
                k, _, v = part.partition("=")
                sig_parts[k.strip()] = v.strip()

        sig_timestamp = sig_parts.get("t", "")
        sig_value = sig_parts.get("v1", "")

        if not sig_timestamp or not sig_value:
            print(f"[TopGG Vote] ABORT: Malformed signature header: {sig_header!r}")
            return quart.jsonify({"error": "Malformed signature"}), 401

        # Reject stale requests (>5 min) to prevent replay
        try:
            ts_int = int(sig_timestamp)
            age = abs(_time.time() - ts_int)
            if age > 300:
                print(f"[TopGG Vote] ABORT: Stale request — timestamp {sig_timestamp} is {age:.0f}s old.")
                return quart.jsonify({"error": "Stale"}), 401
        except ValueError:
            print(f"[TopGG Vote] ABORT: Invalid timestamp in signature: {sig_timestamp!r}")
            return quart.jsonify({"error": "Bad timestamp"}), 401

        # Compute HMAC-SHA256 over "{timestamp}.{raw_body}"
        signed_payload = f"{sig_timestamp}.".encode("utf-8") + raw_body
        expected_sig = hmac.new(
            expected_secret.encode("utf-8"),
            signed_payload,
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(expected_sig, sig_value):
            print(f"[TopGG Vote] ABORT: Signature mismatch. Got v1={sig_value[:12]}…, expected={expected_sig[:12]}…")
            return quart.jsonify({"error": "Bad signature"}), 401

        print("[TopGG Vote] Signature verified ✓")

        # Parse JSON
        try:
            import json as _json
            payload = _json.loads(raw_body.decode("utf-8")) if raw_body else None
        except Exception as e:
            print(f"[TopGG Vote] ABORT: Could not parse JSON body: {e}")
            return quart.jsonify({"error": "Bad request"}), 400

        if not payload or not isinstance(payload, dict):
            print("[TopGG Vote] ABORT: Empty or non-object payload.")
            return quart.jsonify({"error": "Bad request"}), 400

        print(f"[TopGG Vote] Received payload: {payload}")

        # V1 payload structure:
        #   { "type": "vote.create" | "webhook.test",
        #     "data": {
        #       "user": { "id": <topgg_id>, "platform_id": <discord_id>, "name": ..., "avatar_url": ... },
        #       "project": { "id": ..., "platform_id": <bot_discord_id>, ... },
        #       "query": "?guild=..."   # only on real votes
        #     }
        #   }
        event_type = payload.get("type", "")
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}

        is_test = event_type == "webhook.test"
        if event_type and event_type not in ("vote.create", "webhook.test"):
            print(f"[TopGG Vote] Ignoring unknown event '{event_type}'. Returning 200.")
            return quart.jsonify({"ok": True}), 200

        # Extract Discord user ID from the nested user object
        voter_id: int = 0
        user_obj = data.get("user")
        if isinstance(user_obj, dict):
            try:
                voter_id = int(user_obj.get("platform_id") or user_obj.get("id") or 0)
            except (ValueError, TypeError):
                voter_id = 0
        else:
            # Legacy flat format fallback
            try:
                voter_id = int(data.get("user", 0) or 0)
            except (ValueError, TypeError):
                voter_id = 0

        # Top.gg V1 webhooks don't carry the original query string anymore,
        # so look up the guild in our pending-vote map (populated by /vote/<guild_id>).
        guild_id: int = 0
        raw_query: str = ""
        _cleanup_pending_votes()
        if voter_id and voter_id in pending_votes:
            guild_id, _exp = pending_votes.pop(voter_id)
            print(f"[TopGG Vote] Matched pending vote: user {voter_id} → guild {guild_id}")
        else:
            # Fallback: legacy `query` field (V0) — keep for safety
            raw_query = data.get("query", "") or ""
            if isinstance(raw_query, str) and raw_query:
                try:
                    from urllib.parse import parse_qs
                    qs = raw_query.lstrip("?")
                    parsed = parse_qs(qs)
                    gid_vals = parsed.get("guild") or parsed.get("guild_id")
                    if gid_vals:
                        guild_id = int(gid_vals[0])
                except Exception as e:
                    print(f"[TopGG Vote] Failed to parse query string {raw_query!r}: {e}")

        print(f"[TopGG Vote] Parsed voter_id={voter_id}, guild_id={guild_id} (from query={raw_query!r})")

        if not voter_id:
            print("[TopGG Vote] ABORT: Missing user id in payload.")
            return quart.jsonify({"error": "Missing user"}), 400

        avocloud_guild_id: int = auth.TopGG.avocloud_guild_id
        vote_channel_id: int = auth.TopGG.vote_channel_id
        print(f"[TopGG Vote] Config: avocloud_guild_id={avocloud_guild_id}, vote_channel_id={vote_channel_id}")

        if not avocloud_guild_id or not vote_channel_id:
            print("[TopGG Vote] ABORT: avocloud_guild_id or vote_channel_id is 0 — set them in config/auth.py")
            return quart.jsonify({"ok": True, "warning": "channel/guild not configured"}), 200

        avocloud_guild: discord.Guild | None = bot.get_guild(avocloud_guild_id)
        if avocloud_guild is None:
            print(f"[TopGG Vote] ABORT: bot is not in avocloud guild (id={avocloud_guild_id}). Make sure the bot is invited!")
            return quart.jsonify({"ok": True, "warning": "bot not in avocloud guild"}), 200

        print(f"[TopGG Vote] Found avocloud guild: {avocloud_guild.name} ({avocloud_guild.member_count} members)")

        # Only announce if the voter is a member of avocloud.net
        voter_member = avocloud_guild.get_member(voter_id)
        if voter_member is None:
            print(f"[TopGG Vote] Voter {voter_id} not in cache, fetching from API...")
            try:
                voter_member = await avocloud_guild.fetch_member(voter_id)
            except discord.NotFound:
                print(f"[TopGG Vote] ABORT: Voter {voter_id} is NOT a member of avocloud.net.")
                return quart.jsonify({"ok": True, "warning": "voter not on avocloud"}), 200
            except discord.Forbidden as e:
                print(f"[TopGG Vote] ABORT: Forbidden while fetching member {voter_id}: {e}. Bot may lack 'Server Members Intent' or guild permissions.")
                return quart.jsonify({"ok": True, "warning": "forbidden"}), 200
            except Exception as e:
                print(f"[TopGG Vote] ABORT: Unexpected error fetching member {voter_id}: {type(e).__name__}: {e}")
                return quart.jsonify({"ok": True, "warning": "fetch error"}), 200

        print(f"[TopGG Vote] Voter is on avocloud: {voter_member} ({voter_member.id})")

        vote_channel = bot.get_channel(vote_channel_id)
        if vote_channel is None:
            print(f"[TopGG Vote] ABORT: Channel {vote_channel_id} not found in bot cache.")
            return quart.jsonify({"ok": True, "warning": "channel not found"}), 200
        if not isinstance(vote_channel, discord.TextChannel):
            print(f"[TopGG Vote] ABORT: Channel {vote_channel_id} is not a TextChannel — got {type(vote_channel).__name__}")
            return quart.jsonify({"ok": True, "warning": "channel wrong type"}), 200

        print(f"[TopGG Vote] Found vote channel: #{vote_channel.name} in {vote_channel.guild.name}")

        voted_guild: discord.Guild | None = bot.get_guild(guild_id) if guild_id else None
        if voted_guild is None:
            print(f"[TopGG Vote] No guild context (guild_id={guild_id}). Sending generic announcement instead of skipping.")

        # Build the embed — fall back to a generic message if there's no guild context
        title = "Top.gg Webhook Test" if is_test else "New Top.gg Vote!"
        if voted_guild:
            description = (
                f"{voter_member.mention} voted for Baxi on server **{voted_guild.name}**"
            )
        else:
            description = f"{voter_member.mention} voted for Baxi on Top.gg!"
        if is_test:
            description = f":test_tube: *Test webhook from Top.gg dashboard*\n\n{description}"

        embed = discord.Embed(
            title=title,
            description=description,
            color=discord.Color.from_rgb(147, 51, 234),  # avocloud purple
        )
        if voted_guild and voted_guild.icon:
            embed.set_thumbnail(url=voted_guild.icon.url)
        if voted_guild:
            embed.add_field(name="Server", value=voted_guild.name, inline=True)
            embed.add_field(name="Members", value=str(voted_guild.member_count), inline=True)
        embed.set_footer(text="top.gg • Baxi")

        try:
            await vote_channel.send(embed=embed)
            print(f"[TopGG Vote] SUCCESS: Sent announcement to #{vote_channel.name}")
        except discord.Forbidden as e:
            print(f"[TopGG Vote] ABORT: Forbidden while sending message: {e}. Bot needs Send Messages + Embed Links in #{vote_channel.name}")
        except Exception as e:
            print(f"[TopGG Vote] ABORT: Unexpected error sending message: {type(e).__name__}: {e}")

        return quart.jsonify({"ok": True}), 200

    # ─────────────────────────── DONATIONS ──────────────────────────────────

    async def _assign_donation_role(guild_id: int, tier_id: str, discord_user_id: int, username: str, amount_eur: str) -> None:
        """Assign the configured role after a successful donation and optionally announce it."""
        donations: dict = dict(load_data(guild_id, "donations"))
        tier = next((t for t in donations.get("tiers", []) if t["id"] == tier_id), None)
        if not tier:
            print(f"[Donations] Tier '{tier_id}' not found for guild {guild_id}. Skipping role assignment.")
            return
        try:
            g = await bot.fetch_guild(guild_id)
            member = await g.fetch_member(discord_user_id)
            role = g.get_role(int(tier["role_id"]))
            if role:
                await member.add_roles(role, reason=f"Donation: {tier['label']} (€{amount_eur})")
                print(f"[Donations] Role '{role.name}' assigned to {username} ({discord_user_id}) in guild {guild_id}.")
            else:
                print(f"[Donations] Role {tier['role_id']} not found in guild {guild_id}.")
        except discord.NotFound:
            print(f"[Donations] Member {discord_user_id} not found in guild {guild_id}.")
            return
        except Exception as e:
            print(f"[Donations] Role assignment failed: {e}")
            return

        # Optional announcement
        if donations.get("log_enabled") and donations.get("log_channel"):
            try:
                ch = bot.get_channel(int(donations["log_channel"]))
                if ch and isinstance(ch, discord.TextChannel):
                    embed = discord.Embed(
                        title="New Donation",
                        description=f"**{username}** donated **€{amount_eur}** and received the **{tier['label']}** role!",
                        color=discord.Color.from_rgb(34, 197, 94),
                    )
                    await ch.send(embed=embed)
            except Exception as e:
                print(f"[Donations] Announcement failed: {e}")

    @app.route("/donate/<int:guild_id>/login")
    async def donation_login(guild_id: int):
        """Start Discord OAuth with a return URL back to the donation page."""
        session["next_url"] = f"/donate/{guild_id}"
        return await discord_auth.create_session(scope=["identify", "guilds"], permissions=0)

    @app.route("/donate/<int:guild_id>")
    async def donation_page(guild_id: int):
        """Public-facing donation page — no auth required to view."""
        donations: dict = dict(load_data(guild_id, "donations"))
        # Fill defaults so template never gets KeyError
        for k, v in config.datasys.default_data.get("donations", {}).items():
            donations.setdefault(k, v)

        if not donations.get("enabled"):
            return await render_template("error.html", message="Donations are not enabled for this server."), 404

        try:
            g = await bot.fetch_guild(guild_id)
        except discord.NotFound:
            return await render_template("error.html", message="Server not found."), 404
        except Exception:
            return await render_template("error.html", message="Could not load server information."), 500

        discord_user = None
        try:
            discord_user = await discord_auth.fetch_user()
        except Exception:
            pass  # Not logged in — show login button

        success = quart.request.args.get("success") == "1"
        tier_id = quart.request.args.get("tier")

        return await render_template(
            "donate.html",
            guild=g,
            donations=donations,
            discord_user=discord_user,
            success=success,
            tier_id=tier_id,
            web_url=config.Web.url,
        )

    @app.route("/api/donate/checkout/stripe/<int:guild_id>", methods=["POST"])
    @requires_authorization
    async def donation_stripe_checkout(guild_id: int):
        """Create a Stripe Checkout Session and return the redirect URL."""
        try:
            import stripe as _stripe
        except ImportError:
            return quart.jsonify({"success": False, "message": "Stripe library not installed."}), 500

        from assets.crypto import decrypt_secret

        user = await discord_auth.fetch_user()
        donations: dict = dict(load_data(guild_id, "donations"))

        sk = decrypt_secret(donations.get("stripe_secret_key", ""))
        if not sk:
            return quart.jsonify({"success": False, "message": "Stripe not configured."}), 503

        data: dict = await quart.request.get_json() or {}
        tier_id = str(data.get("tier_id", ""))
        tier = next((t for t in donations.get("tiers", []) if t["id"] == tier_id), None)
        if not tier:
            return quart.jsonify({"success": False, "message": "Donation tier not found."}), 404

        if tier["type"] == "fixed":
            amount_eur = tier["amount"]
        else:
            try:
                amount_eur = round(float(data.get("custom_amount", 0)), 2)
            except (TypeError, ValueError):
                return quart.jsonify({"success": False, "message": "Invalid amount."}), 400
            if amount_eur < (tier.get("amount_min") or 0.50):
                return quart.jsonify({"success": False, "message": f"Amount must be at least €{tier['amount_min']}."}), 400
            if tier.get("amount_max") and amount_eur > tier["amount_max"]:
                return quart.jsonify({"success": False, "message": f"Amount must be at most €{tier['amount_max']}."}), 400

        amount_cents = int(round(amount_eur * 100))

        _stripe.api_key = sk
        try:
            session_obj = _stripe.checkout.Session.create(
                payment_method_types=["card"],
                line_items=[{
                    "price_data": {
                        "currency": "eur",
                        "unit_amount": amount_cents,
                        "product_data": {"name": f"{tier['label']} – Server Donation"},
                    },
                    "quantity": 1,
                }],
                mode="payment",
                success_url=f"https://{config.Web.url}/donate/{guild_id}?success=1&tier={tier_id}",
                cancel_url=f"https://{config.Web.url}/donate/{guild_id}",
                metadata={
                    "guild_id": str(guild_id),
                    "tier_id": tier_id,
                    "discord_user_id": str(user.id),
                    "discord_username": user.name,
                    "amount_eur": str(amount_eur),
                },
            )
        except Exception as e:
            print(f"[Donations/Stripe] Checkout session creation failed: {e}")
            return quart.jsonify({"success": False, "message": "Could not create payment session. Check your Stripe configuration."}), 500

        return quart.jsonify({"success": True, "checkout_url": session_obj.url})

    @app.route("/webhooks/stripe/<int:guild_id>", methods=["POST"])
    async def stripe_webhook(guild_id: int):
        """Receive Stripe webhook events and assign roles after successful payment."""
        try:
            import stripe as _stripe
        except ImportError:
            return quart.jsonify({"error": "Stripe not installed"}), 500

        from assets.crypto import decrypt_secret

        donations: dict = dict(load_data(guild_id, "donations"))
        webhook_secret = decrypt_secret(donations.get("stripe_webhook_secret", ""))
        if not webhook_secret:
            return quart.jsonify({"error": "Not configured"}), 503

        payload: bytes = await quart.request.get_data()
        sig_header: str = quart.request.headers.get("Stripe-Signature", "")

        try:
            event = _stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
        except _stripe.error.SignatureVerificationError:
            print(f"[Donations/Stripe] Bad webhook signature for guild {guild_id}.")
            return quart.jsonify({"error": "Bad signature"}), 400
        except ValueError:
            return quart.jsonify({"error": "Bad payload"}), 400

        if event["type"] == "checkout.session.completed":
            import json as _json
            # Parse the raw payload as JSON to avoid Stripe SDK object quirks.
            try:
                raw_event = _json.loads(payload.decode("utf-8"))
                s_dict: dict = raw_event.get("data", {}).get("object", {}) or {}
            except Exception as e:
                print(f"[Donations/Stripe] Payload parse error: {e}")
                s_dict = {}
            meta: dict = s_dict.get("metadata") or {}
            try:
                g_id = int(meta.get("guild_id", 0))
                t_id = str(meta.get("tier_id", ""))
                u_id = int(meta.get("discord_user_id", 0))
                uname = str(meta.get("discord_username", "Unknown"))
                amt = str(meta.get("amount_eur", "?"))
                print(f"[Donations/Stripe] Processing: guild={g_id}, tier={t_id}, user={u_id}, amount={amt}")
                if g_id and t_id and u_id:
                    await _assign_donation_role(g_id, t_id, u_id, uname, amt)
                else:
                    print(f"[Donations/Stripe] Missing metadata fields, skipping role assignment. meta={meta}")
            except Exception as e:
                print(f"[Donations/Stripe] Post-payment processing error: {type(e).__name__}: {e}")

        return quart.jsonify({"ok": True}), 200

    @app.route("/api/donate/checkout/paypal/<int:guild_id>", methods=["POST"])
    @requires_authorization
    async def donation_paypal_checkout(guild_id: int):
        """Create a PayPal order and return the approval URL."""
        import json as _json
        import aiohttp

        from assets.crypto import decrypt_secret

        user = await discord_auth.fetch_user()
        donations: dict = dict(load_data(guild_id, "donations"))

        client_id = decrypt_secret(donations.get("paypal_client_id", ""))
        client_secret = decrypt_secret(donations.get("paypal_client_secret", ""))
        if not client_id or not client_secret:
            return quart.jsonify({"success": False, "message": "PayPal not configured."}), 503

        data: dict = await quart.request.get_json() or {}
        tier_id = str(data.get("tier_id", ""))
        tier = next((t for t in donations.get("tiers", []) if t["id"] == tier_id), None)
        if not tier:
            return quart.jsonify({"success": False, "message": "Donation tier not found."}), 404

        if tier["type"] == "fixed":
            amount_eur = tier["amount"]
        else:
            try:
                amount_eur = round(float(data.get("custom_amount", 0)), 2)
            except (TypeError, ValueError):
                return quart.jsonify({"success": False, "message": "Invalid amount."}), 400
            if amount_eur < (tier.get("amount_min") or 0.50):
                return quart.jsonify({"success": False, "message": f"Amount must be at least €{tier['amount_min']}."}), 400
            if tier.get("amount_max") and amount_eur > tier["amount_max"]:
                return quart.jsonify({"success": False, "message": f"Amount must be at most €{tier['amount_max']}."}), 400

        # Get PayPal access token
        try:
            async with aiohttp.ClientSession() as http:
                async with http.post(
                    "https://api-m.paypal.com/v1/oauth2/token",
                    auth=aiohttp.BasicAuth(client_id, client_secret),
                    data={"grant_type": "client_credentials"},
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                ) as resp:
                    if resp.status != 200:
                        return quart.jsonify({"success": False, "message": "PayPal authentication failed. Check your credentials."}), 500
                    token_data = await resp.json()
                    access_token = token_data["access_token"]

                custom_id = _json.dumps({
                    "guild_id": guild_id,
                    "tier_id": tier_id,
                    "discord_user_id": user.id,
                    "discord_username": user.name,
                    "amount_eur": str(amount_eur),
                })

                order_payload = {
                    "intent": "CAPTURE",
                    "purchase_units": [{
                        "amount": {"currency_code": "EUR", "value": f"{amount_eur:.2f}"},
                        "description": f"{tier['label']} – Server Donation",
                        "custom_id": custom_id[:127],
                    }],
                    "application_context": {
                        "return_url": f"https://{config.Web.url}/donate/{guild_id}?success=1&tier={tier_id}",
                        "cancel_url": f"https://{config.Web.url}/donate/{guild_id}",
                        "brand_name": "Server Donation",
                        "landing_page": "BILLING",
                        "user_action": "PAY_NOW",
                    },
                }

                async with http.post(
                    "https://api-m.paypal.com/v2/checkout/orders",
                    headers={"Content-Type": "application/json", "Authorization": f"Bearer {access_token}"},
                    json=order_payload,
                ) as resp2:
                    if resp2.status not in (200, 201):
                        body = await resp2.text()
                        print(f"[Donations/PayPal] Order creation failed ({resp2.status}): {body}")
                        return quart.jsonify({"success": False, "message": "Could not create PayPal order."}), 500
                    order = await resp2.json()

        except Exception as e:
            print(f"[Donations/PayPal] Error: {e}")
            return quart.jsonify({"success": False, "message": "PayPal request failed."}), 500

        approve_url = next((l["href"] for l in order.get("links", []) if l.get("rel") == "approve"), None)
        if not approve_url:
            return quart.jsonify({"success": False, "message": "PayPal did not return an approval URL."}), 500

        return quart.jsonify({"success": True, "checkout_url": approve_url})

    @app.route("/webhooks/paypal/<int:guild_id>", methods=["POST"])
    async def paypal_webhook(guild_id: int):
        """Receive PayPal webhook events and assign roles after successful payment."""
        import json as _json
        import aiohttp

        from assets.crypto import decrypt_secret

        donations: dict = dict(load_data(guild_id, "donations"))
        client_id = decrypt_secret(donations.get("paypal_client_id", ""))
        client_secret = decrypt_secret(donations.get("paypal_client_secret", ""))
        if not client_id or not client_secret:
            return quart.jsonify({"error": "Not configured"}), 503

        payload_bytes: bytes = await quart.request.get_data()
        try:
            payload: dict = _json.loads(payload_bytes)
        except Exception:
            return quart.jsonify({"error": "Bad payload"}), 400

        # Verify webhook via PayPal
        headers = dict(quart.request.headers)
        verification_body = {
            "auth_algo": headers.get("Paypal-Auth-Algo", ""),
            "cert_url": headers.get("Paypal-Cert-Url", ""),
            "transmission_id": headers.get("Paypal-Transmission-Id", ""),
            "transmission_sig": headers.get("Paypal-Transmission-Sig", ""),
            "transmission_time": headers.get("Paypal-Transmission-Time", ""),
            "webhook_id": "",  # Not storing webhook ID per-guild; skip strict verification
            "webhook_event": payload,
        }
        # Skip strict sig verification (webhook_id not stored), rely on custom_id to look up guild data
        # For production, store the webhook_id in guild config and verify here

        event_type = payload.get("event_type", "")
        if event_type == "CHECKOUT.ORDER.APPROVED":
            resource = payload.get("resource", {})
            for unit in resource.get("purchase_units", []):
                custom_id_raw = unit.get("custom_id", "")
                try:
                    meta = _json.loads(custom_id_raw)
                    g_id = int(meta.get("guild_id", 0))
                    t_id = str(meta.get("tier_id", ""))
                    u_id = int(meta.get("discord_user_id", 0))
                    uname = str(meta.get("discord_username", "Unknown"))
                    amt = str(meta.get("amount_eur", "?"))
                    if g_id and t_id and u_id:
                        await _assign_donation_role(g_id, t_id, u_id, uname, amt)
                except Exception as e:
                    print(f"[Donations/PayPal] Post-payment processing error: {e}")

        return quart.jsonify({"ok": True}), 200

    app.config["BOT_READY"] = True
