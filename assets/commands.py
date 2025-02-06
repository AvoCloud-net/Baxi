import asyncio
import discord, requests, os
from discord.ext import commands
from discord import Embed, Interaction, app_commands, ui
from assets.ai import *
import config.config as config
import config.auth as auth
import assets.data as datasys
import assets.translate as tr
from assets.ai import ai_conversations
import lang.de as de
import requests
from assets.buttons import (
    BanConfirmView,
    KickConfirmView,
    UbanConfirmView,
    ClearConfirmView,
)
import reds_simple_logger as logger

logger = logger.Logger()


def base_commands(bot: commands.AutoShardedBot):
    logger.debug.info("Base commands loaded.")

    @bot.tree.command(name="help", description="Shows the help panel")
    async def help_cmd(interaction: Interaction):
        try:
            await interaction.response.defer()
            guild_id = interaction.guild.id if interaction.guild is not None else None
            lang = datasys.load_lang(guild_id)
            title = await tr.baxi_translate(de.Help.title, lang)
            content_prefix_title = await tr.baxi_translate(
                de.Help.Description.Prefix.title, lang
            )
            content_prefix_content = await tr.baxi_translate(
                de.Help.Description.Prefix.content, lang
            )
            content_about_title = await tr.baxi_translate(
                de.Help.Description.About.title, lang
            )
            content_about_content = await tr.baxi_translate(
                de.Help.Description.About.content, lang
            )
            content_icons_title = await tr.baxi_translate(
                de.Help.Description.Icons.title, lang
            )
            content_icons_content = await tr.baxi_translate(
                de.Help.Description.Icons.content, lang
            )
            content_bugs_title = await tr.baxi_translate(
                de.Help.Description.Bugs.title, lang
            )
            content_bugs_content = await tr.baxi_translate(
                de.Help.Description.Bugs.content, lang
            )

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
        except Exception as e:
            print(e)


