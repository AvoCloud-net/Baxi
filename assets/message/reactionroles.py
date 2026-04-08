import re

import discord
from discord.ext import commands
from reds_simple_logger import Logger

import assets.data as datasys

logger = Logger()


class RoleButton(discord.ui.DynamicItem[discord.ui.Button], template=r"rr:(?P<role_id>[0-9]+)"):
    """Persistent dynamic button that toggles a role when clicked."""

    def __init__(self, role_id: int) -> None:
        super().__init__(
            discord.ui.Button(
                custom_id=f"rr:{role_id}",
                style=discord.ButtonStyle.secondary,
            )
        )
        self.role_id = role_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ) -> "RoleButton":
        return cls(int(match["role_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        await _toggle_role(interaction, self.role_id)


def _find_panel_for_role(guild_id: int, role_id: str) -> dict | None:
    """Return the panel containing the given role_id, or None."""
    rr_data = datasys.load_data(guild_id, "reaction_roles")
    for panel in rr_data.get("panels", []):
        for entry in panel.get("entries", []):
            if str(entry.get("role_id")) == role_id:
                return panel
    return None


async def _toggle_role(interaction: discord.Interaction, role_id: int) -> None:
    """Toggle a role on the interacting member and reply ephemerally."""
    guild = interaction.guild
    member = interaction.user
    if guild is None or not isinstance(member, discord.Member):
        lang = datasys.load_lang_file(0)
        await interaction.response.send_message(lang["systems"]["button_roles"]["server_only"], ephemeral=True)
        return

    lang = datasys.load_lang_file(guild.id)
    strings = lang["systems"]["button_roles"]

    role = guild.get_role(role_id)
    if role is None:
        await interaction.response.send_message(strings["not_found"], ephemeral=True)
        return

    try:
        if role in member.roles:
            await member.remove_roles(role, reason="Baxi Button Roles")
            msg = strings["removed"].format(role=role.name)
            logger.debug.info(f"[ButtonRoles] -{role.name} ← {member.name} in {guild.name}")
        else:
            # Enforce per-panel max_roles limit before adding
            removed_roles: list[discord.Role] = []
            panel = _find_panel_for_role(guild.id, str(role_id))
            if panel:
                max_roles = int(panel.get("max_roles") or 0)  # 0/empty = unlimited
                if max_roles > 0:
                    panel_role_ids = [
                        int(e["role_id"]) for e in panel.get("entries", [])
                        if str(e.get("role_id")) != str(role_id)
                    ]
                    user_panel_roles = [
                        r for rid in panel_role_ids
                        if (r := guild.get_role(rid)) and r in member.roles
                    ]
                    excess = len(user_panel_roles) - (max_roles - 1)
                    if excess > 0:
                        removed_roles = user_panel_roles[:excess]
                        await member.remove_roles(*removed_roles, reason="Baxi Button Roles (panel limit)")

            await member.add_roles(role, reason="Baxi Button Roles")
            if removed_roles:
                removed_names = ", ".join(f"**{r.name}**" for r in removed_roles)
                msg = strings["group_limit_removed"].format(removed=removed_names, added=role.name)
            else:
                msg = strings["applied"].format(role=role.name)
            logger.debug.info(f"[ButtonRoles] +{role.name} → {member.name} in {guild.name}")

        await interaction.response.send_message(msg, ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message(strings["no_permission"], ephemeral=True)
    except discord.HTTPException as e:
        await interaction.response.send_message(f"An error occurred: {e}", ephemeral=True)


def build_panel_embed(panel: dict) -> discord.Embed:
    """Build the Discord embed for a button-role panel."""
    color_str = panel.get("color", "#9333ea")
    try:
        color = discord.Color.from_str(color_str)
    except Exception:
        color = discord.Color.from_rgb(147, 51, 234)

    embed = discord.Embed(
        title=panel.get("title", "Role Selection"),
        description=panel.get("description", "Click a button below to toggle a role."),
        color=color,
    )
    embed.set_footer(text="Baxi · Button Roles")
    return embed


def build_panel_view(panel: dict) -> discord.ui.View:
    """Build the View with one button per entry for a button-role panel."""
    view = discord.ui.View(timeout=None)
    for entry in panel.get("entries", []):
        role_id = str(entry.get("role_id", ""))
        label = (entry.get("label") or "").strip()
        emoji_str = (entry.get("emoji") or "").strip()

        if not label and not emoji_str:
            label = f"Role {role_id}"
        elif not label:
            label = "\u200b"  # zero-width space so Discord accepts emoji-only buttons

        emoji: discord.PartialEmoji | None = None
        if emoji_str:
            try:
                emoji = discord.PartialEmoji.from_str(emoji_str)
            except Exception:
                emoji = None

        btn = discord.ui.Button(
            label=label[:80],
            emoji=emoji,
            custom_id=f"rr:{role_id}",
            style=discord.ButtonStyle.secondary,
        )
        view.add_item(btn)
    return view
