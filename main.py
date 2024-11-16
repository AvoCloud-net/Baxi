import asyncio
import secrets
import shutil
import time
from collections import defaultdict
from crypt import methods
from typing import cast
import pyotp

import discord
import pytz
import wavelink
from bs4 import BeautifulSoup
from discord import Guild, TextChannel, Interaction, app_commands, ui
from discord.ext import commands, tasks
from quart import session
from quart_cors import cors

from assets.api.dash.save import *
from assets.api.dash.load import *
from assets.api.dash.oauth import *
from assets.api.public.oauth import *
from assets.api.public.security import *
from assets.api.public.endpoints import *
from assets.general.message.counting import *
from assets.general.message.guessing import *
from assets.general.message.suggestion import *
from assets.general.get_saves import *

from assets.general.routine_events import *
from assets.general.get_saves import *
from assets.general.bot_events import *

from assets.dc.embed.embeds import *
from assets.dc.embed.buttons import *
from assets.dc.embed.ticket_buttons import *

from assets.general.message.security_check import *
from assets.general.message.globalchat import *
from assets.general.message.logging import *
from assets.sec_requests import Check

logger = Logger()

logger.working("Preparing to load the configuration files...")
logger.working("General configuration file is being loaded...")
config = configparser.ConfigParser()
config.read("config/runtime.conf")
logger.success("General configuration file has been loaded successfully!")
logger.working("Authentication configuration file is being loaded...")
auth0 = configparser.ConfigParser()
auth0.read("config/auth0.conf")
logger.success("Authentication configuration file has been loaded!")

logger.info("All config files have been applied.")


