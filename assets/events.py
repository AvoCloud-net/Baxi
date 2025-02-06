import asyncio
import json
import os

import assets.data as datasys
import assets.message.chatfilter as chatfilter
import assets.message.globalchat as globalchat
from assets.message.counting import counting
from assets.message.guessing import guessing
import assets.translate as tr
import config.auth as auth
import config.config as config
import discord
import lang.de as de
import requests
import wavelink
from assets.ai import *
from assets.share import globalchat_message_data
from assets.tasks import SyncGlobalchatMessageDataTask
from assets.ai import ai_conversations
from discord.ext import commands
from reds_simple_logger import Logger
from assets.data import load_data, save_data


logger = Logger()


def events(bot: commands.AutoShardedBot):
    logger.debug.info("Events loaded.")

    @bot.event
    async def on_ready():
        logger.info("Almost ready...")

        def load_globalchat_message_data():
            logger.debug.info("Loading globalchat_message_data")
            return dict(datasys.load_data(1001, "globalchat_message_data"))

        globalchat_message_data_file = await asyncio.to_thread(
            load_globalchat_message_data
        )
        globalchat_message_data.update(globalchat_message_data_file)
        logger.debug.info(f"Loaded GCMD!: {globalchat_message_data}")

        try:
            if not hasattr(bot, "synced"):
                bot.synced = True
                await bot.tree.sync()
                logger.info("Bot synced with discord!")
            else:
                logger.info("Sync skipped. (No changes)")
            logger.info(f"Bot started with {bot.shard_count} shards!")
            await bot.change_presence(
                activity=discord.Activity(
                    type=discord.ActivityType.playing,
                    name=f"on {len(bot.guilds)} Worlds! - v{config.Discord.version}",
                )
            )
            sync_task = SyncGlobalchatMessageDataTask(bot)
            sync_task.sync_globalchat_message_data.start()
            logger.debug.info("Globalchat message data sync task started.")
        except Exception as e:
            await bot.change_presence(
                activity=discord.Activity(
                    type=discord.ActivityType.watching,
                    name=f"die Crash logs durch... - Server start Fehler",
                )
            )
            logger.error("ERROR SYNCING! " + str(e))

        bot.loop.create_task(node_connect())

    @bot.event
    async def on_shard_ready():
        logger.info(f"Shard {bot.shard_id} is ready!")

    async def node_connect():
        try:
            logger.waiting("Connecting to Lavalink node...")
            node = wavelink.Node(
                uri=auth.Music.uri,
                resume_timeout=80,
                password=auth.Music.password,
                client=bot,
                retries=3,
                identifier="SoundNode1",
            )
            await wavelink.Pool.connect(nodes=[node], client=bot)
            logger.success("Successfully connected to Lavalink!")

        except TimeoutError:
            logger.error("Timeout connecting to Node")
        except Exception as e:
            logger.error(f"Unknown error: {e}")

    @bot.event
    async def on_guild_join(guild: discord.Guild):
        guild_data_dir = f"data/{guild.id}"
        data_dir_exists: bool = os.path.exists(guild_data_dir)
        updates_channel = datasys.load_data(1001, "updates")
        if not data_dir_exists:
            logger.info("New Guild joined! Config directory and file is created...")
            os.makedirs(guild_data_dir)
            json_file_path = os.path.join(guild_data_dir, "conf.json")
            with open(json_file_path, "w", encoding="utf-8") as json_file:
                json.dump(config.datasys.default_data, json_file, indent=4)
            data_text = de.Events.on_guild_join.saved_data.new_data
            channel = await guild.create_text_channel(
                name="baxi-updates",
                reason="Baxi info channel setup.",
                topic="Here all information, updates and warnings that are issued by our team are displayed.",
            )
            updates_channel[str(guild.id)] = {"cid": channel.id}
            datasys.save_data(1001, "updates", updates_channel.to_dict())
        else:
            logger.info("Already joined a known guild. Existing data is loaded...")
            data_text = de.Events.on_guild_join.saved_data.existing_data
            updates_channel = datasys.load_data(1001, "updates")
            channel = guild.get_channel(updates_channel[str(guild.id)]["cid"])

        lang = datasys.load_data(guild.id, "lang")
        embed = discord.Embed(
            title=await tr.baxi_translate(de.Events.on_guild_join.title, lang),
            description=await tr.baxi_translate(
                de.Events.on_guild_join.content, lang
            ).format(saved_data=await tr.baxi_translate(data_text, lang)),
        )
        await channel.send(embed=embed)

    @bot.event
    async def on_message(message: discord.Message):
        guild_data = datasys.get_guild_data(message.guild.id)
        print(guild_data.icon)
        try:
            gc_data = datasys.load_data(1001, "globalchat")
            guild_id = message.guild.id if message.guild is not None else None
            lang = datasys.load_lang(guild_id)
            chatfilter_data = datasys.load_data(message.guild.id, "chatfilter")
            chatfilter_req = chatfilter.Chatfilter().check(
                message=message.content, gid=message.guild.id, cid=message.channel.id
            )

            if chatfilter_req.flagged is True:
                if str(message.guild.id) not in gc_data.data:
                    if (
                        bool(chatfilter_data.enabled)
                        and message.channel.id not in chatfilter_data.bypass
                    ):

                        await del_chatfilter(message=message, word = chatfilter_req.original_word, match = chatfilter_req.match)
                        return
                    else:
                        pass
                else:
                    await del_chatfilter(message=message)
                    return
            else:
                pass

            if message.author.bot:
                return
            if (
                str(message.guild.id) in gc_data.data
                and message.channel.id == gc_data.data[str(message.guild.id)]["cid"]
            ):
                return await globalchat.globalchat(
                    bot=bot, message=message, gc_data=gc_data
                )

            if await counting(message=message):
                return

            if await guessing(message=message):
                return

            await conversation_start_response(bot=bot, message=message, lang=lang)
            if await conversation_answer_response(bot=bot, message=message, lang=lang):
                return
            if await conversation_start_response(bot=bot, message=message, lang=lang):
                return

        except Exception as e:
            print(e)


