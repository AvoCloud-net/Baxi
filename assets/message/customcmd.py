import discord
from discord.ext import commands
from reds_simple_logger import Logger

import assets.data as datasys
import config.config as config

logger = Logger()


async def check_custom_command(message: discord.Message, bot: commands.AutoShardedBot) -> bool:
    if message.guild is None:
        return False

    custom_commands: dict = dict(datasys.load_data(message.guild.id, "custom_commands"))
    if not custom_commands:
        return False

    content = message.content.strip().lower()

    for trigger, cmd_data in custom_commands.items():
        if content == trigger.lower():
            response = str(cmd_data.get("response", ""))
            response = response.format(
                user=message.author.mention,
                username=message.author.name,
                server=message.guild.name,
                membercount=message.guild.member_count,
            )

            embed_enabled = cmd_data.get("embed", True)

            if embed_enabled:
                embed_color = config.Discord.color
                color_hex = cmd_data.get("embed_color", "")
                if color_hex and isinstance(color_hex, str) and len(color_hex) == 7:
                    try:
                        r, g, b = int(color_hex[1:3], 16), int(color_hex[3:5], 16), int(color_hex[5:7], 16)
                        embed_color = discord.Color.from_rgb(r, g, b)
                    except ValueError:
                        pass

                embed = discord.Embed(
                    description=response,
                    color=embed_color,
                )

                embed_title = cmd_data.get("embed_title", "")
                if embed_title:
                    embed.title = str(embed_title)

                embed_footer = cmd_data.get("embed_footer", "")
                if embed_footer:
                    embed.set_footer(text=str(embed_footer))

                await message.channel.send(embed=embed)
            else:
                await message.channel.send(response)

            return True

    return False
