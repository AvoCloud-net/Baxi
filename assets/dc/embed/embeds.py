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

import discord

from assets.general.get_saves import *

config = configparser.ConfigParser()
config.read("config/runtime.conf")


def lock_embed():
    icons_url = config["WEB"]["icons_url"]
    embed_lock = discord.Embed(
        title="Emergency stop",
        description="> This is a Universal message, so it is in English.\n\nEmergency mode has been activated! The bot is in lockdown and all systems are unavailable.")
    embed_lock.set_thumbnail(
        url=icons_url + "warn.png")
    return embed_lock

def user_ban_embed(user: discord.User):
    icons_url = config["WEB"]["icons_url"]
    gbaned = load_data("json/banned_users.json")

    embed_ban = discord.Embed(
        title="Violation of terms of use",
        description="> This is a Universal message, so it is in English.\n\nWe regret that we have excluded you from our systems and features. We have determined that you have violated our Terms of Service (https://pyropixle.com/gtc/). This means that you are temporarily or permanently excluded from using our services.",
        color=discord.Color.red()
    )

    embed_ban.add_field(
        name="What you can do?",
        value="If you think this exclusion was a mistake or if you have any questions about it, please contact our support team. We are ready to help you troubleshoot problems and provide you with additional information if needed.",
        inline=False
    )

    embed_ban.add_field(
        name="Possible reasons",
        value="Reasons for exclusion can be: \n"
              "- SPAM: The senseless, excessive sending of messages in the global chat\n"
              "- INSULT: Insulting users without context\n"
              "- ATTACK: Using bot functions with the aim of making them unusable\n"
              "- AI: The AI ​​running in the background thinks it has detected harmful behavior\n"
              "- GUIDELINES: You have violated the Guidelines of the developer studio PyroPixle. Read them again!\n"
              "- BEHAVIOR: Posting racist, sexual, hateful, extremely political content"
    )

    embed_ban.add_field(name="", value=" ")
    embed_ban.add_field(name=" ", value=" ")

    embed_ban.set_footer(
        text="We hope that you will be able to use our services again in the future. However, please note that we must take action against rule violations to ensure the safety and integrity of our community.")
    embed_ban.set_thumbnail(url=icons_url + "ban.png")

    embed_ban.set_field_at(
        name="Reason for exclusion",
        value=gbaned[str(user.id)]["reason"],
        inline=False,
        index=3
    )

    return embed_ban
