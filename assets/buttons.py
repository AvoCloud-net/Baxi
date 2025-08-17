import random
import string
import os

import assets.data as datasys
import discord
from assets.views import (
    Ticket_Creation_Modal,
    Verify_Captcha_Modal,
    Verify_Password_Modal,
)
from discord import Interaction, ui
import asyncio
import config.config as config
from typing import cast, Optional, Union


class BanConfirmView(ui.View):
    def __init__(self, user: discord.Member, moderator: discord.abc.User, reason: str):
        super().__init__(timeout=None)
        self.user = user
        self.moderator = moderator
        self.reason = reason

    @ui.button(
        label="✅", style=discord.ButtonStyle.danger, custom_id="ban_admin_confirm"
    )
    async def confirm_ban(self, interaction: Interaction, button: ui.Button):
        if interaction.guild is None:
            lang = datasys.load_lang_file(1001)
            return await interaction.response.send_message(
                embed=discord.Embed(
                    title=lang["commands"]["guild_only"],
                    color=config.Discord.warn_color,
                )
            )
        lang = datasys.load_lang_file(interaction.guild.id)
        try:
            await self.user.ban(
                reason=str(lang["commands"]["admin"]["ban"]["audit_reason"]).format(
                    moderator=self.user.name, reason=self.reason
                )
            )

            embed = discord.Embed(
                title=lang["commands"]["admin"]["ban"]["title"],
                description=lang["commands"]["admin"]["ban"]["success"],
                color=discord.Color.red(),
            )
            embed.add_field(
                name=lang["commands"]["admin"]["user"],
                value=self.user.mention,
                inline=False,
            )
            embed.add_field(
                name=lang["commands"]["admin"]["mod"],
                value=interaction.user.mention,
                inline=False,
            )
            embed.add_field(
                name=lang["commands"]["admin"]["reason"],
                value=self.reason,
                inline=False,
            )

            for item in self.children:
                button = cast(discord.ui.Button, item)
                button.disabled = True

            await interaction.response.edit_message(embed=embed, view=self)

        except discord.Forbidden:
            await interaction.response.send_message(
                lang["commands"]["admin"]["ban"]["bot_missing_perms"],
                ephemeral=True,
            )
        except Exception as e:
            await interaction.response.send_message(
                str(lang["commands"]["admin"]["ban"]["error"]).format(error=str(e)),
                ephemeral=True,
            )

    @ui.button(label="❌", style=discord.ButtonStyle.gray, custom_id="ban_admin_cancel")
    async def cancel_ban(self, interaction: Interaction, button: ui.Button):
        if interaction.guild is None:
            lang = datasys.load_lang_file(1001)
            return await interaction.response.send_message(
                embed=discord.Embed(
                    title=lang["commands"]["guild_only"],
                    color=config.Discord.warn_color,
                )
            )
        lang = datasys.load_lang_file(interaction.guild.id)
        embed = discord.Embed(
            title=lang["commands"]["admin"]["ban"]["title"],
            description=lang["commands"]["admin"]["ban"]["abort"],
            color=discord.Color.yellow(),
        )

        for item in self.children:
            button = cast(discord.ui.Button, item)
            button.disabled = True

        await interaction.response.edit_message(embed=embed, view=self)


