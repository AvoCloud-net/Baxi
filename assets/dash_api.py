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


from reds_simple_logger import Logger
import configparser
import discord
from cryptography.fernet import Fernet
from quart import Quart, render_template, request, send_from_directory, jsonify, url_for
from quart_cors import cors

import assets.get_saves as get_saves

logger = Logger()


async def sync_baxi_data(request, channel: discord.TextChannel, bot):
    """

    :param bot:
    :param request:
    :param channel:
    :return:
    """
    auth0 = configparser.ConfigParser()
    auth0.read("config/auth0.conf")
    config = configparser.ConfigParser()
    config.read("config/runtime.conf")
    key = request.headers.get("Authorization")
    if str(key) != str(auth0["DASH"]["baxi_token_key"]):
        return jsonify({'error': "Invalid API KEY"}), 401

    fernet = Fernet(auth0["FLASK"]["key"])
    CLIENT_ID = auth0["DISCORD"]["client_id"]
    REDIRECT_URI = config["DASH"]["callback_url"]

    BOT_TOKEN = auth0["DISCORD"]["token"]
    CLIENT_SECRET = auth0["DISCORD"]["client_secret"]

    bot_token_bytes = BOT_TOKEN.encode('utf-8')
    client_secret_bytes = CLIENT_SECRET.encode('utf-8')

    encrypted_token = fernet.encrypt(bot_token_bytes).decode('utf-8')  # Als String zurückgeben
    encrypted_client_secret = fernet.encrypt(client_secret_bytes).decode('utf-8')

    logger.warn(
        f"[ 1 / 3 ]    BAXI DATA GOT PULLED WITH API KEY! Sensible data was sent in encrypted form. IP: {request.headers.get('X-Forwarded-For', request.remote_addr)}")
    logger.warn(
        f"[ 2 / 3 ]    BAXI DATA GOT PULLED WITH API KEY! Sensible data was sent in encrypted form. IP: {request.headers.get('X-Forwarded-For', request.remote_addr)}")
    logger.warn(
        f"[ 3 / 3 ]    BAXI DATA GOT PULLED WITH API KEY! Sensible data was sent in encrypted form. IP: {request.headers.get('X-Forwarded-For', request.remote_addr)}")

    await channel.send(
        f"<@686634546577670400> \nBAXI DATA GOT PULLED WITH API KEY! Sensible data was sent in encrypted form.\nIP: {request.headers.get('X-Forwarded-For', request.remote_addr)}")

    return jsonify(
        {"token": str(encrypted_token), "client_id": str(CLIENT_ID), "client_secret": str(encrypted_client_secret),
         "redirect_uri": str(REDIRECT_URI), "app_name": str(bot.user.name), "app_id": int(bot.user.id),
         "app_verified": bool(bot.user.verified)})


async def load_antiraid_settings(request, guild: discord.Guild):
    """

    :param request:
    :param guild:
    :return:
    """
    config = configparser.ConfigParser()
    config.read("config/runtime.conf")
    try:
        key = request.headers.get("Authorization")
        if str(key) != auth0["DASH"]["key"]:
            return jsonify({'error': "Invalid API KEY"}), 401
        if bool(config["WEB"]["api_online"]):
            anti_raid_settings = get_saves.load_data("json/anti_raid.json")

            server_roles = {str(role.id) + "-send": str(role.name) + "-show" for role in guild.roles if
                            role != guild.default_role}
            if str(guild.id) in anti_raid_settings:
                try:
                    role = guild.get_role(int(anti_raid_settings[str(guild.id)]["role_id"]))
                except Exception as e:
                    logger.error(str(e))
                    return jsonify({"notify-error": "An error occurred while loading the role information."})
                return {"active-switch": 1,
                        "role-label": "Quarantine role",
                        "role-activedrop": {str(role.id) + "-send": str(role.name) + "-show"},
                        "roles-drop": server_roles
                        }
            else:
                return {"active-switch": 0,
                        "role-label": "Quarantine role",
                        "role-activedrop": None,
                        "roles-drop": server_roles
                        }

        else:
            return {
                "notify-warn": "Unfortunately, our backend server is currently unavailable. Please try again later!"}
    except Exception as e:
        return {"notify-warn": f"An unknown error has occurred! Check that all settings are correct.\n{str(e)}"}


