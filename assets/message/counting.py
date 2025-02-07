import discord
from discord.ext import commands
import assets.data as datasys
import lang.lang as lang
import assets.translate as tr
import config.config as config


async def counting(message: discord.Message):
    counting_data = datasys.load_data(message.guild.id, "counting")
    guild_id = message.guild.id
    channel_id = message.channel.id
    lang = datasys.load_lang(guild_id)

    if counting_data.enabled:
        if channel_id == counting_data.cid:
            if message.author.id != counting_data.last_user:
                if counting_data.number == int(message.content):
                    counting_data.number += 1
                    counting_data.last_user = message.author.id
                    datasys.save_data(guild_id, "counting", counting_data.to_dict())
                    await message.add_reaction("✅")
                    return True
                else:
                    print("6")
                    await message.add_reaction("❌")
                    embed = discord.Embed(
                        title=await tr.baxi_translate(
                            lang.Minigames.Counting.title, lang
                        ),
                        description=str(
                            await tr.baxi_translate(
                                lang.Minigames.Counting.description_wrong_number, lang
                            )
                        ).format(user=message.author.mention),
                        color=config.Discord.color,
                    )
                    counting_data.number = 1
                    await message.channel.send(embed=embed, delete_after=8)
                    await message.delete()
                    datasys.save_data(guild_id, "counting", counting_data.to_dict())
                    return True
            else:
                embed = discord.Embed(
                    title=await tr.baxi_translate(lang.Minigames.Counting.title, lang),
                    description=str(
                        await tr.baxi_translate(
                            lang.Minigames.Counting.description_same_user, lang
                        )
                    ).format(user=message.author.mention),
                    color=config.Discord.color,
                )
                await message.channel.send(embed=embed, delete_after=8)
                await message.delete()
                return True
        else:
            return False
    else:
        return False
