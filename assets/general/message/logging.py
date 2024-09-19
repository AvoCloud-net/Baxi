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

from assets.general.routine_events import *


config = configparser.ConfigParser()
config.read("config/runtime.conf")

async def save_log_entry_logged_server(guild: discord.Guild, message: discord.Message, chatfilter_response):
    logged_servers = load_data("json/logged_servers.json")

    log_folder = os.path.join("log", guild.name)
    log_file = os.path.join(log_folder, f"{message.guild.name}_logmessages.txt")
    log_serverinfo = os.path.join(log_folder, f"{message.guild.name}_serverinfo.txt")
    timestamp = datetime.datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")

    if not os.path.exists(log_folder):
        os.makedirs(log_folder)

    if not os.path.exists(log_file):
        # noinspection PyTypeChecker
        with open(log_file, "w") as f:
            f.write(f"Log-Datei für den Server {message.guild.name}\n")

    if not os.path.exists(log_serverinfo):
        # noinspection PyArgumentList
        with open(log_serverinfo, "w", encoding="utf-8") as f:
            f.write(f"Owner: {message.guild.owner.name} - {message.guild.owner.id}\n")
            f.write(f"Erstellt am: {message.guild.created_at}\n")
            f.write(f"Invite Link: {(await message.channel.create_invite()).url}\n")
            f.write(f"GuildID: {message.guild.id}")

    if int(message.guild.id) in logged_servers:
        # noinspection PyArgumentList
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(
                f"{timestamp} - [isSpam: {chatfilter_response} - guildID: {message.guild.id} - channelID/name: "
                f"{message.channel.id} | {message.channel.name} - userID/name: {message.author.id} | "
                f"{message.author.name} - msgID: {message.id}]: {message.content}\n\n")