async def get_message_chain(message):
    chain = []
    current_message = message

    while current_message.reference:
        try:
            current_message = await current_message.channel.fetch_message(
                current_message.reference.message_id
            )
            chain.append(current_message)
        except discord.NotFound:
            break

    return chain[::-1]


async def del_chatfilter(message: discord.Message, word: str, match: str):
    chatfilter_logs:dict = load_data(1001, "chatfilter_log")
    id = os.urandom(8).hex()
    await message.delete()
    embed = (
        discord.Embed(
            title=de.Chatfilter.title,
            description=de.Chatfilter.Description.text.format(
                user=message.author.mention,
                id=id,
                link=f"https://security.avocloud.net/chatfilterinfo?requestid={id}",
            ),
            color=config.Discord.danger_color,
        )
        .set_footer(text=de.Chatfilter.footer)
        .set_thumbnail(url=config.Icons.danger)
    )
    formatted_time:str = message.created_at.strftime("%d.%m.%Y - %H:%M")
    formatted_time_user:str = message.author.created_at.strftime("%d.%m.%Y - %H:%M")
    chatfilter_logs[str(id)] = {
        "id": str(id),
        "uid": int(message.author.id),
        "uname": str(message.author.name),
        "uicon": str(message.author.avatar.url),
        "sid": int(message.guild.id),
        "sname": str(message.guild.name),
        "sicon": str(message.guild.icon.url),
        "mid": int(message.id),
        "cid": int(message.channel.id),
        "cname": str(message.channel.name),
        "timestamp": str(formatted_time),
        "user_created_at": str(formatted_time_user),
        "word": str(word),
        "match": str(match),
        "message": str(message.content)
    }
    save_data(1001, "chatfilter_log", chatfilter_logs)
    await message.channel.send(embed=embed)
