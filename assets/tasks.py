import asyncio
import aiohttp
import datetime
import discord
import os
from collections import deque
from discord.ext import tasks, commands

from reds_simple_logger import Logger
from assets.share import globalchat_message_data, phishing_url_list, set_task_status, admin_log
from assets.livestream import twitch_api
import assets.data as datasys
import assets.trust as sentinel
import config.config as config
import copy

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
        set_task_status("UpdateStats", "ok", f"Guilds: {guild_count} · Unique users: {user_count}")


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
            set_task_status("Livestream", "running", "Checking Twitch streams...", extra=f"Queue: {len(self._check_queue)} pending")
            await self._do_check()
            set_task_status("Livestream", "ok", f"Stream check complete", extra=f"Queue: {len(self._check_queue)} remaining")
        except Exception as e:
            logger.error(f"[Livestream] Error in check_streams: {e}")
            set_task_status("Livestream", "error", f"Error: {e}")

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

            if guild_id not in self._was_live:
                self._was_live[guild_id] = {}

            first_check = login not in self._was_live[guild_id]
            was_live = self._was_live[guild_id].get(login, False)
            guild = self.bot.get_guild(guild_id)
            guild_name = guild.name if guild else str(guild_id)
            profile = self._user_cache.get(login, {})
            display = profile.get("display_name", streamer.get("login", login))
            stream_info = live_data.get(login)

            if first_check or is_live != was_live:
                # Status changed (or first check — sync channel name/embed regardless)
                self._was_live[guild_id][login] = is_live
                await self._update_channel(
                    guild_id,
                    streamer,
                    is_live,
                    stream_info,
                    ping=is_live and not first_check,
                )
                if not first_check:
                    if is_live:
                        game = stream_info.get("game_name", "") if stream_info else ""
                        viewers = stream_info.get("viewer_count", 0) if stream_info else 0
                        admin_log("success",
                            f"{display} went LIVE · {viewers} viewers"
                            + (f" · {game}" if game else "")
                            + f" @ {guild_name}",
                            source="Livestream")
                    else:
                        admin_log("info", f"{display} went offline @ {guild_name}", source="Livestream")
                else:
                    status_str = "live" if is_live else "offline"
                    admin_log("info", f"First check: {display} is {status_str} @ {guild_name}", source="Livestream")
            elif is_live and was_live:
                # Still live - update embed with current viewer count etc.
                await self._update_embed_content(
                    guild_id,
                    streamer,
                    stream_info,
                )
                viewers = stream_info.get("viewer_count", 0) if stream_info else 0
                game = stream_info.get("game_name", "") if stream_info else ""
                admin_log("info",
                    f"Still live: {display} · {viewers} viewers"
                    + (f" · {game}" if game else "")
                    + f" @ {guild_name}",
                    source="Livestream")

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

        logger.info(
            f"[Livestream] Queue rebuilt: {len(self._check_queue)} streamer checks queued"
        )
        admin_log("info", f"Queue rebuilt: {len(self._check_queue)} streamer checks queued", source="Livestream")

    async def _update_channel(
        self,
        guild_id: int,
        streamer: dict,
        is_live: bool,
        stream_data: dict | None,
        ping: bool = True,
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

        # Update channel name: red dot when live, black dot when offline
        if is_live:
            new_name = ls_lang.get("channel_name_online", "\U0001f534\u2502{name}").format(
                name=display_name.lower()
            )
        else:
            new_name = ls_lang.get("channel_name_offline", "\u26ab\u2502{name}").format(
                name=display_name.lower()
            )

        try:
            if channel.name != new_name:
                await channel.edit(name=new_name)
        except discord.Forbidden:
            logger.error(f"[Livestream] Cannot edit channel name in guild {guild_id}")

        # Build embed
        embed = self._build_embed(ls_lang, display_name, is_live, stream_data, profile)

        # Send a temporary ping message when going live (deleted after short delay).
        # Discord only sends push notifications for new messages, not edits.
        # We wait 2s before deleting so Discord has time to dispatch the notification.
        if is_live and ping:
            ls_config = dict(datasys.load_data(guild_id, "livestream"))
            ping_role_id = ls_config.get("ping_role", "")
            if ping_role_id:
                game = stream_data.get("game_name", "") if stream_data else ""
                ping_text = ls_lang.get(
                    "ping_message", "{role} \u2014 **{name}** is now live playing **{game}**!"
                ).format(role=f"<@&{ping_role_id}>", name=display_name, game=game)
                try:
                    ping_msg = await channel.send(content=ping_text)
                    await asyncio.sleep(2)
                    await ping_msg.delete()
                except (discord.Forbidden, discord.HTTPException):
                    pass

        # Always edit the one permanent embed message (or create it if it doesn't exist yet)
        try:
            if message_id:
                try:
                    msg = await channel.fetch_message(int(message_id))
                    await msg.edit(content=None, embed=embed)
                    return
                except (discord.NotFound, discord.HTTPException):
                    pass

            # No existing message yet — send it and save the ID
            msg = await channel.send(content=None, embed=embed)
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

    async def on_embed_deleted(self, message: discord.Message):
        """Called when any message is deleted. If it was a livestream embed, resend it immediately."""
        if message.guild is None:
            return

        guild_id = message.guild.id
        ls_config = dict(datasys.load_data(guild_id, "livestream"))
        if not ls_config.get("enabled", False):
            return

        for streamer in ls_config.get("streamers", []):
            if str(streamer.get("message_id", "")) == str(message.id):
                # This was the livestream embed — clear the saved ID and resend
                login = streamer["login"].lower()
                streamer["message_id"] = ""
                ls_config["streamers"] = ls_config["streamers"]
                datasys.save_data(guild_id, "livestream", ls_config)

                is_live = self._was_live.get(guild_id, {}).get(login, False)
                # Fetch fresh stream data if live
                stream_data = None
                if is_live:
                    import aiohttp
                    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                        live_data = await twitch_api.get_streams(session, [login])
                        stream_data = live_data.get(login)

                await self._update_channel(
                    guild_id,
                    streamer,
                    is_live,
                    stream_data,
                    ping=False,
                )
                break

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

    async def _do_check(self):
        now = datetime.datetime.utcnow()

        for guild in self.bot.guilds:
            try:
                ta = datasys.load_temp_actions(guild.id)
                changed = False

                # --- Temp bans ---
                remaining_bans = []
                for entry in ta.get("bans", []):
                    try:
                        expires_at = datetime.datetime.fromisoformat(entry["expires_at"])
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
                        expires_at = datetime.datetime.fromisoformat(entry["expires_at"])
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


class TrustScoreTask:
    """Background task that recalculates Prism trust scores every hour.

    Applies score decay/recovery and triggers auto-flag/unflag logic for all
    tracked users without needing a new event to fire.
    """

    @tasks.loop(hours=1)
    async def recalculate_scores(self):
        try:
            set_task_status("TrustScore", "running", "Recalculating Prism scores...")
            total_before = len(sentinel.get_all_profiles())
            await asyncio.to_thread(sentinel.recalculate_all)
            total_after = len(sentinel.get_all_profiles())
            logger.debug.success("[Prism] Periodic score recalculation complete")
            set_task_status("TrustScore", "ok", f"Recalculated {total_after} users")
            admin_log("success", f"Recalculated scores for {total_after} tracked users", source="TrustScore")
        except Exception as e:
            logger.error(f"[Prism] Error in recalculate_scores: {e}")
            set_task_status("TrustScore", "error", f"Error: {e}")


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

        # --- tickets.json per guild ---
        try:
            data_root = "data"
            for guild_dir in os.listdir(data_root):
                tickets_path = os.path.join(data_root, guild_dir, "tickets.json")
                if not os.path.exists(tickets_path):
                    continue
                tickets: dict = datasys.load_json(tickets_path)
                cleaned_tickets = {
                    tid: t for tid, t in tickets.items()
                    if not self._is_old_ticket(t, cutoff)
                }
                delta = len(tickets) - len(cleaned_tickets)
                removed["tickets"] += delta
                if delta > 0:
                    datasys.save_json(tickets_path, cleaned_tickets)
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
        # Extract timestamp from the first Discord snowflake ID found in messages or replies.
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
    def _is_old_ticket(ticket: dict, cutoff: datetime.datetime) -> bool:
        transcript = ticket.get("transcript", [])
        # Find the most recent message timestamp in the transcript.
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
        return False  # no parseable timestamp → keep

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