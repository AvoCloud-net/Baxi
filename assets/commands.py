import discord

from discord.ext import commands
from discord import Embed, Interaction, app_commands
import config.config as config
import assets.data as datasys
from typing import cast, Optional
import datetime

from assets.buttons import (
    BanConfirmView,
    KickConfirmView,
    UbanConfirmView,
    ClearConfirmView,
)
from assets.message.warnings import add_warning, remove_warning, get_warnings
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
                    embed.add_field(
                        name=f"{i}. {user['name']}",
                        value=f"-  **{lang["commands"]["user"]["scan_users"]["reason"]}:** {user['reason']}\n"
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
                    "❌ Invalid duration format. Use e.g. `7d`, `2h`, `30m`, `1w`.", ephemeral=True
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
                "❌ Dieser Channel unterstützt keine Nachrichten.", ephemeral=True
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
                embed=discord.Embed(description="❌ You cannot mute someone with an equal or higher role.", color=config.Discord.danger_color)
            )

        parsed = datasys.parse_duration(duration)
        if not parsed:
            return await interaction.edit_original_response(
                embed=discord.Embed(description="❌ Invalid duration format. Use e.g. `10m`, `1h`, `7d`.", color=config.Discord.danger_color)
            )
        if parsed.total_seconds() > 28 * 86400:
            return await interaction.edit_original_response(
                embed=discord.Embed(description="❌ Maximum timeout duration is 28 days.", color=config.Discord.danger_color)
            )

        duration_str = datasys.format_duration(parsed)
        until = discord.utils.utcnow() + parsed
        until_naive = datetime.datetime.utcnow() + parsed

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
                embed=discord.Embed(description="❌ Missing permissions to timeout this user.", color=config.Discord.danger_color)
            )

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
                embed=discord.Embed(description="❌ Missing permissions to unmute this user.", color=config.Discord.danger_color)
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