class PersistentViewBot(commands.AutoShardedBot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(
            command_prefix=str(commands.when_mentioned_or(config["BOT"]["prefix"])),
            intents=intents,
            shard_count=config.getint("BOT", "shard_count"),
        )

    async def setup_hook(self) -> None:
        self.add_view(VerifyButton())
        self.add_view(TicketMenuButtons())
        self.add_view(TicketChannelButtons())
        self.add_view(TicketChannelDeleteButtons())


bot = PersistentViewBot()

check_api = Check()

logger.info("Booting...")
logger.info("Setting Boot Variables...")

icons_url = config["WEB"]["icon_url"]
top_gg_api = config["TOP_GG"]["url"]
top_gg_key = auth0["TOP_GG"]["api_key"]

# bot.wavelink = wavelink.Client(bot=bot)

app = Quart(
    __name__,
    template_folder=str(config["FLASK"]["template_folder"]),
    static_folder=str(config["FLASK"]["static_folder"]),
)
app = cors(app)
app.secret_key = auth0["FLASK"]["secret"]

# *********************************************************************************************************************
boot_time = datetime.datetime.now()
server_count: int = len(bot.guilds)
api_requests: int = 0
emergency_mode: bool = config.getboolean("ADMINISTRATION", "sys_lockdown")
booted: bool = False
embedColor = discord.Color.from_rgb(
    int(config["BOT"]["embed_color_red"]),
    int(config["BOT"]["embed_color_green"]),
    int(config["BOT"]["embed_color_blue"]),
)  # FF5733
botadmin = list(map(int, auth0["DISCORD"]["admins"].split(",")))
encryption_key = auth0["FLASK"]["key"]

action_counts = defaultdict(lambda: defaultdict(lambda: {"actions": 0, "timestamp": 0}))

logger.success("Success!")
logger.waiting("Waiting for boot to finish...")

# *********************************************************************************************************************


app.secret_key = os.urandom(24)

CLIENT_ID = auth0["DISCORD"]["client_id"]
CLIENT_SECRET = auth0["DISCORD"]["client_secret"]
REDIRECT_URI = config["DASH"]["callback_url"]
API_ENDPOINT = "https://discord.com/api/v10"
AUTH_URL = "https://discord.com/api/oauth2/authorize"
TOKEN_URL = "https://discord.com/api/oauth2/token"
BOT_TOKEN = auth0["DISCORD"]["token"]


@app.route("/api/oauth/get/data/baxi")
async def update_guild_tokens():
    guild = bot.get_guild(1175803684567908402)
    channel = guild.get_channel(1262552071731675249)
    return await sync_baxi_data(request=request, channel=channel, bot=bot)


# @app.before_request
# async def app_before_request():
#     if request.endpoint != 'update_guild_tokens' or 'hello':


@app.route("/api/dash/get/active_systems/<int:guild_id>", methods=["GET"])
async def get_active_systems_dash_api(guild_id: int):
    data = await request.get_json()
    code_check = verify_one_time_code(
        one_time_code=data["otc"], secret_key=auth0["FLASK"]["secret"]
    )
    if not code_check:
        logger.debug.info("Illegal access attempt")
        return (
            jsonify(
                {
                    "error": "Illegal access attempt! The attempt to carry out this action was denied. Access token (otc) invalid."
                }
            ),
            401,
        )
    else:
        logger.debug.info("/api/dash/get/active_systems/ - Access authorized : ")
        return await get_active_systems(request=request, guild=bot.get_guild(guild_id))


@app.route("/api/dash/settings/load/anti_raid/<int:guild_id>", methods=["GET"])
async def get_antiraid_guild_settings(guild_id: int):
    data = await request.get_json()
    code_check = verify_one_time_code(
        one_time_code=data["otc"], secret_key=auth0["FLASK"]["secret"]
    )
    if not code_check:
        logger.debug.info("Illegal access attempt")
        return (
            jsonify(
                {
                    "error": "Illegal access attempt! The attempt to carry out this action was denied. Access token (otc) invalid."
                }
            ),
            401,
        )
    else:
        logger.debug.info("/api/dash/settings/load/anti_raid/ - Access authorized : ")
        return await load_antiraid_settings(
            request=request, guild=bot.get_guild(guild_id)
        )


# noinspection PyBroadException
@app.route("/api/dash/settings/save/anti_raid/<int:guild_id>", methods=["POST"])
async def save_antiraid_guild_settings(guild_id: int):
    data = await request.get_json()
    code_check = verify_one_time_code(
        one_time_code=data["otc"], secret_key=auth0["FLASK"]["secret"]
    )
    if not code_check:
        logger.debug.info("Illegal access attempt")
        return (
            jsonify(
                {
                    "error": "Illegal access attempt! The attempt to carry out this action was denied. Access token (otc) invalid."
                }
            ),
            401,
        )
    else:
        logger.debug.info("/api/dash/settings/save/anti_raid/ - Access authorized : ")
        return await save_antiraid_settings(
            request=request, guild=bot.get_guild(guild_id)
        )


@app.route("/api/dash/settings/load/gc/<int:guild_id>", methods=["GET"])
async def get_gc_guild_settings(guild_id: int):
    data = await request.get_json()
    code_check = verify_one_time_code(
        one_time_code=data["otc"], secret_key=auth0["FLASK"]["secret"]
    )
    if not code_check:
        logger.debug.info("Illegal access attempt")
        return (
            jsonify(
                {
                    "error": "Illegal access attempt! The attempt to carry out this action was denied. Access token (otc) invalid."
                }
            ),
            401,
        )
    else:
        logger.debug.info("/api/dash/settings/load/gc/ - Access authorized : ")
        return await load_globalchat_settings(
            request=request, guild=bot.get_guild(guild_id)
        )


@app.route("/api/dash/settings/save/gc/<int:guild_id>", methods=["POST"])
async def save_gc_guild_settings(guild_id: int):
    data = await request.get_json()
    code_check = verify_one_time_code(
        one_time_code=data["otc"], secret_key=auth0["FLASK"]["secret"]
    )
    if not code_check:
        logger.debug.info("Illegal access attempt")
        return (
            jsonify(
                {
                    "error": "Illegal access attempt! The attempt to carry out this action was denied. Access token (otc) invalid."
                }
            ),
            401,
        )
    else:
        logger.debug.info("/api/dash/settings/save/gc/ - Access authorized : ")
        return await save_globalchat_settings(
            request=request, guild=bot.get_guild(guild_id)
        )


@app.route("/api/dash/settings/load/mgg/<int:guild_id>", methods=["GET"])
async def get_mgg_guild_settings(guild_id: int):
    data = await request.get_json()
    code_check = verify_one_time_code(
        one_time_code=data["otc"], secret_key=auth0["FLASK"]["secret"]
    )
    if not code_check:
        logger.debug.info("Illegal access attempt")
        return (
            jsonify(
                {
                    "error": "Illegal access attempt! The attempt to carry out this action was denied. Access token (otc) invalid."
                }
            ),
            401,
        )
    else:
        logger.debug.info("/api/dash/settings/load/mgg/ - Access authorized : ")
        return await load_minigame_guessing_settings(
            request=request, guild=bot.get_guild(guild_id)
        )


@app.route("/api/dash/settings/save/mgg/<int:guild_id>", methods=["POST"])
async def save_mgg_guild_settings(guild_id: int):
    data = await request.get_json()
    code_check = verify_one_time_code(
        one_time_code=data["otc"], secret_key=auth0["FLASK"]["secret"]
    )
    if not code_check:
        logger.debug.info("Illegal access attempt")
        return (
            jsonify(
                {
                    "error": "Illegal access attempt! The attempt to carry out this action was denied. Access token (otc) invalid."
                }
            ),
            401,
        )
    else:
        logger.debug.info("/api/dash/settings/save/mgg/ - Access authorized : ")
        return await save_minigame_guessing_settings(
            request=request, guild=bot.get_guild(guild_id)
        )


@app.route("/api/dash/settings/load/mgc/<int:guild_id>", methods=["GET"])
async def load_mgc_guild_settings(guild_id: int):
    data = await request.get_json()
    code_check = verify_one_time_code(
        one_time_code=data["otc"], secret_key=auth0["FLASK"]["secret"]
    )
    if not code_check:
        logger.debug.info("Illegal access attempt")
        return (
            jsonify(
                {
                    "error": "Illegal access attempt! The attempt to carry out this action was denied. Access token (otc) invalid."
                }
            ),
            401,
        )
    else:
        logger.debug.info("/api/dash/settings/load/mgc/ - Access authorized : ")
        return await load_minigame_counting_game(
            request=request, guild=bot.get_guild(guild_id)
        )


@app.route("/api/dash/settings/save/mgc/<int:guild_id>", methods=["POST"])
async def save_mgc_guild_settings(guild_id: int):
    data = await request.get_json()
    code_check = verify_one_time_code(
        one_time_code=data["otc"], secret_key=auth0["FLASK"]["secret"]
    )
    if not code_check:
        logger.debug.info("Illegal access attempt")
        return (
            jsonify(
                {
                    "error": "Illegal access attempt! The attempt to carry out this action was denied. Access token (otc) invalid."
                }
            ),
            401,
        )
    else:
        logger.debug.info("/api/dash/settings/save/mgc/ - Access authorized : ")
        return await save_minigame_counting_settings(
            request=request, guild=bot.get_guild(guild_id)
        )


@app.route("/api/dash/settings/load/sec/<int:guild_id>", methods=["GET"])
async def load_sec_guild_settings(guild_id: int):
    data = await request.get_json()
    code_check = verify_one_time_code(
        one_time_code=data["otc"], secret_key=auth0["FLASK"]["secret"]
    )
    if not code_check:
        logger.debug.info("Illegal access attempt")
        return (
            jsonify(
                {
                    "error": "Illegal access attempt! The attempt to carry out this action was denied. Access token (otc) invalid."
                }
            ),
            401,
        )
    else:
        logger.debug.info("/api/dash/settings/load/sec/ - Access authorized : ")
        return await load_security_settings(
            request=request, guild=bot.get_guild(guild_id)
        )


@app.route("/api/dash/settings/save/sec/<int:guild_id>", methods=["POST"])
async def save_sec_guild_settings(guild_id: int):
    data = await request.get_json()
    code_check = verify_one_time_code(
        one_time_code=data["otc"], secret_key=auth0["FLASK"]["secret"]
    )
    if not code_check:
        logger.debug.info("Illegal access attempt")
        return (
            jsonify(
                {
                    "error": "Illegal access attempt! The attempt to carry out this action was denied. Access token (otc) invalid."
                }
            ),
            401,
        )
    else:
        logger.debug.info("/api/dash/settings/save/sec/ - Access authorized : ")
        return await save_security_settings(
            request=request, guild=bot.get_guild(guild_id)
        )


@app.route("/api/dash/settings/load/welc/<int:guild_id>", methods=["GET"])
async def load_welc_guild_settings(guild_id: int):
    data = await request.get_json()
    code_check = verify_one_time_code(
        one_time_code=data["otc"], secret_key=auth0["FLASK"]["secret"]
    )
    if not code_check:
        logger.debug.info("Illegal access attempt")
        return (
            jsonify(
                {
                    "error": "Illegal access attempt! The attempt to carry out this action was denied. Access token (otc) invalid."
                }
            ),
            401,
        )
    else:
        logger.debug.info("/api/dash/settings/load/welc/ - Access authorized : ")
        return await load_welcome_settings(
            request=request, guild=bot.get_guild(guild_id)
        )


@app.route("/api/dash/settings/save/welc/<int:guild_id>", methods=["POST"])
async def save_welc_guild_settings(guild_id: int):
    data = await request.get_json()
    code_check = verify_one_time_code(
        one_time_code=data["otc"], secret_key=auth0["FLASK"]["secret"]
    )
    if not code_check:
        logger.debug.info("Illegal access attempt")
        return (
            jsonify(
                {
                    "error": "Illegal access attempt! The attempt to carry out this action was denied. Access token (otc) invalid."
                }
            ),
            401,
        )
    else:
        logger.debug.info("/api/dash/settings/save/welc/ - Access authorized : ")
        return await save_welcome_settings(
            request=request, guild=bot.get_guild(guild_id)
        )


@app.route("/api/dash/settings/load/verify/<int:guild_id>", methods=["GET"])
async def load_verify_guild_settings(guild_id: int):
    data = await request.get_json()
    code_check = verify_one_time_code(
        one_time_code=data["otc"], secret_key=auth0["FLASK"]["secret"]
    )
    if not code_check:
        logger.debug.info("Illegal access attempt")
        return (
            jsonify(
                {
                    "error": "Illegal access attempt! The attempt to carry out this action was denied. Access token (otc) invalid."
                }
            ),
            401,
        )
    else:
        logger.debug.info("/api/dash/settings/load/verify/ - Access authorized : ")
        return await load_verify_settings(
            request=request, guild=bot.get_guild(guild_id)
        )


# noinspection PyDunderSlots,PyUnresolvedReferences
@app.route("/api/dash/settings/save/verify/<int:guild_id>", methods=["POST"])
async def save_verify_guild_settings(guild_id: int):
    data = await request.get_json()
    code_check = verify_one_time_code(
        one_time_code=data["otc"], secret_key=auth0["FLASK"]["secret"]
    )
    if not code_check:
        logger.debug.info("Illegal access attempt")
        return (
            jsonify(
                {
                    "error": "Illegal access attempt! The attempt to carry out this action was denied. Access token (otc) invalid."
                }
            ),
            401,
        )
    else:
        logger.debug.info("/api/dash/settings/save/verify/ - Access authorized : ")
        return await save_verify_settings(
            request=request, guild=bot.get_guild(guild_id)
        )


@app.route("/api/dash/settings/load/sugg/<int:guild_id>", methods=["GET"])
async def load_sugg_guild_settings(guild_id: int):
    data = await request.get_json()
    code_check = verify_one_time_code(
        one_time_code=data["otc"], secret_key=auth0["FLASK"]["secret"]
    )
    if not code_check:
        logger.debug.info("Illegal access attempt")
        return (
            jsonify(
                {
                    "error": "Illegal access attempt! The attempt to carry out this action was denied. Access token (otc) invalid."
                }
            ),
            401,
        )
    else:
        logger.debug.info("/api/dash/settings/load/sugg/ - Access authorized : ")
        return await load_sugg_settings(request=request, guild=bot.get_guild(guild_id))


@app.route("/api/dash/settings/save/sugg/<int:guild_id>", methods=["POST"])
async def save_sugg_guild_settings(guild_id: int):
    data = await request.get_json()
    code_check = verify_one_time_code(
        one_time_code=data["otc"], secret_key=auth0["FLASK"]["secret"]
    )
    if not code_check:
        logger.debug.info("Illegal access attempt")
        return (
            jsonify(
                {
                    "error": "Illegal access attempt! The attempt to carry out this action was denied. Access token (otc) invalid."
                }
            ),
            401,
        )
    else:
        logger.debug.info("/api/dash/settings/save/sugg/ - Access authorized : ")
        return await save_sugg_settings(request=request, guild=bot.get_guild(guild_id))


@app.route("/api/dash/settings/load/ticket/<int:guild_id>", methods=["GET"])
async def load_ticket_guild_settings(guild_id: int):
    data = await request.get_json()
    code_check = verify_one_time_code(
        one_time_code=data["otc"], secret_key=auth0["FLASK"]["secret"]
    )
    if not code_check:
        logger.debug.info("Illegal access attempt")
        return (
            jsonify(
                {
                    "error": "Illegal access attempt! The attempt to carry out this action was denied. Access token (otc) invalid."
                }
            ),
            401,
        )
    else:
        logger.debug.info("/api/dash/settings/load/ticket/ - Access authorized : ")
        return await load_ticket_settings(
            request=request, guild=bot.get_guild(guild_id)
        )


@app.route("/api/dash/settings/save/ticket/<int:guild_id>", methods=["POST"])
async def save_ticket_guild_settings(guild_id: int):
    data = await request.get_json()
    code_check = verify_one_time_code(
        one_time_code=data["otc"], secret_key=auth0["FLASK"]["secret"]
    )
    if not code_check:
        logger.debug.info("Illegal access attempt")
        return (
            jsonify(
                {
                    "error": "Illegal access attempt! The attempt to carry out this action was denied. Access token (otc) invalid."
                }
            ),
            401,
        )
    else:
        logger.debug.info("/api/dash/settings/save/ticket/ - Access authorized : ")
        return await save_ticket_settings(
            request=request, guild=bot.get_guild(guild_id)
        )


@app.route("/api/dash/settings/load/log/<int:guild_id>", methods=["GET"])
async def load_log_guild_settings(guild_id: int):
    data = await request.get_json()
    code_check = verify_one_time_code(
        one_time_code=data["otc"], secret_key=auth0["FLASK"]["secret"]
    )
    if not code_check:
        logger.debug.info("Illegal access attempt")
        return (
            jsonify(
                {
                    "error": "Illegal access attempt! The attempt to carry out this action was denied. Access token (otc) invalid."
                }
            ),
            401,
        )
    else:
        logger.debug.info("/api/dash/settings/load/log/ - Access authorized : ")
        return await load_log_settings(request=request, guild=bot.get_guild(guild_id))


@app.route("/api/dash/settings/save/log/<int:guild_id>", methods=["POST"])
async def save_log_guild_settings(guild_id: int):
    data = await request.get_json()
    code_check = verify_one_time_code(
        one_time_code=data["otc"], secret_key=auth0["FLASK"]["secret"]
    )
    if not code_check:
        logger.debug.info("Illegal access attempt")
        return (
            jsonify(
                {
                    "error": "Illegal access attempt! The attempt to carry out this action was denied. Access token (otc) invalid."
                }
            ),
            401,
        )
    else:
        logger.debug.info("/api/dash/settings/save/log/ - Access authorized : ")
        return await save_log_settings(request=request, guild=bot.get_guild(guild_id))


@app.route("/api/dash/settings/load/auto_roles/<int:guild_id>", methods=["GET"])
async def load_autoroles_guild_settings(guild_id: int):
    data = await request.get_json()
    code_check = verify_one_time_code(
        one_time_code=data["otc"], secret_key=auth0["FLASK"]["secret"]
    )
    if not code_check:
        logger.debug.info("Illegal access attempt")
        return (
            jsonify(
                {
                    "error": "Illegal access attempt! The attempt to carry out this action was denied. Access token (otc) invalid."
                }
            ),
            401,
        )
    else:
        logger.debug.info("/api/dash/settings/load/auto_roles/ - Access authorized : ")
        return await load_autoroles_guild(
            request=request, guild=bot.get_guild(guild_id)
        )


@app.route("/api/dash/settings/save/auto_roles/<int:guild_id>", methods=["POST"])
async def save_autoroles_guild_settings(guild_id: int):
    data = await request.get_json()
    code_check = verify_one_time_code(
        one_time_code=data["otc"], secret_key=auth0["FLASK"]["secret"]
    )
    if not code_check:
        logger.debug.info("Illegal access attempt")
        return (
            jsonify(
                {
                    "error": "Illegal access attempt! The attempt to carry out this action was denied. Access token (otc) invalid."
                }
            ),
            401,
        )
    else:
        logger.debug.info("/api/dash/settings/save/auto_roles/ - Access authorized : ")
        return await save_autoroles_guild(
            request=request, guild=bot.get_guild(guild_id)
        )


@app.route("/api/dash/msg/send/load/<int:guild_id>")
async def load_guild_channels_dash(guild_id: int):
    data = await request.get_json()
    code_check = verify_one_time_code(
        one_time_code=data["otc"], secret_key=auth0["FLASK"]["secret"]
    )
    if not code_check:
        logger.debug.info("Illegal access attempt")
        return (
            jsonify(
                {
                    "error": "Illegal access attempt! The attempt to carry out this action was denied. Access token (otc) invalid."
                }
            ),
            401,
        )
    else:
        logger.debug.info("/api/dash/msg/send/load/ - Access authorized : ")
        return await load_send_channels(request=request, guild=bot.get_guild(guild_id))


@app.route("/api/dash/msg/send/<int:guild_id>/<int:channel_id>")
async def send_guild_msg_dash(guild_id: int, channel_id: int):
    data = await request.get_json()
    code_check = verify_one_time_code(
        one_time_code=data["otc"], secret_key=auth0["FLASK"]["secret"]
    )
    if not code_check:
        logger.debug.info("Illegal access attempt")
        return (
            jsonify(
                {
                    "error": "Illegal access attempt! The attempt to carry out this action was denied. Access token (otc) invalid."
                }
            ),
            401,
        )
    else:
        logger.debug.info("/api/dash/msg/send/ - Access authorized : ")
        return await send_guild_msg(
            request=request, channel=bot.get_guild(guild_id).get_channel(channel_id)
        )


async def send_message_on_settings_save(
    guild: discord.Guild,
    channel: discord.TextChannel,
    button: str,
    embed: discord.Embed,
):
    try:
        language = load_language_model(guild.id)
        logger.debug.info(guild.name)
        logger.debug.info(channel.name)
        logger.debug.info(button)
        if button == "verify":
            await channel.send(embed=embed, view=VerifyButton())
        elif button == "ticket":
            await channel.send(embed=embed, view=TicketMenuButtons())

        logger.debug.success("Message sent successfully")
        return "sent", 200
    except Exception as e:
        logger.debug.warn("Error sending message: %s", e)
        return "ERROR: " + str(e), 500


@app.route("/api/dash/check/staff/user/perms/")
async def send_user_persm_staff():
    users = load_data("json/staff_users.json")
    return users


@app.route("/")
async def hello():
    return await load_homepage()


# noinspection PyUnresolvedReferences
@app.route("/api/check_api_key", methods=["GET"])
async def check_apikey():
    id = request.args.get("requestid")
    return await check_api_key(id=id)


@app.route("/chatfilterinfo")
async def show_info():
    id = request.args.get("requestid")
    return await load_chatfilterrequest_info(bot=bot, id=id)


@app.route("/userinfo")
async def userinfo():
    id = request.args.get("idInput")
    return await load_user_info(bot=bot, id=id)


@app.route("/welcome_img/<filename>")
async def serve_welcome_image(filename):
    return await send_from_directory(app.config["welcome_img_folder"], filename)


@app.route("/v1/create-banner", methods=["POST"])
async def create_banner():
    data = request.json
    return await create_welcome_banner(data=data)


@app.route("/v1/chatfilter_event_data", methods=["POST"])
async def chatfilter_event_data():
    data = request.json
    return await get_chatfilter_data(data=data)


@app.errorhandler(404)
async def page_not_found(e):  # noqa
    return await load_error_page()


# ****************************************************************************************************************
logger.info("Quart is up and running!")
logger.waiting("Waiting for bot to login...")


@bot.event
async def on_ready():
    logger.info("Logging in as {0.user}".format(bot))
    logger.info("Bot Version:" + config["BOT"]["version"])
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching, name="dem Server beim Starten zu..."
        )
    )
    try:
        if not hasattr(bot, "synced"):
            bot.synced = True
            await bot.tree.sync()
            logger.info("Bot synced with discord!")
        else:
            logger.info("Sync skipped. (No changes)")
        logger.info(f"Bot started with {bot.shard_count} shards!")
        await bot.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.playing,
                name=f"on {len(bot.guilds)} Worlds! - v{config["BOT"]["version"]}",
            )
        )

    except Exception as e:  # noqa
        await bot.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name=f"die Crash logs durch... - Server start Fehler",
            )
        )
        logger.error("ERROR SYNCING! " + str(e))
    bot.loop.create_task(node_connet())  # noqa
    check_actions.start()
    global booted
    booted = True

    logger.success("ready!")


