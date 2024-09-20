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
import datetime

import discord
from reds_simple_logger import Logger

from assets.general.get_saves import *
from assets.general.routine_events import load_language_model
from main import *

logger = Logger()

config = configparser.ConfigParser()
config.read("config/runtime.conf")

embedColor = discord.Color.from_rgb(int(config["BOT"]["embed_color_red"]), int(config["BOT"]["embed_color_green"]),
                                    int(config["BOT"]["embed_color_blue"]))  # FF5733


async def other_button(interaction: discord.Interaction):
    try:
        language = load_language_model(str(interaction.guild.id))
        gbaned = load_data("json/banned_users.json")
        ticketdata = load_data("json/ticketdata.json")
        ticket_info = load_data("json/ticketinfo.json")

        matching_guilds = [v for k, v in ticket_info.items() if v.get('guild_id') == interaction.guild.id]
        if any(v.get('owner') == interaction.user.id for v in matching_guilds):
            await interaction.response.send_message(embed=discord.Embed(title=language["ticket_title"],
                                                                        description=language["ticket_already"],
                                                                        color=embedColor))
            return

        role = discord.utils.get(interaction.guild.roles, id=int(ticketdata[str(interaction.guild.id)]["roleid"]))
        channel = await interaction.guild.create_text_channel(
            name=f"🎫-{language['ticket_title_other']}-{interaction.user.name}")

        ticket_info[str(channel.id)] = {"claimed": None,
                                        "owner": interaction.user.id,
                                        "guild_id": interaction.guild.id
                                        }
        save_data("json/ticketinfo.json", ticket_info)

        await channel.set_permissions(interaction.guild.default_role, view_channel=False)
        await channel.set_permissions(interaction.user, view_channel=True, send_messages=True,
                                      read_message_history=True)
        await channel.set_permissions(role, view_channel=True, send_messages=True, read_message_history=True)

        if str(interaction.user.id) in gbaned:
            await channel.send(embed=user_ban_embed(interaction.user))  # noqa

        message = await channel.send("@here", embed=discord.Embed(
            title=language["ticket_menu_title"].format(server=interaction.guild.name),
            description=f"{language['ticket_welcome_message']}.\n**{language['ticket_welcome_user']}**{interaction.user.mention}\n**{language['ticket_welcome_reason']}** *{language['ticket_title_other']}*",
            color=discord.Color.blurple(),
            timestamp=datetime.datetime.now()),
                                     view=TicketChannelButtons())
        await message.pin()

        await interaction.response.send_message(embed=discord.Embed(title=language["ticket_title"],  # noqa
                                                                    description=f"{language['ticket_created']} {channel.mention}"),
                                                ephemeral=True)
        category = discord.utils.get(interaction.guild.categories,
                                     id=int(ticketdata[str(interaction.guild.id)]["categoryid"]))
        await channel.edit(category=category)
    except Exception as e:
        logger.error(str(e))
        await interaction.response.send_message(language["unknown_error"], ephemeral=True)  # noqa


async def report_button(interaction: discord.Interaction):
    try:
        language = load_language_model(str(interaction.guild.id))
        gbaned = load_data("json/banned_users.json")
        ticketdata = load_data("json/ticketdata.json")
        ticket_info = load_data("json/ticketinfo.json")

        matching_guilds = [v for k, v in ticket_info.items() if v.get('guild_id') == interaction.guild.id]
        if any(v.get('owner') == interaction.user.id for v in matching_guilds):
            # noinspection PyUnresolvedReferences
            await interaction.response.send_message(embed=discord.Embed(title=language["ticket_title"],
                                                                        description=language["ticket_already"],
                                                                        color=embedColor))
            return

        role = discord.utils.get(interaction.guild.roles, id=int(ticketdata[str(interaction.guild.id)]["roleid"]))
        channel = await interaction.guild.create_text_channel(
            name=f"🎫-{language['ticket_title_report']}-{interaction.user.name}")

        ticket_info[str(channel.id)] = {"claimed": None,
                                        "owner": interaction.user.id,
                                        "guild_id": interaction.guild.id
                                        }
        save_data("json/ticketinfo.json", ticket_info)
        await channel.set_permissions(interaction.guild.default_role, view_channel=False)
        await channel.set_permissions(interaction.user, view_channel=True, send_messages=True,
                                      read_message_history=True)
        await channel.set_permissions(role, view_channel=True, send_messages=True, read_message_history=True)

        if str(interaction.user.id) in gbaned:
            await channel.send(embed=user_ban_embed(interaction.user))  # noqa

        message = await channel.send("@here", embed=discord.Embed(
            title=language["ticket_menu_title"].format(server=interaction.guild.name),
            description=f"{language['ticket_welcome_message']}.\n**{language['ticket_welcome_user']}**{interaction.user.mention}\n**{language['ticket_welcome_reason']}** *{language['ticket_title_report']}*",
            color=discord.Color.red(),
            timestamp=datetime.datetime.now()),
                                     view=TicketChannelButtons())
        await message.pin()

        await interaction.response.send_message(embed=discord.Embed(title=language["ticket_title"],  # noqa
                                                                    description=f"{language['ticket_created']} {channel.mention}"),
                                                ephemeral=True)
        category = discord.utils.get(interaction.guild.categories,
                                     id=int(ticketdata[str(interaction.guild.id)]["categoryid"]))
        await channel.edit(category=category)
    except Exception as e:
        logger.error(str(e))
        await interaction.response.send_message(language["unknown_error"], ephemeral=True)  # noqa


