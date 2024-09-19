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
import configparser

from cara_api import CaraAPI
from reds_simple_logger import Logger

from assets.dc.embed.buttons import *
from assets.general.routine_events import *

config = configparser.ConfigParser()
config.read("config/runtime.conf")
auth0 = configparser.ConfigParser()
auth0.read("config/auth0.conf")

logger = Logger()
caraAPI = CaraAPI(auth0["CARA"]["key"])


embedColor = discord.Color.from_rgb(int(config["BOT"]["embed_color_red"]), int(config["BOT"]["embed_color_green"]),
                                    int(config["BOT"]["embed_color_blue"]))  # FF5733


async def on_guild_join_event(guild: discord.Guild, bot):
    icons_url = config["WEB"]["icon_url"]
    banned_server = load_data("json/banned_server.json")
    logger.info("Joined Server")
    if str(guild.id) in banned_server:
        await guild.leave()
    else:
        channel = await guild.create_text_channel(name="baxi-notifications")
        newschannel = load_data("json/newschannel.json")
        newschannel[guild.id] = {"channelid": channel.id}
        save_data("json/newschannel.json", newschannel)

        await channel.send(embed=discord.Embed(title="Hi!",
                                               description="Hello everyone! I'm very happy to be part of this server. "
                                                           "My name is Baxi and I'm a PyroPixle project. If you have "
                                                           "any questions or need help, support is happy to help!\n\n",
                                               color=embedColor).set_thumbnail(
            url=icons_url + "hi.png").set_footer(text="PyroPixle"),
                           view=InviteUndWebUndDiscordundDocsButton())

        await bot.get_channel(1175821691860033536).send(embed=discord.Embed(
            title="Ein neuer Server!", description=f"Der Server `{guild.name}` nutzt nun Baxi!",
            color=embedColor).set_thumbnail(url=guild.icon.url))

async def on_member_join_event(member: discord.Member, bot):
    language = load_language_model(member.guild.id)
    welcomelist = load_data("json/welcome.json")
    auto_roles = load_data("json/auto_roles.json")

    get_user = caraAPI.get_user(str(member.id))

    if get_user.isSpammer:
        icons_url = config["WEB"]["icons_url"]
        embedwarn = discord.Embed(title=language["security_title"],
                                  description=f"{language['join_user_warn']} {member.mention}",
                                  color=discord.Color.red()).set_thumbnail(url=icons_url + "warn.png")
        log_channels = load_data("json/log_channels.json")

        try:
            await member.guild.get_channel(log_channels[str(member.guild.id)]["channel_id"]).send(embed=embedwarn)
            logger.success("Channel found!")
        except:
            logger.warn("Channel not found!")

        try:
            await member.guild.owner.send(embed=embedwarn)
        except:  # noqa
            pass

    if str(member.guild.id) in welcomelist:
        color_mapping = {
            "rot": discord.Color.red(),
            "blau": discord.Color.blue(),
            "grün": discord.Color.green(),
            "lila": discord.Color.purple(),
            "zufall": discord.Color.random(),
            "crimson": discord.Color.from_rgb(220, 20, 60)
        }
        guild_color = welcomelist[str(member.guild.id)]["color"]
        embed = discord.Embed(title=language["welcome_title"],
                              description=f"{str(welcomelist[str(member.guild.id)]['message']).replace('[@username]', f'{member.mention}').replace('@user', f'{member.mention}').replace('[@user]', f'{member.mention}').replace(";", "/n")}",
                              color=color_mapping.get(guild_color)).set_thumbnail(url=member.avatar.url)

        guild_id = str(member.guild.id)
        guild_data = welcomelist.get(guild_id, {})

        if "image" in guild_data:
            image_url = guild_data["image"]
            if image_url:
                embed.set_image(url=image_url)

        await bot.get_channel(int(welcomelist[str(member.guild.id)]["channel_id"])).send(embed=embed)

    if str(member.guild.id) in auto_roles:
        for role_id in auto_roles[str(member.guild.id)]["roles"]:
            role = member.guild.get_role(int(role_id))
            await member.add_roles(role, reason="Auto Role System")