@bot.event
async def on_shard_ready(shard_id):
    logger.info(f"Shard {shard_id} ready!")


async def node_connet():
    try:
        logger.waiting("Connecting to Lavalink node...")
        node = wavelink.Node(
            uri="http://lavalink.avocloud.net:2333",
            resume_timeout=80,
            password="jompo",
            client=bot,
            retries=3,
            identifier="SoundNode1",
        )
        await wavelink.Pool.connect(nodes=[node], client=bot)
        logger.success("Successfully connected to Lavalink!")

    except TimeoutError:
        logger.error("Timeout connecting to Node")
    except Exception as e:
        logger.error(f"Unknown error: {e}")


class GuidelinesButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Button(
                style=discord.ButtonStyle.url,
                label="Guidelines",
                url="https://pyropixle.com/gtc/",
            )
        )


class DiscordButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Button(
                style=discord.ButtonStyle.url,
                label="Discord",
                url="https://link.pyropixle.com/discord/",
            )
        )


class InviteButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Button(
                style=discord.ButtonStyle.url,
                label="Add me",
                url="https://link.pyropixle.com/baxi/",
            )
        )


class InviteUndWebButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Button(
                style=discord.ButtonStyle.url,
                label="Add me",
                url="https://link.pyropixle.com/baxi/",
            )
        )
        self.add_item(
            discord.ui.Button(
                style=discord.ButtonStyle.url,
                label="Website",
                url="https://pyropixle.com/",
            )
        )


class InviteUndWebUndDiscordButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Button(
                style=discord.ButtonStyle.url,
                label="Add me",
                url="https://link.pyropixle.com/baxi/",
            )
        )
        self.add_item(
            discord.ui.Button(
                style=discord.ButtonStyle.url,
                label="Website",
                url="https://pyropixle.com/",
            )
        )
        self.add_item(
            discord.ui.Button(
                style=discord.ButtonStyle.url,
                label="Discord",
                url="https://link.pyropixle.com/discord/",
            )
        )
        self.add_item(
            discord.ui.Button(
                style=discord.ButtonStyle.url,
                label="Privacy",
                url="https://pyropixle.com/privacy/",
            )
        )
        self.add_item(
            discord.ui.Button(
                style=discord.ButtonStyle.url,
                label="GTC",
                url="https://pyropixle.com/gtc/",
            )
        )


# noinspection SpellCheckingInspection
class InviteUndWebUndDiscordundDocsButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Button(
                style=discord.ButtonStyle.url,
                label="Add me",
                url="https://link.pyropixle.com/baxi/",
            )
        )
        self.add_item(
            discord.ui.Button(
                style=discord.ButtonStyle.url,
                label="Website",
                url="https://pyropixle.com/",
            )
        )
        self.add_item(
            discord.ui.Button(
                style=discord.ButtonStyle.url,
                label="Discord",
                url="https://link.pyropixle.com/discord/",
            )
        )
        self.add_item(
            discord.ui.Button(
                style=discord.ButtonStyle.url,
                label="Docs",
                url="https://docs.pyropixle.com/",
            )
        )
        self.add_item(
            discord.ui.Button(
                style=discord.ButtonStyle.url,
                label="Privacy",
                url="https://pyropixle.com/privacy/",
            )
        )
        self.add_item(
            discord.ui.Button(
                style=discord.ButtonStyle.url,
                label="GTC",
                url="https://pyropixle.com/gtc/",
            )
        )


class TicketMenuButtons(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        style=discord.ButtonStyle.green,
        custom_id="FrageButton",
        emoji="<:question:1244724909481922791>",
    )
    async def FrageButton(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):  # noqa
        await question_button(interaction=interaction)

    @discord.ui.button(
        custom_id="melden_button",
        style=discord.ButtonStyle.red,
        emoji="<:mod:1244728840803192933>",
    )
    async def melden_button(
        self, interaction: Interaction, Button: discord.ui.Button
    ):  # noqa
        await report_button(interaction=interaction)

    @discord.ui.button(
        custom_id="bewerben_button",
        style=discord.ButtonStyle.blurple,
        emoji="<:person_wave:1244725776671314031>",
    )
    async def bewerben_button(
        self, interaction: Interaction, Button: discord.ui.Button
    ):  # noqa
        await other_button(interaction=interaction)


class VerifyButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    # noinspection PyUnresolvedReferences
    @discord.ui.button(
        custom_id="verifybutton",
        style=discord.ButtonStyle.green,
        emoji="<:verify:1244723476825243718>",
    )
    async def verifybutton(
        self, interaction: Interaction, button: discord.ui.Button
    ):  # noqa
        await verify_button(interaction=interaction)


class BugReportOptions(discord.ui.View):  # noqa
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Button(
                label="Github",
                style=discord.ButtonStyle.url,
                url="https://github.com/rwolf2467/Baxi/issues",
            )
        )

    @discord.ui.button(
        label="InApp Formular",
        custom_id="report_form_inapp",
        style=discord.ButtonStyle.gray,
    )
    async def report_form_inapp_btn(
        self, interaction: discord.Interaction, Button: discord.ui.Button
    ):  # noqa
        await interaction.response.send_modal(BUGREPORT())  # noqa


# *********************************************************************************************************************
# EVENTS
# *********************************************************************************************************************


@bot.event
async def on_guild_join(guild: discord.Guild):
    await on_guild_join_event(guild=guild, bot=bot)


@bot.event
async def on_member_join(member: discord.Member):
    await on_member_join_event(member=member, bot=bot)


@app.route("/globalchat_img/<filename>")
async def serve_image(filename):
    return await send_from_directory(config["FLASK"]["global_img_folder"], filename)


@app.route("/globalchat_images/<filename>")
async def server_image_two(filename):
    return await send_from_directory(config["FLASK"]["global_img_folder"], filename)


@app.route("/_images_/<filename>")
async def server_image_general(filename):
    return await send_from_directory(config["FLASK"]["general_img_folder"], filename)


