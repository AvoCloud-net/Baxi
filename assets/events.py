import asyncio
import json
import os
import datetime
from zoneinfo import ZoneInfo

_VIENNA = ZoneInfo("Europe/Vienna")

from pathlib import Path
from PIL import Image
from io import BytesIO
import random

import assets.data as datasys
import assets.message.globalchat as globalchat
import assets.message.chatfilter as chatfilter
import assets.message.welcomer as welcomer
from assets.buttons import TicketView
import assets.message.customcmd as customcmd
from assets.message.antispam import AntiSpam
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
)
from discord.ext import commands
from reds_simple_logger import Logger
from assets.data import load_data, save_data
from assets.dash.dash import dash_web


logger = Logger()


antispam_instance = AntiSpam()


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

            logger.working("Starting Livestream task...")
            share.livestream_task = LivestreamTask(bot)
            share.livestream_task.check_streams.start()
            share.task_instances["Livestream"] = share.livestream_task
            logger.debug.success("Livestream check task started.")

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
        admin_log("info", f"Bot joined guild: {guild.name} ({guild.id}) — {guild.member_count} members", source="GuildJoin")
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

    @bot.event
    async def on_message_delete(message: discord.Message):
        if message.guild is None:
            return

        # Resend livestream embed if deleted
        if share.livestream_task is not None:
            await share.livestream_task.on_embed_deleted(message) # type: ignore

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
                    panel_msg = await channel.send(embed=embed, view=TicketView())
                    ticket_config["panel_message_id"] = str(panel_msg.id)
                    datasys.save_data(message.guild.id, "ticket", ticket_config)
            except (discord.Forbidden, discord.HTTPException, Exception):
                pass

    @bot.event
    async def on_member_join(member: discord.Member):
        admin_log("info", f"Member joined: {member.name} ({member.id}) → {member.guild.name}", source="MemberJoin")
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
        await welcomer.on_member_remove(member, bot)

    @bot.event
    async def on_voice_state_update(
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        guild = member.guild
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


async def process_message(message: discord.Message, bot: commands.AutoShardedBot):
    if message.author.bot:
        return
    assert message.guild is not None, "Message guild is unknown!"
    guild_data = datasys.get_guild_data(message.guild.id)
    assert guild_data is not None, "Guild is unknown!"
    stats: dict = dict(datasys.load_data(1001, "stats"))
    stats["prossesed_messages"] = int(stats.get("prossesed_messages", 0)) + 1
    datasys.save_data(1001, "stats", stats)
    try:
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
                async for hist_msg in message.channel.history(limit=8, before=message):
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
                description="We saw that your message mentioned **self-harm**, **suicide**, or **disordered eating**, and we want you to know something really important: **you are not alone**. So many people struggle with these feelings, and it's okay to feel overwhelmed sometimes. What you're going through matters, and it's completely okay to ask for help—because you deserve support and kindness.\n\n"
                "If you ever feel like talking to someone, whether it's a **friend**, **family member**, or a **mental health professional**, please don't hesitate. **You don't have to carry this by yourself.** There are people who care deeply and want to be there for you.\n\n"
                "For immediate support, you can reach out to the **International Suicide Prevention Lifeline** at **+1-800-273-8255** (this number also connects you to help worldwide), or visit https://www.iasp.info/resources/Crisis_Centres/ to find a crisis center near you.\n\n"
                "If you're in **Austria** or **Germany**, here are some local resources you can contact anytime:\n"
                "- Austria: Telefonseelsorge — 142 (free & confidential) | https://www.telefonseelsorge.at/\n"
                "- Germany: Telefonseelsorge — 0800 111 0 111 or 0800 111 0 222 (free & confidential) | https://www.telefonseelsorge.de/",
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
                    event_type = "chatfilter_phishing" if prism_req.get("reason") == "phishing" else "chatfilter_violation"
                    sentinel.record_event(
                        user_id=message.author.id,
                        user_name=message.author.name,
                        event_type=event_type,
                        guild_id=message.guild.id,
                        reason=f"[Silent] {prism_req.get('reason', 'unknown')}",
                        account_age_days=account_age,
                    )
                    logger.info(
                        f"[Prism] Silent scan recorded — user={message.author.name} "
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
        f"Chatfilter [{detected_system}] — {message.author.name} in #{cname} @ {message.guild.name}: "
        f"{reason_list.get(reason, reason)} | \"{message.content[:80]}{'…' if len(message.content) > 80 else ''}\" | ID: {id}",
        source="Chatfilter"
    )

    # Prism: record chatfilter violation
    try:
        account_age = (datetime.datetime.now(datetime.timezone.utc) - message.author.created_at).days
        event_type = "chatfilter_phishing" if reason == "phishing" else "chatfilter_violation"
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
