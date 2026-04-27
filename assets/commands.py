import discord

from discord.ext import commands
from discord import Embed, Interaction, app_commands
import config.config as config
import assets.data as datasys
from typing import cast, Optional
import datetime
from datetime import timezone

from assets.buttons import (
    BanConfirmView,
    KickConfirmView,
    UbanConfirmView,
    ClearConfirmView,
)
from assets.message.warnings import add_warning, remove_warning, get_warnings
import assets.trust as sentinel
import reds_simple_logger

logger = reds_simple_logger.Logger()


def base_commands(bot: commands.AutoShardedBot):
    logger.debug.info("Base commands loaded.")

    @bot.tree.command(name="help", description="Shows the help panel")
    async def help_cmd(interaction: Interaction):
        await interaction.response.defer()
        guild_id: int = interaction.guild.id if interaction.guild is not None else 0

        lang = datasys.load_lang_file(guild_id)
        title = f"{config.Icons.questionmark} {lang["commands"]["user"]["help"]["title"]}"
        content_prefix_title = lang["commands"]["user"]["help"]["prefix"]["title"]
        content_prefix_content = lang["commands"]["user"]["help"]["prefix"]["content"]
        content_about_title = lang["commands"]["user"]["help"]["about"]["title"]
        content_about_content = lang["commands"]["user"]["help"]["about"]["content"]
        content_icons_title = lang["commands"]["user"]["help"]["icons"]["title"]
        content_icons_content = lang["commands"]["user"]["help"]["icons"]["content"]
        content_bugs_title = lang["commands"]["user"]["help"]["bugs"]["title"]
        content_bugs_content = lang["commands"]["user"]["help"]["bugs"]["content"]

        embed = Embed(
            title=title,
            description=(
                f"## {content_prefix_title}\n> {content_prefix_content}\n"
                f"## {content_about_title}\n> {content_about_content}\n"
                f"## {content_icons_title}\n> {content_icons_content}\n"
                f"## {content_bugs_title}\n> {content_bugs_content}"
            ),
            color=config.Discord.color,
        )
        await interaction.edit_original_response(embed=embed)

    @bot.tree.command(name="dashboard", description="Get the link to the Baxi dashboard")
    async def dashboard_cmd(interaction: Interaction):
        await interaction.response.send_message(
            "## Baxi Dashboard\nConfigure Baxi for your server at: https://baxi.avocloud.net",
            ephemeral=True,
        )

    @bot.tree.command(
        name="my_trust",
        description="Shows your personal Prism trust score and what has influenced it.",
    )
    async def my_trust_cmd(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            guild_id    = interaction.guild.id if interaction.guild else 1001
            lang        = datasys.load_lang_file(guild_id)
            t           = lang["commands"]["user"]["my_trust"]

            account_age = (datetime.datetime.now(timezone.utc) - interaction.user.created_at).days
            sentinel.ensure_profile(interaction.user.id, interaction.user.name, account_age)

            # Check user opt-out
            if sentinel.is_opted_out(interaction.user.id):
                embed = discord.Embed(
                    title=f"{config.Icons.info} {t['title']}",
                    color=config.Discord.color,
                )
                embed.add_field(
                    name=t["opted_out_title"],
                    value=t["opted_out_value"],
                    inline=False,
                )
                embed.add_field(
                    name=t["what_is_prism_title"],
                    value=t["what_is_prism_value"],
                    inline=False,
                )
                embed.set_footer(text=t["footer"])
                await interaction.edit_original_response(embed=embed)
                return

            explanation = sentinel.get_score_explanation(interaction.user.id)
            score       = explanation["score"]
            trend       = explanation["trend"]
            impacts     = explanation["recent_impacts"]
            recovery    = explanation["recovery_days_remaining"]
            event_cnt   = explanation["event_count"]
            account_age = explanation["account_age_days"]

            # LLM summary -  pull directly from profile
            profile     = sentinel.get_profile(interaction.user.id)
            llm_summary = profile.get("llm_summary") if profile else None

            trend_icon = {"falling": "↓", "rising": "↑", "stable": "→"}.get(trend, "→")
            if score >= 75:
                score_color = config.Discord.success_color
            elif score >= 45:
                score_color = config.Discord.warn_color
            else:
                score_color = config.Discord.danger_color

            embed = discord.Embed(
                title=f"{config.Icons.info} {t['title']}",
                description=t["score_line"].format(score=score, trend=trend_icon, count=event_cnt),
                color=score_color,
            )

            if llm_summary:
                embed.add_field(
                    name="Risk Summary",
                    value=f"*{llm_summary}*",
                    inline=False,
                )

            if impacts:
                impact_lines = []
                for ev in impacts:
                    decay_note = " *(½)*" if ev["decayed"] else ""
                    impact_lines.append(
                        f"• **{ev['label']}** · {ev['severity_label']} · "
                        f"`{ev['weight']:+d}` pts · {ev['age_days']}d{decay_note}"
                        + (f"\n  *{ev['reason']}*" if ev["reason"] else "")
                    )
                embed.add_field(
                    name=t["recent_events_title"],
                    value="\n".join(impact_lines),
                    inline=False,
                )
            else:
                embed.add_field(
                    name=t["recent_events_title"],
                    value=t["no_events"],
                    inline=False,
                )

            if account_age < sentinel.AGE_FULL_TRUST_DAYS:
                embed.add_field(
                    name=t["new_account_title"],
                    value=t["new_account_value"].format(
                        age=account_age,
                        full=sentinel.AGE_FULL_TRUST_DAYS,
                        days=sentinel.AGE_FULL_TRUST_DAYS - account_age,
                    ),
                    inline=False,
                )

            if score < 100 and recovery is not None:
                embed.add_field(
                    name=t["recovery_title"],
                    value=t["recovery_value"].format(days=recovery),
                    inline=False,
                )
            elif score == 100:
                embed.add_field(
                    name=t["recovery_title"],
                    value=t["perfect_value"],
                    inline=False,
                )

            embed.add_field(
                name=t["what_is_prism_title"],
                value=t["what_is_prism_value"],
                inline=False,
            )
            embed.set_footer(text=t["footer"])
            await interaction.edit_original_response(embed=embed)

        except Exception as e:
            logger.error(f"[my_trust] {e}")
            await interaction.edit_original_response(
                embed=discord.Embed(
                    title="ERROR",
                    description="Could not load your trust profile. Please try again later.",
                    color=config.Discord.danger_color,
                )
            )

    @bot.tree.command(
        name="prism_optout",
        description="Opt out of (or back into) Prism trust scoring.",
    )
    async def prism_optout_cmd(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            guild_id = interaction.guild.id if interaction.guild else 1001
            lang     = datasys.load_lang_file(guild_id)
            t        = lang["commands"]["user"]["prism_optout"]

            account_age = (datetime.datetime.now(timezone.utc) - interaction.user.created_at).days
            sentinel.ensure_profile(interaction.user.id, interaction.user.name, account_age)

            currently_out = sentinel.is_opted_out(interaction.user.id)
            sentinel.set_opt_out(interaction.user.id, not currently_out)

            if not currently_out:
                description = t["opted_out"]
                color = config.Discord.warn_color
            else:
                description = t["opted_in"]
                color = config.Discord.success_color

            embed = discord.Embed(
                title=f"{config.Icons.info} {t['title']}",
                description=description,
                color=color,
            )
            embed.set_footer(text=t["footer"])
            await interaction.edit_original_response(embed=embed)

        except Exception as e:
            logger.error(f"[prism_optout] {e}")
            await interaction.edit_original_response(
                embed=discord.Embed(
                    title="ERROR",
                    description="Could not update your opt-out preference. Please try again later.",
                    color=config.Discord.danger_color,
                )
            )

    @bot.tree.command(
    name="scan_users",
    description="Scans this server for users flagged globally on Baxi for malicious or suspicious behavior.",
    )
    async def scan_user(interaction: discord.Interaction):
        
        try:
            lang = datasys.load_lang_file(1001)
            await interaction.response.defer()
            if interaction.guild is None:
                
                embed = discord.Embed(
                    title="ERROR // SERVER ONLY",
                    description="This command can only be used in a server.",
                    color=config.Discord.warn_color
                )
                return await interaction.response.send_message(embed=embed)
            
            guild_terms: bool = bool(datasys.load_data(sid=interaction.guild.id, sys="terms"))
            if not guild_terms:
                    embed = discord.Embed(description=str(lang["systems"]["terms"]["description"]).format(url=f"https://{config.Web.url}"), color=config.Discord.danger_color)
                    embed.set_footer(text="Baxi · avocloud.net")
                    await interaction.response.send_message(embed=embed)
                    return
            if interaction.user.avatar is None:
                user_avatar = ""
            else:
                user_avatar = interaction.user.avatar.url

            lang = datasys.load_lang_file(interaction.guild.id)
            users_list: dict = dict(datasys.load_data(1001, "users"))
            flagged_users = []

            for member in interaction.guild.members:
                if str(member.id) in users_list and bool(users_list[str(member.id)]["flagged"]):
                    flagged_users.append(users_list[str(member.id)])

            embed = discord.Embed(
                title=f"{config.Icons.search} SCAN USERS // {interaction.guild.name} // {interaction.guild.member_count} members",
                description=str(lang["commands"]["user"]["scan_users"]["user_count"]).format(users=interaction.guild.member_count),
                color=config.Discord.color if len(flagged_users) == 0 else config.Discord.danger_color
            )
            
            embed.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else None)
            embed.set_footer(text=f"Baxi · avocloud.net  |  Requested by {interaction.user}", icon_url=user_avatar)

            if len(flagged_users) == 0:
                embed.add_field(
                    name=f"{config.Icons.info} {lang["commands"]["user"]["scan_users"]["no_threats"]}",
                    value=lang["commands"]["user"]["scan_users"]["no_users_detected"],
                    inline=False
                )
            else:
                embed.add_field(
                    name=f"{config.Icons.alert} {len(flagged_users)} {lang["commands"]["user"]["scan_users"]["users_found"]}",
                    value=f"{lang["commands"]["user"]["scan_users"]["users_found_description"]}",
                    inline=False
                )
                
                for i, user in enumerate(flagged_users, 1):
                    # Prism: enrich with trust profile if available
                    trust_profile = sentinel.get_profile(int(user["id"]))
                    if trust_profile:
                        score     = trust_profile.get("score", "?")
                        flag_src  = f"{config.Icons.robot} Auto" if user.get("auto_flagged") else f"{config.Icons.user} Manuell"
                        event_cnt = len(trust_profile.get("events", []))
                        score_str = f"`{score}/100` · {flag_src} · {event_cnt} Ereignisse"
                    else:
                        score_str = "kein Prism-Profil"

                    embed.add_field(
                        name=f"{i}. {user['name']}",
                        value=f"-  **{lang["commands"]["user"]["scan_users"]["reason"]}:** {user['reason']}\n"
                            f"-  **Prism Score:** {score_str}\n"
                            f"-  **{lang["commands"]["user"]["scan_users"]["date"]}:** {user['entry_date']}\n"
                            f"-  **{lang["commands"]["user"]["scan_users"]["id"]}:** `{user['id']}`",
                        inline=False
                    )
                
                embed.add_field(
                    name=f"{config.Icons.people_crossed} {lang["commands"]["user"]["scan_users"]["recommendation"]}",
                    value=f"{lang["commands"]["user"]["scan_users"]["recommendation_description"]}",
                    inline=False
                )

            await interaction.edit_original_response(embed=embed)

        except Exception as e:
            logger.error(str(e))
            error_embed = discord.Embed(
                title="ERROR // SCAN FAILED",
                description="Failed to complete the scan. Please try again later.",
                color=config.Discord.danger_color
            )
            await interaction.edit_original_response(embed=error_embed)

    from assets.music import register_music_commands
    register_music_commands(bot)


def utility_commands(bot: commands.AutoShardedBot):
    logger.debug.info("Utility commands loaded.")

    @bot.tree.command(name="ban", description="Ban a user from the server.")
    @app_commands.checks.has_permissions(ban_members=True)
    @app_commands.describe(user="The user you want to ban.", reason="The reason for the ban.", duration="Optional duration, e.g. 7d, 2h, 30m. Leave empty for permanent.")
    async def ban_cmd(
        interaction: Interaction, user: discord.Member, reason: str = "N/A", duration: Optional[str] = None
    ):
        if interaction.guild is None:
            lang = datasys.load_lang_file(1001)
            return await interaction.response.send_message(
                embed=discord.Embed(
                    title="ERROR // SERVER ONLY",
                    color=config.Discord.warn_color,
                )
            )

        lang = datasys.load_lang_file(interaction.guild.id)
        member = cast(discord.Member, interaction.user)

        if member.top_role <= user.top_role:
            await interaction.response.send_message(
                lang["commands"]["admin"]["ban"]["missing_perms"], ephemeral=True
            )
            return

        parsed_duration = None
        if duration:
            parsed_duration = datasys.parse_duration(duration)
            if parsed_duration is None:
                return await interaction.response.send_message(
                    f"{config.Icons.cross} Invalid duration format. Use e.g. `7d`, `2h`, `30m`, `1w`.", ephemeral=True
                )

        duration_str = datasys.format_duration(parsed_duration) if parsed_duration else "Permanent"

        embed = discord.Embed(
            title=f'{config.Icons.people_crossed} {lang["commands"]["admin"]["ban"]["title"]} // {user.name}',
            description=lang["commands"]["admin"]["ban"]["confirmation"],
            color=config.Discord.danger_color,
        )
        embed.add_field(
            name=lang["commands"]["admin"]["user"],
            value=user.mention,
            inline=False,
        )
        embed.add_field(
            name=lang["commands"]["admin"]["mod"],
            value=interaction.user.mention,
            inline=False,
        )
        embed.add_field(
            name=lang["commands"]["admin"]["reason"],
            value=reason,
            inline=False,
        )
        embed.add_field(name="Duration", value=duration_str, inline=False)

        view = BanConfirmView(user, member, reason, parsed_duration)

        await interaction.response.send_message(embed=embed, view=view)

    @bot.tree.command(name="kick", description="Kick a user from the server.")
    @app_commands.checks.has_permissions(kick_members=True)
    @app_commands.describe(user="The user you want to kick.")
    @app_commands.describe(reason="The reason for the kick.")
    async def kick_cmd(
        interaction: Interaction, user: discord.Member, reason: str = "N/A"
    ):

        if interaction.guild is None:
            lang = datasys.load_lang_file(1001)
            return await interaction.response.send_message(
                embed=discord.Embed(
                    title="ERROR // SERVER ONLY",
                    color=config.Discord.warn_color,
                )
            )

        lang = datasys.load_lang_file(interaction.guild.id)
        member = cast(discord.Member, interaction.user)

        if member.top_role <= user.top_role:
            await interaction.response.send_message(
                lang["commands"]["admin"]["kick"]["missing_perms"],
                ephemeral=True,
            )
            return
        embed = discord.Embed(
            title=f'{config.Icons.people_crossed} {lang["commands"]["admin"]["kick"]["title"]} // {user.name}',
            description=lang["commands"]["admin"]["kick"]["confirmation"],
            color=config.Discord.danger_color,
        )
        embed.add_field(
            name=lang["commands"]["admin"]["user"],
            value=user.mention,
            inline=False,
        )
        embed.add_field(
            name=lang["commands"]["admin"]["mod"],
            value=interaction.user.mention,
            inline=False,
        )
        embed.add_field(
            name=lang["commands"]["admin"]["reason"],
            value=reason,
            inline=False,
        )

        view = KickConfirmView(user, member, reason)

        await interaction.response.send_message(embed=embed, view=view)

    @bot.tree.command(name="unban", description="Unban a user from the server.")
    @app_commands.checks.has_permissions(ban_members=True)
    @app_commands.describe(user="The user id of the user you want to unban.")
    async def unban_cmd(interaction: Interaction, user: int):
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
            title=f'{config.Icons.people_crossed} {lang["commands"]["admin"]["unban"]["title"]} // {user_member.name}',
            description=lang["commands"]["admin"]["unban"]["confirmation"],
            color=config.Discord.success_color,
        )
        user_member = interaction.guild.get_member(user)
        if user_member is None:
            user_member = await bot.fetch_user(user)

        embed.add_field(
            name=lang["commands"]["admin"]["user"],
            value=user_member.name,
            inline=False,
        )
        embed.add_field(
            name=lang["commands"]["admin"]["mod"],
            value=interaction.user.mention,
            inline=False,
        )
        view = UbanConfirmView(user_member, interaction.user)
        await interaction.response.send_message(embed=embed, view=view)

    @bot.tree.command(name="clear", description="Clear messages from a channel.")
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.describe(amount="The amount of messages to clear.")
    async def clear_cmd(interaction: Interaction, amount: int):

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
            title=f'{lang["commands"]["admin"]["clear"]["title"]} // #{interaction.channel.name} // {amount} msgs',
            description=lang["commands"]["admin"]["clear"]["confirmation"],
            color=config.Discord.warn_color,
        )
        embed.add_field(
            name=lang["commands"]["admin"]["amount"],
            value=amount,
            inline=False,
        )
        channel = interaction.channel
        if not isinstance(channel, discord.abc.Messageable):
            await interaction.response.send_message(
                f"{config.Icons.cross} Dieser Channel unterstützt keine Nachrichten.", ephemeral=True
            )
            return
        if isinstance(interaction.channel, discord.TextChannel):
            view = ClearConfirmView(amount, interaction.user, interaction.channel)
        else:
            await interaction.response.send_message(
                "Dieser Befehl kann nur in Textkanälen genutzt werden.", ephemeral=True
            )
            return
        await interaction.response.send_message(embed=embed, view=view)

    @bot.tree.command(name="mute", description="Timeout (mute) a user.")
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.describe(user="The user to mute.", duration="Duration, e.g. 10m, 1h, 7d (max 28 days).", reason="Reason for the mute.")
    async def mute_cmd(interaction: Interaction, user: discord.Member, duration: str = "10m", reason: str = "N/A"):
        if interaction.guild is None:
            lang = datasys.load_lang_file(1001)
            return await interaction.response.send_message(
                embed=discord.Embed(title="ERROR // SERVER ONLY", color=config.Discord.warn_color)
            )
        await interaction.response.defer(ephemeral=True)
        lang = datasys.load_lang_file(interaction.guild.id)
        member = cast(discord.Member, interaction.user)

        if member.top_role <= user.top_role:
            return await interaction.edit_original_response(
                embed=discord.Embed(description=f"{config.Icons.cross} You cannot mute someone with an equal or higher role.", color=config.Discord.danger_color)
            )

        parsed = datasys.parse_duration(duration)
        if not parsed:
            return await interaction.edit_original_response(
                embed=discord.Embed(description=f"{config.Icons.cross} Invalid duration format. Use e.g. `10m`, `1h`, `7d`.", color=config.Discord.danger_color)
            )
        if parsed.total_seconds() > 28 * 86400:
            return await interaction.edit_original_response(
                embed=discord.Embed(description=f"{config.Icons.cross} Maximum timeout duration is 28 days.", color=config.Discord.danger_color)
            )

        duration_str = datasys.format_duration(parsed)
        until = discord.utils.utcnow() + parsed
        until_naive = datetime.datetime.now(timezone.utc) + parsed

        try:
            dm_embed = discord.Embed(
                title=f"ACTION // MUTE // {interaction.guild.name}",
                color=config.Discord.warn_color,
            )
            dm_embed.add_field(name="Duration", value=duration_str, inline=False)
            dm_embed.add_field(name="Reason", value=reason, inline=False)
            dm_embed.add_field(name="Moderator", value=str(interaction.user), inline=False)
            dm_embed.add_field(name="Expires", value=f"<t:{int(until_naive.timestamp())}:F>", inline=False)
            dm_embed.set_footer(text="Baxi · avocloud.net")
            await user.send(embed=dm_embed)
        except (discord.Forbidden, discord.HTTPException):
            pass

        try:
            await user.timeout(until, reason=reason)
        except discord.Forbidden:
            return await interaction.edit_original_response(
                embed=discord.Embed(description=f"{config.Icons.cross} Missing permissions to timeout this user.", color=config.Discord.danger_color)
            )

        # Log mod event for BaxiInsights
        try:
            datasys.append_mod_event(interaction.guild.id, {
                "type": "mute",
                "user_id": str(user.id),
                "user_name": user.name,
                "mod_id": str(interaction.user.id),
                "mod_name": interaction.user.name,
                "reason": reason,
                "timestamp": datetime.datetime.utcnow().isoformat(),
            })
        except Exception:
            pass

        ta = datasys.load_temp_actions(interaction.guild.id)
        ta["timeouts"].append({
            "user_id": user.id,
            "user_name": str(user),
            "reason": reason,
            "expires_at": until_naive.isoformat(),
            "moderator_name": str(interaction.user),
            "guild_name": interaction.guild.name,
        })
        datasys.save_temp_actions(interaction.guild.id, ta)

        embed = discord.Embed(
            title=f"{config.Icons.people_crossed} ACTION // MUTE",
            description=f"{user.mention} has been muted.",
            color=config.Discord.warn_color,
        )
        embed.add_field(name="Duration", value=duration_str, inline=False)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(name="Expires", value=f"<t:{int(until_naive.timestamp())}:F>", inline=False)
        embed.set_footer(text="Baxi · avocloud.net")
        await interaction.edit_original_response(embed=embed)

    @bot.tree.command(name="unmute", description="Remove the timeout from a user.")
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.describe(user="The user to unmute.", reason="Reason for unmuting.")
    async def unmute_cmd(interaction: Interaction, user: discord.Member, reason: str = "N/A"):
        if interaction.guild is None:
            lang = datasys.load_lang_file(1001)
            return await interaction.response.send_message(
                embed=discord.Embed(title="ERROR // SERVER ONLY", color=config.Discord.warn_color)
            )
        await interaction.response.defer(ephemeral=True)

        try:
            await user.timeout(None, reason=reason)
        except discord.Forbidden:
            return await interaction.edit_original_response(
                embed=discord.Embed(description=f"{config.Icons.cross} Missing permissions to unmute this user.", color=config.Discord.danger_color)
            )

        # Remove stored timeout entry + DM user
        ta = datasys.load_temp_actions(interaction.guild.id)
        ta["timeouts"] = [t for t in ta["timeouts"] if t.get("user_id") != user.id]
        datasys.save_temp_actions(interaction.guild.id, ta)

        try:
            dm_embed = discord.Embed(
                title=f"ACTION // UNMUTE // {interaction.guild.name}",
                description="You can now send messages again.",
                color=config.Discord.success_color,
            )
            dm_embed.add_field(name="Moderator", value=str(interaction.user), inline=False)
            dm_embed.set_footer(text="Baxi · avocloud.net")
            await user.send(embed=dm_embed)
        except (discord.Forbidden, discord.HTTPException):
            pass

        embed = discord.Embed(
            title=f"{config.Icons.info} ACTION // UNMUTE",
            description=f"{user.mention} has been unmuted.",
            color=config.Discord.success_color,
        )
        embed.set_footer(text="Baxi · avocloud.net")
        await interaction.edit_original_response(embed=embed)

    # --- Warning System ---

    @bot.tree.command(name="warn", description="Warn a user.")
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.describe(user="The user to warn.", reason="Reason for the warning.")
    async def warn_cmd(interaction: Interaction, user: discord.Member, reason: str = "N/A"):
        if interaction.guild is None:
            lang = datasys.load_lang_file(1001)
            return await interaction.response.send_message(
                embed=discord.Embed(title="ERROR // SERVER ONLY", color=config.Discord.warn_color)
            )
        await interaction.response.defer()
        lang = datasys.load_lang_file(interaction.guild.id)
        try:
            await add_warning(
                guild_id=interaction.guild.id,
                user=user,
                moderator=interaction.user,
                reason=reason,
                bot=bot,
                channel=interaction.channel,
            )
            await interaction.delete_original_response()
        except Exception as e:
            await interaction.edit_original_response(
                embed=discord.Embed(
                    title=f'WARN FAILED // {user.name}',
                    description=str(lang["commands"]["admin"]["warn"]["error"]).format(error=str(e)),
                    color=config.Discord.danger_color,
                )
            )

    @bot.tree.command(name="unwarn", description="Remove a warning from a user.")
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.describe(user="The user to remove the warning from.", warn_id="The warning ID to remove.")
    async def unwarn_cmd(interaction: Interaction, user: discord.Member, warn_id: str):
        if interaction.guild is None:
            lang = datasys.load_lang_file(1001)
            return await interaction.response.send_message(
                embed=discord.Embed(title="ERROR // SERVER ONLY", color=config.Discord.warn_color)
            )
        lang = datasys.load_lang_file(interaction.guild.id)
        removed = await remove_warning(interaction.guild.id, user.id, warn_id)
        if removed:
            embed = discord.Embed(
                title=f"{config.Icons.info} {lang['commands']['admin']['unwarn']['title']} // {user.name}",
                description=str(lang["commands"]["admin"]["unwarn"]["success"]).format(id=warn_id, user=user.mention),
                color=config.Discord.success_color,
            )
        else:
            embed = discord.Embed(
                title=f'WARN NOT FOUND // {user.name} // ID {warn_id}',
                description=str(lang["commands"]["admin"]["unwarn"]["not_found"]).format(id=warn_id),
                color=config.Discord.danger_color,
            )
        await interaction.response.send_message(embed=embed)

    @bot.tree.command(name="warnings", description="View all warnings for a user.")
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.describe(user="The user to check warnings for.")
    async def warnings_cmd(interaction: Interaction, user: discord.Member):
        if interaction.guild is None:
            lang = datasys.load_lang_file(1001)
            return await interaction.response.send_message(
                embed=discord.Embed(title="ERROR // SERVER ONLY", color=config.Discord.warn_color)
            )
        lang = datasys.load_lang_file(interaction.guild.id)
        warns = get_warnings(interaction.guild.id, user.id)

        if not warns:
            embed = discord.Embed(
                title=f"{config.Icons.info} {lang['commands']['admin']['warnings']['title']} // {user.name} // CLEAN",
                description=str(lang["commands"]["admin"]["warnings"]["no_warnings"]).format(user=user.mention),
                color=config.Discord.color,
            )
        else:
            description = ""
            for warn in warns:
                description += str(lang["commands"]["admin"]["warnings"]["entry"]).format(
                    id=warn["id"], reason=warn["reason"], mod=warn["mod"], date=warn["date"]
                ) + "\n\n"
            embed = discord.Embed(
                title=f"{config.Icons.alert} {lang['commands']['admin']['warnings']['title']} - {user.name} ({len(warns)})",
                description=description,
                color=config.Discord.warn_color,
            )

        await interaction.response.send_message(embed=embed)

    # --- BaxiInsights ---

    insights_group = app_commands.Group(
        name="insights",
        description="BaxiInsights -  server moderation statistics",
    )

    @insights_group.command(name="stats", description="Show a quick overview of moderation stats (last 30 days).")
    async def insights_stats(interaction: discord.Interaction):
        if interaction.guild is None:
            return await interaction.response.send_message(
                embed=discord.Embed(title="ERROR // SERVER ONLY", color=config.Discord.warn_color),
                ephemeral=True,
            )
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message(
                embed=discord.Embed(description=f"{config.Icons.cross} You need Manage Server permission to use this command.", color=config.Discord.danger_color),
                ephemeral=True,
            )
        await interaction.response.defer(ephemeral=True)
        try:
            import json as _json
            import os as _os
            cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=30)
            guild_id = interaction.guild.id

            # Load mod events
            mod_path = _os.path.join("data", str(guild_id), "mod_events.json")
            mod_events = []
            if _os.path.exists(mod_path):
                try:
                    with open(mod_path, "r") as f:
                        mod_events = _json.load(f)
                except Exception:
                    pass
            recent_mod = [e for e in mod_events if datetime.datetime.fromisoformat(e.get("timestamp", "2000-01-01")) >= cutoff]
            warns  = sum(1 for e in recent_mod if e.get("type") == "warn")
            kicks  = sum(1 for e in recent_mod if e.get("type") == "kick")
            bans   = sum(1 for e in recent_mod if e.get("type") == "ban")
            mutes  = sum(1 for e in recent_mod if e.get("type") == "mute")

            # Load filter events
            filter_path = _os.path.join("data", str(guild_id), "filter_events.json")
            filter_events = []
            if _os.path.exists(filter_path):
                try:
                    with open(filter_path, "r") as f:
                        filter_events = _json.load(f)
                except Exception:
                    pass
            recent_filter = [e for e in filter_events if datetime.datetime.fromisoformat(e.get("timestamp", "2000-01-01")) >= cutoff]

            # Health score
            member_count = max(interaction.guild.member_count or 1, 1)
            mod_rate = len(recent_mod) / member_count
            filter_rate = len(recent_filter) / max(member_count * 30, 1)
            health = 100 - (mod_rate * 20) - (filter_rate * 15)
            health = max(0, min(100, round(health)))

            insights_url = f"https://{config.Web.url}/guild/insights/?guild_login={guild_id}"
            embed = discord.Embed(
                title=f"{config.Icons.stats} BaxiInsights // {interaction.guild.name}",
                description=f"Moderation overview -  last 30 days\n[**View full dashboard →**]({insights_url})",
                color=config.Discord.color,
            )
            embed.add_field(name=f"{config.Icons.alert} Warns", value=str(warns), inline=True)
            embed.add_field(name=f"{config.Icons.people_crossed} Kicks", value=str(kicks), inline=True)
            embed.add_field(name=f"{config.Icons.people_crossed} Bans", value=str(bans), inline=True)
            embed.add_field(name=f"{config.Icons.mute} Mutes", value=str(mutes), inline=True)
            embed.add_field(name=f"{config.Icons.shield} Filter Hits", value=str(len(recent_filter)), inline=True)
            color_health = config.Discord.success_color if health >= 70 else (config.Discord.warn_color if health >= 40 else config.Discord.danger_color)
            embed.add_field(name=f"{config.Icons.health} Health Score", value=f"{health}/100", inline=True)
            embed.set_footer(text="Baxi · avocloud.net")
            await interaction.edit_original_response(embed=embed)
        except Exception as e:
            logger.error(f"[insights stats] {e}")
            await interaction.edit_original_response(
                embed=discord.Embed(title="ERROR", description="Could not load insights.", color=config.Discord.danger_color)
            )

    bot.tree.add_command(insights_group)


