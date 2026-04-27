import asyncio
import discord
from discord import Interaction, app_commands
from discord.ext import commands
from typing import Optional, cast

import config.config as config
import assets.data as datasys
import assets.share as share
from assets.music.player import MusicPlayer, Track
from assets.music.sources import RADIO_PRESETS, extract_track, is_safe_radio_url
from reds_simple_logger import Logger

logger = Logger()


def _conf(guild_id: int) -> dict:
    return dict(datasys.load_data(guild_id, "music") or {})


def _t(guild_id: int) -> dict:
    lang = datasys.load_lang_file(guild_id)
    return lang.get("systems", {}).get("music", {})


def _err_embed(text: str) -> discord.Embed:
    return discord.Embed(description=f"{config.Icons.cross} {text}", color=config.Discord.danger_color)


def _ok_embed(title: str, desc: str = "") -> discord.Embed:
    return discord.Embed(title=title, description=desc, color=config.Discord.color)


def _get_or_create_player(bot: commands.AutoShardedBot, guild_id: int, text_channel_id: int) -> MusicPlayer:
    player = share.music_players.get(guild_id)
    if player is None:
        conf = _conf(guild_id)
        player = MusicPlayer(
            guild_id=guild_id,
            text_channel_id=text_channel_id,
            volume=max(0, min(200, int(conf.get("default_volume", 100)))) / 100.0,
        )
        player._bot = bot
        share.music_players[guild_id] = player
    return player


async def _ensure_voice(interaction: Interaction, t: dict) -> Optional[discord.VoiceChannel]:
    member = cast(discord.Member, interaction.user)
    if not member.voice or not member.voice.channel:
        await interaction.followup.send(embed=_err_embed(t.get("not_in_voice", "Join a voice channel first.")), ephemeral=True)
        return None
    return cast(discord.VoiceChannel, member.voice.channel)


def _bot_busy_in_other_channel(guild: discord.Guild, target_channel: discord.VoiceChannel) -> bool:
    vc = guild.voice_client
    if vc and vc.channel and vc.channel.id != target_channel.id:
        humans = [m for m in vc.channel.members if not m.bot]
        if humans:
            return True
    return False


