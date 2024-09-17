from reds_simple_logger import Logger
import get_saves as get_saves
import discord

logger = Logger()


async def sync_baxi_data(request, auth0, channel: discord.abc.TextChannel):
    key = request.headers.get("Authorization")
    if str(key) != str(auth0["DASH"]["baxi_token_key"]):
        return jsonify({'error': "Invalid API KEY"}), 401

    fernet = Fernet(auth0["FLASK"]["key"])

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


async def load_antiraid_settings(request, config, guild: discord.abc.Guild):
    try:
        key = request.headers.get("Authorization")
        logger.info(str(key))
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


async def save_antiraid_settings(request, config, guild: discord.abc.Guild):
    try:
        key = request.headers.get("Authorization")
        logger.info(str(key))
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


async def load_globalchat_settings(request, config, guild: discord.abc.Guild):
    try:
        key = request.headers.get("Authorization")
        logger.info(str(key))
        logger.info(str(key))
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