@bot.event
async def on_message(message: discord.Message):
    try:

        await log_action(
            message.guild.id, message.author.id, "message", action_counts=action_counts
        )

        if message.author.bot:
            return "Bot User"

        logger.working(
            f"Processing new message... U: {message.author.name}; S: {message.guild.name}; M: {message.content}"
        )

        settings_counting = load_data("json/countgame_data.json")
        settings_guessing = load_data("json/guessing.json")
        settings_suggestion = load_data("json/suggestion.json")

        message_api = await check_message_sec(message=message, bot=bot)
        user_api = await check_user_sec(user=message.author)

        logger.info(message_api)
        logger.info(user_api)

        if message_api["response"] != 0 or message_api["nsfw_server"]:
            logger.debug.info("CHATFILTER")
            await del_message(
                message=message, message_api=message_api, user_api=user_api
            )
            return

        if get_globalchat(message.guild.id, message.channel.id):
            logger.debug.info("GC")
            await handel_gc(
                booted=booted,
                emergency_mode=emergency_mode,
                message=message,
                user_api=user_api,
                bot=bot,
            )

        if emergency_mode:
            return 503

        if (
            str(message.guild.id) in settings_suggestion
            and message.channel.id
            in settings_suggestion[str(message.guild.id)]["channels"]
        ):
            logger.debug.info("Suggestion")
            await run_suggestion(message=message, booted=booted)

        elif str(message.guild.id) in settings_counting and int(
            settings_counting[str(message.guild.id)]["channel_id"]
        ) == int(
            message.channel.id
        ):  # noqa
            logger.debug.info("Counting")
            await run_counting(message=message, booted=booted)

        elif str(message.guild.id) in settings_guessing and int(
            message.channel.id
        ) == int(settings_guessing[str(message.guild.id)]["channel_id"]):
            logger.debug.info("Guessing")
            await run_guessing(message=message, booted=booted)
        else:
            logger.info("@on_message: OTHER")

        logger.success("Message processed!\n ")
    except Exception as e:
        logger.error("Error processing new message! - UNKNOWN")
        logger.error(str(e))
        return

    await bot.process_commands(message)


@bot.event
async def on_message_edit(before: discord.Message, after: discord.Message):
    await message_edit(before=before, after=after, bot=bot)


@bot.event
async def on_audit_log_entry_create(entry: discord.AuditLogEntry):
    await audit_log_entry(entry=entry, action_counts=action_counts)


@tasks.loop(seconds=int(config["ANTI_RAID"]["check_interval"]))
async def check_actions():
    await check_actions_antiraid(bot=bot, action_counts=action_counts)


@bot.tree.command(
    name="delete_gc_message", description="Delete a message sent in our global chat."
)
@app_commands.describe(msg_id="Custom Message ID")
async def delete_gc_message(interaction: Interaction, msg_id: str):
    await delete_gc_messages_cmd(bot=bot, interaction=interaction, msg_id=msg_id)


# *********************************************************************************************************************
# COMMANDS
# *********************************************************************************************************************


# Beginn help_command
@bot.tree.command(name="help", description="Helps you")
async def help_command(interaction: discord.Interaction):
    language = load_language_model(interaction.guild.id)
    embed = discord.Embed(title=language["help_title"], color=0x7289DA)
    embed.add_field(
        name=language["help_title_1"],
        value=language["help_description_1"],
        inline=False,
    )
    embed.add_field(
        name=language["help_title_2"],
        value=language["help_description_2"],
        inline=False,
    )
    embed.add_field(
        name=language["help_title_4"],
        value=language["help_description_4"],
        inline=False,
    )
    embed.add_field(
        name=language["help_title_3"],
        value=language["help_description_3"],
        inline=False,
    )

    handle_log_event(
        interaction.command.name.upper(),
        interaction.guild.name,
        interaction.user.name.upper(),
    )
    await interaction.response.send_message(
        embed=embed, view=InviteUndWebUndDiscordundDocsButton()
    )  # noqa


@bot.tree.command(
    name="rules", description="Shows you the rules of the bot / global chat"
)
async def rules(interaction: discord.Interaction):
    try:
        language = load_language_model(interaction.guild.id)
        embed = discord.Embed(title=language["bot_rules_title"], color=embedColor)
        embed.add_field(
            name=f'{language["bot_rule_note"]}', value="\u200b", inline=False
        )
        embed.add_field(name=f'{language["bot_rule_1"]}', value="\u200b", inline=False)

        embed.set_footer(text=language["bot_rules_footer"])
        embed.set_thumbnail(url=icons_url + "rules.png")  # book_icon

        handle_log_event(
            interaction.command.name.upper(),
            interaction.guild.name,
            interaction.user.name.upper(),
        )

        await interaction.response.send_message(
            embed=embed, ephemeral=True, view=GuidelinesButton()
        )  # noqa
    except Exception as e:
        await interaction.channel.send(str(e))


# Ende Rules


@bot.tree.command(name="bot-stats", description="Shows the stats of the bot.")
async def stats(interaction: discord.Interaction):
    try:
        await interaction.response.defer()
        language = load_language_model(interaction.guild.id)
        guild_count = len(bot.guilds)
        user_count = sum(len(guild.members) for guild in bot.guilds)
        embed = discord.Embed(
            title=language["bot_stats_title"],
            description=language["bot_stats_users"]
            + str(user_count)
            + "\n"
            + language["bot_stats_servers"]
            + str(guild_count),
            color=embedColor,
        )
        await interaction.edit_original_response(embed=embed)
    except Exception as e:
        logger.error(str(e))


# Beginn userstatus
# noinspection PyUnresolvedReferences,PyShadowingBuiltins
@bot.tree.command(name="get", description="Show you specific information.")
@app_commands.describe(id="ID")
@app_commands.choices(
    option=[
        app_commands.Choice(name="Message", value=1),
        app_commands.Choice(name="User", value=2),
    ]
)
async def userstatus(interaction: discord.Interaction, option: int, id: str):
    try:
        language = load_language_model(interaction.guild.id)
        if option == 2:
            user_check_request = check_api.check_user(int(id))

            userFlagged:bool = user_check_request.flagged
            userFlaggedReason = user_check_request.reason
            user = bot.get_user(int(id))
            embed = discord.Embed(
                title=language["security_title"],
                description=f"{language['userstatus_description']} {user.mention} ({user.name}):",
                color=discord.Color.random(),
            )
            gbaned = load_data("json/banned_users.json")
            if str(interaction.user.id) in gbaned:
                embed.add_field(name="System Ban:", value="> Yes")
            else:
                embed.add_field(name="System Ban:", value="> No")

            if userFlagged:
                reason = userFlaggedReason

                embed.add_field(
                    name=f"{language['userstatus_dangerous_tag']}: ", value=userFlagged
                )
                embed.add_field(
                    name=f"{language['userstatus_reason_tag']}: ", value="> " + reason
                )
                embed.add_field(
                    name=f"{language['userstatus_time_tag']}: ",
                    value="> " + str(datetime.datetime.now()),
                )
                embed.set_thumbnail(url=icons_url + "warn.png")
            else:
                embed.add_field(
                    name=f"{language['userstatus_dangerous_tag']}: ", value=userFlagged
                )
                embed.add_field(
                    name=f"{language['userstatus_time_tag']}: ",
                    value="> " + str(datetime.datetime.now()),
                )
                embed.set_thumbnail(url=icons_url + "shield-check.png")

            await interaction.response.send_message(embed=embed)  # noqa
            handle_log_event(
                interaction.command.name.upper(),
                interaction.guild.name,
                interaction.user.name.upper(),
            )

        elif option == 1:
            in_baxiDB: bool = False

            embed_search = discord.Embed(
                title=language["get_db_title"],
                description=language["get_db_searching"],
                color=embedColor,
            ).set_thumbnail(url=f"{icons_url}loading.gif")

            await interaction.response.send_message(embed=embed_search)
            await asyncio.sleep(2)

            data = load_data("json/chatfilterrequest.json")
            for key, entry in data.items():
                if (
                    id in entry["user"].lower()
                    or id in str(entry["userid"])
                    or id in entry["message"].lower()
                    or id in entry["server"].lower()
                    or id in str(entry["serverid"])
                    or id in str(entry["requestid"])
                ):
                    in_baxiDB = True

            embed_new = discord.Embed(
                title=language["get_db_title_new"],
                description=language["get_db_finish"].format(
                    baxidb=in_baxiDB
                ),
                color=embedColor,
            )

            await interaction.edit_original_response(embed=embed_new)

    except Exception as e:
        logger.error(str(e))


# noinspection PyUnresolvedReferences
@bot.tree.command(
    name="scan-server", description="Scan your server for dangerous users."
)
async def scanserver(interaction: discord.Interaction):
    language = load_language_model(interaction.guild.id)
    bypass = load_data("json/spamdb_bypass.json")

    if not booted:
        embed = discord.Embed(
            title=language["035_title"],
            description=f"{language['system_not_booted_error']}"
            "[PyroPixle System Status](https://status.pyropixle.com)",
        ).set_thumbnail(url=icons_url + "info.png")
        await interaction.response.send_message(embed=embed)
        return 503

    handle_log_event(
        interaction.command.name.upper(),
        interaction.guild.name,
        interaction.user.name.upper(),
    )
    gbaned = load_data("json/banned_users.json")
    if str(interaction.user.id) in gbaned:
        await interaction.response.send_message(embed=user_ban_embed(interaction.user))
        return

    if emergency_mode:
        await interaction.response.send_message(embed=lock_embed())
        return
    await interaction.response.defer()
    embed_scan = discord.Embed(
        title=language["security_title"],
        color=discord.Color.orange(),
        description=f"# {language['scan_server_scanning']}...",
    ).set_thumbnail(url=f"{icons_url}loading.gif")
    processes = await interaction.channel.send(embed=embed_scan)
    spammers = []
    scan_count = 0
    start_time = time.time()
    total_members = len(interaction.guild.members)

    async def check_member(member):
        nonlocal scan_count
        try:
            user_check_request = check_api.check_user(int(member.id))
            userFlagged = user_check_request.flagged
            userFlaggedReason = user_check_request.reason

            scan_count += 1
            if userFlagged:
                spammers.append(
                    "- "
                    + member.mention
                    + f"\n> {language['scan_server_reason_tag']}: "
                    + userFlaggedReason
                )
        except Exception as e:
            fail = f"{language['unknown_error']}\n> `{e}`"
            # noinspection PyShadowingNames
            embed = discord.Embed(
                title=language["security_title"],
                color=discord.Color.red(),
                description=f"> {fail}",
            )
            embed.set_thumbnail(url=icons_url + "warn.png")
            await interaction.edit_original_response(embed=embed)
            await processes.delete()
            raise e

    # noinspection PyShadowingNames
    tasks = [check_member(member) for member in interaction.guild.members]
    for index, task in enumerate(asyncio.as_completed(tasks)):
        await task  # Await each task to catch any exceptions

    end_time = time.time()
    scan_duration = end_time - start_time

    if spammers:
        spammers_list = "\n".join(spammers)
        embed = discord.Embed(
            title=language["security_title"], color=discord.Color.red()
        )
        embed.add_field(
            name=f'<:warn:1244734095888486462> {language["scan_server_found_spammers"]}',
            value=f"{len(spammers)} Spammer",
            inline=False,
        )
        embed.add_field(
            name=f'<:user:1244726847401492590>  {language["scan_server_list_title"]}',
            value=spammers_list,
            inline=False,
        )
        spammer_percentage = (len(spammers) / total_members) * 100
        embed.add_field(
            name=f'<:rocketlunch:1244729975899422783> {language["scan_server_spammer_percent_title"]}',
            value=f'{language["scan_server_spammer_percent"].format(num=f"{spammer_percentage:.2f}")}',
            inline=False,
        )
        embed.set_thumbnail(url=icons_url + "warn.png")
    else:
        embed = discord.Embed(
            title=language["security_title"], color=discord.Color.green()
        )
        embed.add_field(
            name=f'<:verify:1244723476825243718> {language["scan_server_found_spammers"]}',
            value=f'{language["scan_server_no_spammers"]}',
            inline=False,
        )
        embed.set_thumbnail(url=icons_url + "shield-check.png")

    embed.add_field(
        name=f'<:verify:1244723476825243718> {language["scan_server_checked_users_title"]}',
        value=f'{language["scan_server_user_count"].format(scan_count=scan_count)}',
        inline=False,
    )
    embed.add_field(
        name=f'<:clock:1244734378882629682> {language["scan_server_duration_title"]}',
        value=f'{scan_duration:.2f} {language["scan_server_seconds"]}',
        inline=False,
    )

    embed.set_footer(text=language["security_twinkle_ad"])

    await processes.edit(embed=embed)
    await interaction.delete_original_response()


