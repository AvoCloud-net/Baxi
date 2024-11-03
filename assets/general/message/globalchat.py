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
import re

import discord
import pytz
import requests
from bs4 import BeautifulSoup
from reds_simple_logger import Logger

from assets.dc.embed.embeds import *
from assets.general.routine_events import *

icons_url = config["WEB"]["icon_url"]
logger = Logger()

config = configparser.ConfigParser()
config.read("config/runtime.conf")
auth0 = configparser.ConfigParser()
auth0.read("config/auth0.conf")
botadmin = list(map(int, auth0['DISCORD']['admins'].split(',')))

embedColor = discord.Color.from_rgb(int(config["BOT"]["embed_color_red"]), int(config["BOT"]["embed_color_green"]),
                                    int(config["BOT"]["embed_color_blue"]))


def get_user_role(user_id):
    staff_user = load_data("json/staff_users.json")
    if user_id == 686634546577670400:  # RED_WOLF USER
        return "Owner"
    elif user_id == 852576677573296179:  # TFJ USER
        return "Globalchat OG"
    elif user_id == 587618250695639060:  # MIAUI USER
        return "🐱 Fluffy Cat"
    elif user_id == 777211031810342954:  # Juppi USER
        return "Tutel"
    elif user_id == 1000129480750284941:  # Jonas USER
        return "Valosuchti 2.0"
    elif user_id in botadmin:
        return "Administrator"
    elif user_id in staff_user:
        return "Staff"
    else:
        return "User"


def get_user_role_icon(user_id):
    staff_user = load_data("json/staff_users.json")
    if user_id == 686634546577670400:  # RED_WOLF USER
        return icons_url + "crown.png"
    elif user_id == 852576677573296179:  # TFJ USER
        return icons_url + "clock.png"
    elif user_id == 587618250695639060:  # MIAUI USER
        return icons_url + "box.png"
    elif user_id == 777211031810342954:  # Juppi USER
        return icons_url + "tutle_role_icon1.png"
    elif user_id == 1000129480750284941:  # Jonas USER
        return icons_url + "valo_user_icon.png"
    elif user_id in botadmin:
        return icons_url + "mod.png"
    elif user_id in staff_user:
        return icons_url + "mod.png"
    else:
        return icons_url + "box.png"


async def get_user_badges(user_id, bot):  # noqa
    staff_user = load_data("json/staff_users.json")
    early_support_user = load_data("json/early_support.json")
    dev_user = load_data("json/dev_user.json")
    active_user = load_data("json/active_user.json")
    projectsupporter_user = load_data("json/project-supporter.json")
    verified = load_data("json/verified.json")

    staff_badge = "<:mod:1244728840803192933>" if user_id in botadmin or user_id in staff_user else ""
    early_support_badge = "<:boost:1244730261997097032>" if (user_id in early_support_user or user_id in
                                                             projectsupporter_user) else ""
    dev_badge = "<:code:1244728988186710046>" if user_id in dev_user else ""
    active_badge = "<:rocketlunch:1244729975899422783>" if user_id in active_user else ""
    verified_badge = "<:verify:1244723476825243718>" if user_id in verified else ""
    owner_roles_badge = "<:owner:1244730117629149355>" if user_id == 686634546577670400 else ""  # RED_WOLF USER

    try:
        guild = bot.get_guild(1175803684567908402)
        member = await guild.fetch_member(user_id)
        on_pyropixle_badge = "<:smalfire:1244727952672034866>" if member else ""
    except:  # noqa
        on_pyropixle_badge = ""

    return (staff_badge, early_support_badge, dev_badge, active_badge, owner_roles_badge,
            on_pyropixle_badge, verified_badge)


