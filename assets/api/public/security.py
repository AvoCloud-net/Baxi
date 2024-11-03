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
from io import BytesIO

import discord
import requests
from PIL import Image, ImageDraw, ImageFont
from cara_api import CaraAPI
from quart import render_template, jsonify, url_for
from reds_simple_logger import Logger
import configparser

logger = Logger()

from assets.general.get_saves import *
from assets.api.public.endpoints import *

auth0 = configparser.ConfigParser()
auth0.read("config/auth0.conf")
config = configparser.ConfigParser()
config.read("config/runtime.conf")

cara_api = CaraAPI(auth0["CARA"]["key"])


async def load_homepage():
    if bool(config["WEB"]["api_online"]):
        return await render_template("security-home.html")  # noqa
    else:
        return await render_template("503.html"), 503  # noqa


async def load_error_page():
    if bool(config["WEB"]["api_online"]):
        return await render_template('404.html'), 404  # noqa
    else:
        return await render_template("503.html"), 503  # noqa


async def load_chatfilterrequest_info(bot, id):
    auth0 = configparser.ConfigParser()
    auth0.read("config/auth0.conf")
    config = configparser.ConfigParser()
    config.read("config/runtime.conf")
    if bool(config["WEB"]["api_online"]):
       

        if id:
            try:
                with open('json/chatfilterrequest.json', 'r') as file:

                    data = json.load(file)
                    result = data.get(str(id))

                    if result:
                        guild = bot.get_guild(int(result["serverid"]))
                        user = guild.get_member(int(result["userid"]))
                        return await render_template('info.html', result=result, guild=guild, user=user)  # noqa
                    else:
                        return await render_template("chatfiltererror.html", msg="RequestID not found")  # noqa
            except:
                return await render_template("chatfiltererror.html", msg="RequestID not found in system")  # noqa
        else:
            return await render_template("chatfiltererror.html", msg="Missing information in your request")  # noqa
    else:
        return await render_template("503.html"), 503  # noqa


async def load_user_info(bot, id):
    if bool(config["WEB"]["api_online"]):

        if id:
            try:

                user_check = cara_api.get_user(id)
                isSpammer = user_check.isSpammer
                userid = user_check.user_id
                isspammerreason = user_check.reason

                try:
                    user = bot.get_user(int(id))  # Diese Zeile verursacht den Fehler

                    userPB = user.avatar.url
                    username = user.name
                    onDiscordSince = user.created_at
                except:
                    return await render_template("chatfiltererror.html", msg="User not found")  # noqa

                result = {"id": int(userid), "username": str(username), "pb": str(userPB), "isSpammer": isSpammer,
                          "isspammerreason": isspammerreason, "onDiscordSince": onDiscordSince}
                if result:
                    return await render_template('user-info.html', result=result)  # noqa
                else:
                    return await render_template("chatfiltererror.html", msg="Corrupt data")  # noqa
            except FileNotFoundError:
                return await render_template("chatfiltererror.html", msg="Unknwon error")  # noqa
        else:
            return await render_template("chatfiltererror.html", msg="Missing information in your request")  # noqa
    else:
        return await render_template("503.html"), 503  # noqa