# Ende Scanserver

# Beginn Feedback


class FeedbackModal(ui.Modal, title="Feedback"):
    titleM = ui.TextInput(
        label="Feedback title",
        placeholder="Title of your idea/feedback",
        style=discord.TextStyle.short,
    )
    description = ui.TextInput(
        label="Description",
        placeholder="Describe your idea/feedback",
        style=discord.TextStyle.long,
        min_length=50,
    )

    async def on_submit(self, interaction: discord.Interaction):
        report_channel = bot.get_channel(1175817727873659021)
        embed = discord.Embed(
            title=self.title,
            description=f"**{self.titleM.label}:** *{self.titleM}*\n**{self.description.label}:** *{self.description}*\n **Benutzer:** *{interaction.user.mention}*",
            timestamp=datetime.datetime.now(),
            color=embedColor,
        )
        embed.set_thumbnail(url=icons_url + "bulb.png")  # light-bulb_icon
        embed.set_author(
            name=interaction.user.name, icon_url=interaction.user.avatar.url
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)  # noqa
        await report_channel.send(embed=embed)


@bot.tree.command(name="feedback", description="Give us your feedback")
async def feedback(interaction: discord.Interaction):
    gbaned = load_data("json/banned_users.json")
    if str(interaction.user.id) in gbaned:
        await interaction.response.send_message(
            embed=user_ban_embed(interaction.user)
        )  # noqa
        return

    if emergency_mode:
        await interaction.response.send_message(embed=lock_embed())  # noqa
        return
    await interaction.response.send_modal(FeedbackModal())  # noqa
    handle_log_event(
        interaction.command.name.upper(),
        interaction.guild.name,
        interaction.user.name.upper(),
    )


# Beginn report


