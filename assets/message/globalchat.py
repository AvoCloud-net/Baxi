import os

import assets.data as datasys
import config.config as config
import discord
import asyncio
from assets.share import globalchat_message_data
from discord import (
    Message,
    TextChannel,
)
from discord.ext import commands
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO


async def globalchat(bot: commands.AutoShardedBot, message: Message, gc_data: dict):
    try:
        reply: bool = False
        guild_id = message.guild.id if message.guild is not None else 0
        lang = datasys.load_lang_file(guild_id)
        gc_ban = datasys.load_data(1001, "gc_ban")
        ba_ban = datasys.load_data(1001, "ba_ban")
        gcmid: str = os.urandom(8).hex()
        if str(message.author.id) in gc_ban or str(message.author.id) in ba_ban:
            await message.reply(
                content=lang["systems"]["globalchat"]["error"]["baned"],
                delete_after=10,
            )
            await message.delete(delay=10)
            return

        users_list: dict = dict(datasys.load_data(1001, "users"))
        if (
            str(message.author.id) in users_list
            and users_list[str(message.author.id)]["flagged"] is True
        ):
            await message.reply(
                content=lang["systems"]["globalchat"]["error"]["baned"],
                delete_after=10,
            )
            await message.delete(delay=10)
            return

        if len(message.content) > 1000:
            await message.reply(
                content=lang["systems"]["globalchat"]["error"]["message_to_long"],
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
        assert message.guild is not None, "Message guild none"
        assert message.author.avatar is not None, "Message authr avatar none"
        embed = discord.Embed(
            description=message.content,
            color=discord.Color.blurple(),
            timestamp=message.created_at,
        )

        embed.set_author(
            name=f"{message.author.name}", icon_url=message.author.avatar.url
        )

        embed.set_thumbnail(url=message.author.avatar.url)

        embed.set_footer(
            text=(
                f"{message.guild.name} | {message.guild.id} | "
                f"{message.author.id} | {gcmid}"
            )
        )

        if len(message.attachments) == 1:
            attachment = message.attachments[0]
            content_type = attachment.content_type

            if content_type and content_type.startswith("image/"):
                image_bytes = await attachment.read()
                image = Image.open(BytesIO(image_bytes)).convert("RGBA")

                watermark_lines = ["avocloud.net - baxi", message.author.name]
                width, height = image.size

                txt = Image.new("RGBA", image.size, (255, 255, 255, 0))
                draw = ImageDraw.Draw(txt)

                font_size = int(height / 12)
                font = ImageFont.load_default(size=font_size)

                text_heights = []
                text_widths = []

                for line in watermark_lines:
                    bbox = draw.textbbox((0, 0), line, font=font)
                    w = bbox[2] - bbox[0]
                    h = bbox[3] - bbox[1]
                    text_widths.append(w)
                    text_heights.append(h)

                total_text_height = sum(text_heights) + 10
                y = (height - total_text_height) // 2

                for i, line in enumerate(watermark_lines):
                    x = (width - text_widths[i]) // 2
                    draw.text((x + 2, y + 2), line, fill=(0, 0, 0, 60), font=font)
                    draw.text((x, y), line, fill=(255, 255, 255, 80), font=font)
                    y += text_heights[i] + 5

                watermarked = Image.alpha_composite(image, txt)
                file_path = Path(config.Globalchat.attachments_dir) / f"{gcmid}.png"
                watermarked.save(file_path)
                embed.set_image(url=f"{config.Globalchat.attachments_url}{gcmid}.png")
            else:
                await message.reply(
                    content=f'{message.author.mention}\n{lang["systems"]["globalchat"]["error"]["file_not_image"]}',
                    delete_after=5,
                )
                await message.delete(delay=5)
                return

        elif len(message.attachments) > 1:
            await message.reply(
                content=f'{message.author.mention}\n{lang["systems"]["globalchat"]["error"]["to_many_files"]}',
                delete_after=5,
            )
            await message.delete(delay=5)
            return

        if message.reference and message.reference.message_id:
            replied_message = await message.channel.fetch_message(
                message.reference.message_id
            )

            if replied_message and replied_message.embeds:
                referenced_embed = replied_message.embeds[0]
                if referenced_embed.footer and referenced_embed.footer.text:
                    referenced_mid = referenced_embed.footer.text.split(" | ")[3]
                    embed.set_footer(
                        text=(
                            f"{message.guild.name} | {message.guild.id} | {message.author.id} | {gcmid} | {referenced_mid}"
                        )
                    )

                    replied_author = (
                        referenced_embed.author.name
                        if referenced_embed.author
                        else "Unknown"
                    )

                    reply_preview = referenced_embed.description
                    if reply_preview and len(reply_preview) > 60:
                        reply_preview = reply_preview[:60] + "..."

                    if reply_preview:
                        embed.add_field(
                            name=f"{config.Icons.message} Replies to {config.Icons.user} {replied_author}'s message:",
                            value=reply_preview,
                            inline=False,
                        )

        sent_message = await message.channel.send(embed=embed)
        guild_id = sent_message.guild.id if sent_message.guild else None
        channel_id = sent_message.channel.id if sent_message.channel else None
        message_id = sent_message.id

        globalchat_message_data[str(gcmid)]["messages"].append(
            {
                "gid": guild_id,
                "channel": channel_id,
                "mid": message_id,
            }
        )

        globalchat_message_data[str(gcmid)]["reply"] = reply
        if reply and referenced_mid is not None:
            globalchat_message_data[str(gcmid)]["referenceid"] = referenced_mid
            if str(referenced_mid) not in globalchat_message_data:
                globalchat_message_data[str(referenced_mid)] = {"replies": []}
            elif "replies" not in globalchat_message_data[str(referenced_mid)]:
                globalchat_message_data[str(referenced_mid)]["replies"] = []

            globalchat_message_data[str(referenced_mid)]["replies"].append(
                {
                    "gid": guild_id,
                    "channel": channel_id,
                    "mid": message_id,
                    "referenceid": gcmid,
                    "replyid": referenced_mid,
                }
            )

        async def gc_send_msg():
            for server_id, server in gc_data.items():
                if int(server["channel"]) == message.channel.id:
                    continue
                guild = bot.get_guild(server["gid"])
                if guild is None:
                    continue
                channel = guild.get_channel(int(server["channel"]))
                if isinstance(channel, TextChannel):
                    sent_message = await channel.send(embed=embed)
                else:
                    print(
                        f"[WARN] Channel {server['channel']} is not a TextChannel (type: {type(channel)})"
                    )
                    continue
                if str(gcmid) not in globalchat_message_data:
                    globalchat_message_data[str(gcmid)] = {
                        "messages": [],
                        "replies": [],
                    }
                assert sent_message.guild is not None, "sent message guild none"
                globalchat_message_data[str(gcmid)]["messages"].append(
                    {
                        "gid": sent_message.guild.id,
                        "channel": sent_message.channel.id,
                        "mid": sent_message.id,
                    }
                )
                if reply:
                    globalchat_message_data[str(referenced_mid)]["replies"].append(
                        {
                            "gid": sent_message.guild.id,
                            "channel": sent_message.channel.id,
                            "mid": sent_message.id,
                        }
                    )

        await asyncio.create_task(gc_send_msg(), name="gc_send_msg")
        await message.delete()
    except Exception as e:
        print(f"Error in global chat: {e}\n{e.with_traceback}")
