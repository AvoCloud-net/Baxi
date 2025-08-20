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
import re
from urllib.parse import urlparse
import aiohttp
from bs4 import BeautifulSoup
import requests

async def globalchat(bot: commands.AutoShardedBot, message: Message, gc_data: dict):
    try:
        reply: bool = True if message.reference else False
        referenced_mid = None
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
        guild = await bot.fetch_guild(int(guild_id))
        guild_icon = guild.icon.url if guild.icon is not None else "https://avocloud.net/icon.png"
        guild_user = await guild.fetch_member(int(message.author.id))
        role_color = guild_user.top_role.color if guild_user.top_role.color != discord.Color.default() else discord.Color.blurple()
        embed = discord.Embed(
            description=message.content,
            color=role_color,
            timestamp=message.created_at,
        )

        embed.set_author(
            name=f"{message.author.name}", icon_url=message.author.avatar.url
        )

        embed.set_thumbnail(url=message.author.avatar.url)

        embed.set_footer(
            text=(
                f"{message.guild.name} | {gcmid}"
            ),
            icon_url=guild_icon
        )

        def extract_gif_link(tenor_link_var):
            response = requests.get(tenor_link_var)

            if response.status_code != 200:
                raise Exception(
                    f"Failed to retrieve page. Status code: {response.status_code}"
                )

            soup = BeautifulSoup(response.text, "html.parser")

            gif_link = None
            for img_gif_var in soup.find_all("img"):
                if img_gif_var.get("src") and "gif" in img_gif_var.get("src"):
                    gif_link = img_gif_var.get("src")
                    break

            if gif_link is None:
                pass

            return gif_link

        async def process_image_links(content):
            
            url_pattern = r'https?://[^\s<>"]+|www\.[^\s<>"]+'
            urls = re.findall(url_pattern, content)
            
            if not urls:
                return None, None
                
            
            image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tiff', '.svg']
            video_extensions = ['.mp4', '.mov', '.avi', '.webm', '.mkv', '.wmv', '.flv', '.m4v']
            
            for url in urls:
                try:
                    
                    if url.startswith('www.'):
                        url = 'https://' + url
                    
                    parsed_url = urlparse(url)
                    path = parsed_url.path.lower()
                    
                    
                    if any(path.endswith(ext) for ext in image_extensions):
                        return url, 'image'
                    
                    
                    if any(path.endswith(ext) for ext in video_extensions):
                        return url, 'video'
                    
                    
                    if 'tenor.com' in parsed_url.netloc:
                        gif_url: str = str(extract_gif_link(str(url)))
                        gif_id = gif_url.split('/m/')[1].split('/')[0]
                        cleaned_gif_url: str = f"https://c.tenor.com/{gif_id}/tenor.gif"
                        print(cleaned_gif_url)
                        return cleaned_gif_url, 'gif'
                    
                    
                    if 'imgur.com' in parsed_url.netloc:
                        
                        if parsed_url.netloc == 'i.imgur.com':
                            return url, 'image'
                        
                        
                        imgur_id = path.split('/')[-1]
                        if imgur_id and '.' not in imgur_id:  
                            
                            for ext in ['.jpg', '.png', '.gif', '.mp4']:
                                direct_url = f"https://i.imgur.com/{imgur_id}{ext}"
                                async with aiohttp.ClientSession() as session:
                                    async with session.head(direct_url) as response:
                                        if response.status == 200:
                                            media_type = 'video' if ext == '.mp4' else 'image'
                                            return direct_url, media_type
                    
                    
                    if 'reddit.com' in parsed_url.netloc or 'i.redd.it' in parsed_url.netloc or 'v.redd.it' in parsed_url.netloc:
                        if 'i.redd.it' in parsed_url.netloc:
                            return url, 'image'
                        if 'v.redd.it' in parsed_url.netloc:
                            return url, 'video'
                        
                        if '/comments/' in path:
                            
                            post_id = path.split('/comments/')[1].split('/')[0]
                            if post_id:
                                return f"https://i.redd.it/{post_id}.jpg", 'image'
                    
                    
                    async with aiohttp.ClientSession() as session:
                        async with session.head(url, allow_redirects=True) as response:
                            if response.status == 200:
                                content_type = response.headers.get('content-type', '')
                                if content_type and content_type.startswith('image/'):
                                    return url, 'image'
                                elif content_type and content_type.startswith('video/'):
                                    return url, 'video'
                    
                except Exception as e:
                    print(f"Error processing URL {url}: {e}")
                    continue
                    
            return None, None

        
        image_url, media_type = await process_image_links(message.content)
        
        
        if len(message.attachments) == 1:
            attachment = message.attachments[0]
            content_type = attachment.content_type

            if content_type and (content_type.startswith("image/") or content_type.startswith("video/")):
                
                
                if content_type.startswith("video/") or content_type == "image/gif":
                    embed.set_image(url=attachment.url)
                else:
                    
                    image_bytes = await attachment.read()
                    image = Image.open(BytesIO(image_bytes)).convert("RGBA")
                    
                    file_path = Path(config.Globalchat.attachments_dir) / f"{gcmid}.png"
                    image.save(file_path)
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
            
        
        elif image_url and len(message.attachments) == 0:
            try:
                
                if media_type in ['video', 'gif']:
                    embed.set_image(url=image_url)
                else:
                    
                    async with aiohttp.ClientSession() as session:
                        async with session.get(image_url) as response:
                            if response.status == 200:
                                content_type = response.headers.get('content-type', '')
                                
                                if content_type and content_type.startswith('image/'):
                                    
                                    image_data = await response.read()
                                    
                                    try:
                                        image = Image.open(BytesIO(image_data)).convert("RGBA")
                                        
                                        file_path = Path(config.Globalchat.attachments_dir) / f"{gcmid}.png"
                                        image.save(file_path)
                                        embed.set_image(url=f"{config.Globalchat.attachments_url}{gcmid}.png")
                                        
                                    except Exception as img_error:
                                        print(f"Error processing downloaded image: {img_error}")
                                        embed.set_image(url=image_url)
                                
            except Exception as e:
                print(f"Error processing image URL: {e}")

        if message.reference and message.reference.message_id:
            replied_message = await message.channel.fetch_message(
                message.reference.message_id
            )

            if replied_message and replied_message.embeds:
                referenced_embed = replied_message.embeds[0]
                if referenced_embed.footer and referenced_embed.footer.text:
                    
                    referenced_mid = referenced_embed.footer.text.split(" | ")[1]
                    embed.set_footer(
                        text=(
                            f"{message.guild.name} | {gcmid} | {referenced_mid}"
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
                if reply and referenced_mid is not None:  
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
        print(f"Error in global chat: {e}")