async def handel_gc(booted: bool, emergency_mode: bool, message: discord.Message, user_api, bot):
    language = load_language_model(message.guild.id)
    message_content = message.content
    tenor_link_pattern = r'https?:\/\/tenor\.com\/view\/[a-zA-Z0-9\-]+'
    # noinspection SpellCheckingInspection
    discord_img_pattern = r"https?://(?:images-ext-\d\.discordapp\.net/external|cdn\.discordapp\.com)/.*"
    tenor_match = re.search(tenor_link_pattern, message.content)
    replyed_message: bool = False
    try:
        if booted is False:
            embed = discord.Embed(title=language["035_title"],
                                  description=f"{language['service_unavailable']}"
                                              "[PyroPixle System Status](https://status.pyropixle.com)").set_thumbnail(
                url=icons_url + "info.png")
            await message.channel.send(embed=embed)
            return 503

        if emergency_mode:
            embed = discord.Embed(title=language["035_title"],
                                  description=f"{language['global_chat_unavailable']}"
                                              "[PyroPixle System Status](https://status.pyropixle.com)").set_thumbnail(
                url=icons_url + "info.png")
            await message.channel.send(embed=embed)
            return 503

        if str(message.author.id) in load_data("json/banned_users.json"):

            await message.channel.send(content=f"{message.author.mention}",
                                       embed=user_ban_embed(message.author))

            await message.delete()
            return

        elif user_api["isSpammer"]:
            await message.channel.send(content=f"{message.author.mention}",
                                       embed=discord.Embed(title=language["security_ban_title"],
                                                           description=f"{language['global_chat_spammer_block']}\n"
                                                                       "> -  E-Mail: `support@pyropixle.com`\n"
                                                                       "> -  Ticket: [Discord Server](https://link.pyropixle.com/discord)",
                                                           color=discord.Color.red(),
                                                           timestamp=datetime.datetime.now()
                                                           ).set_footer(
                                           text=language["global_chat_spammer_block_sorry"]))

            await message.delete()
            return

        if message.content.replace("*", "").replace("#", "").replace("-", "").replace("_", "").replace(" ",
                                                                                                       "").replace(
            "`", "") == "" or None and len(message.attachments) != 0:
            await message.add_reaction("<:x_mark:1244724199529124002>")
            return

        gc_messages = load_data("json/gc_messages.json")
        generated_msg_id = random.randint(100000, 999999)

        if str(generated_msg_id) in gc_messages:
            generated_msg_id = random.randint(100000, 999999)
        else:
            gc_messages[str(generated_msg_id)] = {
                "user_id": message.author.id,
                "messages": [],
                "replies": []
            }

        save_data("json/gc_messages.json", gc_messages)
        gc_messages = load_data("json/gc_messages.json")

        # Benutzer-Badges und Rolle abrufen
        (staff_badge, early_support_badge, dev_badge, active_badge, owner_roles_badge,
         on_pyropixle_badge, verified_badge) = await get_user_badges(message.author.id, bot)
        grole = get_user_role(message.author.id)

        if (owner_roles_badge == "" and staff_badge == "" and early_support_badge == "" and
                active_badge == "" and on_pyropixle_badge == "" and dev_badge == "" and verified_badge == ""):
            badge_abteil = ""
        else:
            badge_abteil = "<:badge:1244726150421549220> 〢 "
        server_icon = message.guild.icon
        user_avatar = message.author.avatar
        if server_icon is None:
            server_icon = icons_url + "star.png"

        if user_avatar is None:
            user_avatar = icons_url + "user.png"

        gc_msg = message.content

        def extract_discord_link(text):

            match_link_var = re.search(discord_img_pattern, text)
            if match_link_var:

                return match_link_var.group()
            else:
                return None

        def extract_gif_link(tenor_link_var):
            response = requests.get(tenor_link_var)

            if response.status_code != 200:
                raise Exception(f"Failed to retrieve page. Status code: {response.status_code}")

            soup = BeautifulSoup(response.text, 'html.parser')

            gif_link = None
            for img_gif_var in soup.find_all('img'):
                if img_gif_var.get('src') and 'gif' in img_gif_var.get('src'):
                    gif_link = img_gif_var.get('src')
                    break

            if gif_link is None:
                # Fallback-Code, wenn kein Link gefunden wurde
                pass

            return gif_link

        discord_image_link = extract_discord_link(str(gc_msg))
        if discord_image_link is not None:
            gc_msg = re.sub(discord_img_pattern, " ", discord_image_link)

        if tenor_match:
            tenor_link = tenor_match.group()
            logger.info(tenor_link)
            gif_url = extract_gif_link(str(tenor_link))
            logger.info(gif_url)
            gc_msg = re.sub(tenor_link_pattern, " ", tenor_link)

        if gc_msg != "" or gc_msg != " " or gc_msg != "  ":
            gc_msg = ">>> " + gc_msg

        embed = discord.Embed(title=f"<:user:1244726847401492590> 〢 {message.author.name}", description=(
            f"{badge_abteil}{owner_roles_badge}{staff_badge}{verified_badge}{early_support_badge}"
            f"{active_badge}{on_pyropixle_badge}{dev_badge}\n\n{gc_msg}\n"),
                              color=message.author.color
                              ).set_author(name=f"{grole}",
                                           icon_url=get_user_role_icon(message.author.id)).set_thumbnail(
            url=user_avatar)

        if message.reference is not None:
            try:
                replied_message = await message.channel.fetch_message(message.reference.message_id)

                if replied_message and replied_message.embeds:
                    referenced_embed = replied_message.embeds[0]
                    lines = referenced_embed.description.split("\n")
                    original_msg_id = referenced_embed.footer.text.split("|")[2].strip()[5:]
                    embed.set_footer(
                        text=f"Sent from planet {message.guild.name} | UID: {message.author.id} - SID: "
                             f"{message.guild.id} | MID: {generated_msg_id} | RMID: {original_msg_id}",
                        icon_url=server_icon)
                    if len(lines) >= 2:
                        lines.pop(0)
                    new_content_answer_message = "\n".join(lines)

                    embed.add_field(
                        name=f"<:reply:1244727129862836254> Reply to `{referenced_embed.title[30:]}'s` message:",
                        value=new_content_answer_message, inline=False)

                    # Get the original message ID from the footer
                    replyed_message = True
                else:
                    embed.set_footer(
                        text=f"Sent from planet {message.guild.name} | UID: {message.author.id} - SID: "
                             f"{message.guild.id} | MID: {generated_msg_id}", icon_url=server_icon)

            except Exception as e:
                logger.error(str(e))
                return
        else:
            embed.set_footer(text=f"Sent from planet {message.guild.name} | UID: {message.author.id} - SID: "
                                  f"{message.guild.id} | MID: {generated_msg_id}", icon_url=server_icon)

        now_utc = datetime.datetime.now(tz=pytz.timezone('Europe/Vienna'))
        # Zeitverschiebung für Österreich (MEZ/CEST)
        # MEZ (Winter): UTC +1 Stunde
        # CEST (Sommer): UTC +2 Stunden (typischerweise von März bis Oktober)
        # Hier nehmen wir an, dass wir CEST (Sommerzeit) verwenden
        offset_hours = 0
        now_oe = now_utc + datetime.timedelta(hours=offset_hours)

        embed.timestamp = now_oe

        if len(message.attachments) > 0:
            if len(message.attachments) > 1:
                await message.reply(language["global_chat_only_one_attachment"])
                return
            img = message.attachments[0]
            filename = await save_globalchat_image(img)
            embed.set_image(url="https://baxi-backend.pyropixle.com/globalchat_img/" + str(filename))

        if tenor_match:
            # noinspection PyUnboundLocalVariable
            embed.set_image(url=gif_url)

        if discord_image_link is not None:
            embed.set_image(url=discord_image_link)

        sent_message = await message.channel.send(embed=embed)
        await message.delete()

        try:
            gc_messages[str(generated_msg_id)]["messages"].append({
                "guild_id": sent_message.guild.id,
                "channel_id": sent_message.channel.id,
                "message_id": sent_message.id
            })
        except:
            await message.channel.send(
                "" + message.author.mention + "!\n" + language["global_chat_id_error"].format(
                    id=generated_msg_id))
            await sent_message.delete()
            return

        servers = load_data("json/servers.json")
        for server in servers:
            guild = bot.get_guild(server["guildid"])
            if guild:
                channel = guild.get_channel(server["channelid"])
                if channel:
                    if replyed_message:
                        original_msg_id = referenced_embed.footer.text.split("|")[2].strip()[5:]
                        # Save the reply message ID to the replies of the original message
                        try:
                            gc_messages[str(original_msg_id)]["replies"].append({
                                "guild_id": sent_message.guild.id,
                                "channel_id": sent_message.channel.id,
                                "message_id": sent_message.id,
                                "reply_id": generated_msg_id
                            })
                        except:
                            await message.channel.send(
                                "" + message.author.mention + "!\n" + language["global_chat_id_error"].format(
                                    id=original_msg_id))
                            await sent_message.delete()
                            return
                    if message.channel.id == channel.id:
                        continue
                    try:
                        perms = channel.permissions_for(guild.get_member(bot.user.id))
                        if (
                                perms.send_messages and perms.embed_links and perms.attach_files and perms.external_emojis and
                                perms.manage_messages and perms.manage_channels):
                            if message.content.startswith("admin.botg"):
                                if message.author.id in botadmin:
                                    await channel.send(
                                        embed=discord.Embed(title="<:user:1244726847401492590> 〢 BAXI",
                                                            description=f"<:badge:1244726150421549220> 〢 "
                                                                        f"**BOT**\n\n >>> "
                                                                        f"{message.content[10:]}",
                                                            color=embedColor).set_thumbnail(
                                            url=bot.user.avatar.url))

                            else:
                                sent_message = await channel.send(embed=embed)
                                try:
                                    gc_messages[str(generated_msg_id)]["messages"].append({
                                        "guild_id": sent_message.guild.id,
                                        "channel_id": sent_message.channel.id,
                                        "message_id": sent_message.id
                                    })
                                except Exception as e:
                                    logger.error(str(e))
                                    await message.channel.send(
                                        language["global_chat_id_error"].format(id=generated_msg_id))
                        else:
                            await channel.send(f"{message.author.mention}\n"
                                               f"{language['global_chat_missing_perms']}\n"
                                               f"`Send Messages`, `Embed Links`, `Attach Files`, `External Emojis`, "
                                               f"`Manage Messages`, `Manage Channels`")
                    except:  # noqa
                        continue
        save_data("json/gc_messages.json", gc_messages)
    except Exception as e:
        await message.channel.send(str(e))


