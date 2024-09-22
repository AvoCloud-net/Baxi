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
import datetime

from reds_simple_logger import Logger
import configparser
import discord
from cryptography.fernet import Fernet
from quart import jsonify
from wavelink.lfu import NotFound

from assets.general.get_saves import *
from assets.general.routine_events import load_language_model
from main import VerifyButton, TicketMenuButtons

logger = Logger()
embedColor = discord.Color.from_rgb(int(config["BOT"]["embed_color_red"]), int(config["BOT"]["embed_color_green"]),
                                    int(config["BOT"]["embed_color_blue"]))
icons_url = config["WEB"]["icon_url"]


async def save_antiraid_settings(request, guild: discord.Guild):
    data = await request.get_json()
    logger.debug.info(data)
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
            anti_raid_settings = load_data("json/anti_raid.json")
            request_data = await request.get_json()
            print(request_data["active-switch"])
            if int(request_data["active-switch"]) == 1:
                role_id: int = int(list(request_data["roles-activedrop"].values())[0])
                if role_id is None:
                    return {"notify-warn": "Please fill out all fields!"}

                anti_raid_settings[str(guild.id)] = {"role_id": role_id}
                save_data("json/anti_raid.json", anti_raid_settings)
                return {"notify-success": "The system has been successfully activated / edited."}
            else:
                # noinspection PyBroadException
                try:
                    del anti_raid_settings[str(guild.id)]
                    save_data("json/anti_raid.json", anti_raid_settings)
                    return {"notify-success": "The system has been successfully deactivated."}
                except:  # noqa
                    return {"notify-info": "The system is already deactivated!"}



        else:
            return {
                "notify-warn": "Unfortunately, our backend server is currently unavailable. Please try again later!"}
    except Exception as e:
        return {"notify-warn": f"An unknown error has occurred! Check that all settings are correct.\n{str(e)}"}


async def save_globalchat_settings(request, guild: discord.Guild):
    data = await request.get_json()
    logger.debug.info(data)
    try:
        key = request.headers.get("Authorization")
        if str(key) != auth0["DASH"]["key"]:
            return jsonify({'error': "Invalid API KEY"}), 401
        if bool(config["WEB"]["api_online"]):
            request_data = await request.get_json()
            servers = load_data("json/servers.json")
            gserver_ids = [item["guildid"] for item in servers]
            if int(request_data["active-switch"]) == 1:
                channel_id: int = int(list(request_data["channels-activedrop"].values())[0])
                if channel_id is None:
                    return {"notify-warn": "Please fill out all fields!"}

                server_to_remove = next((server for server in servers if server["guildid"] == guild.id), None)
                if server_to_remove is not None:  # Überprüfung, ob die Guild-ID vorhanden ist
                    servers.remove(server_to_remove)
                    save_data("json/servers.json", servers)
                    servers = load_data("json/servers.json")
                    server = {"guildid": int(guild.id),
                              "channelid": channel_id,
                              "name": guild.name
                              }
                    servers.append(server)
                    save_data("json/servers.json", servers)
                    return {"notify-success": "System has been successfully activated / edited."}, 200
                else:
                    return {"notify-warn": "Guild ID not found in the server list!"}, 404
            elif int(request_data["active-switch"]) == 0 and guild.id in gserver_ids:
                # noinspection PyBroadException
                try:
                    server_to_remove = next((server for server in servers if server["guildid"] == guild.id), None)
                    if server_to_remove is not None:  # Überprüfung, ob die Guild-ID vorhanden ist
                        servers.remove(server_to_remove)
                        save_data("json/servers.json", servers)
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


