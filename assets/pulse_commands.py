"""/pulse - community activity heatmap, personal stats and on-demand recap."""
from __future__ import annotations

import asyncio

import discord
from discord import app_commands
from discord.ext import commands

import assets.data as datasys
import assets.pulse as pulse
import config.config as config
from reds_simple_logger import Logger

logger = Logger()

_DAY_CHOICES = [
    app_commands.Choice(name="7 days", value=7),
    app_commands.Choice(name="14 days", value=14),
    app_commands.Choice(name="30 days", value=30),
    app_commands.Choice(name="90 days", value=90),
]


def pulse_commands(bot: commands.AutoShardedBot):
    group = app_commands.Group(
        name="pulse",
        description="Baxi Pulse - when and how your community is active",
        guild_only=True,
    )

    async def _fail(interaction: discord.Interaction, text: str):
        await interaction.followup.send(
            embed=discord.Embed(description=text, color=config.Discord.danger_color), ephemeral=True,
        )

    @group.command(name="server", description="Activity heatmap, best time to post and top channels of this server")
    @app_commands.describe(days="Time window (default: 28 days)")
    @app_commands.choices(days=_DAY_CHOICES)
    @app_commands.checks.cooldown(1, 15.0, key=lambda i: i.guild_id)
    async def pulse_server(interaction: discord.Interaction, days: app_commands.Choice[int] | None = None):
        await interaction.response.defer()
        try:
            t = datasys.load_lang_file(interaction.guild.id)["pulse"]
            cfg = pulse.load_cfg(interaction.guild.id)
            report = await asyncio.to_thread(
                pulse.build_report, interaction.guild.id, days.value if days else 28, pulse.resolve_tz(cfg["timezone"]),
            )
            payload = await pulse.server_payload(
                interaction.guild, report, t, show_members=bool(cfg.get("show_members", True)),
            )
            await interaction.followup.send(**payload)
        except Exception as e:
            logger.error(f"[pulse server] {e}")
            await _fail(interaction, f"{config.Icons.cross} Could not build the Pulse report. Please try again later.")

    @group.command(name="me", description="Your own activity on this server: streak, rank and weekday profile")
    @app_commands.describe(days="Time window (default: 30 days)")
    @app_commands.choices(days=_DAY_CHOICES)
    @app_commands.checks.cooldown(1, 10.0, key=lambda i: (i.guild_id, i.user.id))
    async def pulse_me(interaction: discord.Interaction, days: app_commands.Choice[int] | None = None):
        await interaction.response.defer(ephemeral=True)
        try:
            t = datasys.load_lang_file(interaction.guild.id)["pulse"]
            ur = await asyncio.to_thread(
                pulse.build_user_report, interaction.guild.id, interaction.user.id, days.value if days else 30,
            )
            payload = await pulse.user_payload(interaction.user, ur, t)
            await interaction.followup.send(**payload, ephemeral=True)
        except Exception as e:
            logger.error(f"[pulse me] {e}")
            await _fail(interaction, f"{config.Icons.cross} Could not build your Pulse report. Please try again later.")

    @group.command(name="recap", description="Post the weekly recap now (uses the channel set in the dashboard)")
    @app_commands.checks.cooldown(1, 60.0, key=lambda i: i.guild_id)
    async def pulse_recap(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        t = datasys.load_lang_file(interaction.guild.id)["pulse"]
        if not interaction.user.guild_permissions.manage_guild:
            return await _fail(interaction, t["no_permission"])
        cfg = pulse.load_cfg(interaction.guild.id)
        if not str(cfg.get("channel", "") or "").isdigit():
            return await _fail(interaction, t["recap_no_channel"])
        try:
            sent = await pulse.post_recap(bot, interaction.guild, cfg)
        except Exception as e:
            logger.error(f"[pulse recap] {e}")
            sent = False
        await interaction.followup.send(
            embed=discord.Embed(
                description=t["recap_sent"] if sent else t["recap_failed"],
                color=config.Discord.success_color if sent else config.Discord.warn_color,
            ),
            ephemeral=True,
        )

    @group.error
    async def _on_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CommandOnCooldown):
            msg = f"{config.Icons.alert} Slow down - try again in {error.retry_after:.0f}s."
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
            return
        logger.error(f"[pulse] {error}")

    bot.tree.add_command(group)
