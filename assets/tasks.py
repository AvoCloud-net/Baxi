import asyncio
import aiohttp
import discord
from collections import deque
from discord.ext import tasks, commands

from reds_simple_logger import Logger
from assets.share import globalchat_message_data
from assets.livestream import twitch_api
import assets.data as datasys
import config.config as config
import copy

logger = Logger()


class GCDH_Task:
    def __init__(self, bot: commands.AutoShardedBot):
        self.bot = bot
        self.old_data: dict = {}

    @tasks.loop(seconds=15)
    async def sync_globalchat_message_data(self):
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
            else:
                logger.debug.success("[GCDH] Data synced with data-structure")
                self.old_data = copy.deepcopy(globalchat_message_data)
        else:
            logger.error(f"[GCDH] Sync failed: {response}")


class UpdateStatsTask:
    def __init__(self, bot: commands.AutoShardedBot):
        self.bot = bot

    @tasks.loop(minutes=10)
    async def update_stats(self):
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


class LivestreamTask:
    """Background task that polls Twitch for streamer status and updates Discord channels/embeds.

    Rate limiting: processes max 20 streamer checks per minute across all guilds.
    Uses a round-robin queue so all guilds get fair polling.
    """

    def __init__(self, bot: commands.AutoShardedBot):
        self.bot = bot
        # Track which streamers were live last check: {guild_id: {login: True/False}}
        self._was_live: dict[int, dict[str, bool]] = {}
        # Queue of (guild_id, streamer_entry) pairs to check
        self._check_queue: deque[tuple[int, dict]] = deque()
        # Cache user profile data: {login: {display_name, profile_image_url, offline_image_url}}
        self._user_cache: dict[str, dict] = {}

    @tasks.loop(seconds=config.Twitch.check_interval_seconds)
    async def check_streams(self):
        try:
            await self._do_check()
        except Exception as e:
            logger.error(f"[Livestream] Error in check_streams: {e}")

    async def _do_check(self):
        # Rebuild queue if empty
        if not self._check_queue:
            self._rebuild_queue()

        if not self._check_queue:
            return

        # Take up to max_checks_per_minute items from queue
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

        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=15)
        ) as session:
            # Fetch stream status for all unique logins in batch
            live_data = await twitch_api.get_streams(session, logins_in_batch)

            # Fetch profile data for any logins we haven't cached yet
            uncached = [l for l in logins_in_batch if l not in self._user_cache]
            if uncached:
                user_data = await twitch_api.get_users(session, uncached)
                self._user_cache.update(user_data)

        # Process each item in the batch
        for guild_id, streamer in batch:
            login = streamer["login"].lower()
            is_live = login in live_data
            was_live = self._was_live.get(guild_id, {}).get(login, False)

            if guild_id not in self._was_live:
                self._was_live[guild_id] = {}

            if is_live != was_live:
                # Status changed
                self._was_live[guild_id][login] = is_live
                await self._update_channel(
                    guild_id,
                    streamer,
                    is_live,
                    live_data.get(login),
                )
            elif is_live and was_live:
                # Still live - update embed with current viewer count etc.
                await self._update_embed_content(
                    guild_id,
                    streamer,
                    live_data[login],
                )

    def _rebuild_queue(self):
        """Rebuild the round-robin queue from all guilds with livestream enabled."""
        self._check_queue.clear()

        for guild in self.bot.guilds:
            ls_config = dict(datasys.load_data(guild.id, "livestream"))
            if not ls_config.get("enabled", False):
                continue

            streamers = ls_config.get("streamers", [])
            for streamer in streamers:
                if streamer.get("login"):
                    self._check_queue.append((guild.id, streamer))

        logger.debug.info(
            f"[Livestream] Queue rebuilt: {len(self._check_queue)} streamer checks queued"
        )

    async def _update_channel(
        self,
        guild_id: int,
        streamer: dict,
        is_live: bool,
        stream_data: dict | None,
    ):
        """Update the Discord channel name and embed when status changes."""
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return

        login = streamer["login"].lower()
        channel_id = streamer.get("channel_id")
        message_id = streamer.get("message_id")
        lang = datasys.load_lang_file(guild_id)
        ls_lang = lang.get("systems", {}).get("livestream", {})
        profile = self._user_cache.get(login, {})
        display_name = profile.get("display_name", streamer["login"])

        channel = guild.get_channel(int(channel_id)) if channel_id else None
        if not isinstance(channel, discord.TextChannel):
            return

        # Update channel name with green/red dot
        if is_live:
            new_name = ls_lang.get("channel_name_online", "\U0001f7e2\u2502{name}").format(
                name=display_name.lower()
            )
        else:
            new_name = ls_lang.get("channel_name_offline", "\U0001f534\u2502{name}").format(
                name=display_name.lower()
            )

        try:
            if channel.name != new_name:
                await channel.edit(name=new_name)
        except discord.Forbidden:
            logger.error(f"[Livestream] Cannot edit channel name in guild {guild_id}")

        # Build embed
        embed = self._build_embed(ls_lang, display_name, is_live, stream_data, profile)

        # Build ping content for going-live notifications
        ping_content = None
        if is_live:
            ls_config = dict(datasys.load_data(guild_id, "livestream"))
            ping_role_id = ls_config.get("ping_role", "")
            if ping_role_id:
                ping_content = f"<@&{ping_role_id}>"

        # Update or send message
        try:
            if message_id:
                try:
                    msg = await channel.fetch_message(int(message_id))
                    await msg.edit(content=ping_content if is_live else None, embed=embed)
                    return
                except (discord.NotFound, discord.HTTPException):
                    pass

            # Send new message and save its ID
            msg = await channel.send(content=ping_content, embed=embed)
            self._save_message_id(guild_id, login, msg.id)
        except discord.Forbidden:
            logger.error(f"[Livestream] Cannot send message in guild {guild_id}")

    async def _update_embed_content(
        self,
        guild_id: int,
        streamer: dict,
        stream_data: dict,
    ):
        """Update embed content for a streamer that is still live (viewer count, etc.)."""
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return

        login = streamer["login"].lower()
        channel_id = streamer.get("channel_id")
        message_id = streamer.get("message_id")
        lang = datasys.load_lang_file(guild_id)
        ls_lang = lang.get("systems", {}).get("livestream", {})
        profile = self._user_cache.get(login, {})
        display_name = profile.get("display_name", streamer["login"])

        channel = guild.get_channel(int(channel_id)) if channel_id else None
        if not isinstance(channel, discord.TextChannel) or not message_id:
            return

        embed = self._build_embed(ls_lang, display_name, True, stream_data, profile)

        try:
            msg = await channel.fetch_message(int(message_id))
            await msg.edit(embed=embed)
        except (discord.NotFound, discord.HTTPException, discord.Forbidden):
            pass

    def _build_embed(
        self,
        ls_lang: dict,
        display_name: str,
        is_live: bool,
        stream_data: dict | None,
        profile: dict,
    ) -> discord.Embed:
        """Build the Discord embed for a streamer."""
        if is_live and stream_data:
            embed = discord.Embed(
                title=ls_lang.get("embed_online_title", "{name} is now LIVE!").format(
                    name=display_name
                ),
                description=stream_data.get("title", ""),
                url=f"https://twitch.tv/{display_name.lower()}",
                color=discord.Color.green(),
            )

            game = stream_data.get("game_name", "")
            viewers = stream_data.get("viewer_count", 0)
            started = stream_data.get("started_at", "")

            if game:
                embed.add_field(
                    name=ls_lang.get("embed_online_game", "Game"),
                    value=game,
                    inline=True,
                )
            embed.add_field(
                name=ls_lang.get("embed_online_viewers", "Viewers"),
                value=str(viewers),
                inline=True,
            )
            if started:
                embed.add_field(
                    name=ls_lang.get("embed_online_started", "Started"),
                    value=f"<t:{self._iso_to_timestamp(started)}:R>",
                    inline=True,
                )

            thumbnail_url = stream_data.get("thumbnail_url", "")
            if thumbnail_url:
                # Add cache buster to always show current thumbnail
                embed.set_image(
                    url=f"{thumbnail_url}?t={int(asyncio.get_event_loop().time())}"
                )

            if profile.get("profile_image_url"):
                embed.set_thumbnail(url=profile["profile_image_url"])

        else:
            embed = discord.Embed(
                title=ls_lang.get("embed_offline_title", "{name} is offline").format(
                    name=display_name
                ),
                description=ls_lang.get(
                    "embed_offline_description",
                    "{name} is not streaming right now. Check back later!",
                ).format(name=display_name),
                url=f"https://twitch.tv/{display_name.lower()}",
                color=discord.Color.red(),
            )

            offline_img = profile.get("offline_image_url", "")
            if offline_img:
                embed.set_image(url=offline_img)

            if profile.get("profile_image_url"):
                embed.set_thumbnail(url=profile["profile_image_url"])

        embed.set_footer(
            text=ls_lang.get("embed_footer", "Baxi Livestream - avocloud.net")
        )
        return embed

    def _save_message_id(self, guild_id: int, login: str, message_id: int):
        """Save the message ID back to the guild config so we can edit it later."""
        ls_config = dict(datasys.load_data(guild_id, "livestream"))
        streamers = ls_config.get("streamers", [])
        for streamer in streamers:
            if streamer.get("login", "").lower() == login.lower():
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
            await self._do_update()
        except Exception as e:
            logger.error(f"[StatsChannels] Error in update_stats_channels: {e}")

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
                        self._last_values[guild.id][stat_type] = count
                        logger.debug.info(
                            f"[StatsChannels] {guild.id} | {stat_type} -> {new_name}"
                        )
                    except discord.Forbidden:
                        logger.error(
                            f"[StatsChannels] Cannot edit channel in guild {guild.id}"
                        )
                    except discord.HTTPException as e:
                        logger.error(
                            f"[StatsChannels] HTTP error for guild {guild.id}: {e}"
                        )
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