class KickConfirmView(ui.View):
    def __init__(self, user: discord.Member, moderator: discord.abc.User, reason: str):
        super().__init__(timeout=None)
        self.user = user
        self.moderator = moderator
        self.reason = reason

    @ui.button(
        label="✅", style=discord.ButtonStyle.danger, custom_id="kick_admin_confirm"
    )
    async def confirm_kick(self, interaction: Interaction, button: ui.Button):
        if interaction.guild is None:
            lang = datasys.load_lang_file(1001)
            return await interaction.response.send_message(
                embed=discord.Embed(
                    title=lang["commands"]["guild_only"],
                    color=config.Discord.warn_color,
                )
            )
        lang = datasys.load_lang_file(interaction.guild.id)
        try:
            await self.user.kick(
                reason=str(lang["commands"]["admin"]["kick"]["audit_reason"]).format(
                    moderator=self.user.name, reason=self.reason
                )
            )

            embed = discord.Embed(
                title=lang["commands"]["admin"]["kick"]["title"],
                description=lang["commands"]["admin"]["kick"]["success"],
                color=discord.Color.red(),
            )
            embed.add_field(
                name=lang["commands"]["admin"]["user"],
                value=self.user.mention,
                inline=False,
            )
            embed.add_field(
                name=lang["commands"]["admin"]["mod"],
                value=interaction.user.mention,
                inline=False,
            )
            embed.add_field(
                name=lang["commands"]["admin"]["reason"],
                value=self.reason,
                inline=False,
            )

            for item in self.children:
                button = cast(discord.ui.Button, item)
                button.disabled = True

            await interaction.response.edit_message(embed=embed, view=self)

        except discord.Forbidden:
            await interaction.response.send_message(
                lang["commands"]["admin"]["kick"]["bot_missing_perms"],
                ephemeral=True,
            )
        except Exception as e:
            await interaction.response.send_message(
                str(lang["commands"]["admin"]["kick"]["error"]).format(error=str(e)),
                ephemeral=True,
            )

    @ui.button(
        label="❌", style=discord.ButtonStyle.gray, custom_id="kick_admin_cancel"
    )
    async def cancel_kick(self, interaction: Interaction, button: ui.Button):
        if interaction.guild is None:
            lang = datasys.load_lang_file(1001)
            return await interaction.response.send_message(
                embed=discord.Embed(
                    title=lang["commands"]["guild_only"],
                    color=config.Discord.warn_color,
                )
            )
        lang = datasys.load_lang_file(interaction.guild.id)
        embed = discord.Embed(
            title=lang["commands"]["admin"]["kick"]["title"],
            description=lang["commands"]["admin"]["kick"]["abort"],
            color=discord.Color.yellow(),
        )

        for item in self.children:
            button = cast(discord.ui.Button, item)
            button.disabled = True

        await interaction.response.edit_message(embed=embed, view=self)


class UbanConfirmView(ui.View):
    def __init__(
        self,
        user: Union[discord.Member, discord.User],
        moderator: discord.abc.User,
        reason: Optional[str] = "N/A",
    ):
        super().__init__(timeout=None)
        self.user = user
        self.moderator = moderator
        self.reason = reason

    @ui.button(
        label="✅", style=discord.ButtonStyle.danger, custom_id="unban_admin_confirm"
    )
    async def confirm_uban(self, interaction: Interaction, button: ui.Button):
        if interaction.guild is None:
            lang = datasys.load_lang_file(1001)
            return await interaction.response.send_message(
                embed=discord.Embed(
                    title=lang["commands"]["guild_only"],
                    color=config.Discord.warn_color,
                )
            )
        lang = datasys.load_lang_file(interaction.guild.id)
        try:
            await interaction.guild.unban(
                self.user,
                reason=str(lang["commands"]["admin"]["unban"]["audit_reason"]).format(
                    moderator=interaction.user.name  # vermutlich Moderator, nicht User!
                ),
            )

            embed = discord.Embed(
                title=lang["commands"]["admin"]["unban"]["title"],
                description=lang["commands"]["admin"]["unban"]["success"],
                color=discord.Color.red(),
            )
            embed.add_field(
                name=lang["commands"]["admin"]["user"],
                value=self.user.mention,
                inline=False,
            )
            embed.add_field(
                name=lang["commands"]["admin"]["mod"],
                value=interaction.user.mention,
                inline=False,
            )
            embed.add_field(
                name=lang["commands"]["admin"]["reason"],
                value=self.reason,
                inline=False,
            )

            for item in self.children:
                button = cast(discord.ui.Button, item)
                button.disabled = True

            await interaction.response.edit_message(embed=embed, view=self)

        except discord.Forbidden:
            await interaction.response.send_message(
                lang["commands"]["admin"]["unban"]["bot_missing_perms"],
                ephemeral=True,
            )
        except Exception as e:
            await interaction.response.send_message(
                str(lang["commands"]["admin"]["unban"]["error"]).format(error=str(e)),
                ephemeral=True,
            )

    @ui.button(
        label="❌", style=discord.ButtonStyle.gray, custom_id="unban_admin_cancel"
    )
    async def cancel_unban(self, interaction: Interaction, button: ui.Button):
        if interaction.guild is None:
            lang = datasys.load_lang_file(1001)
            return await interaction.response.send_message(
                embed=discord.Embed(
                    title=lang["commands"]["guild_only"],
                    color=config.Discord.warn_color,
                )
            )
        lang = datasys.load_lang_file(interaction.guild.id)
        embed = discord.Embed(
            title=lang["commands"]["admin"]["unban"]["title"],
            description=lang["commands"]["admin"]["unban"]["abort"],
            color=discord.Color.yellow(),
        )

        for item in self.children:
            button = cast(discord.ui.Button, item)
            button.disabled = True

        await interaction.response.edit_message(embed=embed, view=self)