def leveling_commands(bot: commands.AutoShardedBot):
    logger.debug.info("Leveling commands loaded.")

    import assets.leveling as leveling_sys

    def _disabled_embed(t: dict) -> Embed:
        return Embed(title=t["disabled_title"], description=t["disabled_desc"], color=config.Discord.warn_color)

    def _check_enabled(leveling_cfg: dict) -> bool:
        return bool(leveling_cfg.get("enabled", False))

    @bot.tree.command(name="level", description="Show your current level and XP progress on this server")
    async def level_cmd(interaction: discord.Interaction):
        await interaction.response.defer()
        if interaction.guild is None:
            lang = datasys.load_lang_file(0)
            await interaction.followup.send(lang["commands"]["guild_only"], ephemeral=True)
            return

        guild_id = interaction.guild.id
        lang = datasys.load_lang_file(guild_id)
        t: dict = lang["leveling"]

        if not _check_enabled(dict(datasys.load_data(guild_id, "leveling"))):
            await interaction.edit_original_response(embed=_disabled_embed(t))
            return

        entry = leveling_sys.get_user_entry(guild_id, interaction.user.id)
        total_xp: int = int(entry.get("xp", 0))
        cur_level, xp_into, xp_needed = leveling_sys.xp_progress(total_xp)

        bar_filled = int((xp_into / xp_needed) * 20) if xp_needed else 20
        bar = "█" * bar_filled + "░" * (20 - bar_filled)

        embed = Embed(
            title=t["level_title"].format(user=interaction.user.display_name),
            color=config.Discord.color,
        )
        embed.add_field(name=t["level_field"], value=str(cur_level), inline=True)
        embed.add_field(name=t["xp_field"], value=f"{total_xp:,} XP", inline=True)
        embed.add_field(
            name=t["progress_field"],
            value=f"`{bar}` {xp_into:,} / {xp_needed:,} XP",
            inline=False,
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.set_footer(text="Baxi · avocloud.net")
        await interaction.edit_original_response(embed=embed)

    @bot.tree.command(name="leaderboard", description="Show the top users for a given system on this server")
    @app_commands.describe(sys="Which leaderboard to show")
    @app_commands.choices(sys=[
        app_commands.Choice(name="Level", value="level"),
        app_commands.Choice(name="Flag Quiz", value="flagquiz"),
    ])
    async def leaderboard_cmd(interaction: discord.Interaction, sys: app_commands.Choice[str]):
        await interaction.response.defer()
        if interaction.guild is None:
            lang = datasys.load_lang_file(0)
            await interaction.followup.send(lang["commands"]["guild_only"], ephemeral=True)
            return

        guild_id = interaction.guild.id
        lang = datasys.load_lang_file(guild_id)

        if sys.value == "flagquiz":
            from assets.games import quiz as quiz_sys
            t_fq: dict = lang["games"]["flag_quiz"]
            entries = quiz_sys.get_leaderboard(guild_id, bot)[:10]
            if not entries:
                await interaction.edit_original_response(embed=Embed(
                    title=f"{config.Icons.trophy} " + t_fq["leaderboard_title"],
                    description=t_fq["leaderboard_empty"],
                    color=config.Discord.color,
                ))
                return

            medals = [config.Icons.medal, config.Icons.medal, config.Icons.medal]
            lines = []
            for i, (name, pts) in enumerate(entries):
                prefix = medals[i] if i < 3 else f"`{i + 1}.`"
                pts_label = t_fq["leaderboard_pts_single"] if pts == 1 else t_fq["leaderboard_pts_plural"]
                lines.append(f"{prefix} **{name}** -  {pts} {pts_label}")

            embed = Embed(
                title=f"{config.Icons.trophy} " + t_fq["leaderboard_title"],
                description="\n".join(lines),
                color=config.Discord.color,
            )
            embed.set_footer(text="Baxi · avocloud.net")
            await interaction.edit_original_response(embed=embed)
            return

        t: dict = lang["leveling"]

        if not _check_enabled(dict(datasys.load_data(guild_id, "leveling"))):
            await interaction.edit_original_response(embed=_disabled_embed(t))
            return

        users: dict = leveling_sys._load_users(guild_id)
        if not users:
            await interaction.edit_original_response(embed=Embed(
                title=t["leaderboard_title"].format(guild=interaction.guild.name),
                description=t["leaderboard_empty"],
                color=config.Discord.color,
            ))
            return

        sorted_users = sorted(users.items(), key=lambda x: int(x[1].get("xp", 0)), reverse=True)[:10]

        medals = [config.Icons.medal, config.Icons.medal, config.Icons.medal]
        lines = []
        for i, (uid, data) in enumerate(sorted_users):
            prefix = medals[i] if i < 3 else f"`{i + 1}.`"
            member = interaction.guild.get_member(int(uid))
            name = member.display_name if member else data.get("name", f"User {uid}")
            lvl = leveling_sys.current_level_from_xp(int(data.get("xp", 0)))
            xp_val = int(data.get("xp", 0))
            lines.append(f"{prefix} **{name}** -  Level {lvl} · {xp_val:,} XP")

        embed = Embed(
            title=t["leaderboard_title"].format(guild=interaction.guild.name),
            description="\n".join(lines),
            color=config.Discord.color,
        )
        embed.set_footer(text="Baxi · avocloud.net")
        await interaction.edit_original_response(embed=embed)

    @bot.tree.command(name="rank", description="Show a user's level on this server")
    @app_commands.describe(user="The user to look up (defaults to yourself)")
    async def rank_cmd(interaction: discord.Interaction, user: Optional[discord.Member] = None):
        await interaction.response.defer()
        if interaction.guild is None:
            lang = datasys.load_lang_file(0)
            await interaction.followup.send(lang["commands"]["guild_only"], ephemeral=True)
            return

        guild_id = interaction.guild.id
        lang = datasys.load_lang_file(guild_id)
        t: dict = lang["leveling"]

        if not _check_enabled(dict(datasys.load_data(guild_id, "leveling"))):
            await interaction.edit_original_response(embed=_disabled_embed(t))
            return

        target = user or interaction.user
        users: dict = leveling_sys._load_users(guild_id)
        entry: dict = users.get(str(target.id), {})

        total_xp = int(entry.get("xp", 0))
        msgs = int(entry.get("messages", 0))
        cur_level, xp_into, xp_needed = leveling_sys.xp_progress(total_xp)

        sorted_users = sorted(users.items(), key=lambda x: int(x[1].get("xp", 0)), reverse=True)
        rank_pos = next((i + 1 for i, (uid, _) in enumerate(sorted_users) if uid == str(target.id)), None)

        bar_filled = int((xp_into / xp_needed) * 20) if xp_needed else 20
        bar = "█" * bar_filled + "░" * (20 - bar_filled)

        embed = Embed(
            title=t["rank_title"].format(user=target.display_name),
            color=config.Discord.color,
        )
        embed.add_field(name=t["level_field"], value=str(cur_level), inline=True)
        embed.add_field(name=t["rank_xp_field"], value=f"{total_xp:,} XP", inline=True)
        embed.add_field(name=t["rank_msgs_field"], value=f"{msgs:,}", inline=True)
        embed.add_field(
            name=t["progress_field"],
            value=f"`{bar}` {xp_into:,} / {xp_needed:,} XP",
            inline=False,
        )
        if rank_pos is not None:
            embed.add_field(name=t["rank_pos_field"], value=f"#{rank_pos}", inline=True)
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.set_footer(text="Baxi · avocloud.net")
        await interaction.edit_original_response(embed=embed)


def mc_link_commands(bot: commands.AutoShardedBot):
    logger.debug.info("MC link commands loaded.")

    mc_group = app_commands.Group(name="mc", description="Minecraft account linking")
    mc_admin_group = app_commands.Group(name="admin", description="MC Link admin commands", parent=mc_group)

    def _get_conf(guild_id: int):
        return datasys.load_data(guild_id, "mc_link")

    def _check_enabled(guild_conf: dict, t: dict) -> str | None:
        if not guild_conf.get("enabled", False):
            return t["not_enabled"]
        if not guild_conf.get("api_url", "").strip() or not guild_conf.get("api_secret", "").strip():
            return t["not_configured"]
        return None

    async def _announce_link(interaction: Interaction, guild_conf: dict, mc_name: str, lang: dict):
        channel_id_str: str = guild_conf.get("announce_channel", "")
        if not channel_id_str:
            return
        try:
            channel = interaction.guild.get_channel(int(channel_id_str))
            if channel:
                t = lang["systems"]["mc_link"]
                embed = discord.Embed(
                    description=t["announce"].format(mention=interaction.user.mention, mc_name=mc_name),
                    color=config.Discord.success_color,
                )
                embed.set_footer(text=t["footer"])
                await channel.send(embed=embed)
        except Exception:
            pass

    async def _dm_user(interaction: Interaction, guild_conf: dict, mc_name: str, lang: dict):
        if not guild_conf.get("dm_on_link", False):
            return
        try:
            t = lang["systems"]["mc_link"]
            embed = discord.Embed(
                title=f"{config.Icons.check} {t['success_title']}",
                description=t["dm_desc"].format(mc_name=mc_name, guild=interaction.guild.name),
                color=config.Discord.success_color,
            )
            embed.set_footer(text=t["footer"])
            await interaction.user.send(embed=embed)
        except Exception:
            pass

    @mc_group.command(name="link", description="Link your Minecraft account to Discord.")
    @app_commands.describe(code="The 8-character code shown in the Minecraft kick message.")
    async def mc_link_cmd(interaction: Interaction, code: str):
        await interaction.response.defer(ephemeral=True)

        if interaction.guild is None:
            lang = datasys.load_lang_file(1001)
            t = lang["systems"]["mc_link"]
            return await interaction.followup.send(
                embed=discord.Embed(description=f"{config.Icons.cross} {t['server_only']}", color=config.Discord.danger_color),
                ephemeral=True,
            )

        guild_id = interaction.guild.id
        lang = datasys.load_lang_file(guild_id)
        t = lang["systems"]["mc_link"]
        guild_conf = _get_conf(guild_id)

        err = _check_enabled(guild_conf, t)
        if err:
            return await interaction.followup.send(
                embed=discord.Embed(description=f"{config.Icons.cross} {err}", color=config.Discord.danger_color),
                ephemeral=True,
            )

        api_url: str = guild_conf["api_url"].strip()
        secret: str = guild_conf["api_secret"].strip()

        from assets.mc_link import is_linked, resolve_token, whitelist_player, store_link

        if is_linked(guild_id, interaction.user.id):
            return await interaction.followup.send(
                embed=discord.Embed(description=f"{config.Icons.check} {t['already_linked']}", color=config.Discord.success_color),
                ephemeral=True,
            )

        token_data = await resolve_token(api_url, secret, code.strip().upper())
        if token_data is None:
            return await interaction.followup.send(
                embed=discord.Embed(title=f"{config.Icons.cross} {t['invalid_code']}", color=config.Discord.danger_color),
                ephemeral=True,
            )

        uuid: str = token_data["uuid"]
        mc_name: str = token_data.get("name", "Unknown")
        discord_name: str = interaction.user.name

        success = await whitelist_player(api_url, secret, uuid, mc_name, interaction.user.id, discord_name)
        if not success:
            return await interaction.followup.send(
                embed=discord.Embed(title=f"{config.Icons.cross} {t['link_failed']}", color=config.Discord.danger_color),
                ephemeral=True,
            )

        await store_link(guild_id, interaction.user.id, uuid, mc_name)

        role_id_str: str = guild_conf.get("role_id", "")
        if role_id_str:
            try:
                role = interaction.guild.get_role(int(role_id_str))
                if role:
                    await cast(discord.Member, interaction.user).add_roles(role, reason="MC account linked")
            except Exception:
                pass

        desc = t["success_desc"].format(mc_name=mc_name, mention=interaction.user.mention)
        embed = discord.Embed(
            title=f"{config.Icons.check} {t['success_title']}",
            description=desc,
            color=config.Discord.success_color,
        )
        embed.set_footer(text=t["footer"])
        await interaction.followup.send(embed=embed, ephemeral=True)

        await _announce_link(interaction, guild_conf, mc_name, lang)
        await _dm_user(interaction, guild_conf, mc_name, lang)

    @mc_group.command(name="unlink", description="Unlink your Minecraft account.")
    async def mc_unlink_cmd(interaction: Interaction):
        await interaction.response.defer(ephemeral=True)

        if interaction.guild is None:
            lang = datasys.load_lang_file(1001)
            t = lang["systems"]["mc_link"]
            return await interaction.followup.send(
                embed=discord.Embed(description=f"{config.Icons.cross} {t['server_only']}", color=config.Discord.danger_color),
                ephemeral=True,
            )

        guild_id = interaction.guild.id
        lang = datasys.load_lang_file(guild_id)
        t = lang["systems"]["mc_link"]
        guild_conf = _get_conf(guild_id)

        err = _check_enabled(guild_conf, t)
        if err:
            return await interaction.followup.send(
                embed=discord.Embed(description=f"{config.Icons.cross} {err}", color=config.Discord.danger_color),
                ephemeral=True,
            )

        from assets.mc_link import is_linked, get_link, unlink_player, remove_link

        if not is_linked(guild_id, interaction.user.id):
            return await interaction.followup.send(
                embed=discord.Embed(description=f"{config.Icons.cross} {t['not_linked']}", color=config.Discord.danger_color),
                ephemeral=True,
            )

        if not guild_conf.get("allow_self_unlink", True):
            return await interaction.followup.send(
                embed=discord.Embed(description=f"{config.Icons.cross} {t['unlink_disabled']}", color=config.Discord.danger_color),
                ephemeral=True,
            )

        link = get_link(guild_id, interaction.user.id)
        uuid = link["uuid"]
        mc_name = link.get("name", "Unknown")

        api_url: str = guild_conf["api_url"].strip()
        secret: str = guild_conf["api_secret"].strip()

        # Always clean up Baxi side. MC-side failure (unreachable) = warn but still unlink locally.
        mc_success = await unlink_player(api_url, secret, uuid)
        await remove_link(guild_id, interaction.user.id)

        role_id_str: str = guild_conf.get("role_id", "")
        if role_id_str:
            try:
                role = interaction.guild.get_role(int(role_id_str))
                if role:
                    await cast(discord.Member, interaction.user).remove_roles(role, reason="MC account unlinked")
            except Exception:
                pass

        desc = t["unlink_success_desc"].format(mc_name=mc_name)
        if not mc_success:
            desc += f"\n{config.Icons.alert} MC server unreachable — removed locally. Ask an admin to de-whitelist manually."
        await interaction.followup.send(
            embed=discord.Embed(
                title=f"{config.Icons.check} {t['unlink_success_title']}",
                description=desc,
                color=config.Discord.success_color,
            ),
            ephemeral=True,
        )

    @mc_group.command(name="status", description="Show your linked Minecraft account.")
    async def mc_status_cmd(interaction: Interaction):
        await interaction.response.defer(ephemeral=True)

        if interaction.guild is None:
            lang = datasys.load_lang_file(1001)
            t = lang["systems"]["mc_link"]
            return await interaction.followup.send(
                embed=discord.Embed(description=f"{config.Icons.cross} {t['server_only']}", color=config.Discord.danger_color),
                ephemeral=True,
            )

        guild_id = interaction.guild.id
        lang = datasys.load_lang_file(guild_id)
        t = lang["systems"]["mc_link"]

        from assets.mc_link import is_linked, get_link

        if not is_linked(guild_id, interaction.user.id):
            return await interaction.followup.send(
                embed=discord.Embed(description=f"{config.Icons.cross} {t['not_linked']}", color=config.Discord.danger_color),
                ephemeral=True,
            )

        link = get_link(guild_id, interaction.user.id)
        mc_name = link.get("name", "Unknown")
        import datetime
        linked_at = link.get("linked_at", 0)
        linked_dt = f"<t:{linked_at}:R>" if linked_at else "—"

        embed = discord.Embed(
            title=f"{config.Icons.check} {t['status_title']}",
            description=t["status_desc"].format(mc_name=mc_name, mention=interaction.user.mention, linked_at=linked_dt),
            color=config.Discord.info_color,
        )
        embed.set_footer(text=t["footer"])
        await interaction.followup.send(embed=embed, ephemeral=True)

    @mc_admin_group.command(name="unlink", description="Force-unlink a Discord user's Minecraft account.")
    @app_commands.describe(user="The Discord user to unlink.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def mc_admin_unlink_cmd(interaction: Interaction, user: discord.Member):
        await interaction.response.defer(ephemeral=True)

        if interaction.guild is None:
            return

        guild_id = interaction.guild.id
        lang = datasys.load_lang_file(guild_id)
        t = lang["systems"]["mc_link"]
        guild_conf = _get_conf(guild_id)

        err = _check_enabled(guild_conf, t)
        if err:
            return await interaction.followup.send(
                embed=discord.Embed(description=f"{config.Icons.cross} {err}", color=config.Discord.danger_color),
                ephemeral=True,
            )

        from assets.mc_link import is_linked, get_link, unlink_player, remove_link

        if not is_linked(guild_id, user.id):
            return await interaction.followup.send(
                embed=discord.Embed(description=f"{config.Icons.cross} {t['not_linked']}", color=config.Discord.danger_color),
                ephemeral=True,
            )

        link = get_link(guild_id, user.id)
        uuid = link["uuid"]
        mc_name = link.get("name", "Unknown")

        api_url: str = guild_conf["api_url"].strip()
        secret: str = guild_conf["api_secret"].strip()
        await unlink_player(api_url, secret, uuid)
        await remove_link(guild_id, user.id)

        role_id_str: str = guild_conf.get("role_id", "")
        if role_id_str:
            try:
                role = interaction.guild.get_role(int(role_id_str))
                if role:
                    await user.remove_roles(role, reason="MC account force-unlinked by admin")
            except Exception:
                pass

        await interaction.followup.send(
            embed=discord.Embed(
                description=t["admin_unlink_success"].format(mention=user.mention, mc_name=mc_name),
                color=config.Discord.success_color,
            ),
            ephemeral=True,
        )

    @mc_admin_group.command(name="link", description="Manually link a Minecraft account to a Discord user.")
    @app_commands.describe(mc_name="Minecraft username.", user="Discord user to link to.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def mc_admin_link_cmd(interaction: Interaction, mc_name: str, user: discord.Member):
        await interaction.response.defer(ephemeral=True)

        if interaction.guild is None:
            return

        guild_id = interaction.guild.id
        lang = datasys.load_lang_file(guild_id)
        t = lang["systems"]["mc_link"]
        guild_conf = _get_conf(guild_id)

        err = _check_enabled(guild_conf, t)
        if err:
            return await interaction.followup.send(
                embed=discord.Embed(description=f"{config.Icons.cross} {err}", color=config.Discord.danger_color),
                ephemeral=True,
            )

        api_url: str = guild_conf["api_url"].strip()
        secret: str = guild_conf["api_secret"].strip()

        from assets.mc_link import admin_link_player, store_link, is_linked

        result = await admin_link_player(api_url, secret, mc_name.strip(), user.id, user.name)
        if result is None:
            return await interaction.followup.send(
                embed=discord.Embed(
                    description=f"{config.Icons.cross} Failed — MC server unreachable or player has never joined.",
                    color=config.Discord.danger_color,
                ),
                ephemeral=True,
            )

        uuid: str = result["uuid"]
        await store_link(guild_id, user.id, uuid, mc_name.strip())

        role_id_str: str = guild_conf.get("role_id", "")
        if role_id_str:
            try:
                role = interaction.guild.get_role(int(role_id_str))
                if role:
                    await user.add_roles(role, reason="MC account manually linked by admin")
            except Exception:
                pass

        await interaction.followup.send(
            embed=discord.Embed(
                description=f"{config.Icons.check} Linked `{mc_name}` → {user.mention} and whitelisted.",
                color=config.Discord.success_color,
            ),
            ephemeral=True,
        )

    @mc_admin_group.command(name="lookup", description="Show which Minecraft account a Discord user has linked.")
    @app_commands.describe(user="The Discord user to look up.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def mc_admin_lookup_cmd(interaction: Interaction, user: discord.Member):
        await interaction.response.defer(ephemeral=True)

        if interaction.guild is None:
            return

        guild_id = interaction.guild.id
        lang = datasys.load_lang_file(guild_id)
        t = lang["systems"]["mc_link"]

        from assets.mc_link import is_linked, get_link

        if not is_linked(guild_id, user.id):
            return await interaction.followup.send(
                embed=discord.Embed(description=f"{config.Icons.cross} {t['not_linked']}", color=config.Discord.danger_color),
                ephemeral=True,
            )

        link = get_link(guild_id, user.id)
        mc_name = link.get("name", "Unknown")
        uuid = link.get("uuid", "—")
        linked_at = link.get("linked_at", 0)
        linked_dt = f"<t:{linked_at}:R>" if linked_at else "—"

        embed = discord.Embed(
            title=t["lookup_title"],
            description=t["lookup_desc"].format(mention=user.mention, mc_name=mc_name, uuid=uuid, linked_at=linked_dt),
            color=config.Discord.info_color,
        )
        embed.set_footer(text=t["footer"])
        await interaction.followup.send(embed=embed, ephemeral=True)

    bot.tree.add_command(mc_group)


def bot_admin_commands(bot: commands.AutoShardedBot):
    """Bot admin commands have been moved to the Admin Dashboard at /admin/"""
    logger.debug.info("Bot admin commands: all admin actions are now handled via the web dashboard at /admin/.")