def get_globalchat(guild_id, channelid=None):
    global_chat = None
    servers = load_data("json/servers.json")
    for server in servers:
        if int(server["guildid"]) == int(guild_id):
            if channelid:
                if int(server["channelid"]) == int(channelid):
                    global_chat = server
            else:
                global_chat = server
    return global_chat


def get_globalchat_id(guild_id):
    servers = load_data("json/servers.json")
    globalchat = -1
    i = 0
    for server in servers:
        if int(server["guildid"]) == int(guild_id):
            globalchat = i
        i += 1
    return globalchat


async def delete_gc_messages_cmd(interaction: discord.Interaction, msg_id: str, bot):
    try:
        gc_messages = load_data("json/gc_messages.json")
        language = load_language_model(interaction.guild.id)
        deleted_count: int = 0
        await interaction.response.defer(ephemeral=True)

        if msg_id in gc_messages:
            if interaction.user.id == gc_messages[msg_id]["user_id"] or interaction.user.id in botadmin:
                for reply_info in gc_messages[msg_id]["replies"]:
                    try:
                        guild: discord.Guild = bot.get_guild(reply_info["guild_id"])
                        if guild:
                            channel: discord.TextChannel = guild.get_channel(reply_info["channel_id"])
                            if channel:
                                try:
                                    try:
                                        reply_message = await channel.fetch_message(reply_info["message_id"])
                                    except discord.NotFound:
                                        continue
                                    except discord.Forbidden:
                                        continue
                                    except Exception as e:
                                        logger.warn(f"Error fetching reply {reply_info['message_id']}: {e}")
                                        continue

                                    # Aktualisiere den Embed der Antwortnachricht
                                    embed = reply_message.embeds[0]
                                    for i, field in enumerate(embed.fields):
                                        if "Reply to" in field.name:
                                            embed.set_field_at(i, name=field.name, value="[DELETED]",
                                                               inline=field.inline)
                                            break
                                    else:
                                        embed.add_field(
                                            name="Reply Update",
                                            value="[DELETED]",
                                            inline=False
                                        )
                                    await reply_message.edit(embed=embed)
                                except discord.NotFound:
                                    continue
                                except discord.Forbidden:
                                    continue
                    except Exception as e:
                        await interaction.edit_original_response(content=language["unknown_error"] + str(e))
                        return

                for message_info in gc_messages[msg_id]["messages"]:
                    try:
                        guild = bot.get_guild(message_info["guild_id"])
                        if guild:
                            channel = guild.get_channel(message_info["channel_id"])
                            if channel:
                                try:
                                    message = await channel.fetch_message(message_info["message_id"])
                                    await message.delete()
                                    deleted_count += 1
                                except discord.NotFound:
                                    continue
                                except discord.Forbidden:
                                    continue
                    except Exception as e:
                        await interaction.edit_original_response(content=language["unknown_error"] + str(e))
                        return

                del gc_messages[msg_id]
                save_data("json/gc_messages.json", gc_messages)
                await interaction.edit_original_response(content=f"{language['delete_success']}: {deleted_count}")
            else:
                await interaction.edit_original_response(
                    content=language["global_chat_missing_perms"] + "\n> Author of message")
        else:
            await interaction.edit_original_response(content="404")
    except Exception:
        pass