class ClearConfirmView(ui.View):
    def __init__(
        self,
        amount: int,
        moderator: discord.abc.User,
        channel: discord.abc.GuildChannel,
    ):
        super().__init__(timeout=None)
        self.amount = amount
        self.moderator = moderator
        self.channel = channel

    @ui.button(
        label="✅", style=discord.ButtonStyle.danger, custom_id="clear_admin_confirm"
    )
    async def confirm_clear(self, interaction: Interaction, button: ui.Button):
        if interaction.guild is None:
            lang = datasys.load_lang_file(1001)
            return await interaction.response.send_message(
                embed=discord.Embed(
                    title=lang["commands"]["guild_only"],
                    color=config.Discord.warn_color,
                )
            )
        lang = datasys.load_lang_file(interaction.guild.id)
        try:
            text_channel = cast(discord.TextChannel, self.channel)
            await text_channel.purge(limit=self.amount + 1)

            embed = discord.Embed(
                title=lang["commands"]["admin"]["clear"]["title"],
                description=lang["commands"]["admin"]["clear"]["success"],
                color=discord.Color.red(),
            )
            embed.add_field(
                name=lang["commands"]["admin"]["user"],
                value=interaction.user.mention,
                inline=False,
            )
            embed.add_field(
                name=lang["commands"]["admin"]["amount"],
                value=self.amount,
                inline=False,
            )
            embed.add_field(
                name=lang["commands"]["admin"]["channel"],
                value=self.channel.name,
                inline=False,
            )

            for item in self.children:
                button = cast(discord.ui.Button, item)
                button.disabled = True

            if isinstance(
                interaction.channel, (discord.TextChannel, discord.DMChannel)
            ):
                await interaction.channel.send(embed=embed, view=self)
            else:
                await interaction.response.send_message(embed=embed, view=self)

        except discord.Forbidden:
            await interaction.response.send_message(
                lang["commands"]["admin"]["clear"]["bot_missing_perms"],
                ephemeral=True,
            )
        except Exception as e:
            await interaction.response.send_message(
                str(lang["commands"]["admin"]["clear"]["error"]).format(error=str(e)),
                ephemeral=True,
            )

    @ui.button(
        label="❌", style=discord.ButtonStyle.gray, custom_id="clear_admin_cancel"
    )
    async def cancel_clear(self, interaction: Interaction, button: ui.Button):
        if interaction.guild is None:
            lang = datasys.load_lang_file(1001)
            return await interaction.response.send_message(
                embed=discord.Embed(
                    title=lang["commands"]["guild_only"],
                    color=config.Discord.warn_color,
                )
            )
        lang = datasys.load_lang_file(interaction.guild.id)
        embed = discord.Embed(
            title=lang["commands"]["admin"]["clear"]["title"],
            description=lang["commands"]["admin"]["clear"]["abort"],
            color=discord.Color.yellow(),
        )

        for item in self.children:
            button = cast(discord.ui.Button, item)
            button.disabled = True

        await interaction.response.edit_message(embed=embed, view=self)