async def save_minigame_guessing_settings(request, guild: discord.Guild):
    data = await request.get_json()
    logger.debug.info(data)
    try:
        key = request.headers.get("Authorization")
        if str(key) != auth0["DASH"]["key"]:
            return jsonify({'error': "Invalid API KEY"}), 401
        if bool(config["WEB"]["api_online"]):
            request_data = await request.get_json()
            logger.info(request_data)
            guessinggame_data = load_data("json/guessing.json")

            if int(request_data["active-switch"]) == 1:
                channel_id: int = int(list(request_data["channels-activedrop"].values())[0])
                if channel_id is None:
                    return {"notify-warn": "Please fill out all fields!"}

                channel = guild.get_channel(channel_id)
                if str(guild.id) not in guessinggame_data:
                    number = random.randint(0, 10000)
                    guessinggame_data[str(guild.id)] = {"number": number,
                                                        "channel_id": channel.id
                                                        }
                else:
                    guessinggame_data[str(guild.id)]["channel_id"] = channel.id

                save_data("json/guessing.json", guessinggame_data)
                return {"notify-success": "System has been successfully activated / edited."}, 200
            else:
                try:
                    del guessinggame_data[str(guild.id)]
                    save_data("json/guessing.json", guessinggame_data)
                    return {"notify-success": "The system has been successfully deactivated."}, 200
                except Exception:
                    return {"notify-info": "The system is already deactivated!"}, 200

        else:
            return {
                "notify-warn": "Unfortunately, our backend server is currently unavailable. Please try again later!"}
    except Exception as e:
        return {"notify-warn": f"An unknown error has occurred! Check that all settings are correct.\n{str(e)}"}


async def save_minigame_counting_settings(request, guild: discord.Guild):
    data = await request.get_json()
    logger.debug.info(data)
    try:
        key = request.headers.get("Authorization")
        logger.info(str(key))
        if str(key) != auth0["DASH"]["key"]:
            return jsonify({'error': "Invalid API KEY"}), 401
        if bool(config["WEB"]["api_online"]):
            request_data = await request.get_json()
            countinggame_data = load_data("json/countgame_data.json")
            logger.info(request_data)

            if int(request_data["active-switch"]) == 1:
                channel_id: int = int(list(request_data["channels-activedrop"].values())[0])
                if channel_id is None:
                    return {"notify-warn": "Please fill out all fields!"}

                channel = guild.get_channel(int(channel_id))
                if str(guild.id) not in countinggame_data:
                    countinggame_data[str(guild.id)] = {"channel_id": channel.id,
                                                        "count": 0,
                                                        "last_user": None
                                                        }

                else:
                    countinggame_data[str(guild.id)]["channel_id"] = channel.id

                save_data("json/countgame_data.json", countinggame_data)
                return {"notify-success": "System has been successfully activated / edited."}, 200
            else:
                try:
                    del countinggame_data[str(guild.id)]
                    save_data("json/countgame_data.json", countinggame_data)
                    return {"notify-success": "The system has been successfully deactivated."}, 200
                except NotFound:
                    return {"notify-info": "The system is already deactivated!"}, 200

        else:
            return {
                "notify-warn": "Unfortunately, our backend server is currently unavailable. Please try again later!"}
    except Exception as e:
        return {"notify-warn": f"An unknown error has occurred! Check that all settings are correct.\n{str(e)}"}