def ai(bot: commands.AutoShardedBot):
    logger.debug.info("AI commands loaded.")

    @bot.tree.command(name="ai", description="Ask a Question")
    @app_commands.describe(question="question")
    async def ai_cmd(interaction: Interaction, question: str):
        await interaction.response.defer()
        conversation_id = os.urandom(8).hex()
        ai_conversations[str(conversation_id)] = []
        ai_conversations[str(conversation_id)].append(
            {f"{interaction.user.name}": f"{question}"}
        )

        try:
            guild_id = interaction.guild.id if interaction.guild is not None else None
            lang = datasys.load_lang(guild_id)
            embed = discord.Embed(
                title=await tr.baxi_translate(de.Ai.title, lang),
                description=await tr.baxi_translate(
                    f"{de.Ai.Waiting.content}\n-# {question}", lang
                ),
                color=config.Discord.color,
            )
            embed.set_thumbnail(url=config.Icons.loading)
            embed.set_author(name="Baxi AI")
            embed.set_footer(text=str(conversation_id))
            await interaction.edit_original_response(embed=embed)

            async def make_request():
                headers = {
                    "Authorization": f"Bearer {auth.Ai.api_key}",
                    "Content-Type": "application/json",
                }
                data = {
                    "model": "llama3.2:latest",
                    "messages": [
                        {
                            "role": "user",
                            "content": f"Username: {interaction.user.name}\nUser input: {question}",
                        }
                    ],
                }
                response = requests.post(auth.Ai.uri, headers=headers, json=data)

                return response

            response = await asyncio.create_task(make_request(), name="ai_make_request")
            if response.status_code == 200:
                answer = response.json()["choices"][0]["message"]["content"]
                embed_new = discord.Embed(
                    title=await tr.baxi_translate(de.Ai.title, lang),
                    description=f"-# {question}\n\n{answer}",
                    color=config.Discord.color,
                )
                embed_new.set_thumbnail(url=config.Icons.chatbot)
                embed_new.set_author(name="Baxi AI")
                embed_new.set_footer(text=str(conversation_id))
                ai_conversations[str(conversation_id)].append(
                    {"Baxi (you)": f"{answer}"}
                )
                await interaction.edit_original_response(embed=embed_new)
            else:
                embed_new = discord.Embed(
                    title=await tr.baxi_translate(de.Ai.title, lang),
                    description=await tr.baxi_translate(de.Ai.Error.unknown, lang),
                    color=config.Discord.color,
                )
                embed_new.set_thumbnail(url=config.Icons.chatbot)
                embed_new.set_author(name="Baxi AI")
        except Exception as e:
            await interaction.channel.send(
                content=await tr.baxi_translate(f"{de.Ai.Error.unknown} : {e}", lang)
            )

    @bot.tree.command(name="ai-web", description="Ask a Question")
    @app_commands.describe(question="question")
    async def ai_cmd(interaction: Interaction, question: str):
        await interaction.response.defer()

        try:
            guild_id = interaction.guild.id if interaction.guild is not None else None
            lang = datasys.load_lang(guild_id)

            embed = discord.Embed(
                title=await tr.baxi_translate(de.Ai.title, lang),
                description=await tr.baxi_translate(
                    f"{de.Ai.Waiting.content}\n-# {question}", lang
                ),
                color=config.Discord.color,
            )
            embed.set_thumbnail(url=config.Icons.loading)
            embed.set_author(name="Baxi AI - Web")
            await interaction.edit_original_response(embed=embed)

            async def make_request():
                search_results = baxi_web_search(question)

                headers = {
                    "Authorization": f"Bearer {auth.Ai.api_key}",
                    "Content-Type": "application/json",
                }
                data = {
                    "model": "qwen2.5:1.5b",
                    "messages": [
                        {
                            "role": "user",
                            "content": f"Answer question from {interaction.user.name}: {question} with the following infos: {search_results}",
                        }
                    ],
                }

                response = requests.post(auth.Ai.uri, headers=headers, json=data)

                return response, search_results

            response, search_results = await asyncio.create_task(
                make_request(), name="ai_make_request"
            )

            if response.status_code == 200:
                answer = response.json()["choices"][0]["message"]["content"]
                embed_new = discord.Embed(
                    title=await tr.baxi_translate(de.Ai.title, lang),
                    description=f"-# {question}\n\n{answer}",
                    color=config.Discord.color,
                )
                embed_new.set_thumbnail(url=config.Icons.chatbot)
                embed_new.set_author(name="Baxi AI - Web")

                if search_results:
                    urls = [result.get("url", "N/A") for result in search_results[:3]]
                    footer_text = "Sources: " + " | ".join(urls)
                    embed_new.set_footer(text=footer_text)

                await interaction.edit_original_response(embed=embed_new)
            else:
                embed_error = discord.Embed(
                    title=await tr.baxi_translate(de.Ai.title, lang),
                    description=await tr.baxi_translate(de.Ai.Error.unknown, lang)
                    + f"{response.text}",
                    color=config.Discord.color,
                )
                embed_error.set_thumbnail(url=config.Icons.chatbot)
                embed_error.set_author(name="Baxi AI - Web")
                await interaction.edit_original_response(embed=embed_error)

        except Exception as e:
            error_message = await tr.baxi_translate(
                f"{de.Ai.Error.unknown} : {e}", lang
            )
            await interaction.channel.send(content=error_message)