async def question_button(interaction: discord.Interaction):
    try:
        language = load_language_model(str(interaction.guild.id))
        gbaned = load_data("json/banned_users.json")
        ticketdata = load_data("json/ticketdata.json")
        ticket_info = load_data("json/ticketinfo.json")

        matching_guilds = [v for k, v in ticket_info.items() if v.get('guild_id') == interaction.guild.id]
        if any(v.get('owner') == interaction.user.id for v in matching_guilds):
            await interaction.response.send_message(embed=discord.Embed(title=language["ticket_title"],
                                                                        description=language["ticket_already"],
                                                                        color=embedColor), ephemeral=True)
            return

        role = discord.utils.get(interaction.guild.roles, id=int(ticketdata[str(interaction.guild.id)]["roleid"]))
        channel = await interaction.guild.create_text_channel(
            name=f"🎫-{language['ticket_title_question']}-{interaction.user.name}")

        ticket_info[str(channel.id)] = {"claimed": None,
                                        "owner": interaction.user.id,
                                        "guild_id": interaction.guild.id
                                        }
        save_data("json/ticketinfo.json", ticket_info)

        await channel.set_permissions(interaction.guild.default_role, view_channel=False)
        await channel.set_permissions(interaction.user, view_channel=True, send_messages=True,
                                      read_message_history=True)
        await channel.set_permissions(role, view_channel=True, send_messages=True, read_message_history=True)

        if str(interaction.user.id) in gbaned:
            await channel.send(embed=user_ban_embed(interaction.user))  # noqa

        message = await channel.send("@here", embed=discord.Embed(
            title=language["ticket_menu_title"].format(server=interaction.guild.name),
            description=f"{language['ticket_welcome_message']}.\n**{language['ticket_welcome_user']}**{interaction.user.mention}\n**{language['ticket_welcome_reason']}** *{language['ticket_title_question']}*",
            color=discord.Color.green(),
            timestamp=datetime.datetime.now()),
                                     view=TicketChannelButtons())
        await message.pin()

        await interaction.response.send_message(embed=discord.Embed(title=language["ticket_title"],  # noqa
                                                                    description=f"{language['ticket_created']} {channel.mention}"),
                                                ephemeral=True)
        category = discord.utils.get(interaction.guild.categories,
                                     id=int(ticketdata[str(interaction.guild.id)]["categoryid"]))
        await channel.edit(category=category)
    except Exception as e:
        logger.error(str(e))
        await interaction.response.send_message(language["unknown_error"], ephemeral=True)  # noqa


