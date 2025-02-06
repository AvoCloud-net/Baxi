import quart
from discord.ext import commands

def dash_auth_endpoint(app: quart.Quart, bot: commands.AutoShardedBot):
    @app.route("/dash/auth/callback")
    async def auth():
        return "Not implemented yet"