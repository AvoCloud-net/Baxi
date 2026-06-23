import asyncio
import aiohttp
import datetime
import discord
import os
from collections import deque
from discord.ext import tasks, commands

from reds_simple_logger import Logger
from assets.share import globalchat_message_data, phishing_url_list, set_task_status, admin_log
from assets.livestream import (
    twitch_api, youtube_api, tiktok_api, instagram_api, twitter_api,
    IGNotFound, IGRateLimited, IGBlocked, IGTransient,
)
import assets.data as datasys
import config.config as config
import config.auth as auth
import copy
import random

logger = Logger()


class GCDH_Task:
    def __init__(self, bot: commands.AutoShardedBot):
        self.bot = bot
        self.old_data: dict = {}

    @tasks.loop(seconds=15)
    async def sync_globalchat_message_data(self):
        set_task_status("GCDH", "running", "Syncing global chat data...")
        async def save_globalchat_message_data():
            if self.old_data == globalchat_message_data:
                return "ncds", True
            else:
                try:
                    datasys.save_data(
                        1001, "globalchat_message_data", globalchat_message_data
                    )
                    return "Success", True
                except Exception as e:
                    return f"{e}", False

        response, success = await asyncio.create_task(
            save_globalchat_message_data(), name="GCDH"
        )

        if success:
            if response == "ncds":
                logger.debug.info("[GCDH] No change in data detected")
                set_task_status("GCDH", "ok", "No changes detected")
            else:
                logger.debug.success("[GCDH] Data synced with data-structure")
                set_task_status("GCDH", "ok", "Data synced successfully")
                self.old_data = copy.deepcopy(globalchat_message_data)
        else:
            logger.error(f"[GCDH] Sync failed: {response}")
            set_task_status("GCDH", "error", f"Sync failed: {response}")


class UpdateStatsTask:
    def __init__(self, bot: commands.AutoShardedBot):
        self.bot = bot

    @tasks.loop(minutes=10)
    async def update_stats(self):
        set_task_status("UpdateStats", "running", "Counting guilds and users...")
        guild_count = len(self.bot.guilds)

        unique_user_ids = set()
        for guild in self.bot.guilds:
            for member in guild.members:
                if not member.bot:
                    unique_user_ids.add(member.id)

        user_count = len(unique_user_ids)

        stats: dict = dict(datasys.load_data(1001, "stats"))
        stats["guild_count"] = guild_count
        stats["user_count"] = user_count
        top_servers: dict = {f"{server.name} - {server.id}": server.member_count for server in self.bot.guilds}
        stats["top_servers"] = dict(
            sorted(
                top_servers.items(),
                key=lambda item: item[1],
                reverse=True,
            )[:10]
        )
        datasys.save_data(1001, "stats", stats)

        logger.debug.info(
            f"[Stats] Updated stats: Guilds: {guild_count}, Unique Users: {user_count}"
        )

        await self._post_topgg_stats(guild_count)
        set_task_status("UpdateStats", "ok", f"Guilds: {guild_count} · Unique users: {user_count}")

    async def _post_topgg_stats(self, guild_count: int):
        token = auth.TopGG.token
        if not token or token == "YOUR-TOPGG-TOKEN":
            return
        bot_id = self.bot.user.id
        url = f"https://top.gg/api/bots/{bot_id}/stats"
        headers = {"Authorization": token, "Content-Type": "application/json"}
        payload = {"server_count": guild_count, "shard_count": self.bot.shard_count}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers) as resp:
                    if resp.status == 200:
                        logger.debug.success(f"[TopGG] Stats posted: {guild_count} guilds")
                    else:
                        logger.warning(f"[TopGG] Failed to post stats: HTTP {resp.status}")
        except Exception as e:
            logger.error(f"[TopGG] Error posting stats: {e}")


