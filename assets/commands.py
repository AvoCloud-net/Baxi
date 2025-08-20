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
            await interaction.response.defer()
            if interaction.guild is None:
                lang = datasys.load_lang_file(1001)
                embed = discord.Embed(
                    title="⚠️ " + lang["commands"]["guild_only"],
                    description="This command can only be used in a server.",
                    color=config.Discord.warn_color
                )
                return await interaction.response.send_message(embed=embed)
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
                title=f"{config.Icons.search} {lang['commands']['user']['scan_users']['title']}",
                description=str(lang["commands"]["user"]["scan_users"]["user_count"]).format(users=interaction.guild.member_count),
                color=0x2b2d31 if len(flagged_users) == 0 else 0xe74c3c
            )
            
            embed.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else None)
            embed.set_footer(text=f"Requested by {interaction.user}", icon_url=user_avatar)

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
                title="❌ An error occurred",
                description="Failed to complete the scan. Please try again later.",
                color=config.Discord.danger_color
            )
            await interaction.edit_original_response(embed=error_embed)


def utility_commands(bot: commands.AutoShardedBot):
    logger.debug.info("Utility commands loaded.")

    @bot.tree.command(name="ban", description="Ban a user from the server.")
    @app_commands.checks.has_permissions(ban_members=True)
    @app_commands.describe(user="The user you want to ban.")
    @app_commands.describe(reason="The reason for the ban.")
    async def ban_cmd(
        interaction: Interaction, user: discord.Member, reason: str = "N/A"
    ):
        if interaction.guild is None:
            lang = datasys.load_lang_file(1001)
            return await interaction.response.send_message(
                embed=discord.Embed(
                    title=lang["commands"]["guild_only"],
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

        embed = discord.Embed(
            title=f'{config.Icons.people_crossed} {lang["commands"]["admin"]["ban"]["title"]}',
            description=lang["commands"]["admin"]["ban"]["confirmation"],
            color=discord.Color.red(),
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

        view = BanConfirmView(user, member, reason)

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
                    title=lang["commands"]["guild_only"],
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
            title=f'{config.Icons.people_crossed} {lang["commands"]["admin"]["kick"]["title"]}',
            description=lang["commands"]["admin"]["kick"]["confirmation"],
            color=discord.Color.red(),
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
                    title=lang["commands"]["guild_only"],
                    color=config.Discord.warn_color,
                )
            )

        lang = datasys.load_lang_file(interaction.guild.id)
        embed = discord.Embed(
            title=f'{config.Icons.people_crossed} {lang["commands"]["admin"]["unban"]["title"]}',
            description=lang["commands"]["admin"]["unban"]["confirmation"],
            color=discord.Color.green(),
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
                    title=lang["commands"]["guild_only"],
                    color=config.Discord.warn_color,
                )
            )

        lang = datasys.load_lang_file(interaction.guild.id)
        embed = discord.Embed(
            title=lang["commands"]["admin"]["clear"]["title"],
            description=lang["commands"]["admin"]["clear"]["confirmation"],
            color=discord.Color.green(),
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

def bot_admin_commands(bot: commands.AutoShardedBot):
    logger.debug.info("Bot admin commands loaded.")

    @bot.tree.command(name="flag-user", description="Flag a user as global troublemaker, triggering increased scrutiny and potential consequences.")
    @app_commands.describe(user="User you want to flag.")
    @app_commands.describe(user_id="The ID of the user you want to flag.")
    @app_commands.describe(reason="Why do you want to flag this user?")
    async def flag_user_command(interaction: discord.Interaction, reason: str, user: Optional[discord.Member] = None, user_id: Optional[int] = 0):
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

        users_list[str(selected_user.id)] = {
            "entry_date": str(datetime.date.today()),
            "id": int(selected_user.id),
            "name": str(selected_user.name),
            "reason": reason,
            "flagged": True
        }

        print(users_list)

        datasys.save_data(1001, "users", users_list)

        await interaction.response.send_message(config.Icons.people_crossed + "" + lang["commands"]["admin"]["flag_user"]["success"])


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
                title="Message Not Found",
                description=f"No message data found for ID: `{mid}`",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed)
            return
        
        embed = discord.Embed(
            title="Global Chat Message Information",
            description=f"Information for message ID: `{mid}`",
            color=discord.Color.blue(),
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
            