async def save_antiraid_settings(request, guild: discord.Guild):
    """

    :param request:
    :param guild:
    :return:
    """
    config = configparser.ConfigParser()
    config.read("config/runtime.conf")
    try:
        key = request.headers.get("Authorization")
        if str(key) != auth0["DASH"]["key"]:
            return jsonify({'error': "Invalid API KEY"}), 401
        if bool(config["WEB"]["api_online"]):
            anti_raid_settings = get_saves.load_data("json/anti_raid.json")
            request_data = await request.get_json()
            print(request_data["active"])
            if int(request_data["active"]) == 1:
                roleid = request_data["roles-drop"]
                if roleid is None:
                    return {"notify-warn": "Please fill out all fields!"}

                anti_raid_settings[str(guild.id)] = {"role_id": int(roleid)}
                get_saves.save_data("json/anti_raid.json", anti_raid_settings)
                return {"notify-success": "The system has been successfully activated / edited."}
            else:
                # noinspection PyBroadException
                try:
                    del anti_raid_settings[str(guild.id)]
                    get_saves.save_data("json/anti_raid.json", anti_raid_settings)
                    return {"notify-success": "The system has been successfully deactivated."}
                except:  # noqa
                    return {"notify-info": "The system is already deactivated!"}



        else:
            return {
                "notify-warn": "Unfortunately, our backend server is currently unavailable. Please try again later!"}
    except Exception as e:
        return {"notify-warn": f"An unknown error has occurred! Check that all settings are correct.\n{str(e)}"}


async def load_globalchat_settings(request, guild: discord.Guild):
    """

    :param request:
    :param guild:
    :return:
    """
    config = configparser.ConfigParser()
    config.read("config/runtime.conf")
    try:
        key = request.headers.get("Authorization")
        if str(key) != auth0["DASH"]["key"]:
            return jsonify({'error': "Invalid API KEY"}), 401
        if bool(config["WEB"]["api_online"]):
            servers = get_saves.load_data("json/servers.json")
            gserver_ids = [item["guildid"] for item in servers]
            guild = bot.get_guild(guild.id)
            server_channels = {str(channel.id) + "-send": str(channel.name + "-show") for channel in
                               guild.text_channels}
            if guild.id in gserver_ids:
                for server in servers:
                    if guild.id == server["guildid"]:
                        channel = guild.get_channel(int(server["channelid"]))
                        return {"active-switch": 1,
                                "channels-label": "Channel",
                                "channels-activedrop": {str(channel.id) + "-send": str(channel.name) + "-show"},
                                "channels-drop": server_channels
                                }
            else:
                return {"active-switch": 0,
                        "channels-label": "Channel",
                        "channels-activedrop": None,
                        "channels-drop": server_channels
                        }
        else:
            return {
                "notify-warn": "Unfortunately, our backend server is currently unavailable. Please try again later!"}
    except Exception as e:
        return {"notify-warn": f"An unknown error has occurred! Check that all settings are correct.\n{str(e)}"}


async def save_globalchat_settings(request, guild: discord.Guild):
    try:
        key = request.headers.get("Authorization")
        if str(key) != auth0["DASH"]["key"]:
            return jsonify({'error': "Invalid API KEY"}), 401
        if bool(config["WEB"]["api_online"]):
            request_data = await request.get_json()
            servers = get_saves.load_data("json/servers.json")
            gserver_ids = [item["guildid"] for item in servers]
            if int(request_data["active"]) == 1:
                if request_data["channels-drop"] is None:
                    return {"notify-warn": "Please fill out all fields!"}

                server_to_remove = next((server for server in servers if server["guildid"] == guild.id), None)
                if server_to_remove is not None:  # Überprüfung, ob die Guild-ID vorhanden ist
                    servers.remove(server_to_remove)
                    get_saves.save_data("json/servers.json", servers)
                    servers = get_saves.load_data("json/servers.json")
                    server = {"guildid": int(guild.id),
                              "channelid": int(int(request_data["channels-drop"])),
                              "name": guild.nam
                              }
                    servers.append(server)
                    get_saves.save_data("json/servers.json", servers)
                    return {"notify-success": "System has been successfully activated / edited."}, 200
                else:
                    return {"notify-warn": "Guild ID not found in the server list!"}, 404
            elif int(request_data["active"]) == 0 and guild.id in gserver_ids:
                # noinspection PyBroadException
                try:
                    server_to_remove = next((server for server in servers if server["guildid"] == guild.id), None)
                    if server_to_remove is not None:  # Überprüfung, ob die Guild-ID vorhanden ist
                        servers.remove(server_to_remove)
                        get_saves.save_data("json/servers.json", servers)
                        return {"notify-success": "The system has been successfully deactivated."}, 200
                    else:
                        return {"notify-info": "The system is already deactivated!"}, 200
                except:
                    return {"notify-info": "The system is already deactivated!"}, 200
            else:
                return {"notify-warn": "Error in the configuration! Please check your settings again!"}, 500
        else:
            return {
                "notify-warn": "Unfortunately, our backend server is currently unavailable. Please try again later!"}
    except Exception as e:
        return {"notify-warn": f"An unknown error has occurred! Check that all settings are correct.\n{str(e)}"}


