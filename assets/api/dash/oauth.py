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
import pyotp
from reds_simple_logger import Logger
import configparser
import discord
from cryptography.fernet import Fernet
from quart import jsonify

from assets.general.get_saves import *

logger = Logger()

def verify_one_time_code(one_time_code, secret_key):
    totp = pyotp.TOTP(secret_key, interval=10)
    if totp.verify(one_time_code):
        return True
    else:
        return False

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
    SECRET = auth0["FLASK"]["secret"]

    BOT_TOKEN = auth0["DISCORD"]["token"]
    CLIENT_SECRET = auth0["DISCORD"]["client_secret"]

    bot_token_bytes = BOT_TOKEN.encode('utf-8')
    client_secret_bytes = CLIENT_SECRET.encode('utf-8')
    secret_bytes = SECRET.encode("utf-8")

    encrypted_token = fernet.encrypt(bot_token_bytes).decode('utf-8')  # Als String zurückgeben
    encrypted_client_secret = fernet.encrypt(client_secret_bytes).decode('utf-8')
    encrypted_secret = fernet.encrypt(secret_bytes).decode("utf-8")

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
         "app_verified": bool(bot.user.verified), "secret": str(encrypted_secret)})
