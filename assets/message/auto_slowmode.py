import asyncio
import time
from collections import defaultdict

import discord
from discord.ext import commands
from reds_simple_logger import Logger

import assets.data as datasys
import config.config as config

logger = Logger()

# {guild_id: {channel_id: [timestamps]}}
_channel_timestamps: dict[int, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
# {channel_id: asyncio.Task} -  active slowmode removal tasks
_active_tasks: dict[int, asyncio.Task] = {}


async def check(message: discord.Message) -> None:
    """
    Track per-channel message rate and apply slowmode when the threshold is exceeded.
    Call this from process_message() in events.py.
    """
    if message.guild is None:
        return
    if not isinstance(message.channel, discord.TextChannel):
        return

    cfg: dict = dict(datasys.load_data(message.guild.id, "auto_slowmode"))
    if not cfg.get("enabled", False):
        return

    guild_id = message.guild.id
    channel_id = message.channel.id

    # If slowmode is already active in this channel, skip
    if channel_id in _active_tasks:
        return

    threshold: int = max(2, int(cfg.get("threshold", 10)))
    interval: int = max(2, int(cfg.get("interval", 10)))
    slowmode_delay: int = max(1, min(21600, int(cfg.get("slowmode_delay", 5))))
    duration: int = max(10, int(cfg.get("duration", 120)))

    now = time.time()
    timestamps = _channel_timestamps[guild_id][channel_id]

    # Prune old timestamps
    _channel_timestamps[guild_id][channel_id] = [t for t in timestamps if now - t < interval]
    _channel_timestamps[guild_id][channel_id].append(now)

    if len(_channel_timestamps[guild_id][channel_id]) < threshold:
        return

    # Threshold exceeded -  apply slowmode
    _channel_timestamps[guild_id][channel_id].clear()

    try:
        await message.channel.edit(
            slowmode_delay=slowmode_delay,
            reason=f"Baxi Auto-Slowmode: >{threshold} msgs/{interval}s detected",
        )
    except (discord.Forbidden, discord.HTTPException):
        return

    embed = discord.Embed(
        title="⏱ Auto-Slowmode activated",
        description=(
            f"Slowmode of **{slowmode_delay}s** has been applied to this channel "
            f"due to a high message rate.\n"
            f"It will be lifted automatically in **{duration}s**."
        ),
        color=config.Discord.warn_color,
    )
    embed.set_footer(text="Baxi · Auto-Slowmode")
    try:
        await message.channel.send(embed=embed)
    except (discord.Forbidden, discord.HTTPException):
        pass

    logger.info(f"[AutoSlowmode] Applied {slowmode_delay}s slowmode in #{message.channel.name} @ {message.guild.name} for {duration}s")

    # Schedule removal
    async def _lift_slowmode(channel: discord.TextChannel, ch_id: int, d: int) -> None:
        await asyncio.sleep(d)
        try:
            await channel.edit(slowmode_delay=0, reason="Baxi Auto-Slowmode: expired")
            logger.info(f"[AutoSlowmode] Lifted slowmode in #{channel.name}")
        except (discord.Forbidden, discord.HTTPException):
            pass
        _active_tasks.pop(ch_id, None)

    task = asyncio.create_task(_lift_slowmode(message.channel, channel_id, duration))
    _active_tasks[channel_id] = task