async def load_minigame_guessing_settings(request, guild: discord.Guild):
    try:
        key = request.headers.get("Authorization")
        if str(key) != auth0["DASH"]["key"]:
            return jsonify({'error': "Invalid API KEY"}), 401
        if bool(config["WEB"]["api_online"]):
            guessinggame_data = get_saves.load_data("json/guessing.json")
            server_channels = {str(channel.id) + "-send": str(channel.name + "-show") for channel in
                               guild.text_channels}
            if guild.id in guessinggame_data or str(guild.id) in guessinggame_data:
                # noinspection PyBroadException
                try:
                    channel = guild.get_channel(int(guessinggame_data[str(guild.id)]["channel_id"]))
                except:
                    channel = guild.get_channel(int(guessinggame_data[str(guild.id)]["channel_id"]))
                return {"active-switch": 1,
                        "channels-label": "Channel",
                        "channels-activedrop": {str(channel.id) + "-send": str(channel.name) + "-show"},
                        "channels-drop": server_channels
                        }
            else:
                return {"active-switch": 0,
                        "channels-label": "Channel",
                        "channels-activedrop": None,
                        "channels-drop": server_channels
                        }
        else:
            return {
                "notify-warn": "Unfortunately, our backend server is currently unavailable. Please try again later!"}
    except Exception as e:
        return {"notify-warn": f"An unknown error has occurred! Check that all settings are correct.\n{str(e)}"}


async def save_minigame_guessing_settings(request, guild: discord.Guild):
    try:
        key = request.headers.get("Authorization")
        if str(key) != auth0["DASH"]["key"]:
            return jsonify({'error': "Invalid API KEY"}), 401
        if bool(config["WEB"]["api_online"]):
            request_data = await request.get_json()
            logger.info(request_data)
            guessinggame_data = get_saves.load_data("json/guessing.json")
            if int(request_data["active"]) == 1:

                if request_data["channels-drop"] is None:
                    return {"notify-warn": "Please fill out all fields!"}

                channel = guild.get_channel(int(request_data["channels-drop"]))
                if str(guild.id) not in guessinggame_data:
                    number = random.randint(0, 10000)
                    guessinggame_data[str(guild.id)] = {"number": number,
                                                        "channel_id": channel.id
                                                        }
                else:
                    guessinggame_data[str(guild.id)]["channel_id"] = channel.id

                get_saves.save_data("json/guessing.json", guessinggame_data)
                return {"notify-success": "System has been successfully activated / edited."}, 200
            else:
                try:
                    del guessinggame_data[str(guild.id)]
                    get_saves.save_data("json/guessing.json", guessinggame_data)
                    return {"notify-success": "The system has been successfully deactivated."}, 200
                except Exception:
                    return {"notify-info": "The system is already deactivated!"}, 200

        else:
            return {
                "notify-warn": "Unfortunately, our backend server is currently unavailable. Please try again later!"}
    except Exception as e:
        return {"notify-warn": f"An unknown error has occurred! Check that all settings are correct.\n{str(e)}"}


async def load_minigame_counting_game(request, guild: discord.Guild):
    try:
        key = request.headers.get("Authorization")
        logger.info(str(key))
        if str(key) != auth0["DASH"]["key"]:
            return jsonify({'error': "Invalid API KEY"}), 401
        if bool(config["WEB"]["api_online"]):
            countinggame_data = get_saves.load_data("json/countgame_data.json")
            server_channels = {str(channel.id) + "-send": str(channel.name) + "-show" for channel in
                               guild.text_channels}
            if str(guild.id) in countinggame_data:
                channel = guild.get_channel(int(countinggame_data[str(guild.id)]["channel_id"]))
                print(channel.name)
                return {"active-switch": 1,
                        "channels-label": "Channel",
                        "channels-activedrop": {str(channel.id) + "-send": str(channel.name) + "-show"},
                        "channels-drop": server_channels
                        }
            else:
                return {"active-switch": 0,
                        "channels-label": "Channel",
                        "channels-activedrop": None,
                        "channels-drop": server_channels
                        }
        else:
            return {
                "notify-warn": "Unfortunately, our backend server is currently unavailable. Please try again later!"}
    except Exception as e:
        return {"notify-warn": f"An unknown error has occurred! Check that all settings are correct.\n{str(e)}"}


