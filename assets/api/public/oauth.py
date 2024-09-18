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
from quart import jsonify

from assets.general.get_saves import *

async def check_api_key(request):
    keys = load_data("json/api_keys.json")
    key = request.args.get("key")
    logger.info(str(key))

    if str(key) not in keys:
        return await jsonify({'error': "Invalid API KEY"}), 500
    else:
        return "Valid key!", 200