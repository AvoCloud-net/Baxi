##################################
# This is the original source code
# of the Discord Bot's Baxi.
#
# When using the code (copy, change)
# all policies and licenses must be adhered to.
#
# Developer: Red_Wolf2467
# Original App: Baxi
##################################
import configparser
import re

import discord

from assets.general.routine_events import *

config = configparser.ConfigParser()
config.read("config/runtime.conf")
async def run_counting(message: discord.Message, booted: bool):
    settings_counting = load_data("json/countgame_data.json")
    icons_url = config["WEB"]["icon_url"]
    language = load_language_model(message.guild.id)
    try:
        if booted is False:
            embed = discord.Embed(title=language["035_title"],
                                  description=f"{language['system_not_booted_error']}"
                                              "[PyroPixle System Status](https://status.pyropixle.com)").set_thumbnail(
                url=icons_url + "info.png")
            await message.channel.send(embed=embed)
            return 503

        if message.content.isdigit() or re.match(r'^\d+(\s*[-+*/]\s*\d+)*$', message.content):
            number = eval(message.content) if re.match(
                r'^\d+(\s*[-+*/]\s*\d+)*$', message.content) else int(message.content)
            count = settings_counting[str(message.guild.id)]["count"]

            if message.author.id == settings_counting[str(message.guild.id)]["last_user"]:
                await message.delete()
                await message.channel.send(embed=discord.Embed(title="Counting",
                                                               description=f"{language['counting_same_user_error']}* **{count + 1}**",
                                                               color=discord.Color.red()), delete_after=5)
                return

            if number == settings_counting[str(message.guild.id)]["count"] + 1:
                settings_counting[str(message.guild.id)]["count"] += 1
                settings_counting[str(message.guild.id)]["last_user"] = message.author.id
                save_data("json/countgame_data.json", settings_counting)
                await message.add_reaction("<:check:1244724215274405979>")
                if settings_counting[str(message.guild.id)]["count"] == 50:
                    await message.add_reaction("<:smalfire:1244727952672034866>")
                    await message.reply(language["counting_reached_50"])

                elif settings_counting[str(message.guild.id)]["count"] == 100:
                    await message.add_reaction("💯")
                    await message.reply(language["counting_reached_100"])

                elif settings_counting[str(message.guild.id)]["count"] == 300:
                    await message.add_reaction("🎊")
                    await message.reply(language["counting_reached_300"])

                elif settings_counting[str(message.guild.id)]["count"] == 500:
                    await message.add_reaction("🎊")
                    await message.reply(language["counting_reached_500"])

                elif settings_counting[str(message.guild.id)]["count"] == 1000:
                    await message.add_reaction("🎊")
                    await message.reply(language["counting_reached_1000"])
            else:
                settings_counting[str(message.guild.id)]["count"] = 0
                settings_counting[str(message.guild.id)]["last_user"] = None
                save_data("json/countgame_data.json", settings_counting)
                await message.reply(embed=discord.Embed(title="Counting",
                                                        description=language[
                                                            "counting_wrong_number"].format(number=number,
                                                                                            count=count + 1),
                                                        color=discord.Color.random()))
        else:
            await message.delete()
            await message.channel.send(embed=discord.Embed(title="Counting",
                                                           description=language["counting_not_math"],
                                                           color=discord.Color.random()), delete_after=5)
    except Exception as e:
        await message.channel.send(str(e))