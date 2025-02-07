import discord
from assets.data import load_data, save_data, load_lang
from assets.translate import baxi_translate
import lang.lang as lang
import config.config as config
import random


async def guessing(message: discord.Message):
    guessing_data = load_data(message.guild.id, "guessing")
    guild_id = message.guild.id
    channel_id = message.channel.id
    lang = load_lang(guild_id)

    if guessing_data.enabled:
        if guessing_data.cid == channel_id:
            if guessing_data.number == int(message.content):
                guessing_data.number = random.randint(1, guessing_data.max_value)
                guessing_data.last_user = message.author.id
                save_data(guild_id, "guessing", guessing_data.to_dict())
                await message.add_reaction("✅")
                embed = discord.Embed(
                    title=await baxi_translate(lang.Minigames.Guessing.title, lang),
                    description=str(
                        await baxi_translate(
                            lang.Minigames.Guessing.description_correct, lang
                        )
                    ).format(max_value=str(guessing_data.max_value)),
                    color=config.Discord.color,
                )
                await message.channel.send(embed=embed)
                return True
            elif int(message.content) > guessing_data.number:
                await message.add_reaction("⬇️")
                return True
            else:
                await message.add_reaction("⬆️")
                return True
    else:
        return False