class LivestreamTask:
    """Background task that polls Twitch, YouTube, and TikTok for streamer status.

    Twitch: batched API calls, max 20 checks/minute, polled every 60 seconds.
    YouTube/TikTok: individual checks every 5 minutes (quota-friendly).

    Internal key format for _was_live: "{platform}:{login}" (e.g. "twitch:pokimane").
    Existing entries without a platform field default to "twitch".
    """

    def __init__(self, bot: commands.AutoShardedBot):
        self.bot = bot
        # Track live state: {guild_id: {"platform:login": True/False}}
        self._was_live: dict[int, dict[str, bool]] = {}
        # Round-robin queue for Twitch (fast path, 60s)
        self._check_queue: deque[tuple[int, dict]] = deque()
        # Profile/channel cache keyed by "platform:login"
        self._user_cache: dict[str, dict] = {}

    # ------------------------------------------------------------------ Twitch

    @tasks.loop(seconds=config.Twitch.check_interval_seconds)
    async def check_streams(self):
        try:
            set_task_status("Livestream", "running", "Checking Twitch streams...", extra=f"Queue: {len(self._check_queue)} pending")
            await self._do_twitch_check()
            set_task_status("Livestream", "ok", "Twitch check complete", extra=f"Queue: {len(self._check_queue)} remaining")
        except Exception as e:
            logger.error(f"[Livestream] Error in check_streams: {e}")
            set_task_status("Livestream", "error", f"Error: {e}")

    async def _do_twitch_check(self):
        if not self._check_queue:
            self._rebuild_twitch_queue()
        if not self._check_queue:
            return

        batch: list[tuple[int, dict]] = []
        logins_in_batch: list[str] = []
        seen_logins: set[str] = set()

        while self._check_queue and len(batch) < config.Twitch.max_checks_per_minute:
            item = self._check_queue.popleft()
            guild_id, streamer = item
            login = streamer["login"].lower()
            batch.append(item)
            if login not in seen_logins:
                logins_in_batch.append(login)
                seen_logins.add(login)

        if not logins_in_batch:
            return

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
            live_data = await twitch_api.get_streams(session, logins_in_batch)

            uncached = [l for l in logins_in_batch if f"twitch:{l}" not in self._user_cache]
            if uncached:
                user_data = await twitch_api.get_users(session, uncached)
                for login_key, profile in user_data.items():
                    self._user_cache[f"twitch:{login_key}"] = profile

        for guild_id, streamer in batch:
            login = streamer["login"].lower()
            cache_key = f"twitch:{login}"
            is_live = login in live_data
            stream_info = live_data.get(login)
            await self._process_streamer_result(guild_id, streamer, "twitch", cache_key, is_live, stream_info)

    def _rebuild_twitch_queue(self):
        """Rebuild the round-robin Twitch queue from all enabled guilds."""
        self._check_queue.clear()
        for guild in self.bot.guilds:
            ls_config = dict(datasys.load_data(guild.id, "livestream"))
            if not ls_config.get("enabled", False):
                continue
            for streamer in ls_config.get("streamers", []):
                platform = streamer.get("platform", "twitch")
                if platform == "twitch" and streamer.get("login"):
                    self._check_queue.append((guild.id, streamer))

        logger.info(f"[Livestream] Twitch queue rebuilt: {len(self._check_queue)} checks queued")
        admin_log("info", f"Twitch queue rebuilt: {len(self._check_queue)} checks queued", source="Livestream")

    # --------------------------------------------------- YouTube + TikTok (5 min)

    @tasks.loop(seconds=config.YouTube.check_interval_seconds)
    async def check_yt_tt_streams(self):
        try:
            set_task_status("LivestreamYT", "running", "Checking YouTube/TikTok streams...")
            await self._do_yt_tt_check()
            set_task_status("LivestreamYT", "ok", "YouTube/TikTok check complete")
        except Exception as e:
            logger.error(f"[Livestream] Error in check_yt_tt_streams: {e}")
            set_task_status("LivestreamYT", "error", f"Error: {e}")

    async def _do_yt_tt_check(self):
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
            for guild in self.bot.guilds:
                ls_config = dict(datasys.load_data(guild.id, "livestream"))
                if not ls_config.get("enabled", False):
                    continue
                for streamer in ls_config.get("streamers", []):
                    platform = streamer.get("platform", "twitch")
                    if platform not in ("youtube", "tiktok"):
                        continue
                    if not streamer.get("login"):
                        continue

                    login = streamer["login"]
                    cache_key = f"{platform}:{login}"

                    # Populate profile cache if missing
                    if cache_key not in self._user_cache:
                        if platform == "youtube":
                            info = await youtube_api.get_channel(session, login)
                        else:
                            info = await tiktok_api.get_user_info(session, login)
                        if info:
                            self._user_cache[cache_key] = info

                    # Check live status
                    if platform == "youtube":
                        stream_info = await youtube_api.get_live_stream(session, login)
                    else:
                        stream_info = await tiktok_api.get_live_stream(session, login)

                    is_live = stream_info is not None
                    await self._process_streamer_result(guild.id, streamer, platform, cache_key, is_live, stream_info)

    # --------------------------------------------------------------- Shared logic

    async def _process_streamer_result(
        self,
        guild_id: int,
        streamer: dict,
        platform: str,
        cache_key: str,
        is_live: bool,
        stream_info: dict | None,
    ):
        """Shared post-check logic: detect state changes, update channel/embed, log."""
        if guild_id not in self._was_live:
            self._was_live[guild_id] = {}

        first_check = cache_key not in self._was_live[guild_id]
        was_live = self._was_live[guild_id].get(cache_key, False)
        guild = self.bot.get_guild(guild_id)
        guild_name = guild.name if guild else str(guild_id)
        profile = self._user_cache.get(cache_key, {})
        display = profile.get("display_name", streamer.get("login", cache_key))

        if first_check or is_live != was_live:
            self._was_live[guild_id][cache_key] = is_live
            await self._update_channel(
                guild_id, streamer, platform, is_live, stream_info,
                ping=is_live and not first_check,
            )
            if not first_check:
                if is_live:
                    viewers = stream_info.get("viewer_count", 0) if stream_info else 0
                    game = stream_info.get("game_name", "") if stream_info else ""
                    admin_log("success",
                        f"[{platform}] {display} went LIVE · {viewers} viewers"
                        + (f" · {game}" if game else "")
                        + f" @ {guild_name}",
                        source="Livestream")
                else:
                    admin_log("info", f"[{platform}] {display} went offline @ {guild_name}", source="Livestream")
            else:
                status_str = "live" if is_live else "offline"
                admin_log("info", f"[{platform}] First check: {display} is {status_str} @ {guild_name}", source="Livestream")
        elif is_live and was_live:
            await self._update_embed_content(guild_id, streamer, platform, stream_info)
            viewers = stream_info.get("viewer_count", 0) if stream_info else 0
            game = stream_info.get("game_name", "") if stream_info else ""
            admin_log("info",
                f"[{platform}] Still live: {display} · {viewers} viewers"
                + (f" · {game}" if game else "")
                + f" @ {guild_name}",
                source="Livestream")

    async def _update_channel(
        self,
        guild_id: int,
        streamer: dict,
        platform: str,
        is_live: bool,
        stream_data: dict | None,
        ping: bool = True,
    ):
        """Update the Discord channel name and embed when status changes."""
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return

        login = streamer["login"]
        cache_key = f"{platform}:{login.lower()}"
        channel_id = streamer.get("channel_id")
        message_id = streamer.get("message_id")
        lang = datasys.load_lang_file(guild_id)
        ls_lang = lang.get("systems", {}).get("livestream", {})
        profile = self._user_cache.get(cache_key, {})
        display_name = profile.get("display_name", streamer.get("display_name", login))

        channel = guild.get_channel(int(channel_id)) if channel_id else None
        if not isinstance(channel, discord.TextChannel):
            return

        if is_live:
            new_name = ls_lang.get("channel_name_online", "\U0001f534\u2502{name}").format(name=display_name.lower())
        else:
            new_name = ls_lang.get("channel_name_offline", "\u26ab\u2502{name}").format(name=display_name.lower())

        try:
            if channel.name != new_name:
                await channel.edit(name=new_name)
        except discord.Forbidden:
            logger.error(f"[Livestream] Cannot edit channel name in guild {guild_id}")

        custom_message = streamer.get("custom_message", "").strip() if is_live else ""
        custom_message_position = streamer.get("custom_message_position", "above")
        embed = self._build_embed(ls_lang, display_name, platform, is_live, stream_data, profile, custom_message if custom_message_position == "in_embed" else "")

        if is_live and ping:
            ls_config = dict(datasys.load_data(guild_id, "livestream"))
            ping_role_id = ls_config.get("ping_role", "")
            if ping_role_id:
                game = stream_data.get("game_name", "") if stream_data else ""
                ping_text = ls_lang.get(
                    "ping_message", "{role} \u2014 **{name}** is now live playing **{game}**!"
                ).format(role=f"<@&{ping_role_id}>", name=display_name, game=game)
                if custom_message:
                    ping_text = f"{ping_text}\n{custom_message}"
                try:
                    ping_msg = await channel.send(content=ping_text)
                    await asyncio.sleep(2)
                    await ping_msg.delete()
                except (discord.Forbidden, discord.HTTPException):
                    pass

        msg_content = custom_message if (custom_message and custom_message_position == "above") else None
        try:
            if message_id:
                try:
                    msg = await channel.fetch_message(int(message_id))
                    await msg.edit(content=msg_content, embed=embed)
                    return
                except (discord.NotFound, discord.HTTPException):
                    pass

            msg = await channel.send(content=msg_content, embed=embed)
            self._save_message_id(guild_id, login, platform, msg.id)
        except discord.Forbidden:
            logger.error(f"[Livestream] Cannot send message in guild {guild_id}")

    async def _update_embed_content(
        self,
        guild_id: int,
        streamer: dict,
        platform: str,
        stream_data: dict,
    ):
        """Update embed content for a streamer that is still live."""
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return

        login = streamer["login"]
        cache_key = f"{platform}:{login.lower()}"
        channel_id = streamer.get("channel_id")
        message_id = streamer.get("message_id")
        lang = datasys.load_lang_file(guild_id)
        ls_lang = lang.get("systems", {}).get("livestream", {})
        profile = self._user_cache.get(cache_key, {})
        display_name = profile.get("display_name", streamer.get("display_name", login))

        channel = guild.get_channel(int(channel_id)) if channel_id else None
        if not isinstance(channel, discord.TextChannel) or not message_id:
            return

        custom_message = streamer.get("custom_message", "").strip()
        custom_message_position = streamer.get("custom_message_position", "above")
        embed = self._build_embed(ls_lang, display_name, platform, True, stream_data, profile, custom_message if custom_message_position == "in_embed" else "")
        msg_content = custom_message if (custom_message and custom_message_position == "above") else None

        try:
            msg = await channel.fetch_message(int(message_id))
            await msg.edit(content=msg_content, embed=embed)
        except (discord.NotFound, discord.HTTPException, discord.Forbidden):
            pass

    def _build_embed(
        self,
        ls_lang: dict,
        display_name: str,
        platform: str,
        is_live: bool,
        stream_data: dict | None,
        profile: dict,
        custom_message_in_embed: str = "",
    ) -> discord.Embed:
        """Build the Discord embed for a streamer (platform-aware URLs)."""
        profile_url = self._profile_url(display_name, platform, stream_data)

        if is_live and stream_data:
            embed = discord.Embed(
                title=ls_lang.get("embed_online_title", "{name} is now LIVE!").format(name=display_name),
                description=stream_data.get("title", ""),
                url=profile_url,
                color=discord.Color.green(),
            )

            game = stream_data.get("game_name", "")
            viewers = stream_data.get("viewer_count", 0)
            started = stream_data.get("started_at", "")

            if game:
                embed.add_field(name=ls_lang.get("embed_online_game", "Game"), value=game, inline=True)
            embed.add_field(name=ls_lang.get("embed_online_viewers", "Viewers"), value=str(viewers), inline=True)
            if started:
                embed.add_field(
                    name=ls_lang.get("embed_online_started", "Started"),
                    value=f"<t:{self._iso_to_timestamp(started)}:R>",
                    inline=True,
                )

            thumbnail_url = stream_data.get("thumbnail_url", "")
            if thumbnail_url:
                embed.set_image(url=f"{thumbnail_url}?t={int(asyncio.get_event_loop().time())}")

            if profile.get("profile_image_url"):
                embed.set_thumbnail(url=profile["profile_image_url"])

            if custom_message_in_embed:
                embed.add_field(name="\u200b", value=custom_message_in_embed, inline=False)

        else:
            embed = discord.Embed(
                title=ls_lang.get("embed_offline_title", "{name} is offline").format(name=display_name),
                description=ls_lang.get(
                    "embed_offline_description", "{name} is not streaming right now. Check back later!"
                ).format(name=display_name),
                url=profile_url,
                color=discord.Color.red(),
            )

            offline_img = profile.get("offline_image_url", "")
            if offline_img:
                embed.set_image(url=offline_img)

            if profile.get("profile_image_url"):
                embed.set_thumbnail(url=profile["profile_image_url"])

        embed.set_footer(text=ls_lang.get("embed_footer", "Baxi Livestream - avocloud.net"))
        return embed

    @staticmethod
    def _profile_url(display_name: str, platform: str, stream_data: dict | None) -> str:
        """Return the platform-appropriate profile/stream URL."""
        name = display_name.lower()
        if platform == "youtube":
            # Link to live video if available, otherwise to channel
            video_id = (stream_data or {}).get("video_id", "")
            if video_id:
                return f"https://www.youtube.com/watch?v={video_id}"
            return f"https://www.youtube.com/@{name}"
        elif platform == "tiktok":
            return f"https://www.tiktok.com/@{name}/live"
        else:  # twitch (default)
            return f"https://twitch.tv/{name}"

    async def on_embed_deleted(self, message: discord.Message):
        """Resend the livestream embed if it was accidentally deleted."""
        if message.guild is None:
            return

        guild_id = message.guild.id
        ls_config = dict(datasys.load_data(guild_id, "livestream"))
        if not ls_config.get("enabled", False):
            return

        for streamer in ls_config.get("streamers", []):
            if str(streamer.get("message_id", "")) != str(message.id):
                continue

            platform = streamer.get("platform", "twitch")
            login = streamer["login"]
            cache_key = f"{platform}:{login.lower()}"
            streamer["message_id"] = ""
            datasys.save_data(guild_id, "livestream", ls_config)

            is_live = self._was_live.get(guild_id, {}).get(cache_key, False)
            stream_data = None
            if is_live:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                    if platform == "youtube":
                        stream_data = await youtube_api.get_live_stream(session, login)
                    elif platform == "tiktok":
                        stream_data = await tiktok_api.get_live_stream(session, login)
                    else:
                        live_data = await twitch_api.get_streams(session, [login.lower()])
                        stream_data = live_data.get(login.lower())

            await self._update_channel(guild_id, streamer, platform, is_live, stream_data, ping=False)
            break

    def _save_message_id(self, guild_id: int, login: str, platform: str, message_id: int):
        """Save the message ID back to the guild config so we can edit it later."""
        ls_config = dict(datasys.load_data(guild_id, "livestream"))
        streamers = ls_config.get("streamers", [])
        for streamer in streamers:
            if (
                streamer.get("login", "").lower() == login.lower()
                and streamer.get("platform", "twitch") == platform
            ):
                streamer["message_id"] = str(message_id)
                break
        ls_config["streamers"] = streamers
        datasys.save_data(guild_id, "livestream", ls_config)

    @staticmethod
    def _iso_to_timestamp(iso_str: str) -> int:
        """Convert ISO 8601 string to Unix timestamp."""
        from datetime import datetime, timezone

        try:
            dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
            return int(dt.timestamp())
        except (ValueError, AttributeError):
            return 0


STAT_TYPES = ["members", "humans", "bots", "channels", "roles"]