async def save_minigame_counting_settings(request, guild: discord.Guild):
    try:
        key = request.headers.get("Authorization")
        logger.info(str(key))
        if str(key) != auth0["DASH"]["key"]:
            return jsonify({'error': "Invalid API KEY"}), 401
        if bool(config["WEB"]["api_online"]):
            request_data = await request.get_json()
            countinggame_data = get_saves.load_data("json/countgame_data.json")
            logger.info(request_data)
            if int(request_data["active"]) == 1:

                if request_data["channels-drop"] is None:
                    return {"notify-warn": "Please fill out all fields!"}

                channel = guild.get_channel(int(request_data["channels-drop"]))
                if str(guild.id) not in countinggame_data:
                    countinggame_data[str(guild.id)] = {"channel_id": channel.id,
                                                        "count": 0,
                                                        "last_user": None
                                                        }

                else:
                    countinggame_data[str(guild.id)]["channel_id"] = channel.id

                get_saves.save_data("json/countgame_data.json", countinggame_data)
                return {"notify-success": "System has been successfully activated / edited."}, 200
            else:
                try:
                    del countinggame_data[str(guild.id)]
                    get_saves.save_data("json/countgame_data.json", countinggame_data)
                    return {"notify-success": "The system has been successfully deactivated."}, 200
                except NotFound:
                    return {"notify-info": "The system is already deactivated!"}, 200

        else:
            return {
                "notify-warn": "Unfortunately, our backend server is currently unavailable. Please try again later!"}
    except Exception as e:
        return {"notify-warn": f"An unknown error has occurred! Check that all settings are correct.\n{str(e)}"}


async def load_security_settings(request, guild: discord.Guild):
    try:
        key = request.headers.get("Authorization")
        logger.info(str(key))
        if str(key) != auth0["DASH"]["key"]:
            return jsonify({'error': "Invalid API KEY"}), 401
        if bool(config["WEB"]["api_online"]):
            chatfilter_data = get_saves.load_data("json/chatfilter.json")
            font_options = {str(1) + "-send": "Block-show", str(0) + "-send": "Allow-show"}

            server_index = next((index for (index, d) in enumerate(chatfilter_data) if d["guildid"] == guild.id), None)

            if server_index is not None:
                server_channels = {str(channel.id) + "-send": str(channel.name) + "-show" for channel in
                                   guild.text_channels if
                                   int(channel.id) not in chatfilter_data[server_index]["bypass_channels"]}
                server_channels["placeholder_none-send"] = "Please select-show"
                channels = {}
                channels_to_rem = {str(channel.id) + "-send": str(channel.name) + "-show" for channel in
                                   guild.text_channels if
                                   int(channel.id) in chatfilter_data[server_index]["bypass_channels"]}
                channels_to_rem["placeholder_none-send"] = "Please select-show"
                for channel in guild.text_channels:
                    if int(channel.id) in chatfilter_data[server_index]["bypass_channels"]:
                        channels[str(channel.id) + "-send"] = str(channel.name) + "-show"

                for guild in chatfilter_data:
                    if guild.id == guild["guildid"]:
                        block_fonts = guild["block_ascci"]
                        if block_fonts:
                            block_fonts = 1
                            block_fonts_txt = "Block"
                        else:
                            block_fonts = 0
                            block_fonts_txt = "Allow"
                        return {"active-switch": 1,
                                "block_unknown_symbols-label": "Allow unknown symbols?",
                                "block_unknown_symbols-drop": font_options,
                                "block_unknown_symbols-activedrop": {
                                    str(block_fonts) + "-send": str(block_fonts_txt) + "-show"},
                                "channels_add-label": "Add chatfilter bypass",
                                "channels_add-drop": server_channels,
                                "channels_add-activedrop": None,
                                "channels_rem-label": "Remove chatfilter bypass",
                                "channels_rem-drop": channels_to_rem,
                                "channels_rem-activedrop": None,
                                "channels-label": "Bypassed channels",
                                "channels-table": channels
                                }
            else:
                server_channels = {str(channel.id) + "-send": str(channel.name) + "-show" for channel in
                                   guild.text_channels}
                server_channels["placeholder_none-send"] = "Please select-show"
                channels = {}
                channels_to_rem = {"placeholder_none-send": "Please select-show"}
                return {"active-switch": 0,
                        "block_unknown_symbols-label": "Allow unknown symbols?",
                        "block_unknown_symbols-drop": font_options,
                        "block_unknown_symbols-activedrop": "None",
                        "channels_add-label": "Add chatfilter bypass",
                        "channels_add-drop": server_channels,
                        "channels_add-activedrop": None,
                        "channels_rem-label": "Remove chatfilter bypass",
                        "channels_rem-drop": channels_to_rem,
                        "channels_rem-activedrop": None,
                        "channels-label": "Bypassed channels",
                        "channels-table": channels
                        }
        else:

            return {
                "notify-warn": "Unfortunately, our backend server is currently unavailable. Please try again later!"}
    except Exception as e:
        return {"notify-warn": f"An unknown error has occurred! Check that all settings are correct.\n{str(e)}"}


