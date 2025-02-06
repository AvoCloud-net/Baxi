import asyncio
import random
import string

import assets.data as datasys
import assets.translate as tr
import discord
import lang.de as de
from assets.views import (
    Ticket_Creation_Modal,
    Verify_Captcha_Modal,
    Verify_Password_Modal,
)
from discord import Interaction, ui


class BanConfirmView(ui.View):
    def __init__(self, user: discord.Member, moderator: discord.Member, reason: str):
        super().__init__(timeout=None)
        self.user = user
        self.moderator = moderator
        self.reason = reason

    @ui.button(
        label="✅", style=discord.ButtonStyle.danger, custom_id="ban_admin_confirm"
    )
    async def confirm_ban(self, interaction: Interaction, button: ui.Button):
        lang = datasys.load_lang(interaction.guild.id)
        try:
            await self.user.ban(
                reason=await tr.baxi_translate(
                    de.Utility.Ban.audit_reason.format(
                        moderator=self.user.name, reason=self.reason
                    ),
                    lang,
                )
            )

            embed = discord.Embed(
                title=await tr.baxi_translate(de.Utility.Ban.title, lang),
                description=f"{await tr.baxi_translate(de.Utility.Ban.success, lang)}",
                color=discord.Color.red(),
            )
            embed.add_field(
                name=await tr.baxi_translate(de.Utility.user, lang),
                value=self.user.mention,
                inline=False,
            )
            embed.add_field(
                name=await tr.baxi_translate(de.Utility.mod, lang),
                value=interaction.user.mention,
                inline=False,
            )
            embed.add_field(
                name=await tr.baxi_translate(de.Utility.reason, lang),
                value=self.reason,
                inline=False,
            )

            for item in self.children:
                item.disabled = True

            await interaction.response.edit_message(embed=embed, view=self)

        except discord.Forbidden:
            await interaction.response.send_message(
                await tr.baxi_translate(de.Utility.Ban.bot_missing_perms, lang),
                ephemeral=True,
            )
        except Exception as e:
            await interaction.response.send_message(
                await tr.baxi_translate(
                    de.Utility.Ban.error.format(error=str(e)), lang
                ),
                ephemeral=True,
            )

    @ui.button(label="❌", style=discord.ButtonStyle.gray, custom_id="ban_admin_cancel")
    async def cancel_ban(self, interaction: Interaction, button: ui.Button):
        lang = datasys.load_lang(interaction.guild.id)
        embed = discord.Embed(
            title=await tr.baxi_translate(de.Utility.Ban.title, lang),
            description=await tr.baxi_translate(de.Utility.Ban.abort, lang),
            color=discord.Color.yellow(),
        )

        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(embed=embed, view=self)


class KickConfirmView(ui.View):
    def __init__(self, user: discord.Member, moderator: discord.Member, reason: str):
        super().__init__(timeout=None)
        self.user = user
        self.moderator = moderator
        self.reason = reason

    @ui.button(
        label="✅", style=discord.ButtonStyle.danger, custom_id="kick_admin_confirm"
    )
    async def confirm_kick(self, interaction: Interaction, button: ui.Button):
        lang = datasys.load_lang(interaction.guild.id)
        try:
            await self.user.kick(
                reason=await tr.baxi_translate(
                    de.Utility.Kick.audit_reason.format(
                        moderator=self.user.name, reason=self.reason
                    ),
                    lang,
                )
            )

            embed = discord.Embed(
                title=await tr.baxi_translate(de.Utility.Kick.title, lang),
                description=f"{await tr.baxi_translate(de.Utility.Kick.success, lang)}",
                color=discord.Color.red(),
            )
            embed.add_field(
                name=await tr.baxi_translate(de.Utility.user, lang),
                value=self.user.mention,
                inline=False,
            )
            embed.add_field(
                name=await tr.baxi_translate(de.Utility.mod, lang),
                value=interaction.user.mention,
                inline=False,
            )
            embed.add_field(
                name=await tr.baxi_translate(de.Utility.reason, lang),
                value=self.reason,
                inline=False,
            )

            for item in self.children:
                item.disabled = True

            await interaction.response.edit_message(embed=embed, view=self)

        except discord.Forbidden:
            await interaction.response.send_message(
                await tr.baxi_translate(de.Utility.Kick.bot_missing_perms, lang),
                ephemeral=True,
            )
        except Exception as e:
            await interaction.response.send_message(
                await tr.baxi_translate(
                    de.Utility.Kick.error.format(error=str(e)), lang
                ),
                ephemeral=True,
            )

    @ui.button(
        label="❌", style=discord.ButtonStyle.gray, custom_id="kick_admin_cancel"
    )
    async def cancel_kick(self, interaction: Interaction, button: ui.Button):
        lang = datasys.load_lang(interaction.guild.id)
        embed = discord.Embed(
            title=await tr.baxi_translate(de.Utility.Kick.title, lang),
            description=await tr.baxi_translate(de.Utility.Kick.abort, lang),
            color=discord.Color.yellow(),
        )

        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(embed=embed, view=self)