class StatsChannelsTask:
    """Background task that updates voice channel names with server statistics.

    Runs every 10 minutes to stay within Discord's channel rename rate limits.
    Only updates a channel if the displayed value has actually changed.
    """

    def __init__(self, bot: commands.AutoShardedBot):
        self.bot = bot
        # Cache last displayed values: {guild_id: {stat_type: last_count}}
        self._last_values: dict[int, dict[str, int]] = {}

    @tasks.loop(minutes=10)
    async def update_stats_channels(self):
        try:
            set_task_status("StatsChannels", "running", "Updating stats channels...")
            await self._do_update()
            set_task_status("StatsChannels", "ok", "Stats channels updated")
        except Exception as e:
            logger.error(f"[StatsChannels] Error in update_stats_channels: {e}")
            set_task_status("StatsChannels", "error", f"Error: {e}")

    async def _do_update(self):
        for guild in self.bot.guilds:
            try:
                sc_config = dict(datasys.load_data(guild.id, "stats_channels"))
                if not sc_config.get("enabled", False):
                    continue

                stats_cfg = sc_config.get("stats", {})
                counts = self._compute_counts(guild)

                for stat_type in STAT_TYPES:
                    stat = stats_cfg.get(stat_type, {})
                    if not stat.get("enabled", False):
                        continue

                    channel_id = stat.get("channel_id", "")
                    if not channel_id:
                        continue

                    channel = guild.get_channel(int(channel_id))
                    if not isinstance(channel, discord.VoiceChannel):
                        continue

                    count = counts.get(stat_type, 0)
                    last = self._last_values.get(guild.id, {}).get(stat_type)
                    if last == count:
                        continue

                    template = stat.get("template", f"{stat_type.capitalize()}: {{count}}")
                    new_name = template.replace("{count}", str(count))

                    try:
                        await channel.edit(name=new_name)
                        if guild.id not in self._last_values:
                            self._last_values[guild.id] = {}
                        old_val = self._last_values.get(guild.id, {}).get(stat_type, "?")
                        self._last_values[guild.id][stat_type] = count
                        logger.debug.info(
                            f"[StatsChannels] {guild.id} | {stat_type} -> {new_name}"
                        )
                        admin_log("info",
                            f"{guild.name} · {stat_type}: {old_val} → {count} ({new_name})",
                            source="StatsChannels")
                    except discord.Forbidden:
                        logger.error(
                            f"[StatsChannels] Cannot edit channel in guild {guild.id}"
                        )
                        admin_log("error", f"{guild.name} · Cannot edit {stat_type} channel (Forbidden)", source="StatsChannels")
                    except discord.HTTPException as e:
                        logger.error(
                            f"[StatsChannels] HTTP error for guild {guild.id}: {e}"
                        )
                        admin_log("error", f"{guild.name} · HTTP error for {stat_type}: {e}", source="StatsChannels")
            except Exception as e:
                logger.error(f"[StatsChannels] Error processing guild {guild.id}: {e}")

    @staticmethod
    def _compute_counts(guild: discord.Guild) -> dict[str, int]:
        all_members = guild.members
        bots = sum(1 for m in all_members if m.bot)
        humans = len(all_members) - bots
        return {
            "members": guild.member_count or len(all_members),
            "humans": humans,
            "bots": bots,
            "channels": len(guild.channels),
            "roles": len(guild.roles),
        }


class TempActionsTask:
    """Background task that checks expired temp-bans and timeouts, unbans users and sends DMs."""

    def __init__(self, bot: commands.AutoShardedBot):
        self.bot = bot

    @tasks.loop(seconds=60)
    async def check_temp_actions(self):
        try:
            set_task_status("TempActions", "running", "Checking expired bans/mutes...")
            await self._do_check()
            set_task_status("TempActions", "ok", "Temp actions checked")
        except Exception as e:
            logger.error(f"[TempActions] Error in check_temp_actions: {e}")
            set_task_status("TempActions", "error", f"Error: {e}")

    @staticmethod
    def _parse_expiry(value: str) -> datetime.datetime:
        """Parse a stored expires_at ISO string to an aware-UTC datetime.

        Writers are inconsistent: buttons.py stores naive UTC (utcnow().isoformat())
        while commands.py stores aware UTC (now(timezone.utc).isoformat()). Normalize
        both to aware-UTC so comparisons never raise 'offset-naive vs offset-aware'.
        """
        dt = datetime.datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt

    async def _do_check(self):
        now = datetime.datetime.now(datetime.timezone.utc)

        for guild in self.bot.guilds:
            try:
                ta = datasys.load_temp_actions(guild.id)
                changed = False

                # --- Temp bans ---
                remaining_bans = []
                for entry in ta.get("bans", []):
                    try:
                        expires_at = self._parse_expiry(entry["expires_at"])
                        if now >= expires_at:
                            user_id = int(entry["user_id"])
                            try:
                                user = await self.bot.fetch_user(user_id)
                                await guild.unban(user, reason="Temporary ban expired")
                                admin_log("info",
                                    f"Temp ban expired: {user} ({user_id}) @ {guild.name} · Reason: {entry.get('reason', 'N/A')}",
                                    source="TempActions")
                                try:
                                    dm_embed = discord.Embed(
                                        title=f"ACTION // BAN EXPIRED // {entry.get('guild_name', guild.name)}",
                                        description="Your temporary ban has been lifted. You may rejoin the server.",
                                        color=discord.Color.green(),
                                    )
                                    dm_embed.add_field(name="Original reason", value=entry.get("reason", "N/A"), inline=False)
                                    dm_embed.set_footer(text="Baxi - avocloud.net")
                                    await user.send(embed=dm_embed)
                                except (discord.Forbidden, discord.HTTPException):
                                    pass
                                changed = True
                            except discord.NotFound:
                                changed = True  # Already unbanned, drop entry
                            except discord.HTTPException:
                                remaining_bans.append(entry)  # Retry next cycle
                        else:
                            remaining_bans.append(entry)
                    except Exception as e:
                        logger.error(f"[TempActions] Error processing ban entry: {e}")
                        remaining_bans.append(entry)
                ta["bans"] = remaining_bans

                # --- Temp timeouts (DM on expiry) ---
                remaining_timeouts = []
                for entry in ta.get("timeouts", []):
                    try:
                        expires_at = self._parse_expiry(entry["expires_at"])
                        if now >= expires_at:
                            user_id = int(entry["user_id"])
                            try:
                                user = await self.bot.fetch_user(user_id)
                                admin_log("info",
                                    f"Temp mute expired: {user} ({user_id}) @ {guild.name} · Reason: {entry.get('reason', 'N/A')}",
                                    source="TempActions")
                                dm_embed = discord.Embed(
                                    title=f"ACTION // MUTE EXPIRED // {entry.get('guild_name', guild.name)}",
                                    description="You can now send messages again.",
                                    color=discord.Color.green(),
                                )
                                dm_embed.add_field(name="Original reason", value=entry.get("reason", "N/A"), inline=False)
                                dm_embed.set_footer(text="Baxi - avocloud.net")
                                await user.send(embed=dm_embed)
                            except (discord.Forbidden, discord.HTTPException, discord.NotFound):
                                pass
                            changed = True
                        else:
                            remaining_timeouts.append(entry)
                    except Exception as e:
                        logger.error(f"[TempActions] Error processing timeout entry: {e}")
                        remaining_timeouts.append(entry)
                ta["timeouts"] = remaining_timeouts

                if changed:
                    datasys.save_temp_actions(guild.id, ta)

            except Exception as e:
                logger.error(f"[TempActions] Error for guild {guild.id}: {e}")


class AntiRaidTask:
    """Rolls the per-guild Anti-Raid windows every 5s: updates the learned baselines,
    detects message floods, and lifts expired lockdowns (restoring changed settings)."""

    def __init__(self, bot: commands.AutoShardedBot):
        self.bot = bot

    @tasks.loop(seconds=5)
    async def tick(self):
        try:
            set_task_status("AntiRaid", "running", "Rolling raid windows...")
            from assets.moderation.antiraid import antiraid
            for guild in list(self.bot.guilds):
                try:
                    await antiraid.tick(guild, self.bot)
                except Exception as e:
                    logger.error(f"[AntiRaid] tick error @ {guild.id}: {e}")
            set_task_status("AntiRaid", "ok", "Raid windows rolled")
        except Exception as e:
            logger.error(f"[AntiRaid] Error in tick: {e}")
            set_task_status("AntiRaid", "error", f"Error: {e}")


class PhishingListTask:
    """Background task that downloads and refreshes the phishing domain list every 12 hours.

    Source: https://github.com/Discord-AntiScam/scam-links
    """

    @tasks.loop(hours=12)
    async def update_phishing_list(self):
        try:
            set_task_status("PhishingList", "running", "Downloading phishing domain list...")
            await self._fetch_list()
            set_task_status("PhishingList", "ok", f"Loaded {len(phishing_url_list)} phishing domains")
        except Exception as e:
            logger.error(f"[PhishingList] Error updating phishing list: {e}")
            set_task_status("PhishingList", "error", f"Error: {e}")

    async def _fetch_list(self):
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
            async with session.get(config.Chatfilter.phishing_list_url) as response:
                if response.status == 200:
                    text = await response.text()
                    domains = set()
                    for line in text.splitlines():
                        line = line.strip().lower()
                        if line and not line.startswith("#"):
                            domains.add(line)
                    phishing_url_list.clear()
                    phishing_url_list.update(domains)
                    logger.debug.success(
                        f"[PhishingList] Updated: {len(phishing_url_list)} phishing domains loaded"
                    )
                else:
                    logger.error(f"[PhishingList] Fetch returned HTTP {response.status}")