def bot_admin_commands(bot: commands.AutoShardedBot):
    logger.debug.info("Bot admin commands loaded.")

    @bot.tree.command(name="flag-user", description="Flag a user as global troublemaker, triggering increased scrutiny and potential consequences.")
    @app_commands.describe(user_id="The ID of the user you want to flag.")
    @app_commands.describe(reason="Why do you want to flag this user?")
    async def flag_user_command(interaction: discord.Interaction, user_id: str, reason: str):
        admins: list = list(datasys.load_data(1001, "admins"))
        guild_id: int = interaction.guild.id if interaction.guild is not None else 0
        lang: dict = dict(datasys.load_lang_file(guild_id))

        if interaction.user.id not in admins:
            await interaction.response.send_message(lang["commands"]["admin"]["missing_perms"])
            return

        if not user_id.isdigit():
            await interaction.response.send_message(lang["commands"]["admin"]["flag_user"]["invalid_user_id"])
            return

        userid: int = int(user_id)
        users_list: dict = dict(datasys.load_data(1001, "users"))

        try:
            selected_user = await bot.fetch_user(userid)
        except discord.NotFound:
            await interaction.response.send_message(lang["commands"]["admin"]["flag_user"]["user_not_found"])
            return
        except Exception as e:
            await interaction.response.send_message(lang["commands"]["admin"]["flag_user"]["fetch_error"].format(error=str(e)))
            return

        users_list[str(selected_user.id)] = {
            "entry_date": str(datetime.date.today()),
            "id": selected_user.id,
            "name": selected_user.name,
            "reason": reason,
            "flagged": True
        }

        datasys.save_data(1001, "users", users_list)

        await interaction.response.send_message(config.Icons.people_crossed + lang["commands"]["admin"]["flag_user"]["success"])


    @bot.tree.command(name="deflag-user", description="Deflag a user as global troublemaker, triggering increased scrutiny and potential consequences.")
    @app_commands.describe(user="User you want to deflag.")
    @app_commands.describe(user_id="The ID of the user you want to deflag.")
    @app_commands.describe(reason="Why do you want to deflag this user?")
    async def deflag_user_command(interaction: discord.Interaction, reason: str, user: Optional[discord.Member] = None, user_id: Optional[int] = 0):
        admins: list = list(datasys.load_data(1001, "admins"))
        guild_id: int = interaction.guild.id if interaction.guild is not None else 0
        lang: dict = dict(datasys.load_lang_file(guild_id))

        if interaction.user.id not in admins:
            await interaction.response.send_message(lang["commands"]["admin"]["missing_perms"])
            return
        
        if user is None and user_id == 0:
            await interaction.response.send_message(lang["commands"]["admin"]["flag_user"]["missing_parameters"])
            return

        userid: int = user.id if user is not None else (user_id or 0)

        users_list: dict = dict(datasys.load_data(1001, "users"))
        selected_user = await bot.fetch_user(userid)

        users_list[str(selected_user.id)]["flagged"] = False

        datasys.save_data(1001, "users", users_list)

        await interaction.response.send_message(config.Icons.people_crossed + "" + lang["commands"]["admin"]["deflag_user"]["success"])


    @bot.tree.command(name="gc_delete", description="Delete a global chat message. Users can delete their own messages, admins can delete any.")
    @app_commands.describe(message_id="The global chat message ID (shown in the message footer after '|')")
    async def gc_delete_command(interaction: discord.Interaction, message_id: str):
        admins: list = list(datasys.load_data(1001, "admins"))
        guild_id: int = interaction.guild.id if interaction.guild is not None else 0

        await interaction.response.defer(ephemeral=True)

        from assets.share import globalchat_message_data
        message_data = globalchat_message_data.get(message_id)

        if not message_data:
            return await interaction.edit_original_response(
                embed=discord.Embed(
                    title="ERROR // MSG NOT FOUND",
                    description=f"No global chat message found with ID `{message_id}`.",
                    color=config.Discord.danger_color,
                )
            )

        is_admin: bool = interaction.user.id in admins
        is_author: bool = message_data.get("author_id") == interaction.user.id

        if not is_admin and not is_author:
            return await interaction.edit_original_response(
                embed=discord.Embed(
                    title="ERROR // NO PERMISSION",
                    description="You can only delete your own messages.",
                    color=config.Discord.danger_color,
                )
            )

        deleted = 0
        failed = 0
        for msg_entry in message_data.get("messages", []):
            try:
                guild = bot.get_guild(msg_entry["gid"])
                if guild is None:
                    failed += 1
                    continue
                channel = guild.get_channel(msg_entry["channel"])
                if not isinstance(channel, discord.TextChannel):
                    failed += 1
                    continue
                msg = await channel.fetch_message(msg_entry["mid"])
                await msg.delete()
                deleted += 1
            except Exception:
                failed += 1

        del globalchat_message_data[message_id]

        embed = discord.Embed(
            title=f"{config.Icons.people_crossed} EXEC // MSG DELETED",
            description=f"Deleted **{deleted}** message cop{'y' if deleted == 1 else 'ies'} across all servers.",
            color=config.Discord.success_color,
        )
        if failed:
            embed.add_field(name="⚠️ Failed", value=f"{failed} cop{'y' if failed == 1 else 'ies'} could not be deleted.", inline=False)
        await interaction.edit_original_response(embed=embed)


    @bot.tree.command(name="sys_bulk_config", description="[SYSTEM] Bulk-edit a feature setting across all or a percentage of servers.")
    @app_commands.describe(
        feature="Feature to configure: chatfilter, antispam, ticket, auto_roles, temp_voice, livestream",
        action="'enable' or 'disable'",
        percent="Percentage of servers to apply to (1–100, default: 100)",
    )
    async def sys_bulk_config_command(
        interaction: discord.Interaction,
        feature: str,
        action: str,
        percent: int = 100,
    ):
        admins: list = list(datasys.load_data(1001, "admins"))
        if interaction.user.id not in admins:
            return await interaction.response.send_message(
                embed=discord.Embed(description="❌ Missing permissions.", color=config.Discord.danger_color),
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True)

        valid_features = ["chatfilter", "antispam", "ticket", "auto_roles", "temp_voice", "livestream"]
        if feature not in valid_features:
            return await interaction.edit_original_response(
                embed=discord.Embed(
                    title="ERROR // INVALID FEATURE",
                    description=f"Valid features: {', '.join(f'`{f}`' for f in valid_features)}",
                    color=config.Discord.danger_color,
                )
            )

        if action not in ("enable", "disable"):
            return await interaction.edit_original_response(
                embed=discord.Embed(
                    title="ERROR // INVALID ACTION",
                    description="Action must be `enable` or `disable`.",
                    color=config.Discord.danger_color,
                )
            )

        if not 1 <= percent <= 100:
            return await interaction.edit_original_response(
                embed=discord.Embed(
                    title="ERROR // INVALID PERCENTAGE",
                    description="Percentage must be between 1 and 100.",
                    color=config.Discord.danger_color,
                )
            )

        import random

        enable: bool = action == "enable"
        all_guilds = list(bot.guilds)
        count = max(1, round(len(all_guilds) * percent / 100))
        target_guilds = random.sample(all_guilds, count) if percent < 100 else all_guilds

        success = 0
        failed = 0
        for guild in target_guilds:
            try:
                feat_data = datasys.load_data(guild.id, feature)
                if not isinstance(feat_data, dict):
                    feat_data = {}
                feat_data["enabled"] = enable
                datasys.save_data(guild.id, feature, feat_data)
                success += 1
            except Exception:
                failed += 1

        embed = discord.Embed(
            title="EXEC // BULK CONFIG APPLIED",
            description=(
                f"**{action.capitalize()}d** `{feature}` on **{success}** of **{len(target_guilds)}** servers "
                f"({percent}% of {len(all_guilds)} total)."
            ),
            color=config.Discord.success_color if not failed else config.Discord.warn_color,
        )
        if failed:
            embed.add_field(name="⚠️ Failed", value=f"{failed} server(s) could not be updated.", inline=False)

        await interaction.edit_original_response(embed=embed)


    @bot.tree.command(name="search_server", description="Search for servers by name, ID, owner name, or owner ID.")
    @app_commands.describe(query="Partial name, server ID, owner name, or owner ID")
    async def search_server_command(interaction: discord.Interaction, query: str):
        admins: list = list(datasys.load_data(1001, "admins"))
        if interaction.user.id not in admins:
            guild_id = interaction.guild.id if interaction.guild else 0
            lang = datasys.load_lang_file(guild_id)
            await interaction.response.send_message(lang["commands"]["admin"]["missing_perms"])
            return

        await interaction.response.defer()

        query_lower = query.lower().strip()
        matching_guilds: list[discord.Guild] = []

        for guild in bot.guilds:
            if (
                query_lower in guild.name.lower()
                or query_lower in str(guild.id)
                or (guild.owner_id and query_lower in str(guild.owner_id))
            ):
                matching_guilds.append(guild)
                continue

            # Also search owner name from config
            try:
                owner_name = str(datasys.load_data(guild.id, "owner_name"))
                if owner_name and query_lower in owner_name.lower():
                    matching_guilds.append(guild)
            except Exception:
                pass

        if len(matching_guilds) == 0:
            embed = discord.Embed(
                title=f"{config.Icons.search} ERROR // KEINE SERVER",
                description=f"Keine Server gefunden für: `{query}`",
                color=config.Discord.warn_color,
            )
            return await interaction.edit_original_response(embed=embed)

        if len(matching_guilds) == 1:
            # Detailed view for a single result
            guild = matching_guilds[0]
            owner_id = guild.owner_id or 0
            owner_user = bot.get_user(owner_id)
            if owner_user is None and owner_id:
                try:
                    owner_user = await bot.fetch_user(owner_id)
                except Exception:
                    owner_user = None
            owner_display = f"{owner_user.name} (`{owner_id}`)" if owner_user else f"`{owner_id}`"

            text_channels = len(guild.text_channels)
            voice_channels = len(guild.voice_channels)
            categories = len(guild.categories)
            created_at = guild.created_at.strftime("%d.%m.%Y")
            boost_level = guild.premium_tier
            boost_count = guild.premium_subscription_count or 0

            embed = discord.Embed(
                title=f"{config.Icons.search} INFO // {guild.name}",
                color=config.Discord.color,
                timestamp=discord.utils.utcnow(),
            )
            if guild.icon:
                embed.set_thumbnail(url=guild.icon.url)
            if guild.banner:
                embed.set_image(url=guild.banner.url)

            embed.add_field(name="Server ID", value=f"`{guild.id}`", inline=True)
            embed.add_field(name="Inhaber", value=owner_display, inline=True)
            embed.add_field(name="Erstellt am", value=created_at, inline=True)
            embed.add_field(name="Mitglieder", value=str(guild.member_count), inline=True)
            embed.add_field(name="Rollen", value=str(len(guild.roles)), inline=True)
            embed.add_field(
                name="Kanäle",
                value=f"{text_channels} Text · {voice_channels} Voice · {categories} Kategorien",
                inline=True,
            )
            embed.add_field(name="Boost Level", value=f"Level {boost_level} ({boost_count} Boosts)", inline=True)
            embed.add_field(name="Sprache (Config)", value=str(datasys.load_data(guild.id, "lang") or "en"), inline=True)

            terms = datasys.load_data(guild.id, "terms")
            embed.add_field(name="Terms akzeptiert", value="Ja" if terms else "Nein", inline=True)

            embed.set_footer(text="Baxi · avocloud.net")
            return await interaction.edit_original_response(embed=embed)

        # List view for multiple results (max 25 shown)
        shown = matching_guilds[:25]
        lines = []
        for i, guild in enumerate(shown, 1):
            owner_id = guild.owner_id or 0
            lines.append(
                f"**{i}.** {guild.name} · `{guild.id}` · {guild.member_count} Mitglieder · Inhaber: `{owner_id}`"
            )
        if len(matching_guilds) > 25:
            lines.append(f"\n*... und {len(matching_guilds) - 25} weitere Ergebnisse. Verfeinere deine Suche.*")

        embed = discord.Embed(
            title=f"{config.Icons.search} SYS // {len(matching_guilds)} SERVER GEFUNDEN",
            description="\n".join(lines),
            color=config.Discord.color,
        )
        embed.set_footer(text=f"Suche: {query}  |  Baxi · avocloud.net")
        await interaction.edit_original_response(embed=embed)


    @bot.tree.command(name="gc_msg_info", description="Displays information about a message in the global chat.")
    @app_commands.describe(mid="Message ID from message embed")
    async def gc_msg_info_command(interaction: discord.Interaction, mid: str):
        admins = list(datasys.load_data(1001, "admins"))
        guild_id = interaction.guild.id if interaction.guild is not None else 0
        lang = dict(datasys.load_lang_file(guild_id))

        if interaction.user.id not in admins:
            await interaction.response.send_message(lang["commands"]["admin"]["missing_perms"])
            return
        
        from assets.share import globalchat_message_data
        message_data = globalchat_message_data.get(mid)
        
        if not message_data:
            embed = discord.Embed(
                title="ERROR // MSG NOT FOUND",
                description=f"No message data found for ID: `{mid}`",
                color=config.Discord.danger_color
            )
            await interaction.response.send_message(embed=embed)
            return

        embed = discord.Embed(
            title="SYS // GLOBALCHAT MSG INFO",
            description=f"Information for message ID: `{mid}`",
            color=config.Discord.info_color,
            timestamp=discord.utils.utcnow()
        )
        
        embed.add_field(
            name="Author",
            value=f"ID: `{message_data['author_id']}`\nName: {message_data['author_name']}",
            inline=False
        )
        
        message_type = "Reply" if message_data['reply'] else "Original Message"
        embed.add_field(
            name="Type",
            value=message_type,
            inline=True
        )
        
        if message_data['referenceid']:
            embed.add_field(
                name="Reference ID",
                value=f"`{message_data['referenceid']}`",
                inline=True
            )
        
        messages_text = ""
        for i, msg in enumerate(message_data['messages'], 1):
            messages_text += f"{i}. Guild: `{msg['gid']}` | Channel: `{msg['channel']}` | Message: `{msg['mid']}`\n"
        
        embed.add_field(
            name=f"Messages ({len(message_data['messages'])})",
            value=messages_text or "No messages",
            inline=False
        )
        
        if message_data['replies']:
            replies_text = ""
            for i, reply in enumerate(message_data['replies'], 1):
                reply_info = f"{i}. Guild: `{reply['gid']}` | Channel: `{reply['channel']}` | Message: `{reply['mid']}`"
                if 'referenceid' in reply:
                    reply_info += f" | Reference: `{reply['referenceid']}`"
                if 'replyid' in reply:
                    reply_info += f" | Reply ID: `{reply['replyid']}`"
                replies_text += reply_info + "\n"
            
            embed.add_field(
                name=f"Replies ({len(message_data['replies'])})",
                value=replies_text,
                inline=False
            )
        
        await interaction.response.send_message(embed=embed)


    @bot.tree.command(name="leave-server", description="Force the bot to leave a guild by its ID.")
    @app_commands.describe(guild_id="The ID of the guild the bot should leave.")
    async def leave_server_command(interaction: discord.Interaction, guild_id: str):
        admins: list = list(datasys.load_data(1001, "admins"))

        if interaction.user.id not in admins:
            await interaction.response.send_message("❌ Missing permissions.", ephemeral=True)
            return

        if not guild_id.isdigit():
            await interaction.response.send_message("❌ Invalid guild ID.", ephemeral=True)
            return

        guild = bot.get_guild(int(guild_id))
        if guild is None:
            await interaction.response.send_message(f"❌ Guild `{guild_id}` not found or bot is not a member.", ephemeral=True)
            return

        guild_name = guild.name
        try:
            await guild.leave()
            embed = discord.Embed(
                title=f"{config.Icons.info} EXEC // SERVER VERLASSEN",
                description=f"Der Bot hat **{guild_name}** (`{guild_id}`) erfolgreich verlassen.",
                color=config.Discord.success_color,
            )
            embed.set_footer(text="Baxi · avocloud.net")
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Fehler: `{e}`", ephemeral=True)

