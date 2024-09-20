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
from main import *

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


async def message_edit(before, after, bot):
    try:
        channel = before.channel
        author = before.author

        language = load_language_model(channel.guild.id)

        if before.author.bot:
            return

        # Determine what happened to the message
        if before.content != after.content:
            what_happened = language["log_channel_msg_edit_edit"]
        elif before.pinned != after.pinned:
            what_happened = language["log_channel_msg_edit_pinned"]
        else:
            return

        log_channels = load_data("json/log_channels.json")
        try:
            if str(channel.guild.id) in log_channels:
                guild = bot.get_guild(channel.guild.id)
                embed = discord.Embed(title=language["log_channel_title"],
                                      description=language["log_channel_msg_edit"].format(channel=channel.mention,
                                                                                          user=author.mention,
                                                                                          event=what_happened,
                                                                                          old_content=before.content,
                                                                                          new_content=after.content),
                                      color=embedColor
                                      ).set_thumbnail(url=author.avatar.url)

                await guild.get_channel(log_channels[str(channel.guild.id)]["channel_id"]).send(embed=embed)
        except Exception as e:
            logger.error(str(e))
    except Exception as e:
        logger.error(str(e))


async def audit_log_entry(entry, action_counts):
    try:
        logger.info("on_audit_log_entry_create received!")
        language = load_language_model(entry.guild.id)
        log_channels = load_data("json/log_channels.json")

        guild = entry.guild
        try:
            channel = guild.get_channel(log_channels[str(entry.guild.id)]["channel_id"])
            logger.success("Channel found!")
        except:
            logger.info("Channel not found!")
            channel = None

        action = entry.action
        executor: discord.User = entry.user
        target = entry.target

        embed = discord.Embed(title=" ", description=" ")

        if action == discord.AuditLogAction.kick:
            await log_action(entry.guild.id, executor.id, "member_kick", action_counts=action_counts)
            logger.info("Member KICK")
            embed = discord.Embed(title=language["log_channel_title"],
                                  description=language["log_member-kick"].format(user=target.name, reason=entry.reason,
                                                                                 executer=executor.mention),
                                  color=embedColor
                                  ).set_thumbnail(url=executor.avatar.url)

        elif action == discord.AuditLogAction.ban:
            logger.info("member_BAN")
            await log_action(entry.guild.id, executor.id, "member_ban", action_counts=action_counts)
            embed = discord.Embed(title=language["log_channel_title"],
                                  description=language["log_member-ban"].format(user=target.name, reason=entry.reason,
                                                                                executer=executor.mention),
                                  color=embedColor
                                  ).set_thumbnail(url=executor.avatar.url)

        elif action == discord.AuditLogAction.unban:
            logger.info("member_UNBAN")
            embed = discord.Embed(title=language["log_channel_title"],
                                  description=language["log_member-ban_remove"].format(user=target.name,
                                                                                       executer=executor.mention),
                                  color=embedColor
                                  ).set_thumbnail(url=executor.avatar.url)

        elif action == discord.AuditLogAction.member_update:
            logger.info("member_UPDATE")
            embed = discord.Embed(title=language["log_channel_title"],
                                  description=language["log_member-update_perms"].format(user=target.mention,
                                                                                         executer=executor.mention),
                                  color=embedColor
                                  ).set_thumbnail(url=executor.avatar.url)

        elif action == discord.AuditLogAction.member_move:
            logger.info("member_MOVE")
            embed = discord.Embed(title=language["log_channel_title"],
                                  description=language["log_member-moved_vc"].format(user=target.user.name,
                                                                                     executer=executor.mention,
                                                                                     channel_1=entry.changes.before.channel.mention,
                                                                                     channel_2=entry.changes.after.channel.mention),
                                  color=embedColor
                                  ).set_thumbnail(url=executor.avatar.url)

        elif action == discord.AuditLogAction.bot_add:
            logger.info("bot_ADD")
            embed = discord.Embed(title=language["log_channel_title"],
                                  description=language["log_bot-add"].format(executer=executor.mention,
                                                                             bot=target.user.mention),
                                  color=embedColor
                                  ).set_thumbnail(url=executor.avatar.url)

        elif action == discord.AuditLogAction.channel_create:
            logger.info("channel_CREATE")
            await log_action(entry.guild.id, executor.id, "channel_create", action_counts=action_counts)
            # f"{executor.mention} created channel {target.mention}."
            embed = discord.Embed(title=language["log_channel_title"],
                                  description=language["log_channel_create"].format(channel=target.mention,
                                                                                    executer=executor.mention),
                                  color=embedColor
                                  ).set_thumbnail(url=executor.avatar.url)

        elif action == discord.AuditLogAction.channel_update:
            logger.info("channel_UPDATE")
            await log_action(entry.guild.id, executor.id, "channel_update", action_counts=action_counts)
            # message = f"{executor.mention} updated channel {target.mention}."
            embed = discord.Embed(title=language["log_channel_title"],
                                  description=language["log_channel-update"].format(channel=target.mention,
                                                                                    executer=executor.mention),
                                  color=embedColor
                                  ).set_thumbnail(url=executor.avatar.url)

        elif action == discord.AuditLogAction.channel_delete:
            logger.info("channel_DELETE")
            await log_action(entry.guild.id, executor.id, "channel_delete", action_counts=action_counts)
            # message = f"{executor.mention} deleted channel {target.mention}."
            embed = discord.Embed(title=language["log_channel_title"],
                                  description=language["log_channel-delete"].format(channel=entry.changes.before.name,
                                                                                    executer=executor.mention),
                                  color=embedColor
                                  ).set_thumbnail(url=executor.avatar.url)

        elif action == discord.AuditLogAction.message_delete:
            logger.info("message_DELETE")
            embed = discord.Embed(title=language["log_channel_title"],
                                  description=language["log_msg-delete"].format(user=target.name,
                                                                                executer=executor.mention,
                                                                                channel=entry.target.channel.mention),
                                  color=embedColor
                                  ).set_thumbnail(url=executor.avatar.url)

        elif action == discord.AuditLogAction.message_bulk_delete:
            logger.info("message_BULK-DELETE")
            await log_action(entry.guild.id, executor.id, "msg_bulk_delete", action_counts=action_counts)
            # message = f"{executor.mention} deleted {len(entry.extra.bulk_delete_messages)} messages in {entry.channel.mention}."
            embed = discord.Embed(title=language["log_channel_title"],
                                  description=language["log_msg-delete_bulk"].format(user=target.name,
                                                                                     executer=executor.mention,
                                                                                     channel=entry.target.channel.mention,
                                                                                     count=str(
                                                                                         entry.extra.count)),
                                  color=embedColor
                                  ).set_thumbnail(url=executor.avatar.url)

        elif action == discord.AuditLogAction.message_pin:
            logger.info("message_PIN")
            # message = f"{executor.mention} pinned a message sent by {target.mention} in {entry.channel.mention}."
            embed = discord.Embed(title=language["log_channel_title"],
                                  description=language["log_msg-pin"].format(user=target.mention,
                                                                             executer=executor.mention,
                                                                             channel=entry.target.channel.mention),
                                  color=embedColor
                                  ).set_thumbnail(url=executor.avatar.url)

        elif action == discord.AuditLogAction.message_unpin:
            logger.info("message_UNPIN")
            # message = f"{executor.mention} unpinned a message sent by {target.mention} in {entry.channel.mention}."
            embed = discord.Embed(title=language["log_channel_title"],
                                  description=language["log_msg-unpin"].format(user=target.mention,
                                                                               executer=executor.mention,
                                                                               channel=entry.target.channel.mention),
                                  color=embedColor
                                  ).set_thumbnail(url=executor.avatar.url)

        elif action == discord.AuditLogAction.invite_create:
            logger.info("invite_CREATE")
            # message = f"{executor.mention} created an invitation to the server."
            embed = discord.Embed(title=language["log_channel_title"],
                                  description=language["log_invite-create"].format(executer=executor.mention),
                                  color=embedColor
                                  ).set_thumbnail(url=executor.avatar.url)

        elif action == discord.AuditLogAction.invite_delete:
            logger.info("invite_DELETE")
            # message = f"{executor.mention} deleted an invitation to the server."
            embed = discord.Embed(title=language["log_channel_title"],
                                  description=language["log_invite-delete"].format(executer=executor.mention),
                                  color=embedColor
                                  ).set_thumbnail(url=executor.avatar.url)

        elif action == discord.AuditLogAction.emoji_create:
            logger.info("emoji_CREATE")
            # message = f"{executor.mention} created emoji {target.mention}."
            embed = discord.Embed(title=language["log_channel_title"],
                                  description=language["log_emoji-create"].format(executer=executor.mention,
                                                                                  emoji=target.name),
                                  color=embedColor
                                  ).set_thumbnail(url=executor.avatar.url)

        elif action == discord.AuditLogAction.emoji_delete:
            logger.info("emoji_DELETE")
            # message = f"{executor.mention} deleted emoji {target.mention}."
            embed = discord.Embed(title=language["log_channel_title"],
                                  description=language["log_emoji-delete"].format(executer=executor.mention,
                                                                                  emoji=entry.changes.before.name),
                                  color=embedColor
                                  ).set_thumbnail(url=executor.avatar.url)

        elif action == discord.AuditLogAction.sticker_create:
            logger.info("sticker_CREATE")
            # message = f"{executor.mention} created sticker {target.mention}."
            embed = discord.Embed(title=language["log_channel_title"],
                                  description=language["log_sticker-create"].format(executer=executor.mention),
                                  color=embedColor
                                  ).set_thumbnail(url=executor.avatar.url)

        elif action == discord.AuditLogAction.sticker_delete:
            logger.info("sticker_DELETE")
            # message = f"{executor.mention} deleted sticker {target.mention}."
            embed = discord.Embed(title=language["log_channel_title"],
                                  description=language["log_sticker-delete"].format(executer=executor.mention),
                                  color=embedColor
                                  ).set_thumbnail(url=executor.avatar.url)

        elif action == discord.AuditLogAction.guild_update:
            logger.info("guild_UPDATE")
            # message = f"{executor.mention} updated server settings."
            embed = discord.Embed(title=language["log_channel_title"],
                                  description=language["log_guild-update"].format(executer=executor.mention),
                                  color=embedColor
                                  ).set_thumbnail(url=executor.avatar.url)

        elif action == discord.AuditLogAction.integration_create:
            logger.info("interaction_CREATE")
            # message = f"{executor.mention} created integration {target.mention}."
            embed = discord.Embed(title=language["log_channel_title"],
                                  description=language["log_webhook-create"].format(executer=executor.mention,
                                                                                    integration=target.name),
                                  color=embedColor
                                  ).set_thumbnail(url=executor.avatar.url)

        elif action == discord.AuditLogAction.integration_delete:
            logger.info("interaction_DELETE")
            # message = f"{executor.mention} deleted integration {target.mention}."
            embed = discord.Embed(title=language["log_channel_title"],
                                  description=language["log_webhook-delete"].format(executer=executor.mention,
                                                                                    integration=entry.changes.before.name),
                                  color=embedColor
                                  ).set_thumbnail(url=executor.avatar.url)

        if channel is not None:
            await channel.send(embed=embed)
            logger.success("Log sent to " + channel.name)
        else:
            logger.info("Unable to send in channel( channel = none)")
            pass
    except Exception as e:
        logger.error(str(e))
    print("\n")