class GarbageCollectorTask:
    """Background task that deletes log entries older than 30 days.

    Runs once per day and cleans:
    - data/1001/chatfilter_log.json
    - data/1001/globalchat_message_data.json  (in-memory + on disk)
    - data/<guild>/tickets.json  (per guild)
    - data/1001/transcripts.json
    """

    RETENTION_DAYS = 30

    @tasks.loop(hours=24)
    async def collect(self):
        try:
            set_task_status("GarbageCollector", "running", "Cleaning log entries older than 30 days...")
            removed = self._do_collect()
            parts = [f"{v} {k}" for k, v in removed.items() if v > 0]
            summary = " · ".join(parts) if parts else "nothing to clean"
            logger.debug.success(f"[GC] Cleanup complete: {summary}")
            set_task_status("GarbageCollector", "ok", f"Cleaned: {summary}")
        except Exception as e:
            logger.error(f"[GC] Error during garbage collection: {e}")
            set_task_status("GarbageCollector", "error", f"Error: {e}")

    @staticmethod
    def _is_old_chatfilter(entry: dict, cutoff: datetime.datetime) -> bool:
        ts_str = entry.get("timestamp", "")
        if not ts_str:
            return False
        try:
            dt = datetime.datetime.strptime(ts_str, "%d.%m.%Y - %H:%M")
            return dt < cutoff
        except ValueError:
            return False

    @staticmethod
    def _is_old_globalchat(entry: dict, cutoff: datetime.datetime) -> bool:
        mid = None
        if entry.get("messages"):
            mid = entry["messages"][0].get("mid")
        elif entry.get("replies"):
            mid = entry["replies"][0].get("mid")
        if mid is None:
            return False
        try:
            ts_ms = (int(mid) >> 22) + 1420070400000
            dt = datetime.datetime.fromtimestamp(ts_ms / 1000)
            return dt < cutoff
        except (ValueError, TypeError):
            return False

    @staticmethod
    def _is_old_transcript(entry: dict, cutoff: datetime.datetime) -> bool:
        ts_str = entry.get("created_at") or entry.get("timestamp")
        if not ts_str:
            return False
        try:
            dt = datetime.datetime.fromisoformat(ts_str)
            if dt.tzinfo is not None:
                dt = dt.replace(tzinfo=None)
            return dt < cutoff
        except ValueError:
            return False

    @staticmethod
    def _is_old_ticket(ticket: dict, cutoff: datetime.datetime) -> bool:
        transcript = ticket.get("transcript", [])
        for msg in reversed(transcript):
            ts_str = msg.get("timestamp")
            if ts_str:
                try:
                    dt = datetime.datetime.fromisoformat(ts_str)
                    if dt.tzinfo is not None:
                        dt = dt.replace(tzinfo=None)
                    return dt < cutoff
                except ValueError:
                    continue
        return False

    def _do_collect(self) -> dict:
        cutoff = datetime.datetime.now() - datetime.timedelta(days=self.RETENTION_DAYS)
        removed = {"chatfilter": 0, "globalchat": 0, "tickets": 0, "transcripts": 0}

        # --- chatfilter_log.json ---
        try:
            log: dict = datasys.load_data(1001, "chatfilter_log")
            cleaned = {
                k: v for k, v in log.items()
                if not self._is_old_chatfilter(v, cutoff)
            }
            removed["chatfilter"] = len(log) - len(cleaned)
            if removed["chatfilter"] > 0:
                datasys.save_data(1001, "chatfilter_log", cleaned)
        except Exception as e:
            logger.error(f"[GC] chatfilter_log: {e}")

        # --- globalchat_message_data.json ---
        # Operate on the shared in-memory dict so GCDH picks up the change.
        try:
            stale_keys = [
                k for k, v in list(globalchat_message_data.items())
                if self._is_old_globalchat(v, cutoff)
            ]
            for k in stale_keys:
                globalchat_message_data.pop(k, None)
            removed["globalchat"] = len(stale_keys)
            if stale_keys:
                datasys.save_data(1001, "globalchat_message_data", dict(globalchat_message_data))
        except Exception as e:
            logger.error(f"[GC] globalchat_message_data: {e}")

        # --- open_tickets per guild (via repo facade) ---
        try:
            import assets.db as _db
            for guild_id in _db.guild_ids():
                try:
                    tickets: dict = dict(datasys.load_data(guild_id, "open_tickets"))
                    cleaned_tickets = {
                        tid: t for tid, t in tickets.items()
                        if not self._is_old_ticket(t, cutoff)
                    }
                    delta = len(tickets) - len(cleaned_tickets)
                    removed["tickets"] += delta
                    if delta > 0:
                        datasys.save_data(guild_id, "open_tickets", cleaned_tickets)
                except Exception as _inner:
                    logger.error(f"[GC] tickets guild {guild_id}: {_inner}")
        except Exception as e:
            logger.error(f"[GC] tickets: {e}")

        # --- transcripts.json ---
        try:
            transcripts: dict = datasys.load_data(1001, "transcripts")
            cleaned_tr = {
                k: v for k, v in transcripts.items()
                if not self._is_old_transcript(v, cutoff)
            }
            removed["transcripts"] = len(transcripts) - len(cleaned_tr)
            if removed["transcripts"] > 0:
                datasys.save_data(1001, "transcripts", cleaned_tr)
        except Exception as e:
            logger.error(f"[GC] transcripts: {e}")

        return removed


class YouTubeVideoTask:
    """Background task that polls YouTube channels for new video uploads via RSS.

    Every 10 minutes, for each guild with youtube_videos enabled:
    - Fetches the latest video from the public RSS feed for each tracked channel
    - Compares video_id to the stored last_video_id
    - On first check (last_video_id == ""): stores ID silently without notifying
    - On new video: sends embed to alert_channel, pings role if configured
    - Errors for a single channel are logged and skipped; the loop continues
    """

    def __init__(self, bot: commands.AutoShardedBot):
        self.bot = bot

    @tasks.loop(seconds=config.YouTubeVideos.check_interval_seconds)
    async def check_videos(self):
        try:
            set_task_status("YouTubeVideos", "running", "Checking YouTube channels for new uploads...")
            await self._do_check()
            set_task_status("YouTubeVideos", "ok", "YouTube video check complete")
        except Exception as e:
            logger.error(f"[YouTubeVideos] Unexpected error: {e}")
            set_task_status("YouTubeVideos", "error", f"Unexpected error: {e}")

    @check_videos.before_loop
    async def before_check_videos(self):
        await self.bot.wait_until_ready()
        await self._do_check()  # run once immediately on startup

    async def _do_check(self):
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
            # Collect all unique channel IDs and cache configs
            all_channel_ids = set()
            guild_data = {}  # guild_id -> (yv_config, [(ch_entry, channel_id), ...])
            
            for guild in self.bot.guilds:
                yv_config = dict(datasys.load_data(guild.id, "youtube_videos"))
                if not yv_config.get("enabled", False):
                    continue
                
                channels = yv_config.get("channels", [])
                guild_data[guild.id] = (yv_config, [])
                for ch_entry in channels:
                    channel_id = ch_entry.get("channel_id", "")
                    if channel_id:
                        all_channel_ids.add(channel_id)
                        guild_data[guild.id][1].append((ch_entry, channel_id))
            
            if not all_channel_ids:
                return
            
            # Fetch all videos once (deduplicated)
            video_cache = {}
            logger.info(f"[YouTubeVideos] Checking {len(all_channel_ids)} unique channels across {len(guild_data)} guilds")
            import random as _random
            channel_list = list(all_channel_ids)
            _random.shuffle(channel_list)  # vary order each run so the pattern isn't fixed
            for idx, channel_id in enumerate(channel_list):
                try:
                    video = await youtube_api.get_latest_video(session, channel_id)
                    video_cache[channel_id] = video
                    logger.debug.info(f"[YouTubeVideos] {channel_id}: video={video['video_id'] if video else None}")
                except Exception as e:
                    logger.error(f"[YouTubeVideos] Failed to fetch {channel_id}: {e}")
                    video_cache[channel_id] = None
                # Small randomized spacing so checks don't arrive as one identifiable burst.
                if idx < len(channel_list) - 1:
                    await asyncio.sleep(_random.uniform(0.6, 2.0))
            
            # Process each guild with cached videos and cached config
            for guild in self.bot.guilds:
                if guild.id not in guild_data:
                    continue
                try:
                    yv_config, channel_list = guild_data[guild.id]
                    changed = await self._check_guild(session, guild, video_cache, channel_list, yv_config)
                    if changed:
                        datasys.save_data(guild.id, "youtube_videos", yv_config)
                except Exception as e:
                    logger.error(f"[YouTubeVideos] Error processing guild {guild.id}: {e}")

    async def _check_guild(self, session: aiohttp.ClientSession, guild, video_cache: dict, channel_list: list, yv_config: dict) -> bool:
        global_alert_channel_id = str(yv_config.get("alert_channel", "")).strip()
        ping_role_id = str(yv_config.get("ping_role", "")).strip()
        changed = False

        lang = datasys.load_lang_file(guild.id)
        yv_lang = lang.get("systems", {}).get("youtube_videos", {})

        # Cache resolved Discord channel objects to avoid duplicate fetches
        resolved_channels: dict = {}

        for ch_entry, channel_id in channel_list:
            try:
                # Resolve per-channel alert channel, fall back to global
                per_alert = str(ch_entry.get("alert_channel", "")).strip()
                alert_channel_id = per_alert or global_alert_channel_id
                if not alert_channel_id:
                    logger.warning(f"[YouTubeVideos] No alert channel for {channel_id} in {guild.name}, skipping")
                    continue

                if alert_channel_id not in resolved_channels:
                    try:
                        alert_ch = guild.get_channel(int(alert_channel_id))
                        if not alert_ch:
                            alert_ch = await self.bot.fetch_channel(int(alert_channel_id))
                    except (ValueError, TypeError, discord.NotFound, discord.Forbidden, discord.HTTPException):
                        alert_ch = None
                    resolved_channels[alert_channel_id] = alert_ch

                alert_channel = resolved_channels[alert_channel_id]
                if not alert_channel or not isinstance(alert_channel, discord.TextChannel):
                    logger.error(f"[YouTubeVideos] Alert channel {alert_channel_id} not found or not a text channel in {guild.name}")
                    continue
                if not alert_channel.permissions_for(guild.me).send_messages:
                    logger.error(f"[YouTubeVideos] Bot lacks 'Send Messages' permission in alert channel {alert_channel.name} ({alert_channel_id}) in {guild.name}")
                    continue

                # Use cached video instead of fetching again
                video = video_cache.get(channel_id)
                if video is None:
                    continue

                last_video_id        = ch_entry.get("last_video_id", "")
                last_video_published = ch_entry.get("last_video_published", "")
                logger.debug.info(f"[YouTubeVideos] {channel_id} @{guild.name}: last={last_video_id!r} new={video['video_id']!r}")

                if not last_video_id:
                    # First run: seed silently without notifying
                    ch_entry["last_video_id"]        = video["video_id"]
                    ch_entry["last_video_published"] = video.get("published", "")
                    changed = True
                    admin_log(
                        "info",
                        f"[YouTubeVideos] Seeded {ch_entry.get('display_name', channel_id)} "
                        f"@ {guild.name}: {video['video_id']}",
                        source="YouTubeVideos",
                    )
                    continue

                if video["video_id"] == last_video_id:
                    continue  # No new video

                # Check published timestamp -  only notify if video is strictly newer
                # This prevents re-alerts when a video is deleted and an older one surfaces
                video_published = video.get("published", "")
                if video_published and last_video_published:
                    try:
                        from datetime import datetime
                        dt_new  = datetime.fromisoformat(video_published.replace("Z", "+00:00"))
                        dt_last = datetime.fromisoformat(last_video_published.replace("Z", "+00:00"))
                        if dt_new <= dt_last:
                            # RSS surfaced an older video (e.g. newest was deleted) -  update silently
                            ch_entry["last_video_id"]        = video["video_id"]
                            ch_entry["last_video_published"] = video_published
                            changed = True
                            continue
                    except (ValueError, AttributeError):
                        pass  # Can't parse timestamps -  fall through to notify

                # New video detected -  send notification
                ch_entry["last_video_id"]        = video["video_id"]
                ch_entry["last_video_published"] = video_published
                changed = True

                display_name = ch_entry.get("display_name", channel_id)
                profile_img  = ch_entry.get("profile_image_url", "")

                try:
                    embed = self._build_embed(video, display_name, profile_img, yv_lang)
                except Exception as e:
                    logger.error(f"[YouTubeVideos] Error building embed for {channel_id}: {e}")
                    # Fallback to simple embed
                    embed = discord.Embed(
                        title=video.get("title", "New Video"),
                        url=video.get("url", ""),
                        color=discord.Color.from_rgb(255, 0, 0),
                    )

                ping_content = f"<@&{ping_role_id}>" if ping_role_id else None

                try:
                    logger.info(f"[YouTubeVideos] Sending alert to {alert_channel.name} ({alert_channel_id}) in {guild.name}: \"{video['title']}\"")
                    sent_msg = await alert_channel.send(content=ping_content, embed=embed)
                    logger.info(f"[YouTubeVideos] Message sent successfully: {sent_msg.id}")
                    admin_log(
                        "success",
                        f"[YouTubeVideos] New video by {display_name} @ {guild.name}: "
                        f"\"{video['title']}\" ({video['video_id']})",
                        source="YouTubeVideos",
                    )
                except discord.Forbidden as e:
                    logger.error(
                        f"[YouTubeVideos] Permission denied sending to {alert_channel.name} ({alert_channel_id}) "
                        f"in guild {guild.id}: {e}"
                    )
                    admin_log(
                        "error",
                        f"[YouTubeVideos] Permission error: Cannot send to {alert_channel.name} - {e}",
                        source="YouTubeVideos",
                    )
                except discord.HTTPException as e:
                    logger.error(
                        f"[YouTubeVideos] HTTP error sending to {alert_channel.name} ({alert_channel_id}) "
                        f"in guild {guild.id}: {e}"
                    )
                    admin_log(
                        "error",
                        f"[YouTubeVideos] HTTP error: Cannot send to {alert_channel.name} - {e}",
                        source="YouTubeVideos",
                    )
                except Exception as e:
                    logger.error(
                        f"[YouTubeVideos] Unexpected error sending to {alert_channel.name} ({alert_channel_id}) "
                        f"in guild {guild.id}: {type(e).__name__}: {e}"
                    )

            except Exception as e:
                logger.error(
                    f"[YouTubeVideos] Error checking channel "
                    f"{channel_id} in guild {guild.id}: {e}"
                )

        return changed

    @staticmethod
    def _build_embed(video: dict, display_name: str, profile_image_url: str, yv_lang: dict) -> discord.Embed:
        description = yv_lang.get("embed_description", "**{name}** just uploaded a new video!").format(name=display_name)
        embed = discord.Embed(
            title=video.get("title", "New Video"),
            url=video.get("url", ""),
            color=discord.Color.from_rgb(255, 0, 0),
            description=description,
        )
        thumbnail = video.get("thumbnail_url", "")
        if thumbnail:
            embed.set_image(url=thumbnail)
        if profile_image_url:
            embed.set_thumbnail(url=profile_image_url)

        published = video.get("published", "")
        if published:
            try:
                from datetime import datetime, timezone
                dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
                field_name = yv_lang.get("embed_field_published", "Published")
                embed.add_field(name=field_name, value=f"<t:{int(dt.timestamp())}:R>", inline=True)
            except (ValueError, AttributeError):
                pass

        footer = yv_lang.get("embed_footer", "Baxi YouTube Videos · avocloud.net")
        embed.set_footer(text=footer)
        return embed