async def save_security_settings(request, guild: discord.Guild):
    try:
        key = request.headers.get("Authorization")
        logger.info(str(key))
        if str(key) != auth0["DASH"]["key"]:
            return jsonify({'error': "Invalid API KEY"}), 401
        if bool(config["WEB"]["api_online"]):
            request_data = await request.get_json()
            logger.info(request_data)
            chatfilter_data = get_saves.load_data("json/chatfilter.json")
            if int(request_data["active"]) == 1:
                if int(request_data["block_unknown_symbols-drop"]) == 1:
                    block_fonts = True
                else:
                    block_fonts = False

                channel_add_re = request_data["channels_add-drop"]
                channel_rem_re = request_data["channels_rem-drop"]

                server_index = next((index for (index, d) in enumerate(chatfilter_data) if d["guildid"] == guild.id),
                                    None)

                if server_index is not None:
                    # Wenn der Server existiert, aktualisiere die Daten
                    chatfilter_data[server_index]["name"] = guild.name
                    chatfilter_data[server_index]["block_ascci"] = block_fonts

                    if channel_rem_re != "placeholder_none":
                        try:
                            channel = guild.get_channel(int(channel_rem_re))
                            chatfilter_data[server_index]["bypass_channels"].remove(channel.id)
                        except:
                            pass
                    if channel_add_re != "placeholder_none":
                        # noinspection PyBroadException
                        try:
                            channel = guild.get_channel(int(channel_add_re))
                            chatfilter_data[server_index]["bypass_channels"].append(channel.id)
                        except:
                            pass
                else:
                    # Wenn der Server nicht existiert, füge ihn hinzu
                    server = {
                        "guildid": guild.id,
                        "name": guild.name,
                        "block_ascci": block_fonts,
                        "bypass_channels": []
                    }
                    if channel_rem_re != "placeholder_none":
                        try:
                            channel = guild.get_channel(int(channel_rem_re))
                            chatfilter_data[server_index]["bypass_channels"].append(channel.id)
                        except:
                            pass
                    if channel_add_re != "placeholder_none":
                        try:
                            channel = guild.get_channel(int(channel_add_re))
                            chatfilter_data[server_index]["bypass_channels"].remove(channel.id)
                        except:
                            pass
                    chatfilter_data.append(server)

                get_saves.save_data("json/chatfilter.json", chatfilter_data)
                return {"notify-success": "The system has been successfully activated / edited."}
            else:
                try:
                    server_to_remove = next((server for server in chatfilter_data if server["guildid"] == guild.id),
                                            None)
                    chatfilter_data.remove(server_to_remove)
                    get_saves.save_data("json/chatfilter.json", chatfilter_data)
                    return {"notify-success": "The system has been successfully deactivated."}, 200
                except:
                    return {"notify-info": "The system is already deactivated!"}, 200

        else:
            return {
                "notify-warn": "Unfortunately, our backend server is currently unavailable. Please try again later!"}
    except Exception as e:
        return {"notify-warn": f"An unknown error has occurred! Check that all settings are correct.\n{str(e)}"}

async def load_welcome_settings(request, guild: discord.Guild)