def utility_commands(bot: commands.AutoShardedBot):
    logger.debug.info("Utility commands loaded.")

    @bot.tree.command(name="ban", description="Ban a user from the server.")
    @app_commands.checks.has_permissions(ban_members=True)
    @app_commands.describe(user="The user you want to ban.")
    @app_commands.describe(reason="The reason for the ban.")
    async def ban_cmd(
        interaction: Interaction, user: discord.Member, reason: str = None
    ):
        lang = datasys.load_lang(interaction.guild.id)
        if interaction.user.top_role <= user.top_role:
            await interaction.response.send_message(
                "Du hast keine Berechtigung, diesen Benutzer zu bannen.", ephemeral=True
            )
            return

        embed = discord.Embed(
            title=await tr.baxi_translate(de.Utility.Ban.title, lang),
            description=await tr.baxi_translate(de.Utility.Ban.confirmation, lang),
            color=discord.Color.red(),
        )
        embed.add_field(
            name=await tr.baxi_translate(de.Utility.user, lang),
            value=user.mention,
            inline=False,
        )
        embed.add_field(
            name=await tr.baxi_translate(de.Utility.mod, lang),
            value=interaction.user.mention,
            inline=False,
        )
        embed.add_field(
            name=await tr.baxi_translate(de.Utility.reason, lang),
            value=reason,
            inline=False,
        )

        view = BanConfirmView(user, interaction.user, reason)

        await interaction.response.send_message(embed=embed, view=view)

    @bot.tree.command(name="kick", description="Kick a user from the server.")
    @app_commands.checks.has_permissions(kick_members=True)
    @app_commands.describe(user="The user you want to kick.")
    @app_commands.describe(reason="The reason for the kick.")
    async def kick_cmd(
        interaction: Interaction, user: discord.Member, reason: str = None
    ):
        lang = datasys.load_lang(interaction.guild.id)
        if interaction.user.top_role <= user.top_role:
            await interaction.response.send_message(
                await tr.baxi_translate(de.Utility.Kick.missing_perms, lang),
                ephemeral=True,
            )
            return
        embed = discord.Embed(
            title=await tr.baxi_translate(de.Utility.Kick.title, lang),
            description=await tr.baxi_translate(de.Utility.Kick.confirmation, lang),
            color=discord.Color.red(),
        )
        embed.add_field(
            name=await tr.baxi_translate(de.Utility.user, lang),
            value=user.mention,
            inline=False,
        )
        embed.add_field(
            name=await tr.baxi_translate(de.Utility.mod, lang),
            value=interaction.user.mention,
            inline=False,
        )
        embed.add_field(
            name=await tr.baxi_translate(de.Utility.reason, lang),
            value=reason,
            inline=False,
        )

        view = KickConfirmView(user, interaction.user, reason)

        await interaction.response.send_message(embed=embed, view=view)

    @bot.tree.command(name="unban", description="Unban a user from the server.")
    @app_commands.checks.has_permissions(ban_members=True)
    @app_commands.describe(user="The user id of the user you want to unban.")
    async def unban_cmd(interaction: Interaction, user: int):
        lang = datasys.load_lang(interaction.guild.id)
        embed = discord.Embed(
            title=await tr.baxi_translate(de.Utility.Unban.title, lang),
            description=await tr.baxi_translate(de.Utility.Unban.confirmation, lang),
            color=discord.Color.green(),
        )
        user_new = await bot.fetch_user(user)
        embed.add_field(
            name=await tr.baxi_translate(de.Utility.user, lang),
            value=user_new.name,
            inline=False,
        )
        embed.add_field(
            name=await tr.baxi_translate(de.Utility.mod, lang),
            value=interaction.user.mention,
            inline=False,
        )
        view = UbanConfirmView(user, interaction.user)
        await interaction.response.send_message(embed=embed, view=view)

    @bot.tree.command(name="clear", description="Clear messages from a channel.")
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.describe(amount="The amount of messages to clear.")
    async def clear_cmd(interaction: Interaction, amount: int):
        lang = datasys.load_lang(interaction.guild.id)
        embed = discord.Embed(
            title=await tr.baxi_translate(de.Utility.Clear.title, lang),
            description=await tr.baxi_translate(de.Utility.Clear.confirmation, lang),
            color=discord.Color.green(),
        )
        embed.add_field(
            name=await tr.baxi_translate(de.Utility.amount, lang),
            value=amount,
            inline=False,
        )
        view = ClearConfirmView(amount, interaction.user, interaction.channel)
        await interaction.response.send_message(embed=embed, view=view)