class TikTokVideoTask:
    """Background task that polls TikTok accounts for new posts via yt-dlp.

    Every 10 minutes, for each guild with tiktok enabled:
    - Fetches the latest video for each tracked account
    - Compares video_id to stored last_video_id
    - On first check (last_video_id == ""): seeds silently without notifying
    - On new video: sends embed to alert_channel, pings role if configured
    """

    def __init__(self, bot: commands.AutoShardedBot):
        self.bot = bot

    @tasks.loop(seconds=config.TikTokVideos.check_interval_seconds)
    async def check_videos(self):
        try:
            set_task_status("TikTokVideos", "running", "Checking TikTok accounts for new posts...")
            await self._do_check()
            set_task_status("TikTokVideos", "ok", "TikTok video check complete")
        except Exception as e:
            logger.error(f"[TikTokVideos] Unexpected error: {e}")
            set_task_status("TikTokVideos", "error", f"Unexpected error: {e}")

    @check_videos.before_loop
    async def before_check_videos(self):
        await self.bot.wait_until_ready()
        await self._do_check()

    async def _do_check(self):
        all_usernames: set = set()
        guild_data: dict = {}

        for guild in self.bot.guilds:
            tt_config = dict(datasys.load_data(guild.id, "tiktok"))
            if not tt_config.get("enabled", False):
                continue
            channels = tt_config.get("channels", [])
            guild_data[guild.id] = (tt_config, [])
            for ch_entry in channels:
                username = ch_entry.get("username", "")
                if username:
                    all_usernames.add(username)
                    guild_data[guild.id][1].append((ch_entry, username))

        if not all_usernames:
            return

        video_cache: dict = {}
        logger.info(f"[TikTokVideos] Checking {len(all_usernames)} unique accounts across {len(guild_data)} guilds")
        for username in all_usernames:
            try:
                video = await tiktok_api.get_latest_video(username)
                video_cache[username] = video
                logger.debug.info(f"[TikTokVideos] @{username}: video={video['video_id'] if video else None}")
            except Exception as e:
                logger.error(f"[TikTokVideos] Failed to fetch @{username}: {e}")
                video_cache[username] = None

        for guild in self.bot.guilds:
            if guild.id not in guild_data:
                continue
            try:
                tt_config, channel_list = guild_data[guild.id]
                changed = await self._check_guild(guild, video_cache, channel_list, tt_config)
                if changed:
                    datasys.save_data(guild.id, "tiktok", tt_config)
            except Exception as e:
                logger.error(f"[TikTokVideos] Error processing guild {guild.id}: {e}")

    async def _check_guild(self, guild, video_cache: dict, channel_list: list, tt_config: dict) -> bool:
        global_alert_channel_id = str(tt_config.get("alert_channel", "")).strip()
        ping_role_id = str(tt_config.get("ping_role", "")).strip()
        changed = False

        lang = datasys.load_lang_file(guild.id)
        tt_lang = lang.get("systems", {}).get("tiktok", {})

        resolved_channels: dict = {}

        for ch_entry, username in channel_list:
            try:
                per_alert = str(ch_entry.get("alert_channel", "")).strip()
                alert_channel_id = per_alert or global_alert_channel_id
                if not alert_channel_id:
                    logger.warning(f"[TikTokVideos] No alert channel for @{username} in {guild.name}, skipping")
                    continue

                if alert_channel_id not in resolved_channels:
                    try:
                        alert_ch = guild.get_channel(int(alert_channel_id))
                        if not alert_ch:
                            alert_ch = await self.bot.fetch_channel(int(alert_channel_id))
                    except (ValueError, TypeError, discord.NotFound, discord.Forbidden, discord.HTTPException):
                        alert_ch = None
                    resolved_channels[alert_channel_id] = alert_ch

                alert_channel = resolved_channels[alert_channel_id]
                if not alert_channel or not isinstance(alert_channel, discord.TextChannel):
                    logger.error(f"[TikTokVideos] Alert channel {alert_channel_id} not found or not text channel in {guild.name}")
                    continue
                if not alert_channel.permissions_for(guild.me).send_messages:
                    logger.error(f"[TikTokVideos] No send permission in {alert_channel.name} in {guild.name}")
                    continue

                video = video_cache.get(username)
                if video is None:
                    continue

                last_video_id = ch_entry.get("last_video_id", "")
                last_video_published = ch_entry.get("last_video_published", "")

                if not last_video_id:
                    ch_entry["last_video_id"] = video["video_id"]
                    ch_entry["last_video_published"] = video.get("published", "")
                    changed = True
                    admin_log("info", f"[TikTokVideos] Seeded @{username} @ {guild.name}: {video['video_id']}", source="TikTokVideos")
                    continue

                if video["video_id"] == last_video_id:
                    continue

                video_published = video.get("published", "")
                if video_published and last_video_published:
                    try:
                        from datetime import datetime
                        dt_new = datetime.fromisoformat(video_published.replace("Z", "+00:00"))
                        dt_last = datetime.fromisoformat(last_video_published.replace("Z", "+00:00"))
                        if dt_new <= dt_last:
                            ch_entry["last_video_id"] = video["video_id"]
                            ch_entry["last_video_published"] = video_published
                            changed = True
                            continue
                    except (ValueError, AttributeError):
                        pass

                ch_entry["last_video_id"] = video["video_id"]
                ch_entry["last_video_published"] = video_published
                changed = True

                display_name = ch_entry.get("display_name", username)
                profile_img = ch_entry.get("profile_image_url", "")

                try:
                    embed = self._build_embed(video, display_name, profile_img, tt_lang)
                except Exception as e:
                    logger.error(f"[TikTokVideos] Error building embed for @{username}: {e}")
                    embed = discord.Embed(
                        title=video.get("title", "New TikTok"),
                        url=video.get("url", ""),
                        color=discord.Color.from_rgb(1, 1, 1),
                    )

                ping_content = f"<@&{ping_role_id}>" if ping_role_id else None

                try:
                    logger.info(f"[TikTokVideos] Sending alert to {alert_channel.name} in {guild.name}: \"{video['title']}\"")
                    sent_msg = await alert_channel.send(content=ping_content, embed=embed)
                    logger.info(f"[TikTokVideos] Message sent: {sent_msg.id}")
                    admin_log("success", f"[TikTokVideos] New post by @{display_name} @ {guild.name}: \"{video['title']}\"", source="TikTokVideos")
                except discord.Forbidden as e:
                    logger.error(f"[TikTokVideos] Permission denied in {alert_channel.name}: {e}")
                    admin_log("error", f"[TikTokVideos] Permission error: {e}", source="TikTokVideos")
                except discord.HTTPException as e:
                    logger.error(f"[TikTokVideos] HTTP error in {alert_channel.name}: {e}")
                    admin_log("error", f"[TikTokVideos] HTTP error: {e}", source="TikTokVideos")
                except Exception as e:
                    logger.error(f"[TikTokVideos] Unexpected send error: {type(e).__name__}: {e}")

            except Exception as e:
                logger.error(f"[TikTokVideos] Error checking @{username} in guild {guild.id}: {e}")

        return changed

    @staticmethod
    def _build_embed(video: dict, display_name: str, profile_image_url: str, tt_lang: dict) -> discord.Embed:
        description = tt_lang.get("embed_description", "**{name}** posted a new TikTok!").format(name=display_name)
        embed = discord.Embed(
            title=video.get("title", "New TikTok"),
            url=video.get("url", ""),
            color=discord.Color.from_rgb(1, 1, 1),
            description=description,
        )
        thumbnail = video.get("thumbnail_url", "")
        if thumbnail:
            embed.set_image(url=thumbnail)
        if profile_image_url:
            embed.set_thumbnail(url=profile_image_url)

        published = video.get("published", "")
        if published:
            try:
                from datetime import datetime, timezone
                dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
                field_name = tt_lang.get("embed_field_published", "Published")
                embed.add_field(name=field_name, value=f"<t:{int(dt.timestamp())}:R>", inline=True)
            except (ValueError, AttributeError):
                pass

        footer = tt_lang.get("embed_footer", "Baxi TikTok · avocloud.net")
        embed.set_footer(text=footer)
        return embed


