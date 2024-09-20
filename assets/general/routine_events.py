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
import datetime
import time

import discord
from reds_simple_logger import Logger

from assets.general.get_saves import *

config = configparser.ConfigParser()
config.read("config/runtime.conf")

logger = Logger()


embedColor = discord.Color.from_rgb(int(config["BOT"]["embed_color_red"]), int(config["BOT"]["embed_color_green"]),
                                    int(config["BOT"]["embed_color_blue"]))  # FF5733
icons_url = config["WEB"]["icon_url"]

def generate_random_string(length=5):
    all_characters = string.ascii_letters
    return ''.join(random.choice(all_characters) for _ in range(length))

def load_language_model(server_id):
    language_settings = load_data("json/language.json")
    try:
        if str(server_id) not in language_settings:
            return load_data("language/en.json")

        elif language_settings[str(server_id)]["language"] == "en":
            return load_data("language/en.json")

        elif language_settings[str(server_id)]["language"] == "de":
            return load_data("language/de.json")

        elif language_settings[str(server_id)]["language"] == "fr":
            return load_data("language/fr.json")

        elif language_settings[str(server_id)]["language"] == "norsk":
            return load_data("language/norsk.json")

        else:
            return load_data("language/en.json")
    except:
        return load_data("language/en.json")


def handle_log_event(command, guild, username):
    log_folder = os.path.join("log", guild)
    log_file = os.path.join(log_folder, "log.txt")
    timestamp = datetime.datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")

    if not os.path.exists(log_folder):
        os.makedirs(log_folder)

    if not os.path.exists(log_file):
        with open(log_file, "w", encoding="utf-8") as f:
            f.write("Log-Datei für den Server {} \n".format(guild))
        f.close()

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"{timestamp} - {command} - {username}\n")
    f.close()

async def log_action(guild_id, user_id, action_type, action_counts):
    current_time = int(time.time())
    action_counts[guild_id][user_id]["actions"] += 1
    action_counts[guild_id][user_id]["timestamp"] = current_time
    action_counts[guild_id][user_id]["type"] = action_type


async def check_actions_antiraid(action_counts, bot):
    current_time = int(time.time())
    for guild_id, users in list(action_counts.items()):
        for user_id, data in list(users.items()):
            if current_time - data["timestamp"] > int(config["ANTI_RAID"]["time_window"]):
                del action_counts[guild_id][user_id]
            elif data["actions"] > int(config["ANTI_RAID"]["action_threshold"]):
                guild = bot.get_guild(guild_id)
                member = guild.get_member(user_id)
                if member:
                    await quarantine_user(guild, member)
                    logger.success("User quarantined on Guild" + str(guild.name) + "; User: " + str(member.name))
                del action_counts[guild_id][user_id]



async def quarantine_user(guild: discord.Guild, member: discord.Member):
    try:
        setting = load_data("json/anti_raid.json")
        log = load_data("json/log_channels.json")
        language = load_language_model(int(guild.id))
        log_channel = None
        if str(guild.id) in setting:
            logger.info("Quarantine user...")
            try:
                log_channel = guild.get_channel(int(log[str(guild.id)]["channel_id"]))
            except:
                pass
            quarantine_role = guild.get_role(int(setting[str(guild.id)]["role_id"]))
            if not quarantine_role:
                quarantine_role = await guild.create_role(name="Quarantine", permissions=discord.Permissions.none())

            # Alle Rollen des Benutzers entfernen
            if member.bot:
                await member.kick(reason="Baxi Security - Anti Raid / Nuke")
                logger.info("QUARANTINE: Bot kicked!")
            else:
                roles_to_remove = [role for role in member.roles if role != guild.default_role]
                await member.remove_roles(*roles_to_remove)
                await member.add_roles(quarantine_role)
                await member.timeout(datetime.timedelta(minutes=10), reason="Baxi Security - Anti Raid / Nuke")
                logger.info("QUARANTINE: Member timeouted and removed roles!")
            embed = discord.Embed(title=language["security_title"],
                                  description=language["security_antinuke_action"].format(user=member.mention,
                                                                                          guild=guild.name),
                                  color=embedColor).set_thumbnail(url=icons_url + "mod.png").set_footer(
                text=language["security_chatfilter_footer"])
            try:
                await member.send(embed=embed)
            except:
                pass

            try:
                await guild.owner.send(embed=embed)
            except Exception as e:
                logger.error(str(e))

            try:
                await log_channel.send(embed=embed)
            except:
                pass

            logger.info(f"Mitglied {member.name} wurde in Quarantäne gesetzt auf dem Server {guild.name}")
    except Exception as e:
        logger.error(str(e))