class REPORTMODAL(ui.Modal, title="Report User"):
    messageID = ui.TextInput(
        label="MessageID",
        placeholder="Message ID (OPTIONAL)",
        style=discord.TextStyle.short,
        required=False,
        min_length=16,
        max_length=19,
    )
    userID = ui.TextInput(
        label="UserID",
        placeholder="ID of the accused person",
        style=discord.TextStyle.short,
        max_length=18,
        min_length=17,
        required=True,
    )
    anmerkung = ui.TextInput(
        label="Remarks",
        placeholder="Do you have any comments that are important to us??",
        style=discord.TextStyle.long,
        required=False,
    )
    image_input = ui.TextInput(
        label="Image",
        placeholder="Link to an image (OPTIONAL)",
        style=discord.TextStyle.short,
        required=False,
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            report_channel = bot.get_channel(1175817607484543076)

            try:
                message = await interaction.channel.fetch_message(
                    self.messageID
                )  # noqa
            except discord.NotFound:
                if self.messageID is not None:
                    await interaction.response.send_message(
                        "The specified message ID could not be found.", ephemeral=True
                    )  # noqa
                    return
                else:
                    self.messageID = "NO INFO"

            try:
                user = await bot.fetch_user(self.userID)  # noqa
            except discord.NotFound:
                await interaction.response.send_message(
                    "The specified user ID could not be found.", ephemeral=True
                )  # noqa
                return

            try:
                embed = discord.Embed(
                    title=self.title,
                    description=f"**{self.messageID.label}:** *{self.messageID}*\n"  # noqa
                    f"**MSG:** ```{message.content}```\n"  # noqa
                    f"**{self.userID.label}:** *{self.userID} - {user.name}*\n"
                    f"**Guild Name / ID:** *{interaction.guild.name} / {interaction.guild.id}*\n"
                    f"**{self.anmerkung.label}:** {self.anmerkung}",
                    timestamp=datetime.datetime.now(),
                    color=embedColor,
                )
                embed.set_thumbnail(url=icons_url + "bug.png")
                embed.set_image(url=self.image_input)
                embed.set_author(
                    name=interaction.user.name, icon_url=interaction.user.avatar.url
                )

                await interaction.response.send_message(
                    embed=embed, ephemeral=True
                )  # noqa
                await report_channel.send(embed=embed)

            except discord.errors.HTTPException:
                if self.image_input is not None:
                    # noinspection PyUnresolvedReferences
                    await interaction.response.send_message(
                        "The image link provided is not valid!", ephemeral=True
                    )  # noqa
        except Exception as e:  # noqa
            logger.error(str(e))


class BUGREPORT(ui.Modal, title=" Report an error"):
    function_input = ui.TextInput(
        label="Command/Task",
        placeholder="Name of the command or task - e.g. Globalchat",
        style=discord.TextStyle.short,
        required=True,
    )
    what_input = ui.TextInput(
        label="What happened?",
        placeholder="What happened that made you have to report the bug? short form",
        style=discord.TextStyle.short,
        max_length=15,
        required=True,
    )
    besch_input = ui.TextInput(
        label="Description",  # noqa
        placeholder="Give us more information about the problem. Does the bot have all the required permissions?",
        style=discord.TextStyle.long,
        min_length=20,
        required=True,
    )
    image_input = ui.TextInput(
        label="Picture",
        placeholder="Link to an image",
        style=discord.TextStyle.short,
        min_length=5,
        required=False,
    )

    async def on_submit(self, interaction: discord.Interaction):
        report_channel = bot.get_channel(1175817607484543076)

        try:
            embed = discord.Embed(
                title=self.title,
                description=f"**{self.function_input.label}:** *{self.function_input}*\n"
                f"**{self.what_input.label}:** *{self.what_input}*\n"
                f"**{self.besch_input.label}:** {self.besch_input}",
                timestamp=datetime.datetime.now(),
                color=embedColor,
            )
            embed.set_thumbnail(url=icons_url + "bug.png")
            embed.set_image(url=self.image_input)
            embed.set_author(
                name=interaction.user.name, icon_url=interaction.user.avatar.url
            )

            await interaction.response.send_message(embed=embed, ephemeral=True)  # noqa
            await report_channel.send(embed=embed)

        except discord.errors.HTTPException:
            await interaction.response.send_message(
                "Invalid image Link", ephemeral=True  # noqa
            )


@bot.tree.command(name="report", description="Report things")
@app_commands.choices(
    option=[
        app_commands.Choice(name="Bug", value=1),
        app_commands.Choice(name="User", value=2),
    ]
)
async def report(interaction: Interaction, option: int):
    if emergency_mode:
        await interaction.response.send_message(embed=lock_embed())  # noqa
        return
    handle_log_event(
        interaction.command.name.upper(),
        interaction.guild.name,
        interaction.user.name.upper(),
    )

    if option == 1:
        await interaction.response.send_message(  # noqa
            embed=discord.Embed(
                title="Report",
                description="Where would you like to report the error?\n"  # noqa
                "> 1.) On GitHub [Preferred]\n"
                "> 2.) Discord InApp Form",
                color=embedColor,
            ),
            view=BugReportOptions(),
            ephemeral=True,
        )

    elif option == 2:
        await interaction.response.send_modal(REPORTMODAL())  # noqa
        handle_log_event(
            interaction.command.name.upper(),
            interaction.guild.name,
            interaction.user.name.upper(),
        )


# Ende Report


# ********************************************************************************************************
# Manage Commands


@bot.tree.command(name="privacy", description="Privacy related Server settings.")
@app_commands.choices(
    setting=[app_commands.Choice(name="image_processing", value="image_processing")]
)
async def privacy(interaction: discord.Interaction, setting: str):
    try:
        settings = load_data("json/privacy_image.json")
        handle_log_event(
            f"{interaction.command.name.upper()} - {settings} - {setting}",
            interaction.guild.name,
            interaction.user.name.upper(),
        )
        gbaned = load_data("json/banned_users.json")
        language = load_language_model(interaction.guild.id)
        if str(interaction.user.id) in gbaned:
            await interaction.response.send_message(
                embed=user_ban_embed(interaction.user)
            )  # noqa
            return

        if emergency_mode:
            await interaction.response.send_message(embed=lock_embed())  # noqa
            return
        if not interaction.user.guild_permissions.manage_guild:
            embed = discord.Embed(
                title=language["security_title"],
                description=f"{language['permission_denied']}\n" "> Manage Guild",
                color=discord.Color.red(),
            )
            await interaction.response.send_message(embed=embed)  # noqa
            return

        if setting == "image_processing":
            if int(interaction.guild.id) in settings:
                settings.append(int(interaction.guild.id))
                save_data("json/privacy_image.json", settings)
                embed = discord.Embed(
                    title=language["privacy_title"],
                    description=language["privacy_img_enable"],
                    color=embedColor,
                ).set_thumbnail(url=icons_url + "mod.png")
                await interaction.response.send_message(embed=embed)
            else:
                settings.remove(int(interaction.guild.id))
                save_data("json/privacy_image.json", settings)
                embed = discord.Embed(
                    title=language["privacy_title"],
                    description=language["privacy_img_disable"],
                    color=embedColor,
                ).set_thumbnail(url=icons_url + "mod.png")
                await interaction.response.send_message(embed=embed)
    except Exception as e:
        logger.error(str(e))


# noinspection PyDunderSlots
@bot.tree.command(name="enable", description="Activate a System on your Server.")
async def enable_system(interaction: Interaction):
    await interaction.response.send_message(
        "Due to changes to the storage system and the switch to the webpannel, settings by command are not permitted as the commands are outdated. We ask for a little patience!\n> https://baxi.pyropixle.com"
    )
    return


@bot.tree.command(name="disable", description="Deactivate a System on your Server.")
async def disable_system(interaction: Interaction):
    await interaction.response.send_message(
        "Due to changes to the storage system and the switch to the webpannel, settings by command are not permitted as the commands are outdated. We ask for a little patience!\n> https://baxi.pyropixle.com"
    )
    return


@bot.tree.command(
    name="set_language", description="Set the language of baxi on this server."
)
@app_commands.choices(
    option=[
        app_commands.Choice(name="Englisch", value="en"),
        app_commands.Choice(name="Deutsch", value="de"),
        app_commands.Choice(name="Norwegian", value="norsk"),
        app_commands.Choice(name="French", value="fr"),
        app_commands.Choice(name="Russisch", value="ru"),
    ]
)
async def set_language(interaction: Interaction, option: str):
    handle_log_event(
        interaction.command.name.upper(),
        interaction.guild.name,
        interaction.user.name.upper(),
    )
    language = load_language_model(interaction.guild.id)

    language_settings = load_data("json/language.json")
    gbaned = load_data("json/banned_users.json")
    load_data("json/ticketdata,json")
    if str(interaction.user.id) in gbaned:
        await interaction.response.send_message(
            embed=user_ban_embed(interaction.user)
        )  # noqa
        return

    if emergency_mode:
        await interaction.response.send_message(embed=lock_embed())  # noqa
        return
    if not interaction.user.guild_permissions.manage_guild:
        embed = discord.Embed(
            title=language["security_title"],
            description=f"{language['permission_denied']}\n" "> Manage Guild",
            color=discord.Color.red(),
        )
        await interaction.response.send_message(embed=embed)  # noqa
        return

    if option == "en" or option == "de" or option == "fr" or option == "norsk":
        language_settings[str(interaction.guild.id)] = {"language": option}
        save_data("json/language.json", language_settings)

        await interaction.response.send_message(
            language["set_language_success"].format(language=option)
        )  # noqa

    else:
        await interaction.response.send_message(
            "Sorry, currently only the following languages are supported: \n-  English\n-  Französisch\n-  Norwegian\n-  German\n\nBe patient while we work on creating more language models."
        )  # noqa
        return


# ********************************************************************************************************
# Server Admin commands


# noinspection PyDunderSlots,PyUnresolvedReferences
@bot.tree.command(name="embed-it", description="Create a Embed.")
@app_commands.describe(author="Author")
@app_commands.describe(author_url="Author Icon")
@app_commands.describe(title="Title")
@app_commands.describe(message="Message")
@app_commands.describe(thumbnail_url="Thumbnail URL")
@app_commands.describe(footer="Footer")
@app_commands.describe(footer_url="Footer Icon")
@app_commands.describe(image_url="Image URL")
@app_commands.describe(color="Color")
@app_commands.choices(
    color=[
        app_commands.Choice(name="Default", value="default"),
        app_commands.Choice(name="Blurple", value="blurple"),
        app_commands.Choice(name="Grey", value="grey"),
        app_commands.Choice(name="Green", value="green"),
        app_commands.Choice(name="Gold", value="gold"),
        app_commands.Choice(name="Magenta", value="magenta"),
        app_commands.Choice(name="Blue", value="blue"),
        app_commands.Choice(name="Red", value="red"),
    ]
)
async def embed_it(
    interaction: discord.Interaction,
    title: str,
    message: str,
    author: str = None,
    author_url: str = None,
    thumbnail_url: str = None,
    footer: str = None,
    footer_url: str = None,
    image_url: str = None,
    color: str = None,
):
    try:
        handle_log_event(
            interaction.command.name.upper(),
            interaction.guild.name,
            interaction.user.name.upper(),
        )
        language = load_language_model(interaction.guild.id)
        gbaned = load_data("json/banned_users.json")
        if str(interaction.user.id) in gbaned:
            await interaction.response.send_message(
                embed=user_ban_embed(interaction.user)
            )  # noqa
            return

        if emergency_mode:
            await interaction.response.send_message(embed=lock_embed())  # noqa
            return
        if not interaction.user.guild_permissions.manage_messages:
            embed = discord.Embed(
                title=language["security_title"],
                description=f"{language['permission_denied']}\n" "> Manage Messages",
                color=discord.Color.red(),
            )
            await interaction.response.send_message(embed=embed)  # noqa
            return

        message = message.replace(";", "\n")

        embed = discord.Embed(title=title, description=message)
        if author is not None:
            embed.set_author(name=author, url=author_url)

        if footer is not None:
            embed.set_footer(text=footer, icon_url=footer_url)

        if image_url is not None:
            embed.set_image(url=image_url)

        if thumbnail_url is not None:
            embed.set_thumbnail(url=thumbnail_url)

        if color is not None:
            if color == "default":
                embed.color = discord.Color.default()
            elif color == "blurple":
                embed.color = discord.Color.purple()
            elif color == "grey":
                embed.color = discord.Color.light_gray()
            elif color == "red":
                embed.color = discord.Color.red()
            elif color == "green":
                embed.color = discord.Color.green()
            elif color == "gold":
                embed.color = discord.Color.gold()
            elif color == "magenta":
                embed.color = discord.Color.magenta()
            elif color == "blue":
                embed.color = discord.Color.blue()
            elif color == "red":
                embed.color = discord.Color.red()

        await interaction.channel.send(embed=embed)
    except Exception as e:
        logger.error(str(e))


@bot.tree.command(name="clear", description="Delete multiple messages.")
@app_commands.describe(amount="Number of messages")
async def clear(interaction: Interaction, amount: float):
    handle_log_event(
        interaction.command.name.upper(),
        interaction.guild.name,
        interaction.user.name.upper(),
    )
    language = load_language_model(interaction.guild.id)

    gbaned = load_data("json/banned_users.json")
    if str(interaction.user.id) in gbaned:
        await interaction.response.send_message(
            embed=user_ban_embed(interaction.user)
        )  # noqa
        return

    if emergency_mode:
        await interaction.response.send_message(embed=lock_embed())  # noqa
        return
    if not interaction.user.guild_permissions.manage_messages:
        embed = discord.Embed(
            title=language["security_title"],
            description=f"{language['permission_denied']}\n" "> Manage Messages",
            color=discord.Color.red(),
        )
        await interaction.response.send_message(embed=embed)  # noqa
        return

    await interaction.response.send_message("...")  # noqa
    await interaction.channel.purge(
        limit=int(amount + 1), check=lambda msg: not msg.pinned
    )
    embed = discord.Embed(
        title=language["delete_title"],
        description=f"{interaction.user.mention}! **{int(amount)}** {language['delete_success']}",
        color=embedColor,
    ).set_thumbnail(url=icons_url + "trash.png")

    await interaction.channel.send(embed=embed)  # noqa


@bot.tree.command(name="ban", description="Ban users from the server.")
@app_commands.describe(member="User")
@app_commands.describe(reason="Reason")
async def bann(interaction: Interaction, member: discord.User, reason: str):
    handle_log_event(
        interaction.command.name.upper(),
        interaction.guild.name,
        interaction.user.name.upper(),
    )
    language = load_language_model(interaction.guild.id)

    gbaned = load_data("json/banned_users.json")
    if str(interaction.user.id) in gbaned:
        await interaction.response.send_message(
            embed=user_ban_embed(interaction.user)
        )  # noqa
        return

    if emergency_mode:
        await interaction.response.send_message(embed=lock_embed())  # noqa
        return
    if not interaction.user.guild_permissions.ban_members:
        embed = discord.Embed(
            title=language["security_title"],
            description=f"{language['permission_denied']}\n" "> Ban Members",
            color=discord.Color.red(),
        )
        await interaction.response.send_message(embed=embed)  # noqa
        return

    await interaction.response.defer()  # noqa
    await interaction.guild.get_member(int(member.id)).ban(reason=reason)
    embed = discord.Embed(
        title=language["security_title"],
        description=f"{language['ban_success']}\n"
        f"> {language['reason_tag']}: " + str(reason),
        color=embedColor,
    ).set_thumbnail(url=icons_url + "ban.png")
    try:
        await interaction.guild.get_member(int(member.id)).send(
            embed=discord.Embed(
                title="Ban",
                description=f"You have been banned from the server {interaction.guild.name} with the following reason: {reason}",
                color=embedColor,
            ).set_thumbnail(url=icons_url + "ban.png")
        )
    except:
        pass
    await interaction.edit_original_response(embed=embed)


@bot.tree.command(name="kick", description="Kick users from the server.")
@app_commands.describe(member="User")
@app_commands.describe(reason="Reason")
async def kick(interaction: Interaction, member: discord.User, reason: str):
    handle_log_event(
        interaction.command.name.upper(),
        interaction.guild.name,
        interaction.user.name.upper(),
    )
    language = load_language_model(interaction.guild.id)

    gbaned = load_data("json/banned_users.json")
    if str(interaction.user.id) in gbaned:
        await interaction.response.send_message(
            embed=user_ban_embed(interaction.user)
        )  # noqa
        return

    if emergency_mode:
        await interaction.response.send_message(embed=lock_embed())  # noqa
        return
    if not interaction.user.guild_permissions.kick_members:
        embed = discord.Embed(
            title=language["security_title"],
            description=f"{language['permission_denied']}\n" "> Kick Members",
            color=discord.Color.red(),
        )
        await interaction.response.send_message(embed=embed)  # noqa
        return

    await interaction.response.defer()  # noqa
    await interaction.guild.get_member(int(member.id)).kick(reason=reason)
    embed = discord.Embed(
        title=language["security_title"],
        description=f"{language['kick_success']}\n"
        f"> {language['reason_tag']}: " + str(reason),
        color=embedColor,
    ).set_thumbnail(url=icons_url + "ban.png")

    try:
        await interaction.guild.get_member(int(member.id)).send(
            embed=discord.Embed(
                title="Kick",
                description=f"You have been kicked from the server {interaction.guild.name} with the following reason: {reason}",
                color=embedColor,
            ).set_thumbnail(url=icons_url + "ban.png")
        )
    except:
        pass
    await interaction.edit_original_response(embed=embed)


@bot.tree.command(
    name="invite_history", description="Shows you the History of your Servers Invites."
)
async def invite_history(interaction: Interaction):
    language = load_language_model(interaction.guild.id)

    gbaned = load_data("json/banned_users.json")
    if str(interaction.user.id) in gbaned:
        await interaction.response.send_message(
            embed=user_ban_embed(interaction.user)
        )  # noqa
        return

    if emergency_mode:
        await interaction.response.send_message(embed=lock_embed())  # noqa
        return
    if not interaction.user.guild_permissions.kick_members:
        embed = discord.Embed(
            title=language["security_title"],
            description=f"{language['permission_denied']}\n" "> Kick Members",
            color=discord.Color.red(),
        )
        await interaction.response.send_message(embed=embed)  # noqa
        return
    handle_log_event(
        interaction.command.name.upper(),
        interaction.guild.name,
        interaction.user.name.upper(),
    )

    invites = await interaction.guild.invites()
    await interaction.response.defer()
    if not invites:
        await interaction.edit_original_response(
            content=language["invite_history_empty"]
        )

    embed = discord.Embed(title=language["invite_history_title"], color=embedColor)

    for invite in invites:
        embed.add_field(
            name=f"{language['invite_history_1']} {invite.inviter}",
            value=(
                f"{language['invite_history_2']}: {invite.url}\n"
                f"{language['invite_history_3']}: {invite.inviter}\n"
                f"{language['invite_history_4']}: {invite.created_at}\n"
                f"{language['invite_history_5']}: {invite.uses}"
            ),
            inline=False,
        )
    await interaction.edit_original_response(content=None, embed=embed)
    embed.clear_fields()


# ********************************************************************************************************


@bot.tree.command(name="hug", description="Hug someone.")
@app_commands.describe(user="User")
async def hug_command(interaction: Interaction, user: discord.User):
    handle_log_event(
        interaction.command.name.upper(),
        interaction.guild.name,
        interaction.user.name.upper(),
    )
    language = load_language_model(interaction.guild.id)

    gbaned = load_data("json/banned_users.json")
    if str(interaction.user.id) in gbaned:
        await interaction.response.send_message(
            embed=user_ban_embed(interaction.user)
        )  # noqa
        return

    if emergency_mode:
        await interaction.response.send_message(embed=lock_embed())  # noqa
        return

    await interaction.response.send_message(
        embed=discord.Embed(
            title=language["hug_title"],  # noqa
            description=f"**{language['hug_text'].format(u1=interaction.user.mention, u2=user.mention)}!**\n"
            f"> {random.choice(language['hug_random_text'])}",
            color=embedColor,
        ).set_thumbnail(url=icons_url + "heart.png")
    )


@bot.tree.command(name="coolrate", description="Shows you your coolness score.")
@app_commands.describe(user="User")
async def coolrate_command(interaction: Interaction, user: discord.User):
    handle_log_event(
        interaction.command.name.upper(),
        interaction.guild.name,
        interaction.user.name.upper(),
    )
    language = load_language_model(interaction.guild.id)

    gbaned = load_data("json/banned_users.json")
    if str(interaction.user.id) in gbaned:
        await interaction.response.send_message(
            embed=user_ban_embed(interaction.user)
        )  # noqa
        return

    if emergency_mode:
        await interaction.response.send_message(embed=lock_embed())  # noqa
        return

    await interaction.response.send_message(
        embed=discord.Embed(
            title=language["cool_title"],  # noqa
            description=f"**{language['cool_text'].format(user=user.mention, random=random.randint(-15, 115))}!**\n"
            f"> {random.choice(language['cool_random_text'])}",
            color=embedColor,
        ).set_thumbnail(url=icons_url + "event.png")
    )


@bot.tree.command(name="fight", description="Fight someone.")
@app_commands.describe(opponent1="opponent")
async def fight(interaction: Interaction, opponent1: discord.User):
    handle_log_event(
        interaction.command.name.upper(),
        interaction.guild.name,
        interaction.user.name.upper(),
    )
    language = load_language_model(interaction.guild.id)

    gbaned = load_data("json/banned_users.json")
    if str(interaction.user.id) in gbaned:
        await interaction.response.send_message(
            embed=user_ban_embed(interaction.user)
        )  # noqa
        return

    if emergency_mode:
        await interaction.response.send_message(embed=lock_embed())  # noqa
        return

    users = [opponent1, interaction.user]

    embed_kampf_live = discord.Embed(
        title=language["fight_title"], color=embedColor
    ).set_thumbnail(url=icons_url + "kicking.png")

    await interaction.response.send_message(  # noqa
        content=language["fight_start_message"].format(
            u1=interaction.user.mention, u2=opponent1.mention
        ),  # noqa
        embed=embed_kampf_live,
    )  # noqa

    for _ in range(random.randint(4, 6)):
        for user in users:
            action = random.choice(language["fight_actions"])
            embed_kampf_live.description = str(action.format(user.mention))
            await interaction.edit_original_response(embed=embed_kampf_live)
            await asyncio.sleep(random.randint(3, 6))

    winner = random.choice(users)
    loser = random.choice(users)
    while loser == winner:
        loser = random.choice(users)

    # Embed erstellen
    embed = discord.Embed(
        title=language["fight_title"],
        description=language["fight_final_message"].format(
            winner=winner.mention, loser=loser.mention
        ),
        color=embedColor,
    ).set_thumbnail(url=icons_url + "kicking.png")

    # Nachricht senden
    await interaction.edit_original_response(embed=embed, content=None)


@bot.tree.command(name="loverate", description="See how well you fit with someone.")
@app_commands.describe(user="User")
@app_commands.describe(user2="User2")
async def loverate(interaction: Interaction, user: discord.User, user2: discord.User):
    handle_log_event(
        interaction.command.name.upper(),
        interaction.guild.name,
        interaction.user.name.upper(),
    )
    language = load_language_model(interaction.guild.id)

    gbaned = load_data("json/banned_users.json")
    if str(interaction.user.id) in gbaned:
        await interaction.response.send_message(
            embed=user_ban_embed(interaction.user)
        )  # noqa
        return

    if emergency_mode:
        await interaction.response.send_message(embed=lock_embed())  # noqa
        return

    await interaction.response.send_message(
        embed=discord.Embed(
            title=language["love_title"],  # noqa
            description=f"{language['love_text'].format(user=user.mention, user2=user2.mention, random=random.randint(-15, 150))}\n"
            f"> {random.choice(language['love_random_text'])}",
            color=embedColor,
        ).set_thumbnail(url=icons_url + "heart.png")
    )


# ********************************************************************************************************


async def on_wavelink_track_start(payload: wavelink.TrackStartEventPayload) -> None:
    player: wavelink.Player | None = payload.player
    if not player:
        # Handle edge cases...
        return

    original: wavelink.Playable | None = payload.original
    track: wavelink.Playable = payload.track

    embed: discord.Embed = discord.Embed(title="Now Playing")
    embed.description = f"**{track.title}** by `{track.author}`"

    if track.artwork:
        embed.set_image(url=track.artwork)

    if original and original.recommended:
        embed.description += f"\n\n`This track was recommended via {track.source}`"

    if track.album.name:
        embed.add_field(name="Album", value=track.album.name)

    await player.home.send(embed=embed)


@bot.tree.command(name="music", description="Options for the music system")
@app_commands.choices(
    operation=[
        app_commands.Choice(name="play", value="play"),
        app_commands.Choice(name="leave", value="leave"),
        app_commands.Choice(name="pause / resume", value="pr"),
        app_commands.Choice(name="skip", value="skip"),
    ]
)
@app_commands.describe(search="Song name")
async def music(interaction: discord.Interaction, operation: str, search: str = None):
    try:
        handle_log_event(
            interaction.command.name.upper(),
            interaction.guild.name,
            interaction.user.name.upper(),
        )
        language = load_language_model(interaction.guild.id)
        gbaned = load_data("json/banned_users.json")
        if str(interaction.user.id) in gbaned:
            await interaction.response.send_message(
                embed=user_ban_embed(interaction.user)
            )  # noqa
            return

        if emergency_mode:
            await interaction.response.send_message(embed=lock_embed())  # noqa
            return
        if not booted:
            embed = discord.Embed(
                title=language["035_title"],
                description=f"{language['system_not_booted_error']}"
                "[PyroPixle System Status](https://status.pyropixle.com)",
            ).set_thumbnail(url=icons_url + "info.png")
            await interaction.channel.send(embed=embed)
            return 503
        if operation == "play":
            try:

                if not interaction.guild:
                    return
                await interaction.response.defer()

                player: wavelink.Player
                player = cast(wavelink.Player, interaction.guild.voice_client)

                if not player:
                    try:
                        player = await interaction.user.voice.channel.connect(
                            cls=wavelink.Player
                        )
                    except AttributeError:
                        await interaction.edit_original_response(
                            content=language["music_user_not_connected"]
                        )
                        return
                    except discord.ClientException:
                        await interaction.edit_original_response(content="ERROR")
                        return

                player.autoplay = wavelink.AutoPlayMode.enabled

                if not hasattr(player, "home"):
                    player.home = interaction.channel
                elif player.home != interaction.channel:
                    await interaction.edit_original_response(
                        content=language["music_user_not_connected"]
                    )
                    return
                tracks: wavelink.Search = await wavelink.Playable.search(
                    search, source=wavelink.TrackSource.SoundCloud
                )
                if not tracks:
                    await interaction.edit_original_response(
                        content=language["music_song_not_found"]
                    )
                    return

                if isinstance(tracks, wavelink.Playlist):
                    embed = (
                        discord.Embed(
                            title=tracks.author,
                            description=language["music_added_queue"].format(
                                tracks.name
                            )
                            + f".\n[SoundCloud]({tracks.url})",
                            color=embedColor,
                        )
                        .set_thumbnail(url=tracks.artwork)
                        .set_author(name="Baxi Music")
                    )

                else:
                    track: wavelink.Playable = tracks[0]
                    await player.queue.put_wait(track)
                    embed = (
                        discord.Embed(
                            title=track.author,
                            description=language["music_added_queue"].format(track)
                            + f".\n[SoundCloud]({track.uri})",
                            color=embedColor,
                        )
                        .set_thumbnail(url=track.artwork)
                        .set_author(name="Baxi Music")
                    )

                await interaction.edit_original_response(content=None, embed=embed)

                if not player.playing:
                    await player.play(player.queue.get(), volume=30)

            except Exception as e:
                await interaction.edit_original_response(content="ERROR: " + str(e))

        elif str(operation) == "skip":
            await interaction.response.defer()
            player: wavelink.Player = cast(
                wavelink.Player, interaction.guild.voice_client
            )
            if not player:
                return

            await player.skip(force=True)
            await interaction.edit_original_response(content=language["music_skipped"])

        elif str(operation) == "pr":
            await interaction.response.defer()
            player: wavelink.Player = cast(
                wavelink.Player, interaction.guild.voice_client
            )
            if not player:
                return

            await player.pause(not player.paused)
            await interaction.edit_original_response(content=language["music_success"])

        elif str(operation) == "leave":
            await interaction.response.defer(ephemeral=True)
            player: wavelink.Player = cast(
                wavelink.Player, interaction.guild.voice_client
            )
            if not player:
                return

            await player.disconnect()
            await interaction.edit_original_response(
                content=language["music_disconnected"]
            )

    except Exception as e:
        await interaction.response.send_message(str(e), ephemeral=True)


# ********************************************************************************************************


@bot.command(name="admin.uban")
async def admin_uban(interaction: discord.Message, uid: str, reason: str):
    gbaned = load_data("json/banned_users.json")
    if interaction.author.id not in botadmin:
        await interaction.reply(
            "Nice try! But you are not authorized to use this command!"
        )
        return
    try:
        user = await bot.fetch_user(int(uid))
    except discord.NotFound:
        await interaction.channel.send("Benutzer nicht gefunden!")
        return

    if str(user.id) not in gbaned:
        gbaned[str(user.id)] = {"reason": str(reason), "dm_sent": "0"}
        save_data("json/banned_users.json", gbaned)
        await interaction.channel.send(
            f"Erfolg! {user.name} wurde von allen Bot Systemen gebannt!"
        )
    else:
        del gbaned[str(user.id)]
        save_data("json/banned_users.json", gbaned)
        await interaction.channel.send(
            f"Erfolg! {user.name} wurde von allen Bot Systemen entbannt!"
        )


@bot.command(name="admin.save_messages")
async def save_messages(message: discord.Message, num_messages: int):
    try:
        messages = [
            message async for message in message.channel.history(limit=num_messages)
        ]
        server_name = message.guild.name
        date = datetime.date.today().strftime("%Y-%m-%d")
        # noinspection PyShadowingNames
        time = datetime.datetime.now().strftime("%H-%M-%S")
        filename = f"log/.logbot/{server_name}-{date}-{time}-log.txt"
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        # noinspection PyArgumentList
        with open(filename, "w", encoding="utf-8") as f:
            for message in messages:
                f.write(f"{message.author.name}: {message.clean_content}\n")
        file = discord.File(filename, filename)
        message = await message.channel.send(
            content=f"{num_messages} Nachrichten wurden gespeichert! Hier ist die Datei. Sie wurde ebenfalls unter `/log/.logbot/{server_name}-{date}-{time}-log.txt` gespeichert:",
            file=file,
        )
        await message.add_reaction("📝")
    except Exception as e:
        await message.channel.send(str(e))


@bot.command(name="admin.toggle_server_log")
async def admin_toggle_server_log(interaction: discord.Message, sid: str):
    servers = load_data("json/logged_servers.json")
    if interaction.author.id not in botadmin:  # Annahme: botadmin ist definiert
        await interaction.reply(
            "Nice try! But you are not authorized to use this command!"
        )
        return

    try:
        server_id = int(sid)
        server = await bot.fetch_guild(server_id)
    except:  # noqa
        await interaction.reply("Der Server wurde nicht gefunden!")
        return

    if server_id in servers:
        servers.remove(server_id)
        await interaction.reply(
            f"Die Server-Logging für Server {server.name} wurden deaktiviert."
        )
    else:
        servers.append(server_id)
        await interaction.reply(
            f"Die Server-Logging für Server {server.name} wurden aktiviert."
        )

    save_data("json/logged_servers.json", servers)


@bot.command(name="admin.lock_global_img")
async def lock_global_img(interaction: discord.Message, image_name: str):
    if interaction.author.id not in botadmin:  # Annahme: botadmin ist definiert
        await interaction.reply(
            "Nice try! But you are not authorized to use this command!"
        )
        return

    images_dir = os.path.join("static", "globalchat_img")

    # Überprüfe, ob das Verzeichnis existiert
    if not os.path.exists(images_dir):
        logger.error("The directory 'globalchat_img' does not exist.")
        return

    # Definiere den Pfad zum Bild, das ersetzt werden soll
    image_path = os.path.join(images_dir, image_name)

    # Überprüfe, ob das Bild existiert
    if not os.path.exists(image_path):
        logger.warn(f"The image '{image_name}' does not exist.")
        return

    # Definiere den Pfad zum locked.png-Bild
    locked_image_path = os.path.join("static", "locked.png")

    # Ersetze das Bild
    try:
        shutil.copyfile(locked_image_path, image_path)
        logger.success(
            f"The image '{image_name}' was successfully replaced with 'locked.png'."
        )
        await interaction.channel.send(
            f"The image '{image_name}' was successfully replaced with 'locked.png'."
        )
    except Exception as e:
        logger.error(f"Error replacing image: {e}")
        await interaction.channel.send(f"Error replacing image: {e}")


@bot.command(name="admin.announce")
async def admin_announce(interaction: discord.Message, *, content: str):
    if interaction.author.id not in botadmin:  # Annahme: botadmin ist definiert
        await interaction.reply(
            "Nice try! But you are not authorized to use this command!"
        )
        return

    news_channels = load_data("json/newschannel.json")
    servers = load_data("json/servers.json")

    embed = discord.Embed(
        title="Announcement", description=content, color=embedColor
    ).set_thumbnail(url=bot.user.avatar.url)

    for server in servers:
        guild_id = server["guildid"]
        channel_id = server["channelid"]
        guild = bot.get_guild(guild_id)
        if guild:
            channel = guild.get_channel(channel_id)
            if channel:
                try:
                    await channel.send(embed=embed)
                except Exception:
                    continue

    for guild_id, channel_info in news_channels.items():
        guild_id = int(guild_id)
        channel_id = channel_info["channelid"]
        guild = bot.get_guild(guild_id)
        if guild:
            channel = guild.get_channel(channel_id)
            if channel:
                try:
                    await channel.send(embed=embed)
                except Exception:
                    continue


def search_and_write(data, search_term, output_file):
    found_entries = []

    # Suche nach dem Suchbegriff in den verschiedenen Feldern
    for key, entry in data.items():
        if (
            search_term.lower() in entry["user"].lower()
            or search_term.lower() in str(entry["userid"])
            or search_term.lower() in entry["message"].lower()
            or search_term.lower() in entry["server"].lower()
            or search_term.lower() in str(entry["serverid"])
            or search_term.lower() in str(entry["requestid"])
        ):
            found_entries.append(entry)

    # noinspection PyTypeChecker
    with open(output_file, "w") as file:
        # Schreibe die Anzahl der gefundenen Einträge
        file.write(f"Entries found: {len(found_entries)}\n\n")

        # Schreibe die gefundenen Einträge
        for entry in found_entries:
            file.write(f"Request ID: {entry['requestid']}\n")
            file.write(f"User: {entry['user']}\n")
            file.write(f"User ID: {entry['userid']}\n")
            file.write(f"Message: {entry['message']}\n")
            file.write(f"Timestamp: {entry['timestamp']}\n")
            file.write(f"Reason: {entry['reason']}\n")
            file.write(f"Server: {entry['server']}\n")
            file.write(f"Server ID: {entry['serverid']}\n")
            file.write("\n" + "-" * 40 + "\n\n")

        if not found_entries:
            file.write(f"No results for: {search_term}")


@bot.command(name="admin.get_chatfilterlog")
async def admin_get_chatfilterlog(message: discord.Message, query):
    try:
        if message.author.id not in botadmin:  # Annahme: botadmin ist definiert
            await message.reply(
                "Nice try! But you are not authorized to use this command!"
            )
            return
        embed = discord.Embed(
            title="Search for entries...", description="One moment please..."
        ).set_thumbnail(url=f"{icons_url}loading.gif")

        data = load_data("json/chatfilterrequest.json")
        if not query:
            await message.channel.send("Keine eingabe!")
            return
        msg = await message.channel.send(embed=embed)
        file_name = f"output-{generate_random_string(10)}.txt"
        # noinspection PyShadowingNames
        file_path = os.path.join(
            config["FLASK"]["filter_log_request_folder"], file_name
        )
        await asyncio.sleep(1)

        search_and_write(data, query, file_path)

        embed_new = discord.Embed(
            title="Search completed",
            description=f"You can access the data found using the following link: https://security.pyropixle.com/chatfilter_log/{file_name}",
        )
        await msg.edit(embed=embed_new)
    except Exception as e:
        await message.channel.send(str(e))


@app.route("/chatfilter_log/<filename>")
async def download_file(filename):
    return await send_from_directory(
        config["FLASK"]["filter_log_request_folder"], filename
    )


@bot.command(name="admin.delete_chatfilterlog")
async def admin_delete_chatfilterlog(message: discord.Message, query):
    if message.author.id not in botadmin:  # Annahme: botadmin ist definiert
        await message.reply("Nice try! But you are not authorized to use this command!")
        return
    embed = discord.Embed(
        title="Search for entries...", description="One moment please..."
    ).set_thumbnail(url=f"{icons_url}loading.gif")

    data = load_data("json/chatfilterrequest.json")
    if not query:
        await message.channel.send("Keine eingabe!")
        return
    msg = await message.channel.send(embed=embed)
    # Lade die JSON-Daten

    # Filtere die Einträge, die nicht mit dem Suchbegriff übereinstimmen
    new_data = {
        key: entry
        for key, entry in data.items()
        if not (
            query.lower() in entry["user"].lower()
            or query.lower() in str(entry["userid"])
            or query.lower() in entry["message"].lower()
            or query.lower() in entry["server"].lower()
            or query.lower() in str(entry["serverid"])
            or query.lower() in str(entry["requestid"])
        )
    }

    # Speichere die neuen Daten zurück in die JSON-Datei
    # noinspection PyTypeChecker
    with open("json/chatfilterrequest.json", "w") as file:
        json.dump(new_data, file, indent=4)

    deleted_count = len(data) - len(new_data)
    embed_new = discord.Embed(
        title="Search completed",
        description=f"{deleted_count} entries were deleted from the database.",
    )
    await msg.edit(embed=embed_new)


@bot.command(name="admin.help")
async def admin_help(interaction: discord.Message):
    if interaction.author.id not in botadmin:  # Annahme: botadmin ist definiert
        await interaction.reply(
            "Nice try! But you are not authorized to use this command!"
        )
        return
    await interaction.reply(
        "# Admin Commands:\n"
        "> `b?admin.uban <uid> <reason>` - Bannt einen Nutzer von den Bot Systemen.\n"
        "> `b?admin.toggle_server_log <sid>` - Aktiviert das loggen aller Nachrichten auf einem Server.\n"
        "> `b?admin.toggle_security-site` - Aktiviert / Deaktiviert die Seite https://security.pyropixle.com\n"
        "> `b?admin.announce <MESSAGE>` - Sende eine Nachricht an alle Server und im GB.\n"
        "> `b?admin.lock_global_img <IMG NAME>`\n"
        "> `b?admin.save_messages <NUM>` - Speichert die letzten nachrichten des aktuellen channels.\n"
        "> `b?admin.get_chatfilterlog <userName|userID|requestID|guildID|guildName|message>` - Fasst alle Chatfilter einträge mit die mit der suchanfrage gefunden wurden zusammen."
    )


# ********************************************************************************************************


#
async def start_bot():
    await bot.start(token=auth0["DISCORD"]["token"], reconnect=True)


async def main():
    # Starte sowohl den Bot als auch die Quart-Anwendung
    bot_task = asyncio.create_task(start_bot())
    quart_task = app.run_task(port=1637, host="0.0.0.0")

    await asyncio.gather(bot_task, quart_task)


# Starte die Haupt-Async-Funktion
if __name__ == "__main__":
    asyncio.run(main())
# END OF FILE