async def ticket_claim(interaction: discord.Interaction):
    try:
        language = load_language_model(str(interaction.guild.id))
        ticketdata_system = load_data("json/ticketdata.json")
        ticketdata = load_data("json/ticketinfo.json")
        role = discord.utils.get(interaction.guild.roles,
                                 id=int(ticketdata_system[str(interaction.guild.id)]["roleid"]))
        if role in interaction.user.roles:
            if ticketdata[str(interaction.channel.id)]["claimed"] == str(interaction.user.id):
                await interaction.response.send_message(language["ticket_a_claimed"], ephemeral=True)  # noqa
            else:
                if ticketdata[str(interaction.channel.id)]["claimed"] != str(
                        interaction.user.id) and ticketdata[str(interaction.channel.id)]["claimed"] is not None:
                    member = await interaction.guild.fetch_member(
                        int(ticketdata[str(interaction.channel.id)]['claimed']))
                    embed = discord.Embed(title=language["ticket_title"],
                                          description=f"{language['ticket_claim_question']} {member.mention}",
                                          color=embedColor)

                    await interaction.response.send_message(embed=embed, ephemeral=True,  # noqa
                                                            view=TicketClaimQuestionButton())  # noqa

                else:
                    ticketdata[str(interaction.channel.id)]["claimed"] = str(interaction.user.id)
                    save_data("json/ticketinfo.json", ticketdata)
                    embed2 = discord.Embed(title=language["ticket_title"],
                                           description=f"{language['ticket_claim_success']}{interaction.user.mention}",
                                           color=embedColor, timestamp=datetime.datetime.now()).set_thumbnail(
                        url=interaction.user.avatar)
                    await interaction.response.send_message(embed=embed2)  # noqa
        else:
            await interaction.response.send_message(language["permission_denied"], ephemeral=True)  # noqa
    except Exception as e:  # noqa
        logger.error(str(e))
        try:
            await interaction.response.send_message(language["unknown_error"])  # noqa
            await interaction.channel.send(f"{e}")
        except:  # noqa
            await interaction.edit_original_response(content=language["unknown_error"])


class TicketClaimQuestionButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Yes", custom_id="yes_claim", style=discord.ButtonStyle.green,
                       emoji="<:check:1244724215274405979>")
    async def yes_claim_button(self, interaction: Interaction, Button: discord.ui.Button):  # noqa
        await claim_yes_ticket(interaction=interaction)


async def ticket_claim_close(interaction: discord.Interaction):
    language = load_language_model(str(interaction.guild.id))
    ticketdata = load_data("json/ticketdata.json")
    embed = discord.Embed(title=language["ticket_title"],
                          description=language["ticket_close_question"],
                          color=embedColor)
    role = discord.utils.get(interaction.guild.roles, id=int(ticketdata[str(interaction.guild.id)]["roleid"]))
    if role in interaction.user.roles:
        await interaction.response.send_message(embed=embed, view=TicketChannelDeleteButtons())  # noqa
    else:
        await interaction.response.send_message(language["permission_denied"], ephemeral=True)  # noqa


async def claim_yes_ticket(interaction: discord.Interaction):
    try:
        ticketdata = load_data("json/ticketinfo.json")
        language = load_language_model(str(interaction.guild.id))
        if ticketdata[str(interaction.channel.id)]["claimed"] == str(interaction.user.id):
            await interaction.response.send_message(language["ticket_a_claimed"], ephemeral=True)  # noqa
        else:
            ticketdata[str(interaction.channel.id)]["claimed"] = str(interaction.user.id)
            save_data("json/ticketinfo.json", ticketdata)
            embed2 = discord.Embed(title="Claimed",
                                   description=f"{language['ticket_claim_success']}{interaction.user.mention}",
                                   color=embedColor, timestamp=datetime.datetime.now()).set_thumbnail(
                url=interaction.user.avatar)
            await interaction.response.send_message(embed=embed2)  # noqa
    except Exception as e:
        logger.error(str(e))


async def delete_yes(interaction: discord.Interaction):
    language = load_language_model(str(interaction.guild.id))
    ticketdata = load_data("json/ticketinfo.json")
    try:
        del ticketdata[str(interaction.channel.id)]
    except Exception as e:
        logger.error(str(e))
    save_data("json/ticketinfo.json", ticketdata)
    await interaction.channel.delete()


async def delete_no(interaction: discord.Interaction):
    language = load_language_model(str(interaction.guild.id))
    embed = discord.Embed(
        title=language["ticket_deletion_canceled_title"],
        description=language["ticket_deletion_canceled"],
        color=embedColor
    )
    await interaction.response.send_message(embed=embed)  # noqa
    await interaction.message.edit(view=TicketChannelDeleteButtonsDisabled())
    return


class TicketChannelDeleteButtonsDisabled(discord.ui.View):  # noqa
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(label="Delete", custom_id="yes_ticket-disabled",
                                        style=discord.ButtonStyle.danger, emoji="<:trash:1244723837233397772>",
                                        disabled=True))
        self.add_item(discord.ui.Button(label="Cancel", custom_id="no_ticket-disabled",
                                        style=discord.ButtonStyle.gray, emoji="<:trash:1244723837233397772>",
                                        disabled=True))
