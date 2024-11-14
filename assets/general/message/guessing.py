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


async def run_guessing(message: discord.Message, booted: bool):
    icons_url = config["WEB"]["icon_url"]
    language = load_language_model(message.guild.id)
    settings_guessing = load_data("json/guessing.json")
    try:
        if booted is False:
            embed = discord.Embed(title=language["035_title"],
                                  description=f"{language['system_not_booted_error']}"
                                              "[PyroPixle System Status](https://status.avocloud.net)").set_thumbnail(
                url=icons_url + "info.png")
            await message.channel.send(embed=embed)
            return 503
        try:
            guess = int(message.content)
        except ValueError:
            await message.delete()
            await message.channel.send(language["guessing_not_a_number"], delete_after=5)
            return

        if guess < settings_guessing[str(message.guild.id)]["number"]:
            await message.add_reaction("<:upvote:1244728298488070255>")
        elif guess > settings_guessing[str(message.guild.id)]["number"]:
            await message.add_reaction("<:downvote:1244728465199206483>")
        else:
            settings_guessing[str(message.guild.id)]["number"] = random.randint(0, 10000)
            save_data("json/guessing.json", settings_guessing)
            await message.reply(embed=discord.Embed(title=language["guessing_correct_number_title"],
                                                    description=language["guessing_correct_number"],
                                                    color=discord.Color.green()))
    except Exception as e:
        logger.error(str(e))
        await message.reply("Error in guessing.py:  " + str(e))