class UbanConfirmView(ui.View):
    def __init__(self, user: discord.Member, moderator: discord.Member):
        super().__init__(timeout=None)
        self.user = user
        self.moderator = moderator

    @ui.button(
        label="✅", style=discord.ButtonStyle.danger, custom_id="unban_admin_confirm"
    )
    async def confirm_uban(self, interaction: Interaction, button: ui.Button):
        lang = datasys.load_lang(interaction.guild.id)
        try:
            await self.user.unban(
                reason=await tr.baxi_translate(
                    de.Utility.Unban.audit_reason.format(moderator=self.user.name), lang
                )
            )

            embed = discord.Embed(
                title=await tr.baxi_translate(de.Utility.Unban.title, lang),
                description=f"{await tr.baxi_translate(de.Utility.Unban.success, lang)}",
                color=discord.Color.red(),
            )
            embed.add_field(
                name=await tr.baxi_translate(de.Utility.user, lang),
                value=self.user.mention,
                inline=False,
            )
            embed.add_field(
                name=await tr.baxi_translate(de.Utility.mod, lang),
                value=interaction.user.mention,
                inline=False,
            )
            embed.add_field(
                name=await tr.baxi_translate(de.Utility.reason, lang),
                value=self.reason,
                inline=False,
            )

            for item in self.children:
                item.disabled = True

            await interaction.response.edit_message(embed=embed, view=self)

        except discord.Forbidden:
            await interaction.response.send_message(
                await tr.baxi_translate(de.Utility.Unban.bot_missing_perms, lang),
                ephemeral=True,
            )
        except Exception as e:
            await interaction.response.send_message(
                await tr.baxi_translate(
                    de.Utility.Unban.error.format(error=str(e)), lang
                ),
                ephemeral=True,
            )

    @ui.button(
        label="❌", style=discord.ButtonStyle.gray, custom_id="unban_admin_cancel"
    )
    async def cancel_unban(self, interaction: Interaction, button: ui.Button):
        lang = datasys.load_lang(interaction.guild.id)
        embed = discord.Embed(
            title=await tr.baxi_translate(de.Utility.Unban.title, lang),
            description=await tr.baxi_translate(de.Utility.Unban.abort, lang),
            color=discord.Color.yellow(),
        )

        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(embed=embed, view=self)


class ClearConfirmView(ui.View):
    def __init__(
        self, amount: int, moderator: discord.Member, channel: discord.TextChannel
    ):
        super().__init__(timeout=None)
        self.amount = amount
        self.moderator = moderator
        self.channel = channel

    @ui.button(
        label="✅", style=discord.ButtonStyle.danger, custom_id="clear_admin_confirm"
    )
    async def confirm_clear(self, interaction: Interaction, button: ui.Button):
        lang = datasys.load_lang(interaction.guild.id)
        try:
            await self.channel.purge(limit=self.amount + 1)

            embed = discord.Embed(
                title=await tr.baxi_translate(de.Utility.Clear.title, lang),
                description=f"{await tr.baxi_translate(de.Utility.Clear.success, lang)}",
                color=discord.Color.red(),
            )
            embed.add_field(
                name=await tr.baxi_translate(de.Utility.mod, lang),
                value=interaction.user.mention,
                inline=False,
            )
            embed.add_field(
                name=await tr.baxi_translate(de.Utility.amount, lang),
                value=self.amount,
                inline=False,
            )
            embed.add_field(
                name=await tr.baxi_translate(de.Utility.channel, lang),
                value=self.channel.name,
                inline=False,
            )

            for item in self.children:
                item.disabled = True

            await interaction.channel.send(embed=embed, view=self)

        except discord.Forbidden:
            await interaction.response.send_message(
                await tr.baxi_translate(de.Utility.Clear.bot_missing_perms, lang),
                ephemeral=True,
            )
        except Exception as e:
            await interaction.response.send_message(
                await tr.baxi_translate(
                    de.Utility.Clear.error.format(error=str(e)), lang
                ),
                ephemeral=True,
            )

    @ui.button(
        label="❌", style=discord.ButtonStyle.gray, custom_id="clear_admin_cancel"
    )
    async def cancel_clear(self, interaction: Interaction, button: ui.Button):
        lang = datasys.load_lang(interaction.guild.id)
        embed = discord.Embed(
            title=await tr.baxi_translate(de.Utility.Clear.title, lang),
            description=await tr.baxi_translate(de.Utility.Clear.abort, lang),
            color=discord.Color.yellow(),
        )

        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(embed=embed, view=self)


