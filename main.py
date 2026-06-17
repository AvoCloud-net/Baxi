import os
import time
os.environ["TZ"] = "Europe/Vienna"
time.tzset()

import asyncio
import shutil
import signal
import subprocess
import sys
import tempfile

import config.auth as auth
import config.config as config
import discord
import reds_simple_logger

# Initialize the SQLite store and run the one-shot JSON->DB migration BEFORE any
# assets.* module is imported, so no import-time data access hits an uninitialized
# connection. run() is idempotent (no-op once schema_meta.migration_complete is set).
import migrate_to_sqlite as _migrate
_migrate.run()

from assets.commands import base_commands, utility_commands, bot_admin_commands, leveling_commands, mc_link_commands, tempvoice_commands
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
        intents.voice_states = True
        super().__init__(
            command_prefix=str(
                commands.when_mentioned_or(config.Discord.prefix)),
            intents=intents,
            shard_count=config.Discord.shard_count,
            # Chunk every guild's member list at startup. Member-dependent
            # features (stats, member counts, leveling display names, the
            # mc-link confirm flow) need a full cache to be correct. This is the
            # slow part of boot, but correctness wins — see on_ready's background
            # warm if a non-blocking approach is reintroduced later.
            chunk_guilds_at_startup=True,
        )

    async def setup_hook(self) -> None:
        from assets.buttons import TicketButton, TicketAdminButtons, VerifyView
        from assets.message.reactionroles import RoleButton
        from assets.suggestions import SuggestionView
        from assets.giveaway import GiveawayView
        from assets.message.tempvoice import TempVoiceControlView, load_state as _tv_load_state
        self.add_view(TicketAdminButtons())
        self.add_view(VerifyView())
        self.add_view(SuggestionView())
        self.add_view(GiveawayView())
        self.add_view(TempVoiceControlView(self))
        self.add_dynamic_items(RoleButton, TicketButton, PollButton, PollCloseButton)
        _tv_load_state()


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
tempvoice_commands(bot=bot)

web.jinja_env.filters['highlight_word'] = highlight_word


async def run_bot():
    await bot.start(auth.Bot.token, reconnect=True)


async def run_app(shutdown_trigger):
    # shutdown_trigger lets US own SIGINT/SIGTERM. Without it hypercorn installs
    # its own signal handlers, overwriting ours, and only the web server stops.
    await web.run_task(
        port=config.Web.port, host=config.Web.host, shutdown_trigger=shutdown_trigger
    )


async def run_console():
    # Admin console on the bot's stdin (help, add_bot_admin, run_task, …).
    from assets.console import run_console as _console
    await _console(bot)


_shutdown_event: "asyncio.Event | None" = None
_shutdown_started = False


async def _graceful_shutdown():
    global _shutdown_started
    if _shutdown_started:
        return
    _shutdown_started = True
    logger.working("Shutting down…")
    try:
        from assets.music.announce import announce_reboot_in_voice_channels
        await announce_reboot_in_voice_channels(bot)
    except Exception as e:
        logger.error(f"Reboot TTS announce failed: {type(e).__name__}: {e}")
    try:
        await bot.close()
    except Exception:
        pass
    logger.info("Bot closed. Bye.")


def _request_shutdown() -> None:
    if _shutdown_event is not None and not _shutdown_event.is_set():
        logger.working("Stop signal received — shutting down…")
        _shutdown_event.set()


def _install_signal_handlers(loop: asyncio.AbstractEventLoop) -> None:
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_shutdown)
        except (NotImplementedError, RuntimeError):
            pass


async def _amain() -> None:
    global _shutdown_event
    _shutdown_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    _install_signal_handlers(loop)

    web_task = asyncio.create_task(run_app(_shutdown_event.wait), name="web")
    bot_task = asyncio.create_task(run_bot(), name="bot")
    console_task = asyncio.create_task(run_console(), name="console")
    shutdown_waiter = asyncio.create_task(_shutdown_event.wait(), name="shutdown")

    # Wake on an explicit stop signal OR if the bot/web dies on its own (console
    # ending on stdin EOF must NOT bring the bot down → it's excluded here).
    await asyncio.wait(
        {shutdown_waiter, web_task, bot_task},
        return_when=asyncio.FIRST_COMPLETED,
    )

    _shutdown_event.set()        # unblocks the web server's shutdown_trigger
    await _graceful_shutdown()   # TTS announce + bot.close()
    console_task.cancel()        # stdin reader is a daemon thread → safe to drop
    await asyncio.gather(
        web_task, bot_task, console_task, shutdown_waiter, return_exceptions=True
    )


if __name__ == "__main__":
    try:
        asyncio.run(_amain())
    except KeyboardInterrupt:
        pass