async def save_security_settings(request, guild: discord.Guild):
    data = await request.get_json()
    logger.debug.info(data)
    try:
        key = request.headers.get("Authorization")
        logger.info(str(key))
        if str(key) != auth0["DASH"]["key"]:
            return jsonify({'error': "Invalid API KEY"}), 401
        if bool(config["WEB"]["api_online"]):
            request_data = await request.get_json()
            logger.info(request_data)
            chatfilter_data = load_data("json/chatfilter.json")
            if int(request_data["active-switch"]) == 1:
                if int(request_data["block_unknown_symbols-activedrop"]) == 1:
                    block_fonts = True
                else:
                    block_fonts = False

                channel_add_id: int = int(list(request_data["channels_add-activedrop"].values())[0])
                channel_rem_id: int = int(list(request_data["channels_rem-activedrop"].values())[0])
                server_index = next((index for (index, d) in enumerate(chatfilter_data) if d["guildid"] == guild.id),
                                    None)

                if channel_rem_id != 0:
                    channel = guild.get_channel(channel_rem_id)
                    if channel:
                        if channel.id in chatfilter_data[server_index]["bypass_channels"]:
                            try:
                                chatfilter_data[server_index]["bypass_channels"].remove(channel.id)
                            except ValueError:
                                logger.warn("Channel not found: " + channel.name)
                if channel_add_id != 0:
                    channel = guild.get_channel(channel_add_id)
                    if channel:
                        if channel.id not in chatfilter_data[server_index]["bypass_channels"]:
                            try:
                                chatfilter_data[server_index]["bypass_channels"].append(channel.id)
                            except ValueError:
                                logger.warn("Channel not found: " + channel.name)
                else:
                    server = {
                        "guildid": guild.id,
                        "name": guild.name,
                        "block_ascci": block_fonts,
                        "bypass_channels": []
                    }
                    if channel_rem_id != 0:
                        channel = guild.get_channel(channel_rem_id)
                        if channel:
                            if channel.id in server["bypass_channels"]:
                                try:
                                    server["bypass_channels"].remove(channel.id)
                                except ValueError:
                                    pass
                    if channel_add_id != 0:
                        channel = guild.get_channel(channel_add_id)
                        if channel:
                            if channel.id not in server["bypass_channels"]:
                                try:
                                    server["bypass_channels"].append(channel.id)
                                except ValueError:
                                    pass

                    chatfilter_data.append(server)

                save_data("json/chatfilter.json", chatfilter_data)
                return {"notify-success": "The system has been successfully activated / edited."}
            else:
                try:
                    server_to_remove = next((server for server in chatfilter_data if server["guildid"] == guild.id),
                                            None)
                    chatfilter_data.remove(server_to_remove)
                    save_data("json/chatfilter.json", chatfilter_data)
                    return {"notify-success": "The system has been successfully deactivated."}, 200
                except:
                    return {"notify-info": "The system is already deactivated!"}, 200

        else:
            return {
                "notify-warn": "Unfortunately, our backend server is currently unavailable. Please try again later!"}
    except Exception as e:
        logger.error(str(e))
        return {"notify-warn": f"An unknown error has occurred! Check that all settings are correct.\n{str(e)}"}


async def save_welcome_settings(request, guild: discord.Guild):
    data = await request.get_json()
    logger.debug.info(data)
    try:
        key = request.headers.get("Authorization")
        logger.info(str(key))
        if str(key) != auth0["DASH"]["key"]:
            return jsonify({'error': "Invalid API KEY"}), 401
        if bool(config["WEB"]["api_online"]):
            request_data = await request.get_json()
            logger.info(request_data)
            welcomelist = load_data("json/welcome.json")

            if int(request_data["active-switch"]) == 1:
                channel_id: int = int(list(request_data["channels-activedrop"].values())[0])
                color: str = str(list(request_data["color-activedrop"].values())[0])
                if request_data["message-input"] is None or request_data[
                    "image-input"] is None or channel_id is None or color is None:
                    return {"notify-warn": "Please fill out all fields!"}

                message = str(request_data["message-input"])
                image_link = str(request_data["image-input"])
                channel = guild.get_channel(int(channel_id))
                welcomelist[str(guild.id)] = {"channel_id": channel.id,
                                              "message": message,
                                              "color": color,
                                              "image": image_link}
                save_data("json/welcome.json", welcomelist)
                return {"notify-success": "The system has been successfully activated / edited."}
            else:
                try:
                    del welcomelist[str(guild.id)]
                    save_data("json/welcome.json", welcomelist)
                    return {"notify-success": "The system has been successfully deactivated."}
                except:
                    return {"notify-info": "The system is already deactivated!"}

        else:
            return {
                "notify-warn": "Unfortunately, our backend server is currently unavailable. Please try again later!"}
    except Exception as e:
        return {"notify-warn": f"An unknown error has occurred! Check that all settings are correct.\n{str(e)}"}


