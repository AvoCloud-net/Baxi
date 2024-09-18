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
from cara_api import CaraAPI
from PIL import Image, ImageDraw, ImageFont
import discord
from cryptography.fernet import Fernet
from quart import Quart, render_template, request, send_from_directory, jsonify, url_for
from quart_cors import cors
import json

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


async def load_chatfilterrequest_info(request, bot):
    auth0 = configparser.ConfigParser()
    auth0.read("config/auth0.conf")
    config = configparser.ConfigParser()
    config.read("config/runtime.conf")
    if bool(config["WEB"]["api_online"]):
        requestid = request.args.get('requestid')

        if requestid:
            try:
                with open('json/chatfilterrequest.json', 'r') as file:

                    data = json.load(file)
                    result = data.get(str(requestid))
                    guild = bot.get_guild(int(result["serverid"]))
                    user = guild.get_member(int(result["userid"]))
                    if result:
                        return await render_template('info.html', result=result, guild=guild, user=user)  # noqa
                    else:
                        return await render_template("chatfiltererror.html", msg="RequestID not found")  # noqa
            except FileNotFoundError:
                return await render_template("chatfiltererror.html", msg="Unknwon error")  # noqa
        else:
            return await render_template("chatfiltererror.html", msg="Missing information in your request")  # noqa
    else:
        return await render_template("503.html"), 503  # noqa


async def load_user_info(request, bot):
    if bool(config["WEB"]["api_online"]):
        requestid = request.args.get('idInput')

        if requestid:
            try:

                user_check = cara_api.get_user(requestid)
                isSpammer = user_check.isSpammer
                userid = user_check.user_id
                isspammerreason = user_check.reason

                try:
                    user = bot.get_user(int(requestid))  # Diese Zeile verursacht den Fehler

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


async def create_welcome_banner(request):
    keys = get_saves.load_data("json/api_keys.json")
    try:
        data = request.json

        # Extract parameters
        api_key = data.get("api_key")
        background_url = data.get('background_url')
        profile_pic_url = data.get('profile_pic_url')
        text1 = data.get('text1')
        text2 = data.get('text2')

        if str(api_key) not in keys:
            return jsonify({'error': "Invalid API KEY"}), 500

        # Fetch images from URLs
        background_img = Image.open(BytesIO(requests.get(background_url).content))
        profile_pic = Image.open(BytesIO(requests.get(profile_pic_url).content))

        # Resize profile pic to fit a reasonable size (adjust as needed)
        profile_pic = profile_pic.resize((200, 200))

        # Create a circular mask for the profile picture
        mask = Image.new('L', profile_pic.size, 0)
        draw = ImageDraw.Draw(mask)
        draw.ellipse((0, 0) + profile_pic.size, fill=255)
        profile_pic.putalpha(mask)

        # Create a blank image for the banner
        banner = Image.new('RGB', (800, 400), (255, 255, 255))

        # Paste background image
        background_img = background_img.resize((800, 400))
        banner.paste(background_img, (0, 0))

        # Paste profile pic in the center
        banner.paste(profile_pic, (245 - (100 - profile_pic.size[0]) // 2, 5 - (100 - profile_pic.size[1]) // 2),
                     mask=profile_pic)

        # Draw text1 centered below profile pic
        draw = ImageDraw.Draw(banner)
        text1_font = ImageFont.truetype("arial.ttf", 30)
        text1_bbox = draw.textbbox((0, 0), text1, font=text1_font)
        text1_width, text1_height = text1_bbox[2], text1_bbox[3]
        draw.text(((800 - text1_width) / 2, 260), text1, font=text1_font, fill=(255, 255, 255))  # White text

        # Draw text2 centered below text1
        text2_font = ImageFont.truetype("arial.ttf", 25)
        text2_bbox = draw.textbbox((0, 0), text2, font=text2_font)
        text2_width, text2_height = text2_bbox[2], text2_bbox[3]
        draw.text(((800 - text2_width) / 2, 300), text2, font=text2_font, fill=(255, 255, 255))  # White text

        # Save the banner as bytes in memory
        img_bytes = BytesIO()
        banner.save(img_bytes, format='PNG')
        img_bytes.seek(0)

        image = await save_welcome_image(img_bytes.getvalue())

        image_url = "http://sparkle2.pyropixle.com:1650/" + url_for('serve_welcome_image', filename=image)

        return await jsonify({'image_url': image_url}), 200
    except Exception as e:
        logger.error(str(e))
        return await jsonify({'error': str(e)}), 500


async def get_chatfilter_data(request):
    keys = get_saves.load_data("json/api_keys.json")
    try:
        data = request.json

        api_key = data.get("api_key")

        if str(api_key) not in keys:
            return await jsonify({'error': "Invalid API KEY"}), 500

        requestID = data.get('request_id')
        with open('json/chatfilterrequest.json', 'r') as file:
            chatfilter_data = json.load(file)
            result = chatfilter_data.get(str(requestID))
            if result:
                return result, 200
            else:
                return await jsonify({"error": "Unknown RequestID"}), 404


    except Exception as e:
        logger.error(str(e))
        return await jsonify({'error': str(e)}), 500