class VerifyView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(style=discord.ButtonStyle.success, emoji="✅", custom_id="verify_user")
    async def verify(self, interaction: Interaction, button: ui.Button):
        lang: str = datasys.load_lang(interaction.guild.id)
        verify_data: dict = datasys.load_data(interaction.guild.id, "verify")

        if verify_data.enabled:
            role: discord.Role = interaction.guild.get_role(verify_data.rid)
            user: discord.User = interaction.guild.get_member(interaction.user.id)
            option: int = verify_data.verify_option

            embed_success = discord.Embed(
                title=await tr.baxi_translate(de.Verify.title, lang),
                description=await tr.baxi_translate(
                    de.Verify.description_success, lang
                ),
                color=discord.Color.green(),
            )

            if option == 0:
                await user.add_roles(role)
                await interaction.response.send_message(
                    embed=embed_success, ephemeral=True
                )
            elif option == 1:
                characters = string.ascii_letters + string.digits
                captcha = "".join(random.choice(characters) for _ in range(5))
                await interaction.response.send_modal(
                    Verify_Captcha_Modal(
                        user=interaction.user,
                        captcha=captcha,
                        guild=interaction.guild,
                        role=role,
                    )
                )
            elif option == 2:
                await interaction.response.send_modal(
                    Verify_Password_Modal(
                        user=interaction.user.id,
                        captcha=verify_data.password,
                        guild=interaction.guild,
                        role=role,
                    )
                )
        else:
            embed = discord.Embed(
                title=await tr.baxi_translate(de.Verify.title, lang),
                description=await tr.baxi_translate(
                    de.Verify.description_not_enabeld, lang
                ),
                color=discord.Color.red(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)


class TicketView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(
        emoji="🎫", style=discord.ButtonStyle.primary, custom_id="ticket_user_create"
    )
    async def ticket(self, interaction: discord.Interaction, button: ui.Button):
        try:
            print("ticket_create_button")
            lang = datasys.load_lang(interaction.guild.id)
            print("Loaded language:", lang)
            tickets = datasys.load_data(interaction.guild.id, sys="open_tickets")
            print("Loaded tickets:", tickets)
            for ticket in tickets:
                print("print_loop_one")
                print("Current ticket:", ticket)
                if tickets[ticket]["user"] == interaction.user.id:
                    channel = await interaction.guild.fetch_channel(int(ticket))
                    embed = discord.Embed(
                        title=await tr.baxi_translate(de.Ticket.title, lang),
                        description=str(
                            await tr.baxi_translate(
                                de.Ticket.description_already_open, lang
                            )
                        ).format(channel=channel.mention),
                        color=discord.Color.red(),
                    )
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    return
            await interaction.response.send_modal(
                Ticket_Creation_Modal(user=interaction.user, guild=interaction.guild)
            )
        except Exception as e:
            print("An error occurred:", str(e))
            import traceback

            print(traceback.format_exc())


class TicketAdminButtons(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(
        emoji="🗑️", style=discord.ButtonStyle.danger, custom_id="ticket_admin_delete"
    )
    async def delete(self, interaction: discord.Interaction, button: ui.Button):
        lang = datasys.load_lang(interaction.guild.id)
        tickets = datasys.load_data(interaction.guild.id, sys="open_tickets")
        for ticket in tickets:
            print(ticket)
            if int(ticket) == int(interaction.channel.id):
                if int(tickets[ticket]["supporterid"]) == int(interaction.user.id):
                    await interaction.channel.delete(
                        reason=f"Ticket was closes by the supporter {interaction.user.name}"
                    )
                    del tickets[str(ticket)]
                    datasys.save_data(
                        interaction.guild.id, sys="open_tickets", data=tickets
                    )
                    return
                else:
                    embed = discord.Embed(
                        title=await tr.baxi_translate(de.Ticket.title, lang),
                        description=await tr.baxi_translate(
                            de.Ticket.description_no_permission_delete, lang
                        ),
                        color=discord.Color.red(),
                    )
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    return
            else:
                continue

    @ui.button(
        emoji="🖐️", style=discord.ButtonStyle.primary, custom_id="ticket_admin_claim"
    )
    async def claim(self, interaction: discord.Interaction, button: ui.Button):
        lang: str = datasys.load_lang(interaction.guild.id)
        tickets: dict = datasys.load_data(interaction.guild.id, sys="open_tickets")
        guild_settings: dict = datasys.load_data(interaction.guild.id, sys="ticket")
        for ticket in tickets:
            if int(ticket) == int(interaction.channel.id):
                if guild_settings.rid in [role.id for role in interaction.user.roles]:
                    tickets[ticket]["supporterid"] = interaction.user.id
                    datasys.save_data(
                        interaction.guild.id, sys="open_tickets", data=tickets
                    )
                    embed = discord.Embed(
                        title=await tr.baxi_translate(de.Ticket.title, lang),
                        description=str(
                            await tr.baxi_translate(de.Ticket.description_claimed, lang)
                        ).format(user=interaction.user.mention),
                        color=discord.Color.green(),
                    )
                    await interaction.response.send_message(embed=embed)
                else:
                    embed = discord.Embed(
                        title=await tr.baxi_translate(de.Ticket.title, lang),
                        description=await tr.baxi_translate(
                            de.Ticket.description_no_permission_claim, lang
                        ),
                        color=discord.Color.red(),
                    )
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    return
            else:
                continue
