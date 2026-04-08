import random
import re
import string
import os

import assets.data as datasys
import assets.trust as sentinel
import discord
from assets.views import (
    Verify_Captcha_Modal,
    Verify_Password_Modal,
)
from discord import Interaction, ui
import asyncio
import config.config as config
from typing import cast, Optional, Union
import datetime
from zoneinfo import ZoneInfo

_VIENNA = ZoneInfo("Europe/Vienna")


class BanConfirmView(ui.View):
    def __init__(self, user: discord.Member, moderator: discord.abc.User, reason: str, duration: Optional[datetime.timedelta] = None):
        super().__init__(timeout=None)
        self.user = user
        self.moderator = moderator
        self.reason = reason
        self.duration = duration

    @ui.button(
        label="✅", style=discord.ButtonStyle.danger, custom_id="ban_admin_confirm"
    )
    async def confirm_ban(self, interaction: Interaction, button: ui.Button):
        if interaction.guild is None:
            lang = datasys.load_lang_file(1001)
            return await interaction.response.send_message(
                embed=discord.Embed(
                    title="ERROR // SERVER ONLY",
                    color=config.Discord.warn_color,
                )
            )
        lang = datasys.load_lang_file(interaction.guild.id)
        try:
            duration_str = datasys.format_duration(self.duration) if self.duration else "Permanent"
            expires_at = datetime.datetime.utcnow() + self.duration if self.duration else None

            # DM user before ban
            try:
                dm_embed = discord.Embed(
                    title=f"ACTION // BAN // {interaction.guild.name}",
                    color=config.Discord.danger_color,
                )
                dm_embed.add_field(name="Reason", value=self.reason, inline=False)
                dm_embed.add_field(name="Duration", value=duration_str, inline=False)
                dm_embed.add_field(name="Moderator", value=str(interaction.user), inline=False)
                if expires_at:
                    dm_embed.add_field(name="Expires", value=f"<t:{int(expires_at.timestamp())}:F>", inline=False)
                dm_embed.set_footer(text="Baxi · avocloud.net")
                await self.user.send(embed=dm_embed)
            except (discord.Forbidden, discord.HTTPException):
                pass

            await self.user.ban(
                reason=str(lang["commands"]["admin"]["ban"]["audit_reason"]).format(
                    moderator=self.user.name, reason=self.reason
                )
            )

            # Log mod event for BaxiInsights
            try:
                assert interaction.guild is not None
                datasys.append_mod_event(interaction.guild.id, {
                    "type": "ban",
                    "user_id": str(self.user.id),
                    "user_name": self.user.name,
                    "mod_id": str(interaction.user.id),
                    "mod_name": interaction.user.name,
                    "reason": self.reason,
                    "timestamp": datetime.datetime.utcnow().isoformat(),
                })
            except Exception:
                pass

            # Prism: record ban event
            try:
                assert interaction.guild is not None
                account_age = (datetime.datetime.now(datetime.timezone.utc) - self.user.created_at).days
                sentinel.record_event(
                    user_id=self.user.id,
                    user_name=self.user.name,
                    event_type="ban",
                    guild_id=interaction.guild.id,
                    reason=self.reason,
                    account_age_days=account_age,
                )
            except Exception:
                pass

            # Store temp-ban entry for auto-unban
            if self.duration and expires_at:
                ta = datasys.load_temp_actions(interaction.guild.id)
                ta["bans"].append({
                    "user_id": self.user.id,
                    "user_name": str(self.user),
                    "reason": self.reason,
                    "expires_at": expires_at.isoformat(),
                    "moderator_name": str(interaction.user),
                    "guild_name": interaction.guild.name,
                })
                datasys.save_temp_actions(interaction.guild.id, ta)

            embed = discord.Embed(
                title=f'{lang["commands"]["admin"]["ban"]["title"]} // {self.user.name}',
                description=lang["commands"]["admin"]["ban"]["success"],
                color=config.Discord.danger_color,
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
            embed.add_field(name="Duration", value=duration_str, inline=False)

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
                    title="ERROR // SERVER ONLY",
                    color=config.Discord.warn_color,
                )
            )
        lang = datasys.load_lang_file(interaction.guild.id)
        embed = discord.Embed(
            title=f'BAN CANCELLED // {self.user.name}',
            description=lang["commands"]["admin"]["ban"]["abort"],
            color=config.Discord.warn_color,
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
                    title="ERROR // SERVER ONLY",
                    color=config.Discord.warn_color,
                )
            )
        lang = datasys.load_lang_file(interaction.guild.id)
        try:
            # DM user before kick
            try:
                dm_embed = discord.Embed(
                    title=f"ACTION // KICK // {interaction.guild.name}",
                    color=config.Discord.warn_color,
                )
                dm_embed.add_field(name="Reason", value=self.reason, inline=False)
                dm_embed.add_field(name="Moderator", value=str(interaction.user), inline=False)
                dm_embed.set_footer(text="Baxi · avocloud.net")
                await self.user.send(embed=dm_embed)
            except (discord.Forbidden, discord.HTTPException):
                pass

            await self.user.kick(
                reason=str(lang["commands"]["admin"]["kick"]["audit_reason"]).format(
                    moderator=self.user.name, reason=self.reason
                )
            )

            # Log mod event for BaxiInsights
            try:
                assert interaction.guild is not None
                datasys.append_mod_event(interaction.guild.id, {
                    "type": "kick",
                    "user_id": str(self.user.id),
                    "user_name": self.user.name,
                    "mod_id": str(interaction.user.id),
                    "mod_name": interaction.user.name,
                    "reason": self.reason,
                    "timestamp": datetime.datetime.utcnow().isoformat(),
                })
            except Exception:
                pass

            # Prism: record kick event
            try:
                assert interaction.guild is not None
                account_age = (datetime.datetime.now(datetime.timezone.utc) - self.user.created_at).days
                sentinel.record_event(
                    user_id=self.user.id,
                    user_name=self.user.name,
                    event_type="kick",
                    guild_id=interaction.guild.id,
                    reason=self.reason,
                    account_age_days=account_age,
                )
            except Exception:
                pass

            embed = discord.Embed(
                title=f'{lang["commands"]["admin"]["kick"]["title"]} // {self.user.name}',
                description=lang["commands"]["admin"]["kick"]["success"],
                color=config.Discord.danger_color,
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
                    title="ERROR // SERVER ONLY",
                    color=config.Discord.warn_color,
                )
            )
        lang = datasys.load_lang_file(interaction.guild.id)
        embed = discord.Embed(
            title=f'KICK CANCELLED // {self.user.name}',
            description=lang["commands"]["admin"]["kick"]["abort"],
            color=config.Discord.warn_color,
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
                    title="ERROR // SERVER ONLY",
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
                title=f'{lang["commands"]["admin"]["unban"]["title"]} // {self.user_id}',
                description=lang["commands"]["admin"]["unban"]["success"],
                color=config.Discord.success_color,
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
                    title="ERROR // SERVER ONLY",
                    color=config.Discord.warn_color,
                )
            )
        lang = datasys.load_lang_file(interaction.guild.id)
        embed = discord.Embed(
            title=f'UNBAN CANCELLED // {self.user_id}',
            description=lang["commands"]["admin"]["unban"]["abort"],
            color=config.Discord.warn_color,
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
                    title="ERROR // SERVER ONLY",
                    color=config.Discord.warn_color,
                )
            )
        lang = datasys.load_lang_file(interaction.guild.id)
        try:
            text_channel = cast(discord.TextChannel, self.channel)
            await text_channel.purge(limit=self.amount + 1)

            embed = discord.Embed(
                title=f'{lang["commands"]["admin"]["clear"]["title"]} // #{self.channel.name} // {self.amount} msgs',
                description=lang["commands"]["admin"]["clear"]["success"],
                color=config.Discord.success_color,
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
                    title="ERROR // SERVER ONLY",
                    color=config.Discord.warn_color,
                )
            )
        lang = datasys.load_lang_file(interaction.guild.id)
        embed = discord.Embed(
            title=f'CLEAR CANCELLED // #{self.channel.name}',
            description=lang["commands"]["admin"]["clear"]["abort"],
            color=config.Discord.warn_color,
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
                    title="ERROR // SERVER ONLY",
                    color=config.Discord.warn_color,
                )
            )
        lang = datasys.load_lang_file(interaction.guild.id)
        verify_data: dict = dict(datasys.load_data(interaction.guild.id, "verify"))
        guild_terms: bool = bool(
            datasys.load_data(sid=interaction.guild.id, sys="terms")
        )
        if not guild_terms:
            embed = discord.Embed(
                description=str(lang["systems"]["terms"]["description"]).format(
                    url=f"https://{config.Web.url}"
                ),
                color=config.Discord.danger_color,
            )
            embed.set_footer(text="Baxi · avocloud.net")
            await interaction.response.send_message(embed=embed)
            return

        if verify_data.get("enabled", False):
            role: Optional[discord.Role] = interaction.guild.get_role(
                int(verify_data.get("rid", 0))
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
                color=config.Discord.success_color,
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
                color=config.Discord.danger_color,
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)


