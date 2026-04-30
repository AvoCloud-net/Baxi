import asyncio
import json
import os
import re
import datetime
from zoneinfo import ZoneInfo

_VIENNA = ZoneInfo("Europe/Vienna")

# Maps raw AI/chatfilter reason codes to human-readable labels (for Prism event reasons)
_PRISM_REASON_LABELS: dict[str, str] = {
    "phishing":  "Phishing / Scam Link",
    "custom":    "Custom Badword",
    "internal":  "Badword",
    "1":         "NSFW / Explicit Content",
    "2":         "Insults / Toxicity",
    "3":         "Hate Speech / Discrimination",
    "4":         "Doxxing / Personal Data",
    "5":         "Suicide / Self-Harm",
}

from pathlib import Path
from PIL import Image
from io import BytesIO
import random

import assets.data as datasys
import assets.message.globalchat as globalchat
import assets.message.chatfilter as chatfilter
import assets.message.welcomer as welcomer
from assets.buttons import build_ticket_panel_view
import assets.message.customcmd as customcmd
from assets.message.antispam import AntiSpam
import assets.message.reactionroles as reactionroles
import assets.message.auto_slowmode as auto_slowmode
import assets.games.counting as counting_game
import assets.games.quiz as quiz_game
import assets.leveling as leveling_sys
import assets.suggestions as suggestions_sys
import assets.trust as sentinel
import config.config as config
import discord

from typing import cast
from assets.share import globalchat_message_data, temp_voice_channels, admin_log
import assets.share as share
from assets.tasks import (
    GCDH_Task,
    UpdateStatsTask,
    LivestreamTask,
    StatsChannelsTask,
    TempActionsTask,
    PhishingListTask,
    TrustScoreTask,
    GarbageCollectorTask,
    YouTubeVideoTask,
    TikTokVideoTask,
    InstagramTask,
    MusicIdleTask,
    Radio247Task,
)
from assets.giveaway import GiveawayTask
from assets.poll import PollTask
from discord.ext import commands
from reds_simple_logger import Logger
from assets.data import load_data, save_data
from assets.dash.dash import dash_web


logger = Logger()


antispam_instance = AntiSpam()

# Per-channel debounce tasks for sticky messages
# key: "{guild_id}:{channel_id}", value: pending asyncio.Task
_sticky_debounce: dict[str, asyncio.Task] = {}
_STICKY_DEBOUNCE_SECONDS = 4


