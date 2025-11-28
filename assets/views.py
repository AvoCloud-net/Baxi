import assets.data as datasys
import config.config as config
import discord
import datetime

from discord import Interaction, ui


class Verify_Captcha_Modal(ui.Modal):
    def __init__(
        self,
        user: discord.abc.User,
        captcha: str,
        guild: discord.Guild,
        role: discord.Role,
    ):
        super().__init__(timeout=60, title="Verify Captcha")
        self.user: discord.abc.User = user
        self.guild: discord.Guild = guild
        self.role: discord.Role = role
        self.captcha: str = captcha

        self.code_input = ui.TextInput(
            placeholder=self.captcha, min_length=5, max_length=5, label="Captcha Code"
        )
        self.add_item(self.code_input)

    async def callback(self, interaction: Interaction):
        lang = datasys.load_lang_file(self.guild.id)
        member = await self.guild.fetch_member(int(self.user.id))
        if member is None:
            await interaction.response.send_message(
                "Du bist kein Mitglied dieses Servers.", ephemeral=True
            )
            return

        if self.code_input.value == self.captcha:
            embed = discord.Embed(
                title=lang["systems"]["verify"]["title"],
                description=lang["systems"]["verify"]["description_success"],
                color=discord.Color.green(),
            )
            await member.add_roles(self.role, reason="Verified")
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            embed = discord.Embed(
                title=lang["systems"]["verify"]["title"],
                description=lang["systems"]["verify"]["password"][
                    "description_wrong_password"
                ],
                color=discord.Color.red(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)


class Verify_Password_Modal(ui.Modal):
    def __init__(
        self,
        user: discord.abc.User,
        captcha: str,
        guild: discord.Guild,
        role: discord.Role,
    ):
        super().__init__(timeout=60, title="Verify Password")
        self.user: discord.abc.User = user
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
        lang = datasys.load_lang_file(self.guild.id)
        member = await self.guild.fetch_member(int(self.user.id))
        if member is None:
            await interaction.response.send_message(
                "Du bist kein Mitglied dieses Servers.", ephemeral=True
            )
            return

        if self.code_input.value == self.captcha:
            embed = discord.Embed(
                title=lang["systems"]["verify"]["title"],
                description=lang["systems"]["verify"]["description_success"],
                color=discord.Color.green(),
            )
            await member.add_roles(self.role, reason="Verified")
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            embed = discord.Embed(
                title=lang["systems"]["verify"]["title"],
                description=lang["systems"]["verify"]["password"][
                    "description_wrong_password"
                ],
                color=discord.Color.red(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)


class Ticket_Creation_Modal(ui.Modal):
    def __init__(self, user: discord.abc.User, guild: discord.Guild):
        super().__init__(timeout=60, title="Create Ticket")
        self.user: discord.abc.User = user
        self.guild: discord.Guild = guild

        self.ticket_name = ui.TextInput(
            placeholder="Place the name of your ticket request here.",
            min_length=1,
            max_length=20,
            label="Ticket Title",
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

            lang = datasys.load_lang_file(self.guild.id)
            tickets: dict = dict(datasys.load_data(self.guild.id, sys="open_tickets"))
            guild_data = datasys.load_data(self.guild.id, sys="ticket")
            if not isinstance(guild_data, dict):
                guild_data = {"enabled": True, "catid": None, "role": None}

            if "catid" not in guild_data or not guild_data["catid"]:
                await interaction.response.send_message(
                    lang["systems"]["ticket"]["errors"]["no_category"], ephemeral=True
                )
                return

            try:
                category = await self.guild.fetch_channel(int(guild_data["catid"]))
                if not isinstance(category, discord.CategoryChannel):
                    await interaction.response.send_message(
                        lang["systems"]["ticket"]["errors"]["invalid_category"],
                        ephemeral=True,
                    )
                    return
            except (
                ValueError,
                discord.NotFound,
                discord.Forbidden,
                discord.HTTPException,
            ):
                await interaction.response.send_message(
                    lang["systems"]["ticket"]["errors"]["category_access"],
                    ephemeral=True,
                )
                return

            if "role" not in guild_data or not guild_data["role"]:
                await interaction.response.send_message(
                    lang["systems"]["ticket"]["errors"]["no_role"], ephemeral=True
                )
                return

            try:
                role = await self.guild.fetch_role(int(guild_data["role"]))
            except (
                ValueError,
                discord.NotFound,
                discord.Forbidden,
                discord.HTTPException,
            ):
                await interaction.response.send_message(
                    lang["systems"]["ticket"]["errors"]["role_not_found"],
                    ephemeral=True,
                )
                return

            perms_overwrites = {
                self.guild.default_role: discord.PermissionOverwrite(
                    view_channel=False
                ),
                self.user: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    attach_files=True,
                    manage_messages=True,
                    manage_channels=True,
                    manage_permissions=True,
                ),
                role: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    attach_files=True,
                    manage_messages=True,
                ),
            }

            channel_name_template: str = "ticket-{user}"
            channel_name = channel_name_template.format(user=self.user.name)
            channel = await self.guild.create_text_channel(
                name=channel_name, category=category, overwrites=perms_overwrites
            )

            tickets[str(channel.id)] = {
                "user": self.user.id,
                "supporterid": None,
                "created_at": int(datetime.datetime.now().timestamp()),
                "status": "open",
                "title": f"{self.ticket_name.value}",
                "message": f"{self.ticket_description.value}",
                "transcript": [],
            }
            print(tickets)
            datasys.save_data(self.guild.id, "open_tickets", tickets)

            success_embed = discord.Embed(
                title=lang["systems"]["ticket"]["title"],
                description=lang["systems"]["ticket"][
                    "description_creation_successfull"
                ].format(channel=channel.mention),
                color=config.Discord.color,
            )
            await interaction.response.send_message(embed=success_embed, ephemeral=True)

            ticket_embed = discord.Embed(
                title=self.ticket_name.value,
                description=self.ticket_description.value,
                color=config.Discord.color,
            )

            await channel.send(
                content=f"{self.user.mention} {role.mention}",
                embed=ticket_embed,
                view=TicketAdminButtons(),
            )

        except Exception as e:
            print(f"Error in Ticket Creation Modal: {e}")
