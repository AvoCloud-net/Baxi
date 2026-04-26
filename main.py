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
from assets.commands import base_commands, utility_commands, bot_admin_commands, leveling_commands, mc_link_commands
from assets.giveaway import giveaway_commands
from assets.poll import poll_commands, PollButton, PollCloseButton
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
        from assets.buttons import TicketButton, TicketAdminButtons, VerifyView
        from assets.message.reactionroles import RoleButton
        from assets.suggestions import SuggestionView
        from assets.giveaway import GiveawayView
        self.add_view(TicketAdminButtons())
        self.add_view(VerifyView())
        self.add_view(SuggestionView())
        self.add_view(GiveawayView())
        self.add_dynamic_items(RoleButton, TicketButton, PollButton, PollCloseButton)


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


@web.context_processor
def _inject_static_version():
    """Cache-bust static assets by appending file mtime as ?v=<int>."""
    static_dir = config.Web.static_folder
    versions = {}
    try:
        for fname in ("main.css",):
            fpath = os.path.join(static_dir, fname)
            if os.path.isfile(fpath):
                versions[fname] = int(os.path.getmtime(fpath))
    except Exception:
        pass
    return {"static_versions": versions}


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
leveling_commands(bot=bot)
bot_admin_commands(bot=bot)
giveaway_commands(bot=bot)
poll_commands(bot=bot)
mc_link_commands(bot=bot)

web.jinja_env.filters['highlight_word'] = highlight_word


async def run_bot():
    await bot.start(auth.Bot.token, reconnect=True)


async def run_app():
    await web.run_task(port=config.Web.port, host=config.Web.host)


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(asyncio.gather(run_app(), run_bot()))