def events(bot: commands.AutoShardedBot, web):
    logger.debug.info("Events loaded.")

    @bot.event
    async def on_ready():
        logger.info("Almost ready...")

        dash_web(app=web, bot=bot)

        assert bot is not None, "Bot user is None!"
        assert bot.user is not None, "Bot user is None!"

        def load_globalchat_message_data():
            logger.debug.info("Loading globalchat_message_data")
            data = datasys.load_data(1001, "globalchat_message_data")
            return cast(dict, data)

        globalchat_message_data_file: dict = await asyncio.to_thread(
            load_globalchat_message_data
        )

        globalchat_message_data.update(globalchat_message_data_file)

        logger.debug.info(f"Logged in as {bot.user.name} with id {bot.user.id}")
        share.bot = bot  # Prism notifications

        for guild in bot.guilds:
            guild_id = guild.id
            guild_folder = os.path.join("data", str(guild_id))
            config_path = os.path.join(guild_folder, "conf.json")

            # Resolve owner info from cache, fall back to API fetch
            owner_id: int = guild.owner_id or 0
            owner_name: str = ""
            if owner_id:
                owner_user = bot.get_user(owner_id)
                if owner_user is None:
                    try:
                        owner_user = await bot.fetch_user(owner_id)
                    except Exception:
                        owner_user = None
                if owner_user:
                    owner_name = str(owner_user.name)

            # Load or create config data
            if not os.path.exists(guild_folder):
                os.makedirs(guild_folder)
                data: dict = dict(config.datasys.default_data)
                logger.success(f"Ordner und conf.json für Guild {guild_id} erstellt.")
            elif os.path.exists(config_path):
                try:
                    with open(config_path, "r") as config_file:
                        data = json.load(config_file)
                except (json.JSONDecodeError, Exception) as e:
                    logger.error(f"Fehler beim Lesen der conf.json für Guild {guild_id}: {e}")
                    data = dict(config.datasys.default_data)
            else:
                data = dict(config.datasys.default_data)

            # Ensure required fields exist
            if "terms" not in data:
                data["terms"] = False

            # Always update guild info on every start
            data["guild_name"] = str(guild.name)
            data["guild_id"] = guild_id
            data["owner_id"] = owner_id
            data["owner_name"] = owner_name

            with open(config_path, "w") as config_file:
                json.dump(data, config_file, indent=4)
            logger.success(f"Guild {guild_id} ({guild.name}) config aktualisiert.")

        try:
            await bot.tree.sync()
            logger.info("Bot synced with discord!")
            logger.info(f"Bot started with {bot.shard_count} shards!")
            await bot.change_presence(
                activity=discord.Activity(
                    type=discord.ActivityType.playing,
                    name=f"on {len(bot.guilds)} Worlds! - v{config.Discord.version}",
                )
            )
            logger.info("Starting background tasks...")
            logger.working("Starting GCDHT task...")
            GCDTH_task = GCDH_Task(bot)
            GCDTH_task.sync_globalchat_message_data.start()
            share.task_instances["GCDH"] = GCDTH_task
            logger.debug.success("Globalchat message data sync task started.")

            logger.working("Starting UpdateStats task...")
            update_stats_task = UpdateStatsTask(bot)
            update_stats_task.update_stats.start()
            share.task_instances["UpdateStats"] = update_stats_task
            logger.debug.success("Update stats task started.")
            await update_stats_task._post_topgg_stats(len(bot.guilds))

            logger.working("Starting Livestream task...")
            share.livestream_task = LivestreamTask(bot)
            share.livestream_task.check_streams.start()
            share.livestream_task.check_yt_tt_streams.start()
            share.task_instances["Livestream"] = share.livestream_task
            logger.debug.success("Livestream check task started (Twitch + YouTube/TikTok).")

            logger.working("Starting StatsChannels task...")
            stats_channels_task = StatsChannelsTask(bot)
            stats_channels_task.update_stats_channels.start()
            share.task_instances["StatsChannels"] = stats_channels_task
            logger.debug.success("Stats channels update task started.")

            logger.working("Starting TempActions task...")
            temp_actions_task = TempActionsTask(bot)
            temp_actions_task.check_temp_actions.start()
            share.task_instances["TempActions"] = temp_actions_task
            logger.debug.success("Temp actions task started.")

            logger.working("Starting PhishingList task...")
            phishing_list_task = PhishingListTask()
            phishing_list_task.update_phishing_list.start()
            await phishing_list_task._fetch_list()
            share.task_instances["PhishingList"] = phishing_list_task
            logger.debug.success("Phishing list task started.")

            logger.working("Starting Prism task...")
            trust_score_task = TrustScoreTask()
            trust_score_task.recalculate_scores.start()
            share.task_instances["TrustScore"] = trust_score_task
            logger.debug.success("Prism score recalculation task started.")

            logger.working("Starting GarbageCollector task...")
            gc_task = GarbageCollectorTask()
            gc_task.collect.start()
            share.task_instances["GarbageCollector"] = gc_task
            logger.debug.success("Garbage collector task started.")

            logger.working("Starting YouTubeVideos task...")
            yt_video_task = YouTubeVideoTask(bot)
            yt_video_task.check_videos.start()
            share.task_instances["YouTubeVideos"] = yt_video_task
            logger.debug.success("YouTube video tracking task started.")

            logger.working("Starting TikTokVideos task...")
            tt_video_task = TikTokVideoTask(bot)
            tt_video_task.check_videos.start()
            share.task_instances["TikTokVideos"] = tt_video_task
            logger.debug.success("TikTok video tracking task started.")

            logger.working("Starting Instagram task...")
            ig_task = InstagramTask(bot)
            ig_task.check_posts.start()
            share.task_instances["Instagram"] = ig_task
            logger.debug.success("Instagram tracking task started.")

            logger.working("Starting Giveaway task...")
            giveaway_task = GiveawayTask(bot)
            giveaway_task.check_giveaways.start()
            share.task_instances["Giveaway"] = giveaway_task
            logger.debug.success("Giveaway task started.")

            logger.working("Starting Poll task...")
            poll_task = PollTask(bot)
            poll_task.check_polls.start()
            share.task_instances["Poll"] = poll_task
            logger.debug.success("Poll task started.")

            logger.working("Starting MusicIdle task...")
            music_idle_task = MusicIdleTask(bot)
            music_idle_task.watch.start()
            share.task_instances["MusicIdle"] = music_idle_task
            logger.debug.success("Music idle watcher task started.")

            logger.working("Starting Radio247 task...")
            radio_247_task = Radio247Task(bot)
            radio_247_task.watch.start()
            share.task_instances["Radio247"] = radio_247_task
            logger.debug.success("Radio 24/7 task started.")

            # Music: enable discord.py voice debug logging
            import logging as _logging
            _vlog = _logging.getLogger("discord.voice_client")
            _vlog.setLevel(_logging.DEBUG)
            if not _vlog.handlers:
                _h = _logging.StreamHandler()
                _h.setFormatter(_logging.Formatter("%(asctime)s [discord.voice_client] %(levelname)s %(message)s"))
                _vlog.addHandler(_h)
            _gwlog = _logging.getLogger("discord.gateway")
            _gwlog.setLevel(_logging.WARNING)

            # Music: probe FFmpeg + PyNaCl + libopus
            import shutil as _sh
            if _sh.which("ffmpeg") is None:
                logger.error("[Music] FFmpeg binary not found on PATH — playback will fail.")
            else:
                logger.debug.success("[Music] FFmpeg binary detected.")
            try:
                import nacl  # noqa: F401
                logger.debug.success(f"[Music] PyNaCl available (v{nacl.__version__}) — voice encryption ready.")
            except ImportError:
                logger.error("[Music] PyNaCl not installed — voice will not work. Run: pip install PyNaCl")
            try:
                if not discord.opus.is_loaded():
                    for _name in ("libopus.so.0", "libopus.so", "opus"):
                        try:
                            discord.opus.load_opus(_name)
                            if discord.opus.is_loaded():
                                logger.debug.success(f"[Music] libopus loaded explicitly via '{_name}'.")
                                break
                        except OSError:
                            continue
                if discord.opus.is_loaded():
                    logger.debug.success("[Music] libopus is loaded.")
                else:
                    logger.error("[Music] libopus is NOT loaded — voice will fail. Install system package 'libopus0' / 'opus'.")
            except Exception as _e:
                logger.error(f"[Music] libopus probe error: {_e}")

            logger.working("Resuming active Flag Quiz sessions...")
            await quiz_game.resume_all(bot)
            logger.debug.success("Flag Quiz sessions resumed.")

        except Exception as e:
            await bot.change_presence(
                activity=discord.Activity(
                    type=discord.ActivityType.watching,
                    name="die Crash logs durch... - Server start Fehler",
                )
            )
            logger.error("ERROR SYNCING! " + str(e))

    @bot.event
    async def on_shard_ready():
        logger.info(f"Shard {bot.shard_id} is ready!")

    @bot.event
    async def on_guild_join(guild: discord.Guild):
        logger.debug.info("on_guild_join")
        admin_log("info", f"Bot joined guild: {guild.name} ({guild.id}) -  {guild.member_count} members", source="GuildJoin")
        try:
            guild_data_dir = os.path.join("data", str(guild.id))
            data_dir_exists: bool = os.path.exists(guild_data_dir)
            updates_channel: dict = dict(datasys.load_data(1001, "updates"))
            lang = datasys.load_lang_file(guild.id)
            if not data_dir_exists:
                logger.info("New Guild joined! Config directory and file is created...")
                os.makedirs(guild_data_dir)
                json_file_path = os.path.join(guild_data_dir, "conf.json")
                with open(json_file_path, "w", encoding="utf-8") as json_file:
                    json.dump(config.datasys.default_data, json_file, indent=4)
                data_text = lang["events"]["on_guild_join"]["saved_data"]["new_data"]
                try:
                    channel = await guild.create_text_channel(
                        name="baxi-updates",
                        reason="Baxi info channel setup.",
                        topic="Here all information, updates and warnings that are issued by our team are displayed.",
                    )
                    updates_channel[str(guild.id)] = {"cid": channel.id}
                    datasys.save_data(1001, "updates", updates_channel)
                except Exception:
                    channel = None
            else:
                logger.info("Already joined a known guild. Existing data is loaded...")
                data_text = lang["events"]["on_guild_join"]["saved_data"][
                    "existing_data"
                ]
                updates_channel = dict(datasys.load_data(1001, "updates"))
                try:
                    channel = guild.get_channel(updates_channel[str(guild.id)]["cid"])
                except Exception:
                    channel = None
            if channel is None:
                channel = await guild.create_text_channel(
                    name="baxi-updates",
                    reason="Baxi info channel setup.",
                    topic="Here all information, updates and warnings that are issued by our team are displayed.",
                )
                updates_channel[str(guild.id)] = {"cid": channel.id}
                datasys.save_data(1001, "updates", updates_channel)

            embed = discord.Embed(
                title=lang["events"]["on_guild_join"]["title"],
                description=str(
                    lang["events"]["on_guild_join"]["content"] + "\n\n"
                ).format(saved_data=data_text),
                color=config.Discord.color,
            )
            embed.set_footer(text="Baxi · avocloud.net")
            if isinstance(channel, discord.TextChannel):
                await channel.send(embed=embed)
            else:
                logger.warn(
                    f"Channel {channel} is not a TextChannel. Cannot send embed."
                )

        except Exception as e:
            logger.error(f"Error in on_guild_join: {e}")

    @bot.event
    async def on_message(message: discord.Message):
        assert bot.user is not None, "Bot User is None"
        if message.author.id == bot.user.id:
            return

        if message.guild is not None:
            # Delete user messages in livestream channels
            ls_config = dict(datasys.load_data(message.guild.id, "livestream"))
            if ls_config.get("enabled", False):
                for streamer in ls_config.get("streamers", []):
                    if str(streamer.get("channel_id", "")) == str(message.channel.id):
                        try:
                            await message.delete()
                        except (discord.Forbidden, discord.HTTPException):
                            pass
                        return

            # Delete user messages in the ticket panel channel
            ticket_config = dict(datasys.load_data(message.guild.id, "ticket"))
            if ticket_config.get("enabled", False):
                if str(message.channel.id) == str(ticket_config.get("channel", "")):
                    try:
                        await message.delete()
                    except (discord.Forbidden, discord.HTTPException):
                        pass
                    return

        asyncio.create_task(process_message(message, bot))
        asyncio.create_task(handle_sticky_message(message, bot))
        asyncio.create_task(handle_auto_release(message))
        asyncio.create_task(_mc_chat_bridge(message))

    @bot.event
    async def on_message_delete(message: discord.Message):
        if message.guild is None:
            return

        # Resend livestream embed if deleted
        if share.livestream_task is not None:
            await share.livestream_task.on_embed_deleted(message) # type: ignore

        # Resend verify panel embed if deleted
        verify_config = dict(datasys.load_data(message.guild.id, "verify"))
        if (
            verify_config.get("enabled", False)
            and str(message.id) == str(verify_config.get("panel_message_id", ""))
        ):
            try:
                from assets.buttons import VerifyView
                channel = message.guild.get_channel(int(verify_config["channel"]))
                if isinstance(channel, discord.TextChannel):
                    color_str = verify_config.get("color", "#9333ea")
                    try:
                        color = discord.Color.from_str(color_str)
                    except Exception:
                        color = discord.Color.from_rgb(147, 51, 234)
                    embed = discord.Embed(
                        title=verify_config.get("title", "Verification"),
                        description=verify_config.get("description", "Click the button below to verify."),
                        color=color,
                    )
                    embed.set_footer(text="Baxi · Verification")
                    panel_msg = await channel.send(embed=embed, view=VerifyView())
                    verify_config["panel_message_id"] = str(panel_msg.id)
                    datasys.save_data(message.guild.id, "verify", verify_config)
            except (discord.Forbidden, discord.HTTPException, Exception):
                pass

        # Resend ticket panel embed if deleted
        ticket_config = dict(datasys.load_data(message.guild.id, "ticket"))
        if (
            ticket_config.get("enabled", False)
            and str(message.id) == str(ticket_config.get("panel_message_id", ""))
        ):
            try:
                channel = message.guild.get_channel(int(ticket_config["channel"]))
                if isinstance(channel, discord.TextChannel):
                    embed = discord.Embed(
                        title=f"{config.Icons.questionmark} SYS // {message.guild.name} SUPPORT",
                        description=ticket_config.get("message", ""),
                        color=discord.Color.from_str(ticket_config.get("color", "#5865F2")),
                    )
                    panel_msg = await channel.send(
                        embed=embed,
                        view=build_ticket_panel_view(ticket_config.get("buttons", [])),
                    )
                    ticket_config["panel_message_id"] = str(panel_msg.id)
                    datasys.save_data(message.guild.id, "ticket", ticket_config)
            except (discord.Forbidden, discord.HTTPException, Exception):
                pass

    @bot.event
    async def on_member_join(member: discord.Member):
        admin_log("info", f"Member joined: {member.name} ({member.id}) → {member.guild.name}", source="MemberJoin")
        try:
            datasys.update_activity(member.guild.id, member_join=True)
        except Exception:
            pass
        await welcomer.on_member_join(member, bot)

        ar_config: dict = dict(datasys.load_data(member.guild.id, "auto_roles"))
        if ar_config.get("enabled") and ar_config.get("roles"):
            for role_id in ar_config["roles"]:
                try:
                    role = member.guild.get_role(int(role_id))
                    if role:
                        await member.add_roles(role, reason="Baxi Auto-Roles")
                        admin_log("info", f"Auto-role '{role.name}' assigned to {member.name} in {member.guild.name}", source="AutoRole")
                except (discord.Forbidden, discord.HTTPException):
                    pass

    @bot.event
    async def on_member_remove(member: discord.Member):
        admin_log("info", f"Member left: {member.name} ({member.id}) ← {member.guild.name}", source="MemberLeave")
        try:
            datasys.update_activity(member.guild.id, member_leave=True)
        except Exception:
            pass
        await welcomer.on_member_remove(member, bot)

    @bot.event
    async def on_voice_state_update(
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        guild = member.guild

        # Music: log + clean up player on bot voice state transitions
        if bot.user and member.id == bot.user.id:
            b_id = before.channel.id if before.channel else None
            a_id = after.channel.id if after.channel else None
            logger.info(f"[Music:VS] Bot voice state in guild {guild.id}: before={b_id} after={a_id} mute={after.mute} deaf={after.deaf} self_mute={after.self_mute} self_deaf={after.self_deaf}")
            if before.channel and not after.channel:
                logger.warning(f"[Music:VS] Bot was disconnected from voice in guild {guild.id} (channel {b_id})")
                # Don't immediately pop the player — let MusicIdleTask handle cleanup with grace period
                # This allows the bot to reconnect on transient errors (Discord 4006, etc)


        tv_config: dict = dict(datasys.load_data(guild.id, "temp_voice"))

        # Clean up empty temp channels regardless of feature state
        if before.channel and before.channel.id in temp_voice_channels:
            if len(before.channel.members) == 0:
                try:
                    await before.channel.delete(reason="Temporary voice channel empty")
                    temp_voice_channels.discard(before.channel.id)
                except (discord.Forbidden, discord.HTTPException):
                    pass

        if not tv_config.get("enabled", False):
            return

        create_channel_id = str(tv_config.get("create_channel_id", ""))
        name_template = tv_config.get("name_template", "{user}'s Channel")
        category_id = str(tv_config.get("category_id", ""))

        if after.channel and str(after.channel.id) == create_channel_id:
            try:
                category = None
                if category_id:
                    cat = guild.get_channel(int(category_id))
                    if isinstance(cat, discord.CategoryChannel):
                        category = cat
                if category is None:
                    category = after.channel.category

                new_name = name_template.replace("{user}", member.display_name)
                new_channel = await guild.create_voice_channel(
                    name=new_name,
                    category=category,
                    reason="Baxi Temp Voice",
                )
                temp_voice_channels.add(new_channel.id)
                await member.move_to(new_channel)
                admin_log("info", f"Temp voice created: '{new_name}' for {member.name} in {guild.name}", source="TempVoice")
            except (discord.Forbidden, discord.HTTPException) as e:
                logger.error(f"[TempVoice] Failed to create channel in {guild.id}: {e}")


async def handle_auto_release(message: discord.Message):
    """Auto-publish messages in configured news/announcement channels and react with check/cross."""
    if message.guild is None:
        return
    if not isinstance(message.channel, discord.TextChannel):
        return
    if not message.channel.is_news():
        return

    cfg: dict = dict(datasys.load_data(message.guild.id, "auto_release"))
    if not cfg.get("enabled", False):
        return

    channels = cfg.get("channels", []) or []
    if str(message.channel.id) not in [str(c) for c in channels]:
        return

    if cfg.get("ignore_bots", True) and (message.author.bot or message.webhook_id is not None):
        return

    try:
        await message.publish()
        try:
            await message.add_reaction(config.Icons.check)

            async def _remove_check():
                await asyncio.sleep(2)
                try:
                    await message.remove_reaction(config.Icons.check, message.guild.me)
                except (discord.Forbidden, discord.HTTPException, discord.NotFound):
                    pass

            asyncio.create_task(_remove_check())
        except (discord.Forbidden, discord.HTTPException):
            pass
        admin_log("info", f"Auto-Release: published msg {message.id} in #{message.channel.name} @ {message.guild.name}", source="AutoRelease")
    except (discord.Forbidden, discord.HTTPException) as e:
        try:
            await message.add_reaction(config.Icons.cross)
        except (discord.Forbidden, discord.HTTPException):
            pass
        logger.error(f"[AutoRelease] Publish failed in {message.guild.id}/{message.channel.id}: {e}")
        admin_log("warning", f"Auto-Release failed in #{message.channel.name} @ {message.guild.name}: {e}", source="AutoRelease")


async def handle_sticky_message(message: discord.Message, bot: commands.AutoShardedBot):
    """Debounced re-post of sticky message -  waits for a pause in activity before acting."""
    if message.guild is None or message.author.bot:
        return
    channel_id_str = str(message.channel.id)
    sticky_data: dict = dict(datasys.load_data(message.guild.id, "sticky_messages"))
    if channel_id_str not in sticky_data:
        return

    debounce_key = f"{message.guild.id}:{channel_id_str}"

    # Cancel any pending debounce for this channel
    existing = _sticky_debounce.get(debounce_key)
    if existing and not existing.done():
        existing.cancel()

    async def _post_sticky():
        await asyncio.sleep(_STICKY_DEBOUNCE_SECONDS)

        # Re-read fresh data after the wait
        data: dict = dict(datasys.load_data(message.guild.id, "sticky_messages"))
        entry = data.get(channel_id_str)
        if not entry:
            return

        channel = message.channel
        if not isinstance(channel, discord.TextChannel):
            return

        # Delete previous sticky message
        last_id = entry.get("last_message_id")
        if last_id:
            try:
                old_msg = await channel.fetch_message(int(last_id))
                await old_msg.delete()
            except (discord.NotFound, discord.HTTPException):
                pass

        # Send new sticky message
        try:
            embed = discord.Embed(
                description=entry["message"],
                color=config.Discord.color,
            )
            embed.set_footer(text="📌 Sticky Message · Baxi")
            new_msg = await channel.send(embed=embed)
            entry["last_message_id"] = str(new_msg.id)
            data[channel_id_str] = entry
            datasys.save_data(message.guild.id, "sticky_messages", data)
        except (discord.Forbidden, discord.HTTPException) as e:
            logger.error(f"[StickyMessage] Failed to send in {channel_id_str}: {e}")
        finally:
            _sticky_debounce.pop(debounce_key, None)

    _sticky_debounce[debounce_key] = asyncio.create_task(_post_sticky())


async def process_message(message: discord.Message, bot: commands.AutoShardedBot):
    if message.author.bot:
        return
    assert message.guild is not None, "Message guild is unknown!"
    guild_data = datasys.get_guild_data(message.guild.id)
    assert guild_data is not None, "Guild is unknown!"
    stats: dict = dict(datasys.load_data(1001, "stats"))
    stats["prossesed_messages"] = int(stats.get("prossesed_messages", 0)) + 1
    datasys.save_data(1001, "stats", stats)

    # BaxiInsights: track activity (counts only, no content)
    try:
        datasys.update_activity(
            message.guild.id,
            channel_id=str(message.channel.id),
            channel_name=getattr(message.channel, "name", None),
            user_id=str(message.author.id),
            user_name=message.author.name,
            hour=datetime.datetime.now(_VIENNA).hour,
        )
    except Exception:
        pass
    try:
        # Auto-Slowmode check (passive, non-blocking)
        asyncio.create_task(auto_slowmode.check(message))

        # Anti-Spam check (before other processing)
        is_spam = await antispam_instance.check(message, bot)
        if is_spam:
            try:
                await message.delete()
            except discord.Forbidden:
                pass
            account_age = (datetime.datetime.now(datetime.timezone.utc) - message.author.created_at).days
            sentinel.record_event(
                user_id=message.author.id,
                user_name=message.author.name,
                event_type="antispam",
                guild_id=message.guild.id,
                reason="Anti-Spam triggered",
                account_age_days=account_age,
            )
            admin_log("warning", f"Anti-Spam: deleted message from {message.author.name} in #{message.channel.name} @ {message.guild.name}", source="AntiSpam")
            return

        # Custom commands check
        handled = await customcmd.check_custom_command(message, bot)
        if handled:
            return

        # Minigames (dedicated channels – skip further pipeline if matched)
        if await counting_game.check_counting(message, bot):
            return
        if await quiz_game.check_answer(message, bot):
            return

        # Suggestions (dedicated channels – skip further pipeline if matched)
        if await suggestions_sys.check_suggestion(message, bot):
            return

        # Level system -  award XP for this message
        asyncio.create_task(leveling_sys.process_xp(message, bot))

        gc_data: dict = dict(datasys.load_data(1001, "globalchat"))
        guild_terms: bool = bool(load_data(sid=message.guild.id, sys="terms"))
        guild_id: int = message.guild.id if message.guild is not None else 0
        lang = datasys.load_lang_file(guild_id)
        chatfilter_data: dict = dict(datasys.load_data(message.guild.id, "chatfilter"))
        chatfilter_instance = chatfilter.Chatfilter()

        # Fetch recent channel history for AI context (only when AI system is active)
        ai_history: list[dict] | None = None
        if chatfilter_data.get("system", "SafeText").lower() == "ai":
            try:
                ai_history = []
                chatfilter_logs_cache: dict | None = None
                async for hist_msg in message.channel.history(limit=8, before=message):
                    if (
                        hist_msg.author.bot
                        and hist_msg.embeds
                        and hist_msg.embeds[0].footer.text == "Baxi Security - avocloud.net"
                    ):
                        embed_desc = hist_msg.embeds[0].description or ""
                        restid_match = re.search(r"id_chatfilter=([a-f0-9]+)", embed_desc)
                        if restid_match:
                            restid = restid_match.group(1)
                            if chatfilter_logs_cache is None:
                                chatfilter_logs_cache = dict(datasys.load_data(1001, "chatfilter_log"))
                            log_entry = chatfilter_logs_cache.get(restid)
                            if log_entry:
                                ai_history.append({
                                    "author": log_entry["uname"],
                                    "content": f"[deleted by chatfilter: {log_entry['message']}]",
                                })
                    else:
                        ai_history.append({
                            "author":  hist_msg.author.name,
                            "content": hist_msg.clean_content,
                        })
                ai_history.reverse()  # oldest first
            except Exception:
                ai_history = None

        chatfilter_req: dict = await chatfilter_instance.check(
            message=message.clean_content, gid=message.guild.id, cid=message.channel.id,
            user_id=message.author.id, history=ai_history,
        )

        tickets: dict = dict(datasys.load_data(message.guild.id, "open_tickets"))

        if str(message.channel.id) in tickets:
            guild_ticket_config: dict = dict(
                datasys.load_data(message.guild.id, "ticket")
            )
            user_avatar: str = (
                "" if message.author.avatar is None else message.author.avatar.url
            )
            attachments_list: list = []
            if message.attachments:
                for attachment in message.attachments:
                    file_path = (
                        Path(config.Globalchat.attachments_dir)
                        / f"ticket{message.channel.id}-{random.randint(100, 999)}.png"
                    )
                    image = Image.open(BytesIO(await attachment.read()))
                    image.save(file_path)
                    attachments_list.append(
                        str(file_path)
                        .replace(config.Globalchat.attachments_dir, "")
                        .replace("/", "")
                    )

            user = await message.guild.fetch_member(message.author.id)
            is_staff: bool = int(guild_ticket_config.get("role", 0)) in [
                role.id for role in user.roles
            ]

            clean_msg = message.clean_content

            tickets[str(message.channel.id)]["transcript"].append(
                {
                    "type": "message",
                    "user": str(message.author.name),
                    "avatar": str(user_avatar),
                    "timestamp": str(datetime.datetime.now(_VIENNA)),
                    "message": clean_msg,
                    "attachments": attachments_list,
                    "is_staff": is_staff,
                }
            )
            datasys.save_data(message.guild.id, "open_tickets", tickets)
            return
        _cf_reason = str(chatfilter_req["reason"]).lower()
        if _cf_reason in {"s11", "5"}:
            if not guild_terms:
                return
            dm_channel = message.author.dm_channel
            if dm_channel is None:
                dm_channel = await message.author.create_dm()

            embed = discord.Embed(
                title="SYS // NOTICE",
                description="We saw that your message mentioned **self-harm**, **suicide**, or **disordered eating**, and we want you to know something really important: **you are not alone**. So many people struggle with these feelings, and it's okay to feel overwhelmed sometimes. What you're going through matters, and it's completely okay to ask for help- because you deserve support and kindness.\n\n"
                "If you ever feel like talking to someone, whether it's a **friend**, **family member**, or a **mental health professional**, please don't hesitate. **You don't have to carry this by yourself.** There are people who care deeply and want to be there for you.\n\n"
                "For immediate support, you can reach out to the **International Suicide Prevention Lifeline** at **+1-800-273-8255** (this number also connects you to help worldwide), or visit https://www.iasp.info/resources/Crisis_Centres/ to find a crisis center near you.\n\n"
                "If you're in **Austria** or **Germany**, here are some local resources you can contact anytime:\n"
                "- Austria: Telefonseelsorge -  142 (free & confidential) | https://www.telefonseelsorge.at/\n"
                "- Germany: Telefonseelsorge -  0800 111 0 111 or 0800 111 0 222 (free & confidential) | https://www.telefonseelsorge.de/",
                color=config.Discord.danger_color,
            )

            if (
                str(message.guild.id) in gc_data
                and message.channel.id == gc_data[str(message.guild.id)]["channel"]
            ):
                embed = discord.Embed(
                    description=lang["systems"]["globalchat"]["error"]["s11-not-sent"],
                    color=config.Discord.danger_color,
                )
                await message.channel.send(embed=embed)

            await dm_channel.send(embed=embed)
            return

        if (
            bool(chatfilter_data.get("enabled", False))
            and message.channel.id not in chatfilter_data.get("bypass", [])
        ):

            if chatfilter_req["flagged"] is True:
                if not guild_terms:
                    return
                else:
                    await del_chatfilter(
                        message=message, reason=chatfilter_req["reason"], bot=bot,
                        cf_system=chatfilter_data.get("system", "SafeText"),
                    )

        elif not bool(chatfilter_data.get("enabled", False)):
            # Chatfilter OFF → Prism silent scan.
            # SafeText alone is too weak on unconfigured servers, so if it came back clean
            # we run an additional AI check specifically for Prism (no moderation action taken).
            prism_req = chatfilter_req
            if not chatfilter_req.get("flagged"):
                try:
                    prism_req = await chatfilter_instance._try_ai_check_queued(message.clean_content)
                except Exception as _ai_err:
                    logger.error(f"[Prism] Silent AI check error: {_ai_err}")
                    prism_req = None

            if prism_req and prism_req.get("flagged"):
                try:
                    account_age = (datetime.datetime.now(datetime.timezone.utc) - message.author.created_at).days
                    _pr = prism_req.get("reason", "")
                    if _pr == "phishing":
                        event_type = "chatfilter_phishing"
                    elif _pr == "3":
                        event_type = "chatfilter_hate"
                    elif _pr == "2":
                        event_type = "chatfilter_mild"
                    else:
                        event_type = "chatfilter_violation"
                    sentinel.record_event(
                        user_id=message.author.id,
                        user_name=message.author.name,
                        event_type=event_type,
                        guild_id=message.guild.id,
                        reason=f"[Silent] {_PRISM_REASON_LABELS.get(_pr, _pr)}",
                        account_age_days=account_age,
                    )
                    logger.info(
                        f"[Prism] Silent scan recorded -  user={message.author.name} "
                        f"guild={message.guild.id} reason={prism_req.get('reason')}"
                    )
                except Exception as _prism_err:
                    logger.error(f"[Prism] Silent scan record error: {_prism_err}")

        if str(message.guild.id) in gc_data and message.channel.id == int(
            gc_data[str(message.guild.id)]["channel"]
        ):
            if not guild_terms:
                embed = discord.Embed(
                    description=str(lang["systems"]["terms"]["description"]).format(
                        url=f"https://{config.Web.url}"
                    ),
                    color=config.Discord.danger_color,
                )
                embed.set_footer(text="Baxi · avocloud.net")
                await message.reply(embed=embed)
                return
            if chatfilter_req["flagged"] is True:
                await del_chatfilter(
                    message=message, reason=chatfilter_req["reason"], bot=bot,
                    cf_system=chatfilter_data.get("system", "SafeText"),
                )
                return
            else:
                return await globalchat.globalchat(
                    bot=bot, message=message, gc_data=gc_data
                )

    except Exception as e:
        print(e)


async def del_chatfilter(
    message: discord.Message, reason: str, bot: commands.AutoShardedBot,
    cf_system: str = "SafeText",
):
    chatfilter_logs: dict = dict(load_data(1001, "chatfilter_log"))
    id = os.urandom(8).hex()
    assert message.guild is not None, "Message guild unknown!"
    lang = datasys.load_lang_file(message.guild.id)
    try:
        await message.delete()
        deleted = True
    except Exception as e:
        print(f"Chatfilter: Could not delete message: {e}")
        deleted = False
    reason_list: dict = {
        "custom":   "Custom badword",
        "internal": "Badword",
        "phishing": "Phishing / Scam Link",
        # AI safety codes
        "1": "NSFW / Explicit Content",
        "2": "Insults / Toxicity",
        "3": "Hate Speech / Discrimination",
        "4": "Doxxing / Personal Data",
        "5": "Suicide / Self-Harm",
        # Legacy llama-guard codes (kept for existing logs)
        "S3":  "S3 - Sex-Related Crimes",
        "S4":  "S4 - Child Sexual Exploitation",
        "S5":  "S5 - Defamation",
        "S10": "S10 - Hate",
        "S11": "S11 - Suicide & Self-Harm",
        "S12": "S12 - Sexual Content",
        "S13": "S13 - Elections",
    }
    desc_key = "description" if deleted else "description_not_deleted"
    embed = discord.Embed(
        title=config.Icons.messageexclamation
        + " "
        + lang["systems"]["chatfilter"]["title"],
        description=str(lang["systems"]["chatfilter"][desc_key]).format(
            user=f"{message.author.mention}",
            id=f"{id}",
            link=f"https://baxi.avocloud.net?id_chatfilter={id}",
            reason=f"{reason_list.get(reason)}",
        ),
        color=config.Discord.danger_color,
    ).set_footer(text=lang["systems"]["chatfilter"]["footer"])
    formatted_time: str = message.created_at.strftime("%d.%m.%Y - %H:%M")
    formatted_time_user: str = message.author.created_at.strftime("%d.%m.%Y - %H:%M")
    assert bot.user is not None, "Bot user unknwon"
    assert bot.user.avatar is not None, "Bot user avatar unknwon"
    assert message.channel is not None, "Message Channel unknown"
    cname: str = (
        message.channel.name
        if isinstance(message.channel, discord.TextChannel)
        else "DM or Unknown"
    )
    # Infer which system caught this message
    ai_reasons = {"1", "2", "3", "4", "5", "S3", "S4", "S5", "S10", "S11", "S12", "S13"}
    if reason == "phishing":
        detected_system = "Phishing"
    elif reason in ai_reasons:
        detected_system = "AI"
    else:
        detected_system = cf_system  # "SafeText" or whatever was passed

    chatfilter_logs[str(id)] = {
        "id": str(id),
        "uid": int(message.author.id),
        "uname": str(message.author.name),
        "uicon": (
            str(message.author.avatar.url)
            if message.author.avatar
            else bot.user.avatar.url
        ),
        "sid": int(message.guild.id),
        "sname": str(message.guild.name),
        "sicon": (
            str(message.guild.icon.url) if message.guild.icon else bot.user.avatar.url
        ),
        "mid": int(message.id),
        "cid": int(message.channel.id),
        "cname": str(cname),
        "timestamp": str(formatted_time),
        "user_created_at": str(formatted_time_user),
        "reason": str(reason_list[reason]),
        "message": str(message.content),
        "system": detected_system,
    }
    save_data(1001, "chatfilter_log", chatfilter_logs)
    admin_log("warning",
        f"Chatfilter [{detected_system}] -  {message.author.name} in #{cname} @ {message.guild.name}: "
        f"{reason_list.get(reason, reason)} | \"{message.content[:80]}{'…' if len(message.content) > 80 else ''}\" | ID: {id}",
        source="Chatfilter"
    )

    # BaxiInsights: log filter event (no message content)
    try:
        _severity_map = {
            "phishing": 5,
            "1": 4,   # NSFW
            "2": 3,   # Toxicity
            "3": 5,   # Hate
            "4": 4,   # Doxxing
            "5": 4,   # Self-harm
            "internal": 1,
            "custom": 2,
        }
        _category_map = {
            "phishing": "phishing",
            "1": "nsfw",
            "2": "toxicity",
            "3": "hate",
            "4": "doxxing",
            "5": "selfharm",
            "internal": "keyword",
            "custom": "keyword",
        }
        datasys.append_filter_event(message.guild.id, {
            "system": "AI" if detected_system.lower() == "ai" else "SafeText",
            "severity": _severity_map.get(str(reason), 2),
            "category": _category_map.get(str(reason), "keyword"),
            "user_id": str(message.author.id),
            "user_name": message.author.name,
            "channel_id": str(message.channel.id),
            "channel_name": message.channel.name if hasattr(message.channel, "name") else str(message.channel.id),
            "timestamp": datetime.datetime.utcnow().isoformat(),
        })
    except Exception as _ins_err:
        logger.error(f"[BaxiInsights] filter event log error: {_ins_err}")

    # Prism: record chatfilter violation (map AI category 3 = Hate Speech to chatfilter_hate)
    try:
        account_age = (datetime.datetime.now(datetime.timezone.utc) - message.author.created_at).days
        if reason == "phishing":
            event_type = "chatfilter_phishing"
        elif reason == "3":
            event_type = "chatfilter_hate"
        elif reason == "2":
            event_type = "chatfilter_mild"
        else:
            event_type = "chatfilter_violation"
        sentinel.record_event(
            user_id=message.author.id,
            user_name=message.author.name,
            event_type=event_type,
            guild_id=message.guild.id,
            reason=reason_list.get(reason, reason),
            account_age_days=account_age,
        )
    except Exception as _prism_err:
        logger.error(f"[Prism] Hook error in del_chatfilter: {_prism_err}")

    await message.channel.send(embed=embed)
    if not deleted and reason == "phishing":
        await message.channel.send(
            str(lang["systems"]["chatfilter"]["phishing_warning"]).format(
                user=message.author.mention
            )
        )


async def _mc_chat_bridge(message):
    """Relay Discord messages from the bridge channel to MC. Drops unlinked authors silently."""
    try:
        import discord as _discord
        if message.guild is None or message.author.bot:
            return
        if not isinstance(message.channel, (_discord.TextChannel, _discord.Thread)):
            return
        conf = dict(datasys.load_data(message.guild.id, "conf")) if False else None
        # conf.json is read directly
        import json as _json, os as _os
        conf_path = _os.path.join("data", str(message.guild.id), "conf.json")
        if not _os.path.exists(conf_path):
            return
        with open(conf_path) as f:
            conf = _json.load(f)
        mcl = conf.get("mc_link", {})
        if not mcl.get("enabled") or not mcl.get("chat_enabled", False):
            return
        chat_channel_id = str(mcl.get("chat_channel", "")).strip()
        if not chat_channel_id or str(message.channel.id) != chat_channel_id:
            return

        api_url = (mcl.get("api_url") or "").strip()
        api_secret = (mcl.get("api_secret") or "").strip()
        if not api_url or not api_secret:
            return

        from assets.mc_link import get_link, send_chat_in
        link = get_link(message.guild.id, message.author.id)
        if not link:
            return  # unlinked: drop silently per design

        content = (message.clean_content or "").strip()
        if not content:
            return
        await send_chat_in(
            api_url=api_url,
            secret=api_secret,
            discord_id=message.author.id,
            discord_name=message.author.display_name,
            mc_name=link.get("name", "?"),
            content=content,
        )
    except Exception as e:
        try:
            logger.error(f"[mc-chat-bridge] error: {e}")
        except Exception:
            pass
