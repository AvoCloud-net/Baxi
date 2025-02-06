import os

import assets.data as datasys
import assets.translate as tr
import config.config as config
import discord, asyncio
import lang.de as de
from assets.share import globalchat_message_data
from discord import (
    CategoryChannel,
    Client,
    Emoji,
    Guild,
    Member,
    Message,
    Role,
    TextChannel,
    User,
    VoiceChannel,
)
from discord.ext import commands


async def globalchat(bot: commands.AutoShardedBot, message: Message, gc_data: dict):
    print("globalchat")
    try:
        reply: bool = False
        guild_id = message.guild.id if message.guild is not None else None
        lang = datasys.load_lang(guild_id)
        gc_ban = datasys.load_data(1001, "gc_ban")
        ba_ban = datasys.load_data(1001, "ba_ban")
        gcmid: str = os.urandom(8).hex()
        if str(message.author.id) in gc_ban or str(message.author.id) in ba_ban:
            await message.reply(
                content=await tr.baxi_translate(de.Globalchat.Error.baned, lang),
                delete_after=10,
            )
            await message.delete(delay=10)
            return

        if len(message.content) > 1000:
            await message.reply(
                content=await tr.baxi_translate(
                    de.Globalchat.Error.message_to_long, lang
                ),
                delete_after=5,
            )
            await message.delete(delay=5)
            return

        while True:
            gcmid: str = os.urandom(8).hex()
            if gcmid in globalchat_message_data:
                continue
            else:
                break
        globalchat_message_data[str(gcmid)] = {
            "author_id": message.author.id,
            "author_name": message.author.name,
            "reply": reply,
            "referenceid": None,
            "messages": [],
            "replies": [],
        }

        embed = discord.Embed(description=message.content).set_author(
            name=message.author.name, icon_url=config.Icons.user
        )
        embed.set_footer(
            text=f"{message.guild.name} | {message.guild.id} | {message.author.id} | {gcmid}"
        )
        embed.set_thumbnail(url=message.author.avatar.url)
        if len(message.attachments) == 1:  #
            if message.attachments[0].content_type.startswith("image/"):
                file_path = os.path.join(
                    config.Globalchat.attachments_dir, f"{gcmid}.png"
                )
                await message.attachments[0].save(file_path)
                embed.set_image(url=f"{config.Globalchat.attachments_url}{gcmid}.png")
            else:
                await message.reply(
                    content=f"{message.author.mention}\n{await tr.baxi_translate(de.Globalchat.Error.file_not_image)}",
                    delete_after=5,
                )
                await message.delete(delay=5)
                return
        elif len(message.attachments) > 1:
            await message.reply(
                content=f"{message.author.mention}\n{await tr.baxi_translate(de.Globalchat.Error.to_many_files)}",
                delete_after=5,
            )
            await message.delete(delay=5)
            return

        if message.reference:
            replied_message = await message.channel.fetch_message(
                message.reference.message_id
            )
            if replied_message and replied_message.embeds:
                referenced_embed = replied_message.embeds[0]
                if referenced_embed.footer:
                    reply = True
                    referenced_mid = referenced_embed.footer.text.split(" | ")[3]
                    embed.set_footer(
                        text=f"{message.guild.name} | {message.guild.id} | {message.author.id} | {gcmid} | {referenced_mid}"
                    )
                    if len(referenced_embed.description) > 30:
                        embed.add_field(
                            name=f"Replies to {referenced_embed.author.name} message:",
                            value=referenced_embed.description[:30] + "...",
                        )
                    else:
                        embed.add_field(
                            name=f"Replies to {referenced_embed.author.name} message:",
                            value=referenced_embed.description,
                        )

        sent_message = await message.channel.send(embed=embed)
        globalchat_message_data[str(gcmid)]["messages"].append(
            {
                "gid": sent_message.guild.id,
                "cid": sent_message.channel.id,
                "mid": sent_message.id,
            }
        )
        globalchat_message_data[str(gcmid)]["reply"] = reply
        if reply:
            globalchat_message_data[str(gcmid)]["referenceid"] = referenced_mid
            globalchat_message_data[str(referenced_mid)]["replies"].append(
                {
                    "gid": sent_message.guild.id,
                    "cid": sent_message.channel.id,
                    "mid": sent_message.id,
                    "referenceid": gcmid,
                    "replyid": referenced_mid,
                }
            )

        async def gc_send_msg():
            for server_id, server in gc_data.items():
                if server["cid"] == message.channel.id:
                    continue
                guild = bot.get_guild(server["gid"])
                channel = guild.get_channel(server["cid"])
                sent_message = await channel.send(embed=embed)
                if str(gcmid) not in globalchat_message_data:
                    globalchat_message_data[str(gcmid)] = {
                        "messages": [],
                        "replies": [],
                    }

                globalchat_message_data[str(gcmid)]["messages"].append(
                    {
                        "gid": sent_message.guild.id,
                        "cid": sent_message.channel.id,
                        "mid": sent_message.id,
                    }
                )
                if reply:
                    print(referenced_mid)
                    globalchat_message_data[str(referenced_mid)]["replies"].append(
                        {
                            "gid": sent_message.guild.id,
                            "cid": sent_message.channel.id,
                            "mid": sent_message.id,
                        }
                    )

        await asyncio.create_task(gc_send_msg(), name="gc_send_msg")
        await message.delete()
    except Exception as e:
        print(f"Error in global chat: {e}\n{e.with_traceback}")
        print(f"gc_data: {gc_data}")
        print(f"globalchat_message_data: {globalchat_message_data}")
