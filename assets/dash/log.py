import quart
from assets.data import load_data
from discord.ext import commands
from quart import Markup, render_template
from reds_simple_logger import Logger

logger = Logger()

def request_log_home(app: quart.Quart):
    @app.route("/log/")
    async def log_home():
        return await render_template("log_home.html")

def request_chatfilter_log(app: quart.Quart, bot: commands.AutoShardedBot):
    @app.route("/log/chatfilter")
    async def log():
        try:
            id = quart.request.args.get("id_chatfilter")

            chatfilter_log:dict = load_data(1001, "chatfilter_log")
            try:
                requested_data:dict = chatfilter_log.get(str(id))
                if not requested_data:
                    return await render_template("error.html", message="We're not sure what your ID is. Just double-check that you've copied or typed it correctly.")
            except:
                logger.error("LOG VIEW ERROR 1" + str(e))
                return await render_template("error.html", message="We're getting an error we don't recognize. Try again. If this keeps happening, let the development team know.")


            return await render_template("log_request.html", data = requested_data)
        except Exception as e:
            logger.error("LOG VIEW ERROR 2" + str(e))
            return await render_template("error.html", message="We're getting an error we don't recognize. Try again. If this keeps happening, let the development team know.")
    

def highlight_word(message:str, word:str):
    if not message or not word:
        return message
    highlighted = message.lower().replace(
        word.lower(), 
        f'<span style="background-color: rgba(234, 51, 51, 0.2);padding: 2px 8px;color: rgb(254, 180, 180);border-radius: 4px;transition: all 0.3s ease;"><b>{word.lower()}</b></span>'
    )
    return Markup(highlighted)

