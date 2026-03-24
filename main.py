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
from assets.commands import base_commands, utility_commands, bot_admin_commands
from assets.dash.log import highlight_word

from assets.data import set_bot
from assets.events import events
from discord.ext import commands
from quart import Quart
from quart_cors import cors

logger = reds_simple_logger.Logger()


# ──────────────────────────────────────────────────────────────────────── Update

def _run(cmd: list[str], capture=True) -> str | None:
    """Run a shell command, return stdout or None on failure."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=capture,
            text=True,
            cwd=os.path.dirname(os.path.abspath(__file__)),
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip() if capture else ""
    except Exception:
        return None


def _check_git_available() -> bool:
    return _run(["git", "--version"]) is not None


def run_updater():
    """Check GitHub for updates. If behind, ask user whether to update.
    Configs (auth.py, config.py) and all data/ files are preserved across the update."""

    if not _check_git_available():
        logger.working("Git not found, skipping update check.")
        return

    logger.working("Checking for updates...")

    # Fetch latest info from remote
    if _run(["git", "fetch", "origin"]) is None:
        logger.working("Could not reach GitHub, skipping update check.")
        return

    # Get current branch
    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"]) or "main"

    # Compare local HEAD with remote
    local_sha  = _run(["git", "rev-parse", "HEAD"]) or ""
    remote_sha = _run(["git", "rev-parse", f"origin/{branch}"]) or ""

    if not local_sha or not remote_sha:
        logger.working("Could not determine version, skipping update check.")
        return

    if local_sha == remote_sha:
        logger.debug.success("Already up to date.")
        return

    # Count how many commits behind
    behind = _run(["git", "rev-list", "--count", f"HEAD..origin/{branch}"]) or "?"
    ahead  = _run(["git", "rev-list", "--count", f"origin/{branch}..HEAD"]) or "0"

    # Show what's new
    new_commits = _run([
        "git", "log", "--oneline", f"HEAD..origin/{branch}"
    ]) or ""

    print()
    print("─" * 60)
    print(f"  Update available  ({behind} commit(s) behind origin/{branch})")
    if int(ahead) > 0:
        print(f"  NOTE: {ahead} local commit(s) not on remote (will be kept)")
    if new_commits:
        print()
        for line in new_commits.splitlines()[:10]:
            print(f"  • {line}")
        if len(new_commits.splitlines()) > 10:
            print(f"  … and {len(new_commits.splitlines()) - 10} more")
    print("─" * 60)

    try:
        answer = input("  Update now? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return

    if answer != "y":
        print("  Skipping update, starting with current version.")
        print()
        return

    print()
    logger.working("Saving configuration and data...")

    base = os.path.dirname(os.path.abspath(__file__))
    auth_path   = os.path.join(base, "config", "auth.py")
    config_path = os.path.join(base, "config", "config.py")
    data_path   = os.path.join(base, "data")

    # ── 1. Read configs into memory
    try:
        with open(auth_path, "r", encoding="utf-8") as f:
            auth_content = f.read()
        with open(config_path, "r", encoding="utf-8") as f:
            config_content = f.read()
    except Exception as e:
        print(f"  ERROR: Could not read config files: {e}")
        print("  Aborting update to protect your configuration.")
        return

    # ── 2. Backup data/ folder to a temp directory
    tmp_data = None
    if os.path.isdir(data_path):
        try:
            tmp_data = tempfile.mkdtemp(prefix="baxi_data_backup_")
            shutil.copytree(data_path, os.path.join(tmp_data, "data"))
            logger.debug.success(f"Data backed up to {tmp_data}")
        except Exception as e:
            print(f"  ERROR: Could not back up data folder: {e}")
            print("  Aborting update to protect your data.")
            return

    # ── 3. Pull updates (reset to remote state)
    logger.working("Pulling updates from GitHub...")
    if _run(["git", "reset", "--hard", f"origin/{branch}"], capture=False) is None:
        print("  ERROR: git reset failed.")
        _restore(auth_path, auth_content, config_path, config_content, tmp_data, data_path)
        return

    # ── 4. Restore configs
    logger.working("Restoring configuration...")
    _restore(auth_path, auth_content, config_path, config_content, tmp_data, data_path)

    new_sha = _run(["git", "rev-parse", "--short", "HEAD"]) or "unknown"
    logger.debug.success(f"Updated successfully to {new_sha}. Restarting...")
    print()

    # ── 5. Restart the process so imports reload cleanly
    os.execv(sys.executable, [sys.executable] + sys.argv)


def _restore(auth_path, auth_content, config_path, config_content, tmp_data, data_path):
    """Write back saved configs and restore data/ backup."""
    try:
        with open(auth_path, "w", encoding="utf-8") as f:
            f.write(auth_content)
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(config_content)
        logger.debug.success("Config files restored.")
    except Exception as e:
        print(f"  ERROR: Could not restore config files: {e}")
        print(f"  auth.py content:\n{auth_content}")

    if tmp_data:
        backup_data = os.path.join(tmp_data, "data")
        try:
            if os.path.isdir(backup_data):
                # Merge: copy every file from backup back, overwriting git's version
                for root, _, files in os.walk(backup_data):
                    rel = os.path.relpath(root, backup_data)
                    dest_dir = os.path.join(data_path, rel)
                    os.makedirs(dest_dir, exist_ok=True)
                    for fname in files:
                        shutil.copy2(
                            os.path.join(root, fname),
                            os.path.join(dest_dir, fname),
                        )
            shutil.rmtree(tmp_data, ignore_errors=True)
            logger.debug.success("Data folder restored.")
        except Exception as e:
            print(f"  WARNING: Could not fully restore data folder: {e}")
            print(f"  Backup is still at: {tmp_data}")


# ───────────────────────────────────────────────────────────────────── Bot setup

logger.working("Booting...")

run_updater()

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

web.jinja_env.filters['highlight_word'] = highlight_word


async def run_bot():
    await bot.start(auth.Bot.token, reconnect=True)


async def run_app():
    await web.run_task(port=config.Web.port, host=config.Web.host)


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(asyncio.gather(run_app(), run_bot()))
