import asyncio
import datetime
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

import discord
from reds_simple_logger import Logger

logger = Logger()

FFMPEG_BEFORE = (
    "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -nostdin "
    "-protocol_whitelist file,http,https,tcp,tls,crypto "
    "-loglevel warning"
)
FFMPEG_OPTS = "-vn"


@dataclass
class Track:
    title: str
    stream_url: str
    webpage_url: str
    duration: int                # 0 = stream / unknown
    requester_id: int
    thumbnail: Optional[str]
    source_type: str             # "youtube" | "soundcloud" | "radio"


@dataclass
class MusicPlayer:
    guild_id: int
    text_channel_id: int
    voice_client: Optional[discord.VoiceClient] = None
    queue: deque = field(default_factory=deque)
    current: Optional[Track] = None
    volume: float = 1.0
    last_activity: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _bot: Optional[discord.Client] = None

    async def connect(self, channel: discord.VoiceChannel):
        if self.voice_client and self.voice_client.is_connected():
            if self.voice_client.channel.id != channel.id:
                logger.info(f"[Music:{self.guild_id}] Moving to channel {channel.id}")
                await self.voice_client.move_to(channel)
            else:
                logger.debug.info(f"[Music:{self.guild_id}] Already connected to {channel.id}")
        else:
            logger.info(f"[Music:{self.guild_id}] Connecting to channel {channel.id} ({channel.name})")
            try:
                self.voice_client = await channel.connect(self_deaf=False, self_mute=False, timeout=20.0, reconnect=False)
            except asyncio.TimeoutError:
                logger.error(f"[Music:{self.guild_id}] Voice connect timed out after 20s")
                raise
            except discord.ClientException as e:
                logger.error(f"[Music:{self.guild_id}] discord.ClientException during connect: {e}")
                raise
            except Exception as e:
                logger.error(f"[Music:{self.guild_id}] Unexpected error during connect: {type(e).__name__}: {e}")
                raise
            
            try:
                guild = channel.guild
                me = guild.me
                if me and (me.voice and (me.voice.deaf or me.voice.mute)):
                    logger.warning(f"[Music:{self.guild_id}] Bot is server-muted/deafened in this guild — audio output blocked.")
            except Exception:
                pass
            logger.info(f"[Music:{self.guild_id}] Voice connection established")
        self.touch()

    def touch(self):
        self.last_activity = datetime.datetime.now(datetime.timezone.utc)

    def enqueue(self, track: Track) -> None:
        self.queue.append(track)
        self.touch()

    def is_playing(self) -> bool:
        return bool(self.voice_client and self.voice_client.is_playing())

    def is_paused(self) -> bool:
        return bool(self.voice_client and self.voice_client.is_paused())

    async def play_next(self) -> Optional[Track]:
        if not self.voice_client or not self.voice_client.is_connected():
            logger.warning(f"[Music:{self.guild_id}] play_next called without active voice client")
            return None
        if not self.queue:
            self.current = None
            logger.debug.info(f"[Music:{self.guild_id}] play_next: queue empty")
            return None

        track = self.queue.popleft()
        self.current = track
        url_short = (track.stream_url or "")[:120]
        logger.info(f"[Music:{self.guild_id}] Starting playback: type={track.source_type} title={track.title!r} url={url_short!r}")

        # Re-extract stream URL for YouTube/SoundCloud to ensure it's fresh
        # (URLs are valid for ~6 hours and may expire if queued too long)
        if track.source_type in ("youtube", "soundcloud"):
            try:
                from assets.music.sources import extract_track
                logger.debug.info(f"[Music:{self.guild_id}] Re-extracting stream URL for freshness")
                fresh = await extract_track(track.webpage_url)
                track.stream_url = fresh.stream_url
            except Exception as e:
                logger.warning(f"[Music:{self.guild_id}] Failed to re-extract stream URL: {e}")
                # Continue with old URL — might still work

        try:
            source = discord.PCMVolumeTransformer(
                discord.FFmpegPCMAudio(
                    track.stream_url,
                    before_options=FFMPEG_BEFORE,
                    options=FFMPEG_OPTS,
                ),
                volume=self.volume,
            )
        except Exception as e:
            logger.error(f"[Music:{self.guild_id}] Failed to construct FFmpeg source: {e}")
            self.current = None
            return None

        try:
            self.voice_client.play(source, after=self._after)
        except discord.ClientException as e:
            logger.error(f"[Music:{self.guild_id}] voice_client.play raised: {e}")
            self.current = None
            return None
        self.touch()
        return track

    def _after(self, error):
        logger.info(f"[Music:{self.guild_id}] _after fired (error={error!r})")
        if self._bot is None:
            logger.warning(f"[Music:{self.guild_id}] _after: bot reference missing, cannot advance")
            return
        loop = self._bot.loop
        loop.call_soon_threadsafe(asyncio.ensure_future, self._advance(error))

    async def _advance(self, error):
        if error:
            logger.error(f"[Music:{self.guild_id}] FFmpeg playback error: {error}")
        self.touch()
        if self.current and self.current.source_type == "radio":
            logger.info(f"[Music:{self.guild_id}] Radio stream ended; staying connected")
            self.current = None
            return
        if self.queue:
            logger.debug.info(f"[Music:{self.guild_id}] Advancing to next queued track ({len(self.queue)} left)")
            await self.play_next()
        else:
            logger.debug.info(f"[Music:{self.guild_id}] Queue empty after track end")
            self.current = None

    def skip(self) -> None:
        if self.voice_client and (self.voice_client.is_playing() or self.voice_client.is_paused()):
            self.voice_client.stop()
        self.touch()

    def pause(self) -> bool:
        if self.voice_client and self.voice_client.is_playing():
            self.voice_client.pause()
            self.touch()
            return True
        return False

    def resume(self) -> bool:
        if self.voice_client and self.voice_client.is_paused():
            self.voice_client.resume()
            self.touch()
            return True
        return False

    def set_volume(self, level_percent: int) -> None:
        self.volume = max(0.0, min(2.0, level_percent / 100.0))
        if self.voice_client and self.voice_client.source and isinstance(self.voice_client.source, discord.PCMVolumeTransformer):
            self.voice_client.source.volume = self.volume

    async def stop_and_disconnect(self) -> None:
        logger.info(f"[Music:{self.guild_id}] stop_and_disconnect called")
        self.queue.clear()
        self.current = None
        if self.voice_client:
            try:
                if self.voice_client.is_playing() or self.voice_client.is_paused():
                    self.voice_client.stop()
                if self.voice_client.is_connected():
                    await self.voice_client.disconnect(force=False)
            except Exception as e:
                logger.warning(f"[Music:{self.guild_id}] Error during disconnect: {e}")
        self.voice_client = None