class TwitterPostTask:
    """Background task that polls X (Twitter) accounts for new posts via the syndication endpoint.

    Every 10 minutes, for each guild with twitter enabled:
    - Fetches the latest post (original or repost) for each tracked account
    - Compares post_id to stored last_post_id
    - On first check (last_post_id == ""): seeds silently without notifying
    - On new post: sends embed to alert_channel, pings role if configured
    """

    def __init__(self, bot: commands.AutoShardedBot):
        self.bot = bot

    @tasks.loop(seconds=config.TwitterPosts.check_interval_seconds)
    async def check_posts(self):
        try:
            set_task_status("TwitterPosts", "running", "Checking X accounts for new posts...")
            await self._do_check()
            set_task_status("TwitterPosts", "ok", "X post check complete")
        except Exception as e:
            logger.error(f"[TwitterPosts] Unexpected error: {e}")
            set_task_status("TwitterPosts", "error", f"Unexpected error: {e}")

    @check_posts.before_loop
    async def before_check_posts(self):
        await self.bot.wait_until_ready()
        await self._do_check()

    async def _do_check(self):
        all_usernames: set = set()
        guild_data: dict = {}

        for guild in self.bot.guilds:
            tw_config = dict(datasys.load_data(guild.id, "twitter"))
            if not tw_config.get("enabled", False):
                continue
            channels = tw_config.get("channels", [])
            guild_data[guild.id] = (tw_config, [])
            for ch_entry in channels:
                username = ch_entry.get("username", "")
                if username:
                    all_usernames.add(username)
                    guild_data[guild.id][1].append((ch_entry, username))

        if not all_usernames:
            return

        post_cache: dict = {}
        logger.info(f"[TwitterPosts] Checking {len(all_usernames)} unique accounts across {len(guild_data)} guilds")
        for username in all_usernames:
            try:
                post = await twitter_api.get_latest_post(username)
                post_cache[username] = post
                logger.debug.info(f"[TwitterPosts] @{username}: post={post['post_id'] if post else None}")
            except Exception as e:
                logger.error(f"[TwitterPosts] Failed to fetch @{username}: {e}")
                post_cache[username] = None

        for guild in self.bot.guilds:
            if guild.id not in guild_data:
                continue
            try:
                tw_config, channel_list = guild_data[guild.id]
                changed = await self._check_guild(guild, post_cache, channel_list, tw_config)
                if changed:
                    datasys.save_data(guild.id, "twitter", tw_config)
            except Exception as e:
                logger.error(f"[TwitterPosts] Error processing guild {guild.id}: {e}")

    async def _check_guild(self, guild, post_cache: dict, channel_list: list, tw_config: dict) -> bool:
        global_alert_channel_id = str(tw_config.get("alert_channel", "")).strip()
        ping_role_id = str(tw_config.get("ping_role", "")).strip()
        changed = False

        lang = datasys.load_lang_file(guild.id)
        tw_lang = lang.get("systems", {}).get("twitter", {})

        resolved_channels: dict = {}

        for ch_entry, username in channel_list:
            try:
                per_alert = str(ch_entry.get("alert_channel", "")).strip()
                alert_channel_id = per_alert or global_alert_channel_id
                if not alert_channel_id:
                    logger.warning(f"[TwitterPosts] No alert channel for @{username} in {guild.name}, skipping")
                    continue

                if alert_channel_id not in resolved_channels:
                    try:
                        alert_ch = guild.get_channel(int(alert_channel_id))
                        if not alert_ch:
                            alert_ch = await self.bot.fetch_channel(int(alert_channel_id))
                    except (ValueError, TypeError, discord.NotFound, discord.Forbidden, discord.HTTPException):
                        alert_ch = None
                    resolved_channels[alert_channel_id] = alert_ch

                alert_channel = resolved_channels[alert_channel_id]
                if not alert_channel or not isinstance(alert_channel, discord.TextChannel):
                    logger.error(f"[TwitterPosts] Alert channel {alert_channel_id} not found or not text channel in {guild.name}")
                    continue
                if not alert_channel.permissions_for(guild.me).send_messages:
                    logger.error(f"[TwitterPosts] No send permission in {alert_channel.name} in {guild.name}")
                    continue

                post = post_cache.get(username)
                if post is None:
                    continue

                last_post_id = ch_entry.get("last_post_id", "")
                last_post_published = ch_entry.get("last_post_published", "")

                if not last_post_id:
                    ch_entry["last_post_id"] = post["post_id"]
                    ch_entry["last_post_published"] = post.get("published", "")
                    changed = True
                    admin_log("info", f"[TwitterPosts] Seeded @{username} @ {guild.name}: {post['post_id']}", source="TwitterPosts")
                    continue

                if post["post_id"] == last_post_id:
                    continue

                post_published = post.get("published", "")
                if post_published and last_post_published:
                    try:
                        from datetime import datetime
                        dt_new = datetime.fromisoformat(post_published.replace("Z", "+00:00"))
                        dt_last = datetime.fromisoformat(last_post_published.replace("Z", "+00:00"))
                        if dt_new <= dt_last:
                            ch_entry["last_post_id"] = post["post_id"]
                            ch_entry["last_post_published"] = post_published
                            changed = True
                            continue
                    except (ValueError, AttributeError):
                        pass

                ch_entry["last_post_id"] = post["post_id"]
                ch_entry["last_post_published"] = post_published
                changed = True

                display_name = ch_entry.get("display_name", username)
                profile_img = ch_entry.get("profile_image_url", "")

                try:
                    embed = self._build_embed(post, display_name, profile_img, tw_lang)
                except Exception as e:
                    logger.error(f"[TwitterPosts] Error building embed for @{username}: {e}")
                    embed = discord.Embed(
                        title=post.get("title", "New post"),
                        url=post.get("url", ""),
                        color=discord.Color.from_rgb(1, 1, 1),
                    )

                ping_content = f"<@&{ping_role_id}>" if ping_role_id else None

                try:
                    logger.info(f"[TwitterPosts] Sending alert to {alert_channel.name} in {guild.name}: \"{post['title']}\"")
                    sent_msg = await alert_channel.send(content=ping_content, embed=embed)
                    logger.info(f"[TwitterPosts] Message sent: {sent_msg.id}")
                    admin_log("success", f"[TwitterPosts] New post by @{display_name} @ {guild.name}: \"{post['title']}\"", source="TwitterPosts")
                except discord.Forbidden as e:
                    logger.error(f"[TwitterPosts] Permission denied in {alert_channel.name}: {e}")
                    admin_log("error", f"[TwitterPosts] Permission error: {e}", source="TwitterPosts")
                except discord.HTTPException as e:
                    logger.error(f"[TwitterPosts] HTTP error in {alert_channel.name}: {e}")
                    admin_log("error", f"[TwitterPosts] HTTP error: {e}", source="TwitterPosts")
                except Exception as e:
                    logger.error(f"[TwitterPosts] Unexpected send error: {type(e).__name__}: {e}")

            except Exception as e:
                logger.error(f"[TwitterPosts] Error checking @{username} in guild {guild.id}: {e}")

        return changed

    @staticmethod
    def _build_embed(post: dict, display_name: str, profile_image_url: str, tw_lang: dict) -> discord.Embed:
        description = tw_lang.get("embed_description", "**{name}** posted on X!").format(name=display_name)
        embed = discord.Embed(
            title=post.get("title", "New post"),
            url=post.get("url", ""),
            color=discord.Color.from_rgb(1, 1, 1),
            description=description,
        )
        thumbnail = post.get("thumbnail_url", "")
        if thumbnail:
            embed.set_image(url=thumbnail)
        if profile_image_url:
            embed.set_thumbnail(url=profile_image_url)

        published = post.get("published", "")
        if published:
            try:
                from datetime import datetime, timezone
                dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
                field_name = tw_lang.get("embed_field_published", "Published")
                embed.add_field(name=field_name, value=f"<t:{int(dt.timestamp())}:R>", inline=True)
            except (ValueError, AttributeError):
                pass

        footer = tw_lang.get("embed_footer", "Baxi X · avocloud.net")
        embed.set_footer(text=footer)
        return embed


