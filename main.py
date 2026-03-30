import os
import time
os.environ["TZ"] = "Europe/Vienna"
time.tzset()

import asyncio
import shutil
import subprocess
import sys
import tempfile

import config.auth as auth
import config.config as config
import discord
import reds_simple_logger
from assets.commands import base_commands, utility_commands, bot_admin_commands, minigame_commands
from assets.dash.log import highlight_word

from assets.data import set_bot
from assets.events import events
from discord.ext import commands
from quart import Quart
from quart_cors import cors

logger = reds_simple_logger.Logger()


logger.working("Booting...")


class PersistentViewBot(commands.AutoShardedBot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.guilds = True
        intents.guild_messages = True
        super().__init__(
            command_prefix=str(
                commands.when_mentioned_or(config.Discord.prefix)),
            intents=intents,
            shard_count=config.Discord.shard_count,
        )

    async def setup_hook(self) -> None:
        from assets.buttons import TicketView, TicketAdminButtons, VerifyView
        from assets.message.reactionroles import RoleButton
        self.add_view(TicketView())
        self.add_view(TicketAdminButtons())
        self.add_view(VerifyView())
        self.add_dynamic_items(RoleButton)


bot = PersistentViewBot()
set_bot(bot)
web = Quart(
    __name__,
    template_folder=config.Web.web_folder,
    static_folder=config.Web.static_folder,
)
web = cors(web)
web.config["PREFERRED_URL_SCHEME"] = "https"
web.config["BOT_READY"] = False
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"


@web.errorhandler(404)
async def not_found(e):
    if not web.config.get("BOT_READY"):
        from quart import render_template
        return await render_template("starting.html"), 503
    from quart import render_template
    return await render_template("error.html", message="Page not found."), 404


events(bot=bot, web=web)
base_commands(bot=bot)
utility_commands(bot=bot)
bot_admin_commands(bot=bot)
minigame_commands(bot=bot)

web.jinja_env.filters['highlight_word'] = highlight_word


async def run_bot():
    await bot.start(auth.Bot.token, reconnect=True)


async def run_app():
    await web.run_task(port=config.Web.port, host=config.Web.host)


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(asyncio.gather(run_app(), run_bot()))