async def save_verify_settings(request, guild: discord.Guild):
    data = await request.get_json()
    logger.debug.info(data)
    try:
        language = load_language_model(guild.id)
        key = request.headers.get("Authorization")
        logger.info(str(key))
        if str(key) != auth0["DASH"]["key"]:
            return jsonify({'error': "Invalid API KEY"}), 401

        if bool(config["WEB"]["api_online"]):
            request_data = await request.get_json()
            logger.info(request_data)  # Hier await hinzufügen
            request_data = await request.get_json()  # Hier await hinzufügen

            verifylist = load_data("json/verify.json")

            if int(request_data["active-switch"]) == 1:
                channel_id: int = int(list(request_data["channels-activedrop"].values())[0])
                role_id: int = int(list(request_data["roles-activedrop"].values())[0])
                if role_id is None or request_data["message-input"] is None or request_data[
                    "task-activedrop"] is None or channel_id is None:
                    return {"notify-warn": "Please fill out all fields!"}

                role = guild.get_role(int(role_id))
                message = request_data["message-input"]
                task = int(request_data["task-activedrop"])
                channel = guild.get_channel(int(channel_id))

                if int(task) == 0:
                    pass
                elif int(task) == 1:
                    pass
                else:
                    return {"notify-warn": f"TASK not permitted. 0 or 1 expected, {task} received."}

                if str(guild.id) not in verifylist:
                    embedverify = discord.Embed(
                        title=language["verify_title_btn"],
                        description=f"{message.replace(';', '\n')}",
                        color=embedColor
                    ).set_thumbnail(url=icons_url + "lock.png")

                    await channel.send(embed=embedverify, view=VerifyButton())

                    perms1 = discord.PermissionOverwrite()
                    perms1.view_channel = True
                    # noinspection PyDunderSlots
                    perms1.send_messages = False
                    perms1.read_message_history = True
                    perms1.read_messages = True
                    perms1.add_reactions = False

                    await channel.set_permissions(guild.default_role, reason="Verify System Setup", overwrite=perms1)

                    perms2 = discord.PermissionOverwrite()
                    perms2.view_channel = False

                    await channel.set_permissions(role, overwrite=perms2)

                verifylist[str(guild.id)] = {"role_id": role.id,
                                             "message": message,
                                             "task": int(task) + 1
                                             }
                save_data("json/verify.json", verifylist)
                return {"notify-success": "The system has been successfully activated / edited."}
            else:
                try:
                    del verifylist[str(guild.id)]
                    save_data("json/verify.json", verifylist)
                    return {"notify-success": "The system has been successfully deactivated."}
                except:
                    return {"notify-info": "The system is already deactivated!"}

        else:
            return {
                "notify-warn": "Unfortunately, our backend server is currently unavailable. Please try again later!"}
    except Exception as e:
        return {"notify-warn": f"An unknown error has occurred! Check that all settings are correct.\n{str(e)}"}


async def save_sugg_settings(request, guild: discord.Guild):
    data = await request.get_json()
    logger.debug.info(data)
    try:
        key = request.headers.get("Authorization")
        logger.info(str(key))
        if str(key) != auth0["DASH"]["key"]:
            return jsonify({'error': "Invalid API KEY"}), 401

        if bool(config["WEB"]["api_online"]):
            request_data = await request.get_json()
            suggestion_data = load_data("json/suggestion.json")

            if request_data["active-switch"] == 1:
                channel_add_re: int = int(list(request_data["channels_add-activedrop"].values())[0])
                channel_rem_re: int = int(list(request_data["channels_rem-activedrop"].values())[0])
                if str(guild.id) in suggestion_data:
                    if channel_rem_re != 0:
                        rem_channel = guild.get_channel(channel_rem_re)  # Use channel_rem_re here
                        if rem_channel:
                            try:
                                suggestion_data[str(guild.id)]["channels"].remove(rem_channel.id)
                            except ValueError:
                                logger.warn("Channel not found: " + rem_channel.name)
                    if channel_add_re != 0:
                        add_channel = guild.get_channel(channel_add_re)
                        if add_channel:
                            try:
                                suggestion_data[str(guild.id)]["channels"].append(add_channel.id)
                            except ValueError:
                                logger.warn("Channel not found: " + add_channel.name)
                else:
                    suggestion_data[str(guild.id)] = {"channels": []}
                    if channel_add_re != 0:
                        add_channel = guild.get_channel(channel_add_re)
                        if add_channel:
                            try:
                                suggestion_data[str(guild.id)]["channels"].append(add_channel.id)
                            except ValueError:
                                pass

                found = False
                for channel in guild.text_channels:
                    if int(channel.id) in suggestion_data[str(guild.id)]["channels"]:
                        found = True
                        break

                if not found:
                    del suggestion_data[str(guild.id)]

                save_data("json/suggestion.json", suggestion_data)
                return {"notify-success": "Successfully saved!"}
            else:
                try:
                    del suggestion_data[str(guild.id)]
                    save_data("json/suggestion.json", suggestion_data)
                    return {"notify-success": "The system has been successfully deactivated."}
                except:
                    return {"notify-info": "The system is already deactivated!"}


        else:
            return {
                "notify-warn": "Unfortunately, our backend server is currently unavailable. Please try again later!"}
    except Exception as e:
        return {"notify-warn": f"An unknown error has occurred! Check that all settings are correct.\n{str(e)}"}


