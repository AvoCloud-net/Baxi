import assets.data as datasys
import assets.translate as tr
import config.config as config
import discord
import lang.lang as lang

from discord import Interaction, ui
from discord.ext import commands


class Verify_Captcha_Modal(ui.Modal):
    def __init__(
        self, user: discord.User, captcha: str, guild: discord.Guild, role: discord.Role
    ):
        super().__init__(timeout=60, title="Verify Captcha")
        self.user: discord.User = user
        self.guild: discord.Guild = guild
        self.role: discord.Role = role
        self.captcha: str = captcha

        self.code_input = ui.TextInput(
            placeholder=self.captcha, min_length=5, max_length=5, label="Captcha Code"
        )
        self.add_item(self.code_input)

    async def callback(self, interaction: Interaction):
        lang = datasys.load_lang(self.guild.id)
        if self.code_input.value == self.captcha:
            embed = discord.Embed(
                title=await tr.baxi_translate(lang.Verify, lang),
                description=await tr.baxi_translate(
                    lang.Verify.description_success, lang
                ),
                color=discord.Color.green(),
            )
            await self.guild.get_member(self.user.id).add_roles(
                self.role, reason="Verified"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        else:
            embed = discord.Embed(
                title=await tr.baxi_translate(lang.Verify, lang),
                description=await tr.baxi_translate(
                    lang.Verify.Captcha.description_wrong_code, lang
                ),
                color=discord.Color.red(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)


class Verify_Password_Modal(ui.Modal):
    def __init__(
        self, user: discord.User, captcha: str, guild: discord.Guild, role: discord.Role
    ):
        super().__init__(timeout=60, title="Verify Password")
        self.user: discord.User = user
        self.guild: discord.Guild = guild
        self.role: discord.Role = role
        self.captcha: str = captcha

        self.code_input = ui.TextInput(
            placeholder=self.captcha,
            min_length=1,
            max_length=int(len(captcha)) + 1,
            label="Captcha Password",
        )
        self.add_item(self.code_input)

    async def callback(self, interaction: Interaction):
        lang = datasys.load_lang(self.guild.id)
        if self.code_input.value == self.captcha:
            embed = discord.Embed(
                title=await tr.baxi_translate(lang.Verify, lang),
                description=await tr.baxi_translate(
                    lang.Verify.description_success, lang
                ),
                color=discord.Color.green(),
            )
            await self.guild.get_member(self.user.id).add_roles(
                self.role, reason="Verified"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        else:
            embed = discord.Embed(
                title=await tr.baxi_translate(lang.Verify, lang),
                description=await tr.baxi_translate(
                    lang.Verify.Password.description_wrong_password, lang
                ),
                color=discord.Color.red(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

class Ticket_Creation_Modal(ui.Modal):
    def __init__(self, user: discord.User, guild: discord.Guild):
        super().__init__(timeout=60, title="Create Ticket")
        self.user: discord.User = user
        self.guild: discord.Guild = guild


        self.ticket_name = ui.TextInput(
            placeholder="Place the name of your ticket request here.", min_length=1, max_length=20, label="Ticket Title"
        )
        self.add_item(self.ticket_name)

        self.ticket_description = ui.TextInput(
            style=discord.TextStyle.paragraph,
            placeholder="Ticket Description",
            min_length=1,
            max_length=500,
            label="Ticket Description",
        )
        self.add_item(self.ticket_description)

    async def on_submit(self, interaction: Interaction):
        try:
            from assets.buttons import TicketAdminButtons
            lang = datasys.load_lang(self.guild.id)

            
            guild_data = datasys.load_data(self.guild.id, sys="ticket")
            tickets = datasys.load_data(self.guild.id, sys="open_tickets")
            category: discord.CategoryChannel = await self.guild.fetch_channel(guild_data.catid)
            role = self.guild.get_role(guild_data.rid)

            perms_overwrites = {
                self.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                self.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True),
                role: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True, manage_messages=True)
            }

            channel: discord.TextChannel = await self.guild.create_text_channel(name=str(await tr.baxi_translate(lang.Ticket.channel_name, lang)).format(user=self.user.name),
                                                                                category=category,
                                                                                overwrites=perms_overwrites)
            embed = discord.Embed(title = await tr.baxi_translate(lang.Ticket.title, lang), description = str(await tr.baxi_translate(lang.Ticket.description_creation_successfull, lang)).format(channel = channel.mention) , color=config.Discord.color)
            await interaction.followup.send(embed=embed, ephemeral=True)
            embed = discord.Embed(title=self.ticket_name.value, description=self.ticket_description.value, color=config.Discord.color)
            await channel.send(embed=embed, view=TicketAdminButtons())
            tickets[str(channel.id)] = {"user": self.user.id, "supporterid": None}
            datasys.save_data(self.guild.id, "open_tickets", tickets)

        except Exception as e:
            print(str(e))