_BUTTON_STYLE_MAP: dict[str, discord.ButtonStyle] = {
    "primary": discord.ButtonStyle.primary,
    "secondary": discord.ButtonStyle.secondary,
    "success": discord.ButtonStyle.success,
    "danger": discord.ButtonStyle.danger,
}


def _slugify_label(label: str, fallback: str = "ticket") -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (label or "").lower()).strip("-")
    return s or fallback


def build_ticket_panel_view(buttons: list) -> ui.View:
    """Build a persistent panel view with one button per button definition."""
    view = ui.View(timeout=None)
    for b in buttons or []:
        btn_id = str(b.get("id", "")).strip()
        if not btn_id:
            continue
        label = (b.get("label") or "").strip()
        emoji_str = (b.get("emoji") or "").strip()
        style = _BUTTON_STYLE_MAP.get(str(b.get("style", "primary")).lower(), discord.ButtonStyle.primary)

        if not label and not emoji_str:
            label = "Ticket"
        elif not label:
            label = "\u200b"

        emoji: discord.PartialEmoji | None = None
        if emoji_str:
            try:
                emoji = discord.PartialEmoji.from_str(emoji_str)
            except Exception:
                emoji = None

        view.add_item(ui.Button(
            label=label[:80],
            emoji=emoji,
            style=style,
            custom_id=f"ticket_btn:{btn_id}",
        ))
    return view