async def save_ticket_settings(request, guild: discord.Guild):
    data = await request.get_json()
    logger.debug.info(data)
    try:
        language = load_language_model(guild.id)
        key = request.headers.get("Authorization")
        logger.info(str(key))
        if str(key) != auth0["DASH"]["key"]:
            return jsonify({'error': "Invalid API KEY"}), 401

        if bool(config["WEB"]["api_online"]):
            request_data = await request.get_json()
            ticketdata = load_data("json/ticketdata.json")
            channel_id: int = int(list(request_data["channels-activedrop"].values())[0])
            role_id: int = int(list(request_data["roles-activedrop"].values())[0])
            category_id: int = int(list(request_data["category-activedrop"].values())[0])
            if int(request_data["active-switch"]) == 1:

                if channel_id is None or category_id is None or \
                        request_data[
                            "roles-activedrop"] is None:
                    return {"notify-warn": "Please fill out all fields!"}

                channel = guild.get_channel(int(channel_id))
                category = guild.get_channel(int(category_id))
                role = guild.get_role(int(role_id))

                if str(guild.id) not in ticketdata:
                    embed = discord.Embed(title=language["ticket_menu_title"].format(server=guild.name),
                                          description=language["ticket_menu"],
                                          color=embedColor, timestamp=datetime.datetime.now()).set_thumbnail(
                        url=icons_url + "ticket.png")
                    await channel.send(embed=embed, view=TicketMenuButtons())

                    perms = discord.PermissionOverwrite()
                    perms.view_channel = True
                    # noinspection PyUnresolvedReferences
                    perms.read_message_history = True
                    perms.read_messages = True
                    perms.send_messages = False
                    await channel.set_permissions(guild.default_role, overwrite=perms)

                ticketdata[str(guild.id)] = {"categoryid": category.id,
                                             "roleid": role.id,
                                             "ticket_owners": []
                                             }
                save_data("json/ticketdata.json", ticketdata)
                return {"notify-success": "The system has been successfully activated / edited."}
            else:
                try:
                    del ticketdata[str(guild.id)]
                    save_data("json/ticketdata.json", ticketdata)
                    return {"notify-success": "The system has been successfully deactivated."}
                except:
                    return {"notify-info": "The system is already deactivated!"}

        else:
            return {
                "notify-warn": "Unfortunately, our backend server is currently unavailable. Please try again later!"}
    except Exception as e:
        return {"notify-warn": f"An unknown error has occurred! Check that all settings are correct.\n{str(e)}"}


async def save_log_settings(request, guild: discord.Guild):
    data = await request.get_json()
    logger.debug.info(data)
    try:
        log_channels = load_data("json/log_channels.json")
        key = request.headers.get("Authorization")
        logger.info(str(key))
        if str(key) != auth0["DASH"]["key"]:
            return jsonify({'error': "Invalid API KEY"}), 401

        if bool(config["WEB"]["api_online"]):
            request_data = await request.get_json()
            channel_id: int = int(list(request_data["channels-activedrop"].values())[0])

            if channel_id is None:
                return {"notify-warn": "Please fill out all fields!"}

            if int(request_data["active-switch"]) == 1:
                channel = guild.get_channel(int(channel_id))
                log_channels[str(guild.id)] = {"channel_id": int(channel.id)}
                save_data("json/log_channels.json", log_channels)
                return {"notify-success": "System successfully activated / edited."}
            else:
                try:
                    del log_channels[str(guild.id)]
                    save_data("json/log_channels.json", log_channels)
                    return {"notify-success": "The system has been successfully deactivated."}
                except:
                    return {"notify-info": "The system is already deactivated!"}

        else:
            return {
                "notify-warn": "Unfortunately, our backend server is currently unavailable. Please try again later!"}
    except Exception as e:
        return {"notify-warn": f"An unknown error has occurred! Check that all settings are correct.\n{str(e)}"}


