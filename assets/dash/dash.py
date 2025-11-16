import quart
from quart import redirect, url_for, Markup
from assets.data import load_data, save_data
from quart import render_template, send_from_directory, abort
from discord.ext import commands
import discord
import config.auth as auth
from typing import Optional
from quart_discord import DiscordOAuth2Session, requires_authorization, Unauthorized
from datetime import datetime
import random
import re
from typing import cast
import config.config as config
from assets.buttons import TicketView


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
        await discord_auth.callback()
        return redirect(url_for("index"))

    @app.errorhandler(Unauthorized)
    async def redirect_unauthorized(e):
        return redirect(url_for("login"))

    def get_time_based_greeting(username):
        hour = datetime.now().hour

        if 5 <= hour < 12:
            greetings = [
                Markup(
                    f"Good morning, <span class='highlight-purple'>{username}</span>"
                ),
                Markup(
                    f"Rise and shine, <span class='highlight-purple'>{username}</span>!"
                ),
                Markup(
                    f"<span class='highlight-purple'>{username}</span>, ready to conquer the day?"
                ),
                Markup(
                    f"Fresh start for you, <span class='highlight-purple'>{username}</span>?"
                ),
                Markup(
                    f"Hey <span class='highlight-purple'>{username}</span>, coffee's brewing!"
                ),
                Markup(
                    f"<span class='highlight-purple'>{username}</span>, let's make today count!"
                ),
                Markup(
                    f"Morning hustle, <span class='highlight-purple'>{username}</span>?"
                ),
                Markup(
                    f"Greetings, early bird <span class='highlight-purple'>{username}</span>!"
                ),
                Markup(
                    f"<span class='highlight-purple'>{username}</span>, the guild awaits your magic!"
                ),
                Markup(
                    f"Sun's up, <span class='highlight-purple'>{username}</span> – time to shine!"
                ),
            ]

        elif 12 <= hour < 17:
            greetings = [
                Markup(
                    f"Good afternoon, <span class='highlight-purple'>{username}</span>"
                ),
                Markup(
                    f"Back at it, <span class='highlight-purple'>{username}</span>?"
                ),
                Markup(
                    f"<span class='highlight-purple'>{username}</span>, how's the guild today?"
                ),
                Markup(
                    f"Afternoon vibes, <span class='highlight-purple'>{username}</span>!"
                ),
                Markup(
                    f"<span class='highlight-purple'>{username}</span>, productivity mode: ON?"
                ),
                Markup(
                    f"Hey <span class='highlight-purple'>{username}</span>, need a dashboard break?"
                ),
                Markup(
                    f"<span class='highlight-purple'>{username}</span>, let's tweak that guild!"
                ),
                Markup(
                    f"Crushing goals, <span class='highlight-purple'>{username}</span>?"
                ),
                Markup(
                    f"<span class='highlight-purple'>{username}</span>, the guild misses you!"
                ),
                Markup(
                    f"Afternoon fuel for <span class='highlight-purple'>{username}</span>!"
                ),
            ]

        elif 17 <= hour < 22:
            greetings = [
                Markup(
                    f"Good evening, <span class='highlight-purple'>{username}</span>"
                ),
                Markup(
                    f"<span class='highlight-purple'>{username}</span>, still in the grind?"
                ),
                Markup(
                    f"Evening guild session, <span class='highlight-purple'>{username}</span>?"
                ),
                Markup(
                    f"<span class='highlight-purple'>{username}</span>, time to wrap up!"
                ),
                Markup(
                    f"Hey <span class='highlight-purple'>{username}</span>, dinner then guild?"
                ),
                Markup(
                    f"<span class='highlight-purple'>{username}</span>, let's polish that guild!"
                ),
                Markup(
                    f"Evening vibes with <span class='highlight-purple'>{username}</span>!"
                ),
                Markup(
                    f"<span class='highlight-purple'>{username}</span>, guild leader extraordinaire!"
                ),
                Markup(
                    f"Sunset checks by <span class='highlight-purple'>{username}</span>!"
                ),
                Markup(
                    f"<span class='highlight-purple'>{username}</span>, the guild's nightwatch!"
                ),
            ]

        else:
            greetings = [
                Markup(f"Night owl <span class='highlight-purple'>{username}</span>?"),
                Markup(
                    f"<span class='highlight-purple'>{username}</span>, burning midnight oil?"
                ),
                Markup(
                    f"Hey <span class='highlight-purple'>{username}</span>, the guild never sleeps!"
                ),
                Markup(
                    f"<span class='highlight-purple'>{username}</span>, vampire mode activated!"
                ),
                Markup(
                    f"3 AM guild updates, <span class='highlight-purple'>{username}</span>?"
                ),
                Markup(
                    f"<span class='highlight-purple'>{username}</span>, the dashboard misses you!"
                ),
                Markup(
                    f"Shhh... <span class='highlight-purple'>{username}</span> is night-configuring!"
                ),
                Markup(
                    f"Respect the grind, <span class='highlight-purple'>{username}</span>!"
                ),
                Markup(
                    f"<span class='highlight-purple'>{username}</span>, guardian of the night guild!"
                ),
                Markup(
                    f"Insomnia? Or guild passion, <span class='highlight-purple'>{username}</span>?"
                ),
            ]

        return random.choice(greetings)

    @app.route("/")
    @requires_authorization
    async def index():
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

        return await render_template(
            "dash_home.html",
            managed_guilds=valid_guilds,
            greeting=get_time_based_greeting(user.name),
            user=user,
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

            channels = await guild.fetch_channels()

            text_channels = {
                str(channel.id): channel.name
                for channel in channels
                if isinstance(channel, discord.TextChannel)
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
            print(guild_conf)
            return await render_template(
                "dash.html",
                data=guild_conf,
                guild=guild,
                user=user,
                channels=text_channels,
                categorys=catrgorys_list,
                roles=roles_list,
                nick=bot_nick,
                greeting=get_time_based_greeting(user.name),
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
            return await render_template(
                "error.html", message="Missing 'system' or 'guild_id' parameter."
            )

        try:
            user = await discord_auth.fetch_user()
            guild = await bot.fetch_guild(int(guild_id))
            print(guild.name)
            print(guild.id)
            print(guild_id)

            try:
                guild_member = await guild.fetch_member(user.id)
            except discord.NotFound:
                return await render_template(
                    "error.html",
                    message=f"You are not on the guild {guild.name} and therefore do not have the required authorisations to manage this server.",
                )

            if not guild_member.guild_permissions.manage_guild:
                return await render_template(
                    "error.html",
                    message=f"Hello {user.name}! Unfortunately, you are not authorized to manage this guild.",
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

        if system == "chatfilter":
            data: dict = await quart.request.get_json()
            chatfilter = data.get("chatfilter")

            print(chatfilter)

            if not isinstance(chatfilter, dict):
                return await render_template(
                    "error.html",
                    message="Invalid data format: 'chatfilter' must be an object.",
                )

            if chatfilter.get("system") is None or chatfilter["system"] not in [
                "SafeText",
                "AI",
            ]:
                return await render_template(
                    "error.html",
                    message="Invalid or missing 'system'. Must be 'SafeText' or 'AI'.",
                )

            if chatfilter.get("enabled") is None or not isinstance(
                chatfilter["enabled"], bool
            ):
                return await render_template(
                    "error.html",
                    message="'enabled' must be a boolean (true/false) and not null.",
                )

            if (
                chatfilter.get("c_goodwords") is None
                or not isinstance(chatfilter["c_goodwords"], list)
                or not all(isinstance(w, str) for w in chatfilter["c_goodwords"])
            ):
                return await render_template(
                    "error.html",
                    message="'c_goodwords' must be a list of strings and not null.",
                )

            if (
                chatfilter.get("c_badwords") is None
                or not isinstance(chatfilter["c_badwords"], list)
                or not all(isinstance(w, str) for w in chatfilter["c_badwords"])
            ):
                return await render_template(
                    "error.html",
                    message="'c_badwords' must be a list of strings and not null.",
                )

            if chatfilter.get("bypass") is not None and (
                not isinstance(chatfilter["bypass"], list)
                or not all(isinstance(w, str) for w in chatfilter["bypass"])
            ):
                return await render_template(
                    "error.html",
                    message="'bypass' must be a list of strings or omitted.",
                )

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
                return await render_template(
                    "error.html",
                    message="Invalid data format: 'general' must be an object.",
                )
            if general.get("lang") is None or general["lang"] not in [
                "en",
                "de",
            ]:
                return await render_template(
                    "error.html",
                    message="Invalid or missing 'lang'. Must be 'en' or 'de'.",
                )

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
                return await render_template(
                    "error.html",
                    message="'terms' must be provided and not be null.",
                )

            if not isinstance(guild_conf_terms, bool):
                return await render_template(
                    "error.html",
                    message="'terms' must be a boolean (true/false).",
                )

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
                return await render_template(
                    "error.html",
                    message="Invalid data format: 'globalchat' must be an object.",
                )

            if globalchat["enabled"] is None or not isinstance(
                globalchat["enabled"], bool
            ):
                return await render_template(
                    "error.html",
                    message="'enabled' must be a boolean (true/false) and not null.",
                )

            if not isinstance(globalchat["channel"], str) or not re.fullmatch(
                r"\d{17,19}", globalchat["channel"]
            ):
                return await render_template(
                    "error.html",
                    message="Channel ID does not match the Discord ID format.",
                )

            channel = await guild.fetch_channel(int(globalchat["channel"]))
            if channel is None:
                return await render_template(
                    "error.html",
                    message="Selected channel unknown - ID not recognized.",
                )

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
                return await render_template(
                    "error.html",
                    message="Invalid data format: 'ticket' must be an object.",
                )
            if ticket["enabled"] is None or not isinstance(ticket["enabled"], bool):
                return await render_template(
                    "error.html",
                    message="'enabled' must be a boolean (true/false) and not null.",
                )
            if not isinstance(ticket["channel"], str) or not re.fullmatch(
                r"\d{17,19}", ticket["channel"]
            ):
                return await render_template(
                    "error.html",
                    message="Channel ID does not match the Discord ID format.",
                )

            if not isinstance(ticket["role"], str) or not re.fullmatch(
                r"\d{17,19}", ticket["role"]
            ):
                return await render_template(
                    "error.html",
                    message="Role ID does not match the Discord ID format.",
                )

            if not isinstance(ticket["color"], str) or not bool(
                re.fullmatch(
                    r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})", ticket["color"]
                )
            ):
                return await render_template(
                    "error.html",
                    message="You did not specify the color in a valid HEX format.",
                )

            settings: dict = dict(load_data(guild.id, "ticket"))

            channel = await guild.fetch_channel(int(ticket["channel"]))
            if channel is None:
                return await render_template(
                    "error.html",
                    message="The specified channel is unknown. Was it deleted before saving? Reload the page and try again.",
                )
            if not isinstance(channel, discord.TextChannel):
                return await render_template(
                    "error.html",
                    message="The specified channel is not a text channel.",
                )

            cat = await guild.fetch_channel(int(ticket["category"]))
            if cat is None:
                return await render_template(
                    "error.html",
                    message="The specified category is unknown. Was it deleted before saving? Reload the page and try again.",
                )
            if not isinstance(cat, discord.CategoryChannel):
                return await render_template(
                    "error.html",
                    message="The specified category is not a category.",
                )

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

        guild_conf: dict = dict(load_data(sid=int(guild_id), sys="all"))
        return await render_template("dash_success.html", data=guild_conf)

    @app.route("/dash/saved/")
    async def dash_saved():
        dash_login = quart.request.args.get("dash_login")

        if not dash_login:
            return (
                await render_template(
                    "error.html",
                    message='No login token provided.',
                ),
                400,
            )

        return await render_template("dash_success.html")
    
    @app.route("/check/channel/perms/", methods=["POST"])
    async def check_channel_perms():
        data: dict = await quart.request.get_json()
        system: str = data.get("system")
        channel_id: int = int(data.get("channel_id"))
        guild_id: int = int(data.get("guild_id"))
        print(system)
        print(channel_id)
        print(guild_id)

        if not all([system, channel_id, guild_id]):
            print("Missing required fields")
            return quart.jsonify({"error": "Missing required fields"}), 400

        try:
            guild = await bot.fetch_guild(guild_id)
            channel = await guild.fetch_channel(channel_id)
            bot_member = guild.get_member(bot.user.id)
            if not bot_member:
                bot_member = await guild.fetch_member(bot.user.id)

            permissions = channel.permissions_for(bot_member)

            required_perms = set()

            if system == "globalchat":
                required_perms = {
                    "send_messages",
                    "manage_messages",
                    "attach_files",
                    "use_external_emojis",
                    "embed_links",  # oft implizit nötig für Rich Embeds
                    "read_messages",
                    "read_message_history"
                }
            elif system == "ticket":
                required_perms = {
                    "send_messages",
                    "read_messages",
                    "read_message_history",
                    "manage_channels",        # zum Erstellen/Löschen von Ticket-Kanälen
                    "manage_permissions",     # um Berechtigungen im Ticket zu setzen
                    "embed_links"
                }
            elif system == "ticket_transcript":
                required_perms = {
                    "send_messages",
                    "read_messages",
                    "read_message_history",
                    "attach_files",           # um Transkript als .txt oder .html zu senden
                    "embed_links"
                }
            else:
                return quart.jsonify({"error": "Unknown system"}), 400

            # Prüfe, ob alle benötigten Berechtigungen vorhanden sind
            missing = [perm for perm in required_perms if not getattr(permissions, perm, False)]

            valid = len(missing) == 0

            return quart.jsonify({
                "valid": valid,
                "missing": missing if not valid else None
            })

        except Exception as e:
            return quart.jsonify({"error": str(e)}), 500

    @app.route("/attachments/<filename>")
    async def attachments(filename):
        if ".." in filename or filename.startswith("/"):
            return abort(400, "Ungültiger Dateiname")

        return await send_from_directory("attachments", filename)
