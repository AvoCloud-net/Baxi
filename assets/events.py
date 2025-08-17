import asyncio
import json
import os
import datetime

import assets.data as datasys
import assets.message.globalchat as globalchat
import assets.message.chatfilter as chatfilter
import config.config as config
import discord

from typing import cast
from assets.share import globalchat_message_data
from assets.tasks import GCDH_Task
from discord.ext import commands
from reds_simple_logger import Logger
from assets.data import load_data, save_data
from assets.dash.dash import dash_web


logger = Logger()


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

        guild_ids = [guild.id for guild in bot.guilds]

        for guild_id in guild_ids:
            guild_folder = os.path.join("data", str(guild_id))
            if not os.path.exists(guild_folder):
                os.makedirs(guild_folder)
                config_path = os.path.join(guild_folder, "conf.json")

                data: dict = config.datasys.default_data
                guild = await bot.fetch_guild(int(guild_id))
                data["guild_name"] = str(guild.name)

                with open(config_path, "w") as config_file:
                    json.dump(data, config_file, indent=4)
                logger.success(f"Ordner und conf.json für Guild {guild_id} erstellt.")
            else:
                logger.success(f"Ordner für Guild {guild_id} existiert bereits.")

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
            logger.debug.success("Globalchat message data sync task started.")

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
                    lang["events"]["on_guild_join"]["content"]
                    + "\n\n# THIS IS A BETA VERSION"
                ).format(saved_data=data_text),
            )
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

        asyncio.create_task(process_message(message, bot))


async def process_message(message: discord.Message, bot: commands.AutoShardedBot):
    if message.author.bot:
        return
    assert message.guild is not None, "Message guild is unknown!"
    guild_data = datasys.get_guild_data(message.guild.id)
    assert guild_data is not None, "Guild is unknown!"
    try:
        gc_data: dict = dict(datasys.load_data(1001, "globalchat"))
        guild_id: int = message.guild.id if message.guild is not None else 0
        lang = datasys.load_lang_file(guild_id)
        chatfilter_data: dict = dict(datasys.load_data(message.guild.id, "chatfilter"))
        chatfilter_instance = chatfilter.Chatfilter()
        chatfilter_req: dict = await chatfilter_instance.check(
            message=message.clean_content, gid=message.guild.id, cid=message.channel.id
        )
        print(str(chatfilter_req["reason"]).lower())
        if str(chatfilter_req["reason"]).lower() == "s11":
            dm_channel = message.author.dm_channel
            if dm_channel is None:
                dm_channel = await message.author.create_dm()

            embed = discord.Embed(
                title="Hey there!",
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

        print(chatfilter_req)
        if str(message.guild.id) in gc_data:
            if chatfilter_req["flagged"] is True:
                await del_chatfilter(
                    message=message, reason=chatfilter_req["reason"], bot=bot
                )
                return

        elif (
            bool(chatfilter_data.get("enabled", False))
            and message.channel.id not in chatfilter_data["bypass"]
        ):
            if chatfilter_req["flagged"] is True:
                await del_chatfilter(
                    message=message, reason=chatfilter_req["reason"], bot=bot
                )

        if str(message.guild.id) in gc_data and message.channel.id == int(
            gc_data[str(message.guild.id)]["channel"]
        ):
            return await globalchat.globalchat(
                bot=bot, message=message, gc_data=gc_data
            )
        
        settings: dict = dict(datasys.load_data(message.guild.id, sys="ticket"))
        try:
            tickets = settings["open_tickets"]
        except KeyError:
            settings["open_tickets"] = {}
            save_data(message.guild.id, "ticket", settings)
            tickets = settings["open_tickets"]
        if str(message.channel.id) in list(tickets):
            user_avatar: str = (
                "" if message.author.avatar is None else message.author.avatar.url
            )
            tickets[str(message.channel.id)]["transcript"].append(
                {
                    "user": str(message.author.name),
                    "avatar": str(user_avatar),
                    "timestamp": str(datetime.datetime.now()),
                    "message": str(message.content),
                }
            )
            datasys.save_data(message.guild.id, "ticket", settings)
            return

    except Exception as e:
        print(e)


async def del_chatfilter(
    message: discord.Message, reason: str, bot: commands.AutoShardedBot
):
    chatfilter_logs: dict = dict(load_data(1001, "chatfilter_log"))
    id = os.urandom(8).hex()
    assert message.guild is not None, "Message guild unknown!"
    lang = datasys.load_lang_file(message.guild.id)
    await message.delete()
    reason_list: dict = {
        "custom": "Custom badword",
        "internal": "Badword",
        "S3": "S3 - Sex-Related Crimes",
        "S4": "S4 - Child Sexual Exploitation",
        "S5": "S5 - Defamation",
        "S10": "S10 - Hate",
        "S11": "S11 - Suicide & Self-Harm",
        "S12": "S12 - Sexual Content",
        "S13": "S13 - Elections",
    }
    embed = discord.Embed(
        title=config.Icons.messageexclamation
        + " "
        + lang["systems"]["chatfilter"]["title"],
        description=str(lang["systems"]["chatfilter"]["description"]).format(
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
    }
    save_data(1001, "chatfilter_log", chatfilter_logs)
    await message.channel.send(embed=embed)