class VerifyView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(style=discord.ButtonStyle.success, emoji="✅", custom_id="verify_user")
    async def verify(self, interaction: Interaction, button: ui.Button):
        if interaction.guild is None:
            lang = datasys.load_lang_file(1001)
            return await interaction.response.send_message(
                embed=discord.Embed(
                    title=lang["commands"]["guild_only"],
                    color=config.Discord.warn_color,
                )
            )
        lang = datasys.load_lang_file(interaction.guild.id)
        verify_data: dict = dict(datasys.load_data(interaction.guild.id, "verify"))

        if verify_data.get("enabled", False):
            role: Optional[discord.Role] = interaction.guild.get_role(
                verify_data.get("rid", 0)
            )
            if role is None:
                await interaction.response.send_message(
                    "Role not found.", ephemeral=True
                )
                return
            user: Optional[discord.Member] = interaction.guild.get_member(
                interaction.user.id
            )
            if user is None:
                await interaction.response.send_message(
                    "User not found in guild.", ephemeral=True
                )
                return

            option: int = verify_data.get("verify_option", 0)

            embed_success = discord.Embed(
                title=lang["systems"]["verify"]["title"],
                description=lang["systems"]["verify"]["description_success"],
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
                        user=interaction.user,
                        captcha=verify_data.get("password", "password"),
                        guild=interaction.guild,
                        role=role,
                    )
                )
        else:
            embed = discord.Embed(
                title=lang["systems"]["verify"]["title"],
                description=lang["systems"]["verify"]["description_not_enabled"],
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
            if interaction.guild is None:
                lang = datasys.load_lang_file(1001)
                return await interaction.response.send_message(
                    embed=discord.Embed(
                        title=lang["commands"]["guild_only"],
                        color=config.Discord.warn_color,
                    )
                )
            lang = datasys.load_lang_file(interaction.guild.id)
            settings: dict = dict(datasys.load_data(interaction.guild.id, sys="ticket"))
            tickets: dict = dict(settings.get("open_tickets", {}))
            for ticket in list(tickets):
                if dict(tickets.get(ticket, {})).get("user") == interaction.user.id:

                    try:
                        channel = await interaction.guild.fetch_channel(int(ticket))
                        embed = discord.Embed(
                            title=lang["systems"]["ticket"]["title"],
                            description=str(
                                lang["systems"]["ticket"]["description_already_open"]
                            ).format(channel=channel.mention),
                            color=discord.Color.red(),
                        )
                        await interaction.response.send_message(
                            embed=embed, ephemeral=True
                        )
                        return
                    except discord.NotFound:
                        del tickets[ticket]
                        datasys.save_data(interaction.guild.id, "ticket", settings)

            await interaction.response.send_modal(
                Ticket_Creation_Modal(user=interaction.user, guild=interaction.guild)
            )
        except Exception as e:
            print(f"error in ticket button {e}")


class TicketAdminButtons(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(
        emoji="🗑️", style=discord.ButtonStyle.danger, custom_id="ticket_admin_delete"
    )
    async def delete(self, interaction: discord.Interaction, button: ui.Button):
        try:
            if interaction.guild is None:
                lang = datasys.load_lang_file(1001)
                return await interaction.response.send_message(
                    embed=discord.Embed(
                        title=lang["commands"]["guild_only"],
                        color=config.Discord.warn_color,
                    ),
                    ephemeral=True,
                )

            if not isinstance(interaction.channel, discord.TextChannel):
                await interaction.response.send_message(
                    "This command can only be used in a text channel.",
                    ephemeral=True,
                )
                return

            transcript_id: str = os.urandom(8).hex()

            lang = datasys.load_lang_file(interaction.guild.id)
            guild_settings: dict = dict(
                datasys.load_data(interaction.guild.id, sys="ticket")
            )
            tickets = guild_settings.get("open_tickets", {})
            transcripts: dict = dict(datasys.load_data(1001, "transcripts"))

            if not isinstance(tickets, dict):
                tickets = {}

            channel_id = str(interaction.channel.id)
            if channel_id in tickets:
                ticket_data = tickets[channel_id]

                member = interaction.guild.get_member(interaction.user.id)
                if member is None:
                    await interaction.response.send_message(
                        "Error: Member not found.", ephemeral=True
                    )
                    return

                required_role_id = guild_settings.get("role", 0)
                if ticket_data.get("supporterid") == interaction.user.id or int(
                    required_role_id
                ) in [role.id for role in member.roles]:
                    await interaction.response.send_message(
                        embed=discord.Embed(
                            title=lang["systems"]["ticket"]["title"],
                            description=lang["systems"]["ticket"]["wait_delete_confirm"],
                            color=config.Discord.danger_color
                        )
                    )

                    if interaction.channel.id is None:
                        return

                    def check(m):
                        return (m.channel.id == interaction.channel.id and  # pyright: ignore[reportOptionalMemberAccess]
                                m.author.id == interaction.user.id)

                    try:
                        response = await interaction.client.wait_for(
                            "message",
                            check=check,
                            timeout=60.0 
                        )
                        
                        if response.content.lower() == "confirm":
                            await interaction.channel.delete(
                                reason=f"Ticket closed by {interaction.user.name}"
                            )
                            
                            transcript_data: dict = {
                                "guild": str(interaction.guild.id),
                                "id": str(transcript_id),
                                "title": ticket_data["title"],
                                "msg": ticket_data["message"],
                                "transcript": ticket_data["transcript"],
                            }

                            transcript_channel = await interaction.guild.fetch_channel(
                                int(guild_settings.get("channel", 0))
                            )
                            link = f"https://{config.Web.url}/?ticket_transcript={transcript_id}"

                            embed = discord.Embed(
                                title=lang["systems"]["ticket"]["title"],
                                description=f"{lang['systems']['ticket']['link']} {link}",
                            )
                            
                            if transcript_channel is not None and isinstance(
                                transcript_channel, discord.TextChannel
                            ):
                                await transcript_channel.send(embed=embed)

                            if member.dm_channel is not None:
                                await member.dm_channel.send(embed=embed)

                            transcripts[str(transcript_id)] = transcript_data
                            datasys.save_data(1001, "transcripts", transcripts)
                            del tickets[channel_id]
                            datasys.save_data(interaction.guild.id, "open_tickets", tickets)
                        else:
                            await interaction.channel.send("Ticket deletion cancelled.")
                            
                    except asyncio.TimeoutError:
                        await interaction.channel.send("Timed out waiting for confirmation.")
                        
                else:
                    await interaction.response.send_message(
                        embed=discord.Embed(
                            title=lang["systems"]["ticket"]["title"],
                            description=lang["systems"]["ticket"][
                                "description_no_permission_delete"
                            ],
                            color=discord.Color.red(),
                        ),
                        ephemeral=True,
                    )
            else:
                await interaction.response.send_message(
                    "This channel is not a valid ticket.",
                    ephemeral=True,
                )
        except Exception as e:
            print(f"error in ticket delete: {e}")

    @ui.button(
        emoji="🖐️", style=discord.ButtonStyle.primary, custom_id="ticket_admin_claim"
    )
    async def claim(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.guild is None:
            lang = datasys.load_lang_file(1001)
            return await interaction.response.send_message(
                embed=discord.Embed(
                    title=lang["commands"]["guild_only"],
                    color=config.Discord.warn_color,
                ),
                ephemeral=True,
            )

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message(
                "This command can only be used in a text channel.",
                ephemeral=True,
            )
            return

        lang = datasys.load_lang_file(interaction.guild.id)
        guild_settings: dict = dict(
            datasys.load_data(interaction.guild.id, sys="ticket")
        )
        tickets = guild_settings.get("open_tickets", {})

        if not isinstance(tickets, dict):
            tickets = {}
        if not isinstance(guild_settings, dict) or "role" not in guild_settings:
            await interaction.response.send_message(
                "Error: Ticket system not properly configured.",
                ephemeral=True,
            )
            return

        channel_id = str(interaction.channel.id)
        if channel_id in tickets:
            member = interaction.guild.get_member(interaction.user.id)
            if member is None:
                await interaction.response.send_message(
                    "Error: Member not found.",
                    ephemeral=True,
                )
                return

            required_role_id = guild_settings.get("role", 0)
            if int(required_role_id) in [role.id for role in member.roles]:
                tickets[channel_id]["supporterid"] = interaction.user.id
                datasys.save_data(interaction.guild.id, "tickets", guild_settings)

                await interaction.response.send_message(
                    embed=discord.Embed(
                        title=lang["systems"]["ticket"]["title"],
                        description=str(
                            lang["systems"]["ticket"]["description_claimed"]
                        ).format(user=interaction.user.mention),
                        color=discord.Color.green(),
                    )
                )
            else:
                print([role.id for role in member.roles])
                await interaction.response.send_message(
                    embed=discord.Embed(
                        title=lang["systems"]["ticket"]["title"],
                        description=lang["systems"]["ticket"][
                            "description_no_permission_claim"
                        ],
                        color=discord.Color.red(),
                    ),
                    ephemeral=True,
                )
        else:
            await interaction.response.send_message(
                "This channel is not a valid ticket.",
                ephemeral=True,
            )
