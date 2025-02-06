import asyncio

import config.auth as auth
import config.config as config
import discord
import reds_simple_logger
from assets.commands import ai, base_commands, utility_commands
from assets.dash.log import (highlight_word, request_chatfilter_log,
                             request_log_home)
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
        super().__init__(
            command_prefix=str(commands.when_mentioned_or(config.Discord.prefix)),
            intents=intents,
            shard_count=config.Discord.shard_count,
        )

    async def setup_hook(self) -> None:
        from assets.buttons import TicketView, TicketAdminButtons
        self.add_view(TicketView())
        self.add_view(TicketAdminButtons())


bot = PersistentViewBot()
set_bot(bot)
web = Quart(
    __name__,
    template_folder=config.Web.web_folder,
    static_folder=config.Web.static_folder,
)
web = cors(web)

events(bot=bot)
base_commands(bot=bot)
utility_commands(bot=bot)
ai(bot=bot)

request_chatfilter_log(app=web, bot=bot)
request_log_home(app=web)
web.jinja_env.filters['highlight_word'] = highlight_word

@bot.tree.command(name="ticket-test")
async def ticket_test(interaction: discord.Interaction):
    from assets.buttons import TicketView
    await interaction.response.send_message("Ticket Test", view=TicketView())

async def run_bot():
    await bot.start(auth.Bot.token)


async def run_app():
    await web.run_task(port=config.Web.port, host=config.Web.host)


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(asyncio.gather(run_app(), run_bot()))
