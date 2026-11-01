"""Rest mode: keep Baxi cheap while nothing happens.

Activity: messages, interactions and voice changes from real users call
`touch()` (dashboard requests do not: they need neither the model nor the memory,
and an uptime monitor would keep Baxi awake forever). After BAXI_REST_AFTER seconds without any (default 10
min) Baxi rests: the chatfilter model process is stopped, the garbage collector
runs once, freed heap goes back to the OS (malloc_trim) and the presence turns
idle. The next activity wakes it; the model comes back on the first message
that needs it.

Feature index: `guilds_with(bot, sys)` returns only the guilds that have a feature
switched on, so background tasks never read the config of every guild on every
tick. Cached per config key, dropped whenever datasys.save_data writes that key
(and on guild join), rebuilt at least every _INDEX_TTL as a safety net for writes
that bypass save_data.

Background tasks do not pause while resting: a feed post or an expiring ban must
still happen at night. They are cheap because of the feature index instead.
"""
from __future__ import annotations

import asyncio
import ctypes
import gc
import os
import time

import discord
from discord.ext import commands, tasks
from reds_simple_logger import Logger

import config.config as config
from assets.share import set_task_status

logger = Logger()

REST_AFTER = int(os.environ.get("BAXI_REST_AFTER") or 600)
_INDEX_TTL = 600

_last_activity = time.monotonic()
_resting = False
_bot: commands.AutoShardedBot | None = None
_index: dict[tuple[str, str], tuple[float, frozenset[int]]] = {}


# ── feature index ────────────────────────────────────────────────────────────
def guild_ids_with(bot: commands.AutoShardedBot, sys: str, key: str = "enabled") -> frozenset[int]:
    """Ids of the guilds whose `sys` config has a truthy `key`."""
    now = time.monotonic()
    hit = _index.get((sys, key))
    if hit and now - hit[0] < _INDEX_TTL:
        return hit[1]
    import assets.data as datasys
    ids = set()
    for guild in bot.guilds:
        try:
            if dict(datasys.load_data(guild.id, sys) or {}).get(key):
                ids.add(guild.id)
        except Exception as e:
            logger.error(f"[Idle] feature index {sys}.{key} @ {guild.id}: {e}")
    found = frozenset(ids)
    _index[(sys, key)] = (now, found)
    return found


def guilds_with(bot: commands.AutoShardedBot, sys: str, key: str = "enabled") -> list[discord.Guild]:
    """The guilds whose `sys` config has a truthy `key` (default "enabled")."""
    return [g for gid in guild_ids_with(bot, sys, key) if (g := bot.get_guild(gid)) is not None]


def invalidate(sys: str | None = None) -> None:
    """Forget the index for one config key (None = all). Called by save_data."""
    for k in [k for k in _index if sys is None or k[0] == sys]:
        _index.pop(k, None)


# ── activity / rest ──────────────────────────────────────────────────────────
def is_resting() -> bool:
    return _resting


def presence_status() -> discord.Status:
    return discord.Status.idle if _resting else discord.Status.online


def presence_activity(bot: commands.AutoShardedBot) -> discord.Activity:
    return discord.Activity(type=discord.ActivityType.playing,
                            name=f"on {len(bot.guilds)} Worlds! - v{config.Discord.version}")


def touch() -> None:
    global _last_activity
    _last_activity = time.monotonic()
    if _resting:
        try:
            asyncio.get_running_loop().create_task(_wake())
        except RuntimeError:
            pass


def _release_memory() -> int:
    """Collect garbage and hand freed heap back to the OS. Returns objects collected."""
    collected = gc.collect()
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except (OSError, AttributeError):
        pass   # not glibc (musl, macOS): the GC pass is all we can do
    return collected


async def _set_presence() -> None:
    if _bot is None or not _bot.is_ready():
        return
    try:
        await _bot.change_presence(status=presence_status(), activity=presence_activity(_bot))
    except Exception as e:
        logger.debug.info(f"[Idle] presence update failed: {e}")


async def _rest() -> None:
    global _resting
    if _resting:
        return
    _resting = True
    from assets.message.safetext import models
    models.stop_worker("rest mode")
    collected = _release_memory()
    logger.info(f"[Idle] no activity for {REST_AFTER // 60} min - resting ({collected} objects freed)")
    set_task_status("RestMode", "ok", f"Resting since {time.strftime('%H:%M')}")
    await _set_presence()


async def _wake() -> None:
    global _resting
    if not _resting:
        return
    _resting = False
    logger.info("[Idle] activity - waking up")
    set_task_status("RestMode", "ok", "Awake")
    await _set_presence()


class RestModeTask:
    """Enters rest mode once Baxi has been quiet for REST_AFTER seconds."""

    def __init__(self, bot: commands.AutoShardedBot):
        global _bot
        _bot = bot
        self.bot = bot

    @tasks.loop(seconds=60)
    async def watch(self):
        if not _resting and time.monotonic() - _last_activity >= REST_AFTER:
            await _rest()


def register(bot: commands.AutoShardedBot) -> None:
    """Hook the activity sources. Listeners (not @bot.event) so events.py keeps its handlers."""

    async def _on_message(message: discord.Message):
        if not message.author.bot:
            touch()

    async def _on_interaction(_interaction: discord.Interaction):
        touch()

    async def _on_voice(member: discord.Member, _before, _after):
        if not member.bot:
            touch()

    async def _on_guild_join(_guild: discord.Guild):
        invalidate()

    bot.add_listener(_on_message, "on_message")
    bot.add_listener(_on_interaction, "on_interaction")
    bot.add_listener(_on_voice, "on_voice_state_update")
    bot.add_listener(_on_guild_join, "on_guild_join")