async def save_autoroles_guild(request, guild: discord.Guild):
    data = await request.get_json()
    logger.debug.info(data)
    try:
        auto_roles = load_data("json/auto_roles.json")
        request_data = await request.get_json()
        key = request.headers.get("Authorization")
        logger.info(str(key))

        if str(key) != auth0["DASH"]["key"]:
            return jsonify({'error': "Invalid API KEY"}), 401
        print(request_data)
        if bool(config["WEB"]["api_online"]):
            if int(request_data["active-switch"]) == 1:
                rem_role: int = int(list(request_data["roles_to_remove-activedrop"].values())[0])
                add_role: int = int(list(request_data["roles_to_add-activedrop"].values())[0])
                if str(guild.id) in auto_roles:

                    if rem_role != 0:
                        rem_role = guild.get_role(int(rem_role))
                        print(rem_role.name)
                        try:
                            auto_roles[str(guild.id)]["roles"].remove(rem_role.id)
                        except Exception as e:
                            logger.warn("/API/DASH/SETTINGS/SAVE/AUTO_RULES/ID - EXCEPTION - " + str(e))
                    if add_role != 0:
                        add_role = guild.get_role(int(add_role))
                        print(add_role.name)
                        try:
                            auto_roles[str(guild.id)]["roles"].append(add_role.id)
                        except Exception as e:
                            logger.warn("/API/DASH/SETTINGS/SAVE/AUTO_RULES/ID - EXCEPTION - " + str(e))

                else:
                    auto_roles[str(guild.id)] = {"roles": []}
                    if add_role != 0:
                        add_role = guild.get_role(int(add_role))
                        try:
                            auto_roles[str(guild.id)]["roles"].append(add_role.id)
                        except Exception as e:
                            logger.warn("/API/DASH/SETTINGS/SAVE/AUTO_RULES/ID - EXCEPTION - " + str(e))
                found = False
                for role in guild.roles:
                    if int(role.id) in auto_roles[str(guild.id)]["roles"]:
                        found = True
                if not found:
                    del auto_roles[str(guild.id)]
                save_data("json/auto_roles.json", auto_roles)
                return {"notify-success": "System successfully activated / edited."}
            else:
                try:
                    del auto_roles[str(guild.id)]
                    save_data("json/auto_roles.json", auto_roles)
                    return {"notify-success": "The system has been successfully deactivated."}
                except:
                    return {"notify-info": "The system is already deactivated!"}

        else:
            return {
                "notify-warn": "Unfortunately, our backend server is currently unavailable. Please try again later!"}
    except Exception as e:
        return {"notify-warn": f"An unknown error has occurred! Check that all settings are correct.\n{str(e)}"}


async def send_guild_msg(request, channel: discord.TextChannel):
    try:
        key = request.headers.get("Authorization")
        logger.info(str(key))
        if str(key) != auth0["DASH"]["key"]:
            return jsonify({'error': "Invalid API KEY"}), 401
        if bool(config["WEB"]["api_online"]):
            try:
                request_data = await request.get_json()
                message = request_data["message"]

                await channel.send(message)
                return {"notify-success": f"The message has been successfully sent to {channel.name}."}

            except:
                return {
                    "notify-warn": "Unfortunately, an unexpected error has occurred. Please try again. If the error occurs repeatedly, please contact our support."}
    except Exception as e:
        return {"notify-warn": f"An unknown error has occurred! Check that all settings are correct.\n{str(e)}"}