class InstagramTask:
    """Background task that polls Instagram accounts for new posts and reels via instaloader.

    Every 15 minutes, for each guild with instagram enabled:
    - Fetches the latest post and reel for each tracked account
    - Sends separate alerts for new posts and new reels based on guild settings
    """

    def __init__(self, bot: commands.AutoShardedBot):
        self.bot = bot

    @tasks.loop(seconds=config.Instagram.check_interval_seconds)
    async def check_posts(self):
        try:
            set_task_status("Instagram", "running", "Checking Instagram accounts for new content...")
            await self._do_check()
            set_task_status("Instagram", "ok", "Instagram check complete")
        except Exception as e:
            logger.error(f"[Instagram] Unexpected error: {e}")
            set_task_status("Instagram", "error", f"Unexpected error: {e}")

    @check_posts.before_loop
    async def before_check_posts(self):
        await self.bot.wait_until_ready()
        await self._do_check()

    async def _do_check(self):
        import time

        for guild in self.bot.guilds:
            ig_config = dict(datasys.load_data(guild.id, "instagram"))
            if not ig_config.get("enabled", False):
                continue
            channels = ig_config.get("channels", [])
            if not channels:
                continue

            changed = False
            try:
                changed = await self._check_guild(guild, ig_config, channels)
            except Exception as e:
                logger.error(f"[Instagram] Error processing guild {guild.id}: {e}")

            if changed:
                datasys.save_data(guild.id, "instagram", ig_config)

    async def _check_guild(self, guild, ig_config: dict, channels: list) -> bool:
        import time
        global_alert_channel_id = str(ig_config.get("alert_channel", "")).strip()
        ping_role_id = str(ig_config.get("ping_role", "")).strip()
        changed = False

        lang = datasys.load_lang_file(guild.id)
        ig_lang = lang.get("systems", {}).get("instagram", {})

        resolved_channels: dict = {}

        logger.info(f"[Instagram] Checking {len(channels)} accounts in {guild.name}")

        for ch_entry in channels:
            ig_user_id   = ch_entry.get("ig_user_id", "")
            access_token = ch_entry.get("access_token", "")
            username     = ch_entry.get("username", ig_user_id)

            if not ig_user_id or not access_token:
                logger.warning(f"[Instagram] Channel entry missing ig_user_id/access_token in {guild.name}, skipping")
                continue

            if ch_entry.get("token_expired", False):
                logger.warning(f"[Instagram] Token expired for @{username} in {guild.name}, skipping")
                continue

            try:
                # Refresh token if expiring within 7 days
                token_expires = ch_entry.get("token_expires", 0)
                if token_expires and token_expires < time.time() + 7 * 86400:
                    try:
                        new_token, new_expires = await instagram_api.refresh_token(access_token)
                        ch_entry["access_token"]   = new_token
                        ch_entry["token_expires"]  = new_expires
                        access_token = new_token
                        changed = True
                        logger.info(f"[Instagram] Refreshed token for @{username} in {guild.name}")
                    except IGBlocked:
                        logger.warning(f"[Instagram] Token refresh failed (expired) for @{username} in {guild.name}")
                        ch_entry["token_expired"] = True
                        changed = True
                        continue
                    except Exception as e:
                        logger.error(f"[Instagram] Token refresh error for @{username}: {e}")

                content = await instagram_api.get_user_media(ig_user_id, access_token)

            except IGBlocked:
                logger.warning(f"[Instagram] Token invalid for @{username} in {guild.name}, marking expired")
                ch_entry["token_expired"] = True
                changed = True
                continue
            except IGRateLimited as e:
                logger.warning(f"[Instagram] Rate-limited for @{username}: {e}, skipping rest of cycle")
                set_task_status("Instagram", "warn", "Rate-limited; backing off until next cycle")
                break
            except IGNotFound:
                logger.warning(f"[Instagram] @{username} not found (ig_user_id={ig_user_id}), skipping")
                continue
            except IGTransient as e:
                logger.error(f"[Instagram] Transient error for @{username}: {e}")
                continue
            except Exception as e:
                logger.error(f"[Instagram] Failed to fetch @{username}: {e}")
                continue

            try:
                per_alert = str(ch_entry.get("alert_channel", "")).strip()
                alert_channel_id = per_alert or global_alert_channel_id
                if not alert_channel_id:
                    logger.warning(f"[Instagram] No alert channel for @{username} in {guild.name}, skipping")
                    continue

                if alert_channel_id not in resolved_channels:
                    try:
                        alert_ch = guild.get_channel(int(alert_channel_id))
                        if not alert_ch:
                            alert_ch = await self.bot.fetch_channel(int(alert_channel_id))
                    except (ValueError, TypeError, discord.NotFound, discord.Forbidden, discord.HTTPException):
                        alert_ch = None
                    resolved_channels[alert_channel_id] = alert_ch

                alert_channel = resolved_channels[alert_channel_id]
                if not alert_channel or not isinstance(alert_channel, discord.TextChannel):
                    logger.error(f"[Instagram] Alert channel {alert_channel_id} not found in {guild.name}")
                    continue
                if not alert_channel.permissions_for(guild.me).send_messages:
                    logger.error(f"[Instagram] No send permission in {alert_channel.name} in {guild.name}")
                    continue

                display_name = ch_entry.get("display_name", username)
                profile_img  = ch_entry.get("profile_image_url", "")
                ping_content = f"<@&{ping_role_id}>" if ping_role_id else None
                alert_posts  = ch_entry.get("alert_posts", True)
                alert_reels  = ch_entry.get("alert_reels", True)

                if alert_posts:
                    post = content.get("latest_post")
                    if post:
                        last_post_id        = ch_entry.get("last_post_id", "")
                        post_published      = post.get("published", "")
                        last_post_published = ch_entry.get("last_post_published", "")

                        if not last_post_id:
                            ch_entry["last_post_id"]        = post["post_id"]
                            ch_entry["last_post_published"] = post_published
                            changed = True
                            admin_log("info", f"[Instagram] Seeded post for @{username} @ {guild.name}", source="Instagram")
                        elif post["post_id"] != last_post_id:
                            send_alert = True
                            if post_published and last_post_published:
                                try:
                                    from datetime import datetime
                                    dt_new  = datetime.fromisoformat(post_published.replace("Z", "+00:00"))
                                    dt_last = datetime.fromisoformat(last_post_published.replace("Z", "+00:00"))
                                    if dt_new <= dt_last:
                                        send_alert = False
                                except (ValueError, AttributeError):
                                    pass
                            ch_entry["last_post_id"]        = post["post_id"]
                            ch_entry["last_post_published"] = post_published
                            changed = True
                            if send_alert:
                                try:
                                    embed = self._build_embed(post, display_name, profile_img, ig_lang, is_reel=False)
                                    await alert_channel.send(content=ping_content, embed=embed)
                                    admin_log("success", f"[Instagram] New post by @{display_name} @ {guild.name}", source="Instagram")
                                except Exception as e:
                                    logger.error(f"[Instagram] Send error (post) @{username}: {e}")

                if alert_reels:
                    reel = content.get("latest_reel")
                    if reel:
                        last_reel_id        = ch_entry.get("last_reel_id", "")
                        reel_published      = reel.get("published", "")
                        last_reel_published = ch_entry.get("last_reel_published", "")

                        if not last_reel_id:
                            ch_entry["last_reel_id"]        = reel["post_id"]
                            ch_entry["last_reel_published"] = reel_published
                            changed = True
                            admin_log("info", f"[Instagram] Seeded reel for @{username} @ {guild.name}", source="Instagram")
                        elif reel["post_id"] != last_reel_id:
                            send_alert = True
                            if reel_published and last_reel_published:
                                try:
                                    from datetime import datetime
                                    dt_new  = datetime.fromisoformat(reel_published.replace("Z", "+00:00"))
                                    dt_last = datetime.fromisoformat(last_reel_published.replace("Z", "+00:00"))
                                    if dt_new <= dt_last:
                                        send_alert = False
                                except (ValueError, AttributeError):
                                    pass
                            ch_entry["last_reel_id"]        = reel["post_id"]
                            ch_entry["last_reel_published"] = reel_published
                            changed = True
                            if send_alert:
                                try:
                                    embed = self._build_embed(reel, display_name, profile_img, ig_lang, is_reel=True)
                                    await alert_channel.send(content=ping_content, embed=embed)
                                    admin_log("success", f"[Instagram] New reel by @{display_name} @ {guild.name}", source="Instagram")
                                except Exception as e:
                                    logger.error(f"[Instagram] Send error (reel) @{username}: {e}")

            except Exception as e:
                logger.error(f"[Instagram] Error processing @{username} in guild {guild.id}: {e}")

            await asyncio.sleep(1 + random.uniform(0, 1))

        return changed

    @staticmethod
    def _build_embed(post: dict, display_name: str, profile_image_url: str, ig_lang: dict, is_reel: bool = False) -> discord.Embed:
        desc_key = "embed_description_reel" if is_reel else "embed_description_post"
        default_desc = f"**{{name}}** shared a new {'Reel' if is_reel else 'post'} on Instagram!"
        description = ig_lang.get(desc_key, default_desc).format(name=display_name)

        caption = post.get("caption", "")
        if caption:
            description += f"\n\n> {caption}"

        embed = discord.Embed(
            title=("🎬 New Reel" if is_reel else "📸 New Post") + f" — {display_name}",
            url=post.get("url", ""),
            color=discord.Color.from_rgb(225, 48, 108),
            description=description,
        )
        thumbnail = post.get("thumbnail_url", "")
        if thumbnail:
            embed.set_image(url=thumbnail)
        if profile_image_url:
            embed.set_thumbnail(url=profile_image_url)

        published = post.get("published", "")
        if published:
            try:
                from datetime import datetime, timezone
                dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
                field_name = ig_lang.get("embed_field_published", "Published")
                embed.add_field(name=field_name, value=f"<t:{int(dt.timestamp())}:R>", inline=True)
            except (ValueError, AttributeError):
                pass

        footer = ig_lang.get("embed_footer", "Baxi Instagram · avocloud.net")
        embed.set_footer(text=footer)
        return embed