def register_music_commands(bot: commands.AutoShardedBot):
    logger.debug.info("Music commands loaded.")

    music_group = app_commands.Group(name="music", description="Play songs and live radio in voice channels")

    async def _check_common(interaction: Interaction) -> Optional[tuple[dict, dict, MusicPlayer, discord.VoiceChannel]]:
        if interaction.guild is None:
            await interaction.followup.send(embed=_err_embed("Server only."), ephemeral=True)
            return None
        gid = interaction.guild.id
        conf = _conf(gid)
        t = _t(gid)
        if not conf.get("enabled", True):
            await interaction.followup.send(embed=_err_embed(t.get("disabled", "Music is disabled on this server.")), ephemeral=True)
            return None
        channel = await _ensure_voice(interaction, t)
        if channel is None:
            return None
        
        # Check bot permissions in the voice channel
        bot_perms = channel.permissions_for(interaction.guild.me)
        if not bot_perms.connect:
            await interaction.followup.send(embed=_err_embed(t.get("no_connect_perm", "I don't have permission to connect to this voice channel.")), ephemeral=True)
            return None
        if not bot_perms.speak:
            await interaction.followup.send(embed=_err_embed(t.get("no_speak_perm", "I don't have permission to speak in this voice channel.")), ephemeral=True)
            return None
        
        if _bot_busy_in_other_channel(interaction.guild, channel):
            await interaction.followup.send(embed=_err_embed(t.get("bot_busy", "Bot already playing in another voice channel.")), ephemeral=True)
            return None
        player = _get_or_create_player(bot, gid, interaction.channel.id if interaction.channel else 0)
        return conf, t, player, channel

    @music_group.command(name="play", description="Play a song from YouTube or SoundCloud (URL or search term)")
    @app_commands.describe(query="YouTube/SoundCloud URL or search query")
    async def play_cmd(interaction: Interaction, query: str):
        await interaction.response.defer()
        ctx = await _check_common(interaction)
        if not ctx:
            return
        conf, t, player, channel = ctx

        allowed = conf.get("allowed_sources", ["youtube", "soundcloud", "radio"])
        if "youtube" not in allowed and "soundcloud" not in allowed:
            return await interaction.followup.send(embed=_err_embed(t.get("source_blocked", "Songs are disabled — only radio is allowed.")), ephemeral=True)

        logger.info(f"[Music:{interaction.guild.id}] /music play by {interaction.user.id}: query={query!r}")
        try:
            extracted = await extract_track(query)
            logger.debug.info(f"[Music:{interaction.guild.id}] extracted: title={extracted.title!r} type={extracted.source_type} dur={extracted.duration}")
        except Exception as e:
            logger.error(f"[Music] extract failed for {query!r}: {e}")
            return await interaction.followup.send(embed=_err_embed(t.get("extract_failed", "Could not extract that track.")))

        if extracted.source_type not in allowed:
            return await interaction.followup.send(embed=_err_embed(t.get("source_blocked", "This source is not allowed.")), ephemeral=True)

        max_dur = int(conf.get("max_song_duration", 600) or 0)
        if max_dur > 0 and extracted.duration and extracted.duration > max_dur:
            return await interaction.followup.send(embed=_err_embed(t.get("song_too_long", "Track exceeds the configured max duration.")))

        queue_limit = int(conf.get("queue_limit", 50))
        if len(player.queue) >= queue_limit:
            return await interaction.followup.send(embed=_err_embed(t.get("queue_full", "Queue is full.")))

        track = Track(
            title=extracted.title,
            stream_url=extracted.stream_url,
            webpage_url=extracted.webpage_url,
            duration=extracted.duration,
            requester_id=interaction.user.id,
            thumbnail=extracted.thumbnail,
            source_type=extracted.source_type,
        )

        started = False
        async with player.lock:
            try:
                await player.connect(channel)
            except Exception as e:
                logger.error(f"[Music:{interaction.guild.id}] connect failed: {type(e).__name__}: {e}")
                share.music_players.pop(interaction.guild.id, None)
                return await interaction.followup.send(embed=_err_embed(f"Voice connect failed: {type(e).__name__}: {e}"))

            try:
                if player.current and player.current.source_type == "radio":
                    player.queue.clear()
                    player.skip()
                player.enqueue(track)
                if not player.is_playing() and not player.is_paused():
                    await asyncio.sleep(0.5)
                    result = await player.play_next()
                    if result:
                        started = True
                    else:
                        logger.warning(f"[Music:{interaction.guild.id}] play_next returned None")
                        if player.queue:
                            player.queue.popleft()
            except Exception as e:
                logger.error(f"[Music:{interaction.guild.id}] play failed: {type(e).__name__}: {e}")
                return await interaction.followup.send(embed=_err_embed(f"Playback error: {type(e).__name__}: {e}"))

        title = t.get("now_playing", "Now playing") if started else t.get("added", "Added to queue")
        embed = _ok_embed(f"{config.Icons.check} {title}", f"[{track.title}]({track.webpage_url})")
        if track.thumbnail:
            embed.set_thumbnail(url=track.thumbnail)
        if track.duration:
            mins, secs = divmod(track.duration, 60)
            embed.add_field(name=t.get("duration_field", "Duration"), value=f"{mins}:{secs:02d}", inline=True)
        embed.add_field(name=t.get("requester_field", "Requested by"), value=interaction.user.mention, inline=True)
        await interaction.followup.send(embed=embed)

    radio_choices = [app_commands.Choice(name=label, value=key) for key, (label, _u) in RADIO_PRESETS.items()]

    @music_group.command(name="radio", description="Play a live radio station (Hitradio Ö3, KroneHit, FM4) or custom URL")
    @app_commands.describe(station="Preset radio station", custom_url="Custom radio stream URL (must be in radio_whitelist)")
    @app_commands.choices(station=radio_choices)
    async def radio_cmd(interaction: Interaction, station: Optional[app_commands.Choice[str]] = None, custom_url: Optional[str] = None):
        await interaction.response.defer()
        ctx = await _check_common(interaction)
        if not ctx:
            return
        conf, t, player, channel = ctx

        if "radio" not in conf.get("allowed_sources", ["youtube", "soundcloud", "radio"]):
            return await interaction.followup.send(embed=_err_embed(t.get("source_blocked", "Radio is disabled.")), ephemeral=True)

        if not station and not custom_url:
            return await interaction.followup.send(embed=_err_embed(t.get("radio_pick_one", "Pick a station or pass a custom_url.")), ephemeral=True)

        logger.info(f"[Music:{interaction.guild.id}] /music radio by {interaction.user.id}: station={station.value if station else None} custom={custom_url!r}")

        if custom_url:
            url = custom_url.strip()
            if not is_safe_radio_url(url):
                return await interaction.followup.send(embed=_err_embed(t.get("invalid_url", "Invalid URL.")), ephemeral=True)
            if not conf.get("allow_all_radios", False):
                whitelist = conf.get("radio_whitelist", []) or []
                if url not in whitelist:
                    return await interaction.followup.send(embed=_err_embed(t.get("url_not_whitelisted", "URL is not on the radio whitelist.")), ephemeral=True)
            label = url
            stream_url = url
        else:
            preset = RADIO_PRESETS.get(station.value)
            if not preset:
                return await interaction.followup.send(embed=_err_embed(t.get("preset_not_found", "Unknown station.")), ephemeral=True)
            label, stream_url = preset

        track = Track(
            title=label,
            stream_url=stream_url,
            webpage_url=stream_url,
            duration=0,
            requester_id=interaction.user.id,
            thumbnail=None,
            source_type="radio",
        )

        async with player.lock:
            try:
                await player.connect(channel)
            except Exception as e:
                logger.error(f"[Music:{interaction.guild.id}] connect failed: {type(e).__name__}: {e}")
                share.music_players.pop(interaction.guild.id, None)
                return await interaction.followup.send(embed=_err_embed(f"Voice connect failed: {type(e).__name__}: {e}"))
            player.queue.clear()
            if player.is_playing() or player.is_paused():
                player.skip()
            player.queue.append(track)
            await player.play_next()

        embed = _ok_embed(f"{config.Icons.check} {t.get('streaming', 'Streaming')}", f"**{label}**")
        embed.add_field(name=t.get("requester_field", "Requested by"), value=interaction.user.mention, inline=True)
        await interaction.followup.send(embed=embed)

    @music_group.command(name="skip", description="Skip the current track")
    async def skip_cmd(interaction: Interaction):
        await interaction.response.defer()
        if interaction.guild is None:
            return await interaction.followup.send(embed=_err_embed("Server only."), ephemeral=True)
        t = _t(interaction.guild.id)
        player = share.music_players.get(interaction.guild.id)
        if not player or not player.is_playing() and not player.is_paused():
            return await interaction.followup.send(embed=_err_embed(t.get("nothing_playing", "Nothing playing.")), ephemeral=True)
        player.skip()
        await interaction.followup.send(embed=_ok_embed(f"{config.Icons.check} {t.get('skipped', 'Skipped.')}"))

    @music_group.command(name="stop", description="Stop playback, clear queue, leave the voice channel")
    async def stop_cmd(interaction: Interaction):
        await interaction.response.defer()
        if interaction.guild is None:
            return await interaction.followup.send(embed=_err_embed("Server only."), ephemeral=True)
        t = _t(interaction.guild.id)
        player = share.music_players.get(interaction.guild.id)
        if not player:
            return await interaction.followup.send(embed=_err_embed(t.get("nothing_playing", "Nothing playing.")), ephemeral=True)
        await player.stop_and_disconnect()
        share.music_players.pop(interaction.guild.id, None)
        await interaction.followup.send(embed=_ok_embed(f"{config.Icons.check} {t.get('stopped', 'Stopped and left voice.')}"))

    @music_group.command(name="pause", description="Pause playback")
    async def pause_cmd(interaction: Interaction):
        await interaction.response.defer()
        if interaction.guild is None:
            return await interaction.followup.send(embed=_err_embed("Server only."), ephemeral=True)
        t = _t(interaction.guild.id)
        player = share.music_players.get(interaction.guild.id)
        if not player or not player.pause():
            return await interaction.followup.send(embed=_err_embed(t.get("nothing_playing", "Nothing playing.")), ephemeral=True)
        await interaction.followup.send(embed=_ok_embed(f"{config.Icons.check} {t.get('paused', 'Paused.')}"))

    @music_group.command(name="resume", description="Resume paused playback")
    async def resume_cmd(interaction: Interaction):
        await interaction.response.defer()
        if interaction.guild is None:
            return await interaction.followup.send(embed=_err_embed("Server only."), ephemeral=True)
        t = _t(interaction.guild.id)
        player = share.music_players.get(interaction.guild.id)
        if not player or not player.resume():
            return await interaction.followup.send(embed=_err_embed(t.get("not_paused", "Nothing is paused.")), ephemeral=True)
        await interaction.followup.send(embed=_ok_embed(f"{config.Icons.check} {t.get('resumed', 'Resumed.')}"))

    @music_group.command(name="queue", description="Show the current music queue")
    async def queue_cmd(interaction: Interaction):
        await interaction.response.defer()
        if interaction.guild is None:
            return await interaction.followup.send(embed=_err_embed("Server only."), ephemeral=True)
        t = _t(interaction.guild.id)
        player = share.music_players.get(interaction.guild.id)
        embed = _ok_embed(f"{config.Icons.message} {t.get('queue_title', 'Music Queue')}")
        if not player or (not player.current and not player.queue):
            embed.description = t.get("queue_empty", "Queue is empty.")
            return await interaction.followup.send(embed=embed)
        if player.current:
            embed.add_field(name=t.get("now_playing", "Now playing"),
                            value=f"[{player.current.title}]({player.current.webpage_url})",
                            inline=False)
        if player.queue:
            lines = []
            for i, tr in enumerate(list(player.queue)[:10], start=1):
                lines.append(f"`{i}.` [{tr.title}]({tr.webpage_url})")
            more = len(player.queue) - 10
            if more > 0:
                lines.append(t.get("queue_more", "...and {n} more").format(n=more))
            embed.add_field(name=t.get("queue_upcoming", "Up next"), value="\n".join(lines), inline=False)
        await interaction.followup.send(embed=embed)

    @music_group.command(name="nowplaying", description="Show the currently playing track")
    async def now_cmd(interaction: Interaction):
        await interaction.response.defer()
        if interaction.guild is None:
            return await interaction.followup.send(embed=_err_embed("Server only."), ephemeral=True)
        t = _t(interaction.guild.id)
        player = share.music_players.get(interaction.guild.id)
        if not player or not player.current:
            return await interaction.followup.send(embed=_err_embed(t.get("nothing_playing", "Nothing playing.")))
        tr = player.current
        embed = _ok_embed(f"{config.Icons.fire} {t.get('now_playing', 'Now playing')}",
                          f"[{tr.title}]({tr.webpage_url})")
        if tr.thumbnail:
            embed.set_thumbnail(url=tr.thumbnail)
        embed.add_field(name=t.get("source_field", "Source"), value=tr.source_type, inline=True)
        if tr.duration:
            mins, secs = divmod(tr.duration, 60)
            embed.add_field(name=t.get("duration_field", "Duration"), value=f"{mins}:{secs:02d}", inline=True)
        await interaction.followup.send(embed=embed)

    @music_group.command(name="volume", description="Set playback volume (0-200)")
    @app_commands.describe(level="Volume percentage 0-200")
    async def volume_cmd(interaction: Interaction, level: int):
        await interaction.response.defer()
        if interaction.guild is None:
            return await interaction.followup.send(embed=_err_embed("Server only."), ephemeral=True)
        t = _t(interaction.guild.id)
        if level < 0 or level > 200:
            return await interaction.followup.send(embed=_err_embed(t.get("volume_invalid", "Volume must be between 0 and 200.")), ephemeral=True)
        player = share.music_players.get(interaction.guild.id)
        if not player:
            return await interaction.followup.send(embed=_err_embed(t.get("nothing_playing", "Nothing playing.")), ephemeral=True)
        player.set_volume(level)
        msg_tpl = t.get("volume_set", "Volume set: {level}%")
        try:
            msg = msg_tpl.format(level=level)
        except (KeyError, IndexError):
            msg = f"{msg_tpl} {level}%"
        await interaction.followup.send(embed=_ok_embed(f"{config.Icons.check} {msg}"))

    bot.tree.add_command(music_group)
