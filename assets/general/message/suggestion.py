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
import discord

from assets.general.routine_events import *


async def run_suggestion(message: discord.Message, booted: bool):
    settings_suggestion = load_data("json/suggestion.json")
    language = load_language_model(message.guild.id)
    if int(message.channel.id) in settings_suggestion[str(message.guild.id)]["channels"]:
        if booted is False:
            embed = discord.Embed(title=language["035_title"],
                                  description=f"{language['system_not_booted_error']}"
                                              "[PyroPixle System Status](https://status.avocloud.net)").set_thumbnail(
                url=icons_url + "info.png")
            await message.channel.send(embed=embed)
            return 503
        await message.delete()
        send_suggestion = await message.channel.send(
            embed=discord.Embed(title=f"{message.author.name}'s {language['suggestion_title']}",
                                description=f"{message.content}",
                                color=discord.Color.random(),
                                timestamp=datetime.datetime.now()).set_thumbnail(
                url=message.author.avatar.url))
        await send_suggestion.add_reaction("<:check:1244724215274405979>")
        await send_suggestion.add_reaction("<:splash:1244727608655220858>")
        await send_suggestion.add_reaction("<:x_mark:1244724199529124002>")