class MusicIdleTask:
    """Disconnects idle/empty music players every 30s."""

    def __init__(self, bot: commands.AutoShardedBot):
        self.bot = bot

    GRACE_SECONDS = 60   # never disconnect a player younger than this
    DISCONNECT_GRACE = 10  # wait 10s after disconnect before auto-removing player

    @tasks.loop(seconds=30)
    async def watch(self):
        import assets.share as share
        set_task_status("MusicIdle", "running", "Scanning music players...")
        now = datetime.datetime.now(datetime.timezone.utc)
        disconnected = 0
        try:
            for gid, player in list(share.music_players.items()):
                vc = player.voice_client
                if not vc or not vc.is_connected():
                    idle = (now - player.last_activity).total_seconds()
                    # Only remove player if it's been disconnected for > DISCONNECT_GRACE
                    if idle > self.DISCONNECT_GRACE:
                        logger.debug.info(f"[MusicIdle:{gid}] Player has no live voice_client (idle {idle:.0f}s) — popping")
                        share.music_players.pop(gid, None)
                    else:
                        logger.debug.info(f"[MusicIdle:{gid}] Voice client disconnected (idle {idle:.0f}s/{self.DISCONNECT_GRACE}s) — will retry")
                    continue
                conf = dict(datasys.load_data(gid, "music") or {})
                if conf.get("radio_247_enabled", False):
                    logger.debug.info(f"[MusicIdle:{gid}] 24/7 radio mode — skip idle/empty disconnect")
                    continue
                timeout = int(conf.get("disconnect_timeout", 300) or 300)
                channel_humans = [m for m in vc.channel.members if not m.bot] if vc.channel else []
                idle = (now - player.last_activity).total_seconds()
                empty = len(channel_humans) == 0
                stale = (not vc.is_playing()) and (not vc.is_paused()) and idle > timeout

                if idle < self.GRACE_SECONDS:
                    logger.debug.info(f"[MusicIdle:{gid}] grace period ({idle:.0f}s/{self.GRACE_SECONDS}s) — skip checks")
                    continue

                if empty:
                    logger.info(f"[MusicIdle:{gid}] disconnect: channel empty (humans=0)")
                elif stale:
                    logger.info(f"[MusicIdle:{gid}] disconnect: idle for {idle:.0f}s > {timeout}s, not playing/paused")

                if empty or stale:
                    await player.stop_and_disconnect()
                    share.music_players.pop(gid, None)
                    disconnected += 1
            set_task_status("MusicIdle", "ok", f"{disconnected} disconnected" if disconnected else "ok")
        except Exception as e:
            logger.error(f"[MusicIdle] Error: {e}")
            set_task_status("MusicIdle", "error", f"Error: {e}")

    @watch.before_loop
    async def before_watch(self):
        await self.bot.wait_until_ready()


class Radio247Task:
    """Auto-joins and plays 24/7 radio for guilds that have it configured. Runs every 30s."""

    def __init__(self, bot: commands.AutoShardedBot):
        self.bot = bot

    @tasks.loop(seconds=30)
    async def watch(self):
        import assets.share as share
        from assets.music.player import MusicPlayer, Track
        from assets.music.sources import RADIO_PRESETS, is_safe_radio_url

        for guild in self.bot.guilds:
            gid = guild.id
            try:
                conf = dict(datasys.load_data(gid, "music") or {})
                if not conf.get("radio_247_enabled", False):
                    continue

                channel_id_str = str(conf.get("radio_247_channel_id", "") or "")
                stream_url = str(conf.get("radio_247_url", "") or "").strip()
                text_channel_id_str = str(conf.get("radio_247_text_channel_id", "") or "")

                if not channel_id_str or not stream_url:
                    continue

                try:
                    channel_id = int(channel_id_str)
                except (ValueError, TypeError):
                    continue

                channel = guild.get_channel(channel_id)
                if not isinstance(channel, discord.VoiceChannel):
                    continue

                player = share.music_players.get(gid)
                vc = player.voice_client if player else None

                already_playing = (
                    vc
                    and vc.is_connected()
                    and vc.channel
                    and vc.channel.id == channel_id
                    and (vc.is_playing() or vc.is_paused())
                )
                if already_playing:
                    continue

                # Resolve stream URL (preset key or raw URL)
                if stream_url in RADIO_PRESETS:
                    label, resolved_url = RADIO_PRESETS[stream_url]
                else:
                    if not is_safe_radio_url(stream_url):
                        logger.warning(f"[Radio247:{gid}] unsafe URL, skipping")
                        continue
                    label, resolved_url = stream_url, stream_url

                logger.info(f"[Radio247:{gid}] Starting 24/7 radio '{label}' in channel {channel_id}")

                try:
                    text_channel_id = int(text_channel_id_str) if text_channel_id_str else 0
                except (ValueError, TypeError):
                    text_channel_id = 0

                if player is None:
                    player = MusicPlayer(guild_id=gid, text_channel_id=text_channel_id, volume=1.0)
                    player._bot = self.bot
                    share.music_players[gid] = player

                track = Track(
                    title=label,
                    stream_url=resolved_url,
                    webpage_url=resolved_url,
                    duration=0,
                    requester_id=self.bot.user.id if self.bot.user else 0,
                    thumbnail=None,
                    source_type="radio",
                )

                async with player.lock:
                    await player.connect(channel)
                    player.queue.clear()
                    if player.is_playing() or player.is_paused():
                        player.skip()
                        await asyncio.sleep(0.3)
                    player.queue.append(track)
                    await player.play_next()

            except Exception as e:
                logger.error(f"[Radio247:{gid}] Error: {type(e).__name__}: {e}")

    @watch.before_loop
    async def before_watch(self):
        await self.bot.wait_until_ready()


class McLinkSyncTask:
    """Mirror each guild's Minecraft link list from its DiscordGate server.

    The MC server (DiscordGate plugin) is the source of truth for who is
    whitelisted/linked. This pulls GET /dg/links per guild and reconciles it into
    that guild's mc_links (server wins: add/update/remove). Runs once on startup
    (via before_loop) and every 10 minutes thereafter.
    """

    def __init__(self, bot: commands.AutoShardedBot):
        self.bot = bot

    @tasks.loop(minutes=10)
    async def sync_links(self):
        set_task_status("McLinkSync", "running", "Syncing Minecraft links...")
        await self._sync_all()

    async def _sync_all(self):
        from assets.mc_link import sync_guild_from_server

        synced = 0
        total_added = total_updated = total_removed = 0
        for guild in self.bot.guilds:
            cfg = dict(datasys.load_data(guild.id, "mc_link"))
            if not cfg.get("enabled", False):
                continue
            api_url = str(cfg.get("api_url", "")).strip()
            secret = str(cfg.get("api_secret", "")).strip()
            if not api_url or not secret:
                continue
            try:
                stats = await sync_guild_from_server(guild.id, api_url, secret)
            except Exception as e:
                logger.error(f"[McLinkSync] guild {guild.id} failed: {type(e).__name__}: {e}")
                continue
            if stats is None:
                logger.warning(f"[McLinkSync] guild {guild.id}: skipped (server unreachable or guard).")
                continue
            synced += 1
            total_added += stats["added"]
            total_updated += stats["updated"]
            total_removed += stats["removed"]
            if stats["added"] or stats["updated"] or stats["removed"]:
                logger.info(f"[McLinkSync] guild {guild.id}: +{stats['added']} "
                            f"~{stats['updated']} -{stats['removed']} (total {stats['total']})")

        set_task_status(
            "McLinkSync", "ok",
            f"Synced {synced} guild(s): +{total_added} ~{total_updated} -{total_removed}",
        )

    @sync_links.before_loop
    async def before_sync_links(self):
        await self.bot.wait_until_ready()
        await self._sync_all()



class ClassifierTrainTask:
    """Daily self-training pass for the SafeText chatfilter.

    Folds staff-confirmed training samples (from moderator deletions and feedback
    corrections) into a LoRA fine-tune once enough have accumulated. Fully local -
    no external LLM. The fine-tune runs in a subprocess and reloads the model on success.
    """

    @tasks.loop(hours=24)
    async def train(self):
        try:
            from assets.message.safetext import feedback, finetune
            st = feedback.stats()
            untrained = st.get("untrained", 0)
            if untrained < finetune.MIN_SAMPLES:
                set_task_status(
                    "ClassifierTrain", "ok",
                    f"{untrained}/{finetune.MIN_SAMPLES} samples -  waiting for more",
                )
                return
            set_task_status("ClassifierTrain", "running", f"Fine-tuning on {untrained} new samples...")
            res = await finetune.start_job()
            if res.get("ok"):
                set_task_status("ClassifierTrain", "ok", f"Training started (pid {res.get('pid')})")
                logger.debug.success(f"[ClassifierTrain] Fine-tune started on {untrained} samples")
            else:
                set_task_status("ClassifierTrain", "error", f"Could not start: {res.get('error')}")
        except Exception as e:
            logger.error(f"[ClassifierTrain] Error: {e}")
            set_task_status("ClassifierTrain", "error", f"Error: {e}")

    @train.before_loop
    async def before_train(self):
        # Stagger 5 min after start so it never competes with boot-time model loading.
        await asyncio.sleep(300)
