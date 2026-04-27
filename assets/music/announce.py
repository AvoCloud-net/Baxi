import asyncio
import hashlib
import os
import tempfile
from typing import Optional

import discord
import reds_simple_logger

import assets.share as share

logger = reds_simple_logger.Logger()

REBOOT_MESSAGE = "Bot will reboot now, we will be back shortly."
RESTART_NOTICE_MESSAGE = (
    "Hey everyone. Just a quick heads-up — I am currently restarting, "
    "which means music playback has been stopped. "
    "I will be back online in just one to two minutes. Thanks for your patience."
)

_REBOOT_TTS_PATH = os.path.join(tempfile.gettempdir(), "baxi_reboot_tts.mp3")
_NOTICE_TTS_PATH = os.path.join(tempfile.gettempdir(), "baxi_restart_notice_tts.mp3")

_PER_CHANNEL_TIMEOUT = 8.0
_OVERALL_TIMEOUT = 12.0
_NOTICE_PER_CHANNEL_TIMEOUT = 25.0
_NOTICE_OVERALL_TIMEOUT = 30.0
_DEFAULT_NOTICE_VOLUME = 2.0


def _ensure_tts_file(message: str, path: str) -> Optional[str]:
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path
    try:
        from gtts import gTTS
    except ImportError:
        logger.warning("[Announce] gTTS not installed — TTS announce disabled.")
        return None
    try:
        gTTS(text=message, lang="en").save(path)
        return path
    except Exception as e:
        logger.error(f"[Announce] gTTS save failed: {type(e).__name__}: {e}")
        return None


async def _announce_in_vc(vc: discord.VoiceClient, path: str) -> None:
    try:
        if not vc or not vc.is_connected():
            return
        if vc.is_playing() or vc.is_paused():
            try:
                vc.stop()
            except Exception:
                pass
        await asyncio.sleep(0.25)
        done = asyncio.Event()
        loop = asyncio.get_event_loop()

        def _after(err):
            loop.call_soon_threadsafe(done.set)

        try:
            source = discord.FFmpegPCMAudio(path)
            vc.play(source, after=_after)
        except Exception as e:
            logger.error(f"[Announce] play failed in guild={getattr(vc.guild, 'id', '?')}: {type(e).__name__}: {e}")
            return

        try:
            await asyncio.wait_for(done.wait(), timeout=_PER_CHANNEL_TIMEOUT)
        except asyncio.TimeoutError:
            logger.warning(f"[Announce] TTS playback timeout in guild={getattr(vc.guild, 'id', '?')}")
    finally:
        try:
            await vc.disconnect(force=True)
        except Exception:
            pass


async def announce_reboot_in_voice_channels(bot, message: str = REBOOT_MESSAGE) -> None:
    voice_clients = list(getattr(bot, "voice_clients", []) or [])
    if not voice_clients:
        return

    path = _ensure_tts_file(message, _REBOOT_TTS_PATH)
    if not path:
        for vc in voice_clients:
            try:
                await vc.disconnect(force=True)
            except Exception:
                pass
        return

    logger.info(f"[Announce] Playing reboot TTS in {len(voice_clients)} voice channel(s)")
    try:
        await asyncio.wait_for(
            asyncio.gather(*(_announce_in_vc(vc, path) for vc in voice_clients), return_exceptions=True),
            timeout=_OVERALL_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.warning("[Announce] Overall reboot announce timed out")

    share.music_players.clear()


async def _notice_in_vc(vc: discord.VoiceClient, path: str, volume: float) -> None:
    if not vc or not vc.is_connected():
        return
    gid = getattr(vc.guild, "id", "?")
    was_playing = False
    try:
        if vc.is_playing():
            was_playing = True
            try:
                vc.pause()
            except Exception:
                pass
        await asyncio.sleep(0.25)

        done = asyncio.Event()
        loop = asyncio.get_event_loop()

        def _after(err):
            loop.call_soon_threadsafe(done.set)

        try:
            base = discord.FFmpegPCMAudio(path)
            source = discord.PCMVolumeTransformer(base, volume=volume)
        except Exception as e:
            logger.error(f"[Notice] source build failed in guild={gid}: {type(e).__name__}: {e}")
            return

        try:
            vc.play(source, after=_after)
        except discord.ClientException:
            try:
                vc.stop()
                await asyncio.sleep(0.1)
                vc.play(source, after=_after)
            except Exception as e:
                logger.error(f"[Notice] play retry failed in guild={gid}: {type(e).__name__}: {e}")
                return
        except Exception as e:
            logger.error(f"[Notice] play failed in guild={gid}: {type(e).__name__}: {e}")
            return

        try:
            await asyncio.wait_for(done.wait(), timeout=_NOTICE_PER_CHANNEL_TIMEOUT)
        except asyncio.TimeoutError:
            logger.warning(f"[Notice] TTS playback timeout in guild={gid}")
            try:
                vc.stop()
            except Exception:
                pass
    finally:
        # Music stays paused per text ("playback has been stopped"); user resumes manually.
        _ = was_playing


async def announce_restart_notice(bot, guild_id: Optional[int] = None,
                                   message: str = RESTART_NOTICE_MESSAGE,
                                   volume: float = _DEFAULT_NOTICE_VOLUME) -> int:
    voice_clients = list(getattr(bot, "voice_clients", []) or [])
    if guild_id is not None:
        voice_clients = [vc for vc in voice_clients if getattr(vc.guild, "id", None) == int(guild_id)]
    if not voice_clients:
        return 0

    if message == RESTART_NOTICE_MESSAGE:
        cache_path = _NOTICE_TTS_PATH
    else:
        digest = hashlib.sha1(message.encode("utf-8")).hexdigest()[:16]
        cache_path = os.path.join(tempfile.gettempdir(), f"baxi_notice_tts_{digest}.mp3")
    path = _ensure_tts_file(message, cache_path)
    if not path:
        return 0

    logger.info(f"[Notice] Playing restart-notice TTS in {len(voice_clients)} voice channel(s) (guild_id={guild_id}, vol={volume})")
    try:
        await asyncio.wait_for(
            asyncio.gather(*(_notice_in_vc(vc, path, volume) for vc in voice_clients), return_exceptions=True),
            timeout=_NOTICE_OVERALL_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.warning("[Notice] Overall restart-notice timed out")

    return len(voice_clients)