class TicketButton(ui.DynamicItem[ui.Button], template=r"ticket_btn:(?P<btn_id>[A-Za-z0-9_\-]+)"):
    """Persistent dynamic button that opens a ticket for the given button id."""

    def __init__(self, btn_id: str) -> None:
        super().__init__(
            ui.Button(
                custom_id=f"ticket_btn:{btn_id}",
                style=discord.ButtonStyle.primary,
            )
        )
        self.btn_id = btn_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: ui.Button,
        match: re.Match[str],
    ) -> "TicketButton":
        return cls(match["btn_id"])

    async def callback(self, interaction: discord.Interaction) -> None:
        await _open_ticket_from_button(interaction, self.btn_id)


async def _open_ticket_from_button(interaction: discord.Interaction, btn_id: str) -> None:
    try:
        if interaction.guild is None:
            return await interaction.response.send_message("Server only.", ephemeral=True)

        guild = interaction.guild
        user = interaction.user
        lang = datasys.load_lang_file(guild.id)

        guild_terms: bool = bool(datasys.load_data(sid=guild.id, sys="terms"))
        if not guild_terms:
            embed = discord.Embed(
                description=str(lang["systems"]["terms"]["description"]).format(
                    url=f"https://{config.Web.url}"
                ),
                color=config.Discord.danger_color,
            )
            embed.set_footer(text="Baxi · avocloud.net")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        guild_data: dict = dict(datasys.load_data(guild.id, sys="ticket"))
        if not guild_data.get("enabled", False):
            await interaction.response.send_message(
                "The ticket system is currently disabled.", ephemeral=True
            )
            return

        # Find the button definition
        button_def: Optional[dict] = None
        for b in guild_data.get("buttons", []):
            if str(b.get("id", "")) == btn_id:
                button_def = b
                break
        if button_def is None:
            await interaction.response.send_message(
                "This ticket button is no longer available.", ephemeral=True
            )
            return

        # Check existing open ticket
        tickets: dict = dict(datasys.load_data(guild.id, "open_tickets"))
        for tid in list(tickets.keys()):
            t_data: dict = tickets[str(tid)]
            if t_data.get("user") == user.id:
                try:
                    ch = await guild.fetch_channel(int(tid))
                    embed = discord.Embed(
                        title=lang["systems"]["ticket"]["title"],
                        description=str(
                            lang["systems"]["ticket"]["description_already_open"]
                        ).format(channel=ch.mention),
                        color=config.Discord.warn_color,
                    )
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    return
                except (discord.NotFound, discord.Forbidden):
                    del tickets[tid]
                    datasys.save_data(guild.id, "open_tickets", tickets)

        # Category
        cat_id = guild_data.get("catid")
        if not cat_id:
            await interaction.response.send_message(
                "Ticket category is not configured.", ephemeral=True
            )
            return
        try:
            category = await guild.fetch_channel(int(cat_id))
            if not isinstance(category, discord.CategoryChannel):
                await interaction.response.send_message(
                    "Configured ticket category is invalid.", ephemeral=True
                )
                return
        except (ValueError, discord.NotFound, discord.Forbidden, discord.HTTPException):
            await interaction.response.send_message(
                "Cannot access ticket category.", ephemeral=True
            )
            return

        # Staff role
        role_id = guild_data.get("role")
        if not role_id:
            await interaction.response.send_message(
                "Ticket staff role is not configured.", ephemeral=True
            )
            return
        try:
            role = await guild.fetch_role(int(role_id))
        except (ValueError, discord.NotFound, discord.Forbidden, discord.HTTPException):
            await interaction.response.send_message(
                "Configured ticket staff role was not found.", ephemeral=True
            )
            return

        perms_overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(
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

        slug = _slugify_label(str(button_def.get("label", "")), fallback=btn_id)
        channel_name = f"{slug}-{user.name}"[:100]
        channel = await guild.create_text_channel(
            name=channel_name, category=category, overwrites=perms_overwrites
        )

        tickets[str(channel.id)] = {
            "user": user.id,
            "supporterid": None,
            "created_at": int(datetime.datetime.now().timestamp()),
            "status": "open",
            "title": str(button_def.get("label", "Ticket")),
            "message": "",
            "button_id": btn_id,
            "transcript": [],
        }
        datasys.save_data(guild.id, "open_tickets", tickets)

        success_embed = discord.Embed(
            title=lang["systems"]["ticket"]["title"],
            description=str(lang["systems"]["ticket"]["description_creation_successfull"]).format(
                channel=channel.mention
            ),
            color=config.Discord.color,
        )
        await interaction.response.send_message(embed=success_embed, ephemeral=True)

        ticket_embed = discord.Embed(
            title=str(button_def.get("label", "Ticket")),
            description=f"{user.mention} opened a **{button_def.get('label', 'Ticket')}** ticket.",
            color=config.Discord.color,
        )
        await channel.send(
            content=f"{user.mention} {role.mention}",
            embed=ticket_embed,
            view=TicketAdminButtons(),
        )
    except Exception as e:
        print(f"Error in ticket button: {e}")
        try:
            await interaction.response.send_message(
                "An error occurred creating the ticket.", ephemeral=True
            )
        except Exception:
            pass


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
                        title="ERROR // SERVER ONLY",
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
            tickets: dict = dict(
                datasys.load_data(interaction.guild.id, "open_tickets")
            )
            transcripts: dict = dict(datasys.load_data(1001, "transcripts"))

            if not isinstance(tickets, dict):
                tickets = {}

            channel_id: str = str(interaction.channel.id)
            if channel_id in tickets:
                ticket_data = tickets[channel_id]

                member = interaction.guild.get_member(interaction.user.id)
                if member is None:
                    await interaction.response.send_message(
                        "Error: Member not found.",
                        ephemeral=True,
                    )
                    return

                required_role_id: int = int(guild_settings.get("role", 0))
                role = await interaction.guild.fetch_role(required_role_id)
                if role in member.roles:
                    await interaction.response.send_message(
                        embed=discord.Embed(
                            title=lang["systems"]["ticket"]["title"],
                            description=lang["systems"]["ticket"][
                                "wait_delete_confirm"
                            ],
                            color=config.Discord.danger_color,
                        )
                    )

                    if interaction.channel.id is None:
                        return

                    def check(m):
                        return (
                            m.channel.id
                            == interaction.channel.id  # pyright: ignore[reportOptionalMemberAccess]
                            and m.author.id == interaction.user.id
                        )

                    try:
                        response = await interaction.client.wait_for(
                            "message", check=check, timeout=30.0
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
                                "closed_by": str(interaction.user.name),
                                "closed_on": str(datetime.datetime.now(_VIENNA)),
                                "transcript": ticket_data["transcript"],
                            }

                            transcript_channel = await interaction.guild.fetch_channel(
                                int(guild_settings.get("transcript", 0))
                            )
                            link = f"https://{config.Web.url}/?ticket_transcript={transcript_id}"

                            embed = discord.Embed(
                                title=lang["systems"]["ticket"]["title"],
                                description=f"{str(lang['systems']['ticket']['link']).format(guild=interaction.guild.name)} {link}",
                            )

                            if transcript_channel is not None and isinstance(
                                transcript_channel, discord.TextChannel
                            ):
                                await transcript_channel.send(embed=embed)

                            try:
                                member = interaction.guild.get_member(
                                    int(tickets[channel_id]["user"])
                                )
                                if member is None:
                                    return
                                if member.dm_channel is None:
                                    dm_channel = await member.create_dm()
                                else:
                                    dm_channel = member.dm_channel

                                await dm_channel.send(embed=embed)
                                if transcript_channel is not None and isinstance(
                                    transcript_channel, discord.TextChannel
                                ):
                                    await transcript_channel.send(
                                        f"Transcript sent to user {member.mention} via DM."
                                    )
                            except discord.Forbidden:
                                if transcript_channel is not None and isinstance(
                                    transcript_channel, discord.TextChannel
                                ):
                                    await transcript_channel.send(
                                        f"Unable to send transcript to user: DMs closed or blocked."
                                    )

                            transcripts[str(transcript_id)] = transcript_data
                            datasys.save_data(1001, "transcripts", transcripts)
                            tickets.pop(str(channel_id))
                            datasys.save_data(
                                interaction.guild.id, "open_tickets", tickets
                            )
                        else:
                            await interaction.channel.send(str(lang["systems"]["ticket"]["close_cancel"]).format(user=interaction.user.name))
                            tickets[channel_id]["transcript"].append(
                                {
                                    "type": "sys_msg",
                                    "msg": str(
                                        lang["systems"]["ticket"]["close_cancel"]
                                    ).format(user=interaction.user.name),
                                    "avatar": "https://avocloud.net/img/icons/gear.svg",
                                    "timestamp": str(datetime.datetime.now(_VIENNA)),
                                    "is_staff": True,
                                }
                            )
                            datasys.save_data(interaction.guild.id, "open_tickets", tickets)

                    except asyncio.TimeoutError:
                        await interaction.channel.send(str(lang["systems"]["ticket"]["close_cancel"]).format(user=interaction.user.name))
                        tickets[channel_id]["transcript"].append(
                            {
                                "type": "sys_msg",
                                "msg": str(
                                    lang["systems"]["ticket"]["close_cancel"]
                                ).format(user=interaction.user.name),
                                "avatar": "https://avocloud.net/img/icons/gear.svg",
                                "timestamp": str(datetime.datetime.now(_VIENNA)),
                                "is_staff": True,
                            }
                        )
                        datasys.save_data(interaction.guild.id, "open_tickets", tickets)


                else:
                    await interaction.response.send_message(
                        embed=discord.Embed(
                            title=lang["systems"]["ticket"]["title"],
                            description=lang["systems"]["ticket"][
                                "description_no_permission_delete"
                            ],
                            color=config.Discord.danger_color,
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
        try:
            if interaction.guild is None:
                lang = datasys.load_lang_file(1001)
                return await interaction.response.send_message(
                    embed=discord.Embed(
                        title="ERROR // SERVER ONLY",
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
            tickets: dict = dict(
                datasys.load_data(interaction.guild.id, "open_tickets")
            )

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

                required_role_id: int = int(guild_settings.get("role", 0))
                role = await interaction.guild.fetch_role(required_role_id)
                if role in member.roles:
                    tickets[channel_id]["supporterid"] = interaction.user.id
                    tickets[channel_id]["transcript"].append(
                        {
                            "type": "sys_msg",
                            "msg": str(
                                lang["systems"]["ticket"]["description_claimed"]
                            ).format(user=interaction.user.name),
                            "avatar": "https://avocloud.net/img/icons/gear.svg",
                            "timestamp": str(datetime.datetime.now(_VIENNA)),
                            "is_staff": True,
                        }
                    )
                    datasys.save_data(interaction.guild.id, "open_tickets", tickets)

                    await interaction.response.send_message(
                        embed=discord.Embed(
                            title=lang["systems"]["ticket"]["title"],
                            description=str(
                                lang["systems"]["ticket"]["description_claimed"]
                            ).format(user=interaction.user.mention),
                            color=config.Discord.success_color,
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
                            color=config.Discord.danger_color,
                        ),
                        ephemeral=True,
                    )
            else:
                await interaction.response.send_message(
                    "This channel is not a valid ticket.",
                    ephemeral=True,
                )
        except Exception as e:
            print(f"error in ticket claim: {e}")
            await interaction.response.send_message(
                "An error occurred while trying to claim the ticket.",
                ephemeral=True,
            )
