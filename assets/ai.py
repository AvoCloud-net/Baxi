import asyncio
import http.client
import os
import re

import assets.translate as tr
import config.auth as auth
import config.config as config
import discord
import discord.ext
import lang.de as de
import requests
from bs4 import BeautifulSoup
from discord.ext import commands
from googlesearch import search

ai_conversations = {}


def baxi_web_search(query):
    def google_search(query):
        try:
            return list(search(query, num_results=2))
        except Exception as e:
            print(f"Google search error: {e}")
            return []

    def scrape_content(url):
        try:
            conn = http.client.HTTPSConnection("website-summarizer.p.rapidapi.com")

            headers = {
                "x-rapidapi-key": "fbe5587232mshc622bc538f57669p1fdbc7jsn79b43ab3cb41",
                "x-rapidapi-host": "website-summarizer.p.rapidapi.com",
            }

            # Properly encode the URL
            encoded_url = requests.utils.quote(url)
            conn.request("GET", f"/summarize?url={encoded_url}", headers=headers)

            res = conn.getresponse()
            data = res.read()
            return data.decode("utf-8")
        except Exception as e:
            print(f"Scraping error for {url}: {e}")
            return ""

    result = []
    try:
        urls = google_search(query)
        for url in urls:
            content = scrape_content(url)
            if content:
                result.append({"url": url, "content": content})
    except Exception as e:
        print(f"Overall search error: {e}")

    return result


async def conversation_start_response(
    bot: commands.AutoShardedBot, message: discord.Message, lang: str
):
    if bot.user in message.mentions:
        user_text = message.content.replace(f"<@{bot.user.id}>", "").strip()
        conversation_id = os.urandom(8).hex()
        ai_conversations[str(conversation_id)] = []
        ai_conversations[str(conversation_id)].append(
            {f"{message.author.name}": f"{user_text}"}
        )

        if conversation_id in ai_conversations:
            embed = discord.Embed(
                title=await tr.baxi_translate(de.Ai.title, lang),
                description=await tr.baxi_translate(
                    f"{de.Ai.Waiting.content}\n-# {message.content}", lang
                ),
                color=config.Discord.color,
            )
            embed.set_thumbnail(url=config.Icons.loading)
            embed.set_author(name="Baxi AI")
            embed.set_footer(text=str(conversation_id))
            msg_resp = await message.reply(embed=embed)
            ai_conversations[conversation_id].append(
                {f"{message.author.name}": f"{message.content}"}
            )

            def make_request():
                headers = {
                    "Authorization": f"Bearer {auth.Ai.api_key}",
                    "Content-Type": "application/json",
                }
                data = {
                    "model": "llama3.2:latest",
                    "messages": [
                        {
                            "role": "user",
                            "content": f"Username: {message.author.name}\nConversation history:\n{ai_conversations[conversation_id]}\nUser input: {user_text}",
                        }
                    ],
                }
                response = requests.post(auth.Ai.uri, headers=headers, json=data)

                return response

            response = await asyncio.to_thread(make_request)

            answer = response.json()["choices"][0]["message"]["content"]
            embed_new = discord.Embed(
                title=await tr.baxi_translate(de.Ai.title, lang),
                description=f"-# {message.content}\n\n{answer}",
                color=config.Discord.color,
            )
            embed_new.set_thumbnail(url=config.Icons.chatbot)
            embed_new.set_author(name="Baxi AI")
            embed_new.set_footer(text=str(conversation_id))
            await msg_resp.edit(content=None, embed=embed_new)
            ai_conversations[str(conversation_id)].append({"Baxi (you)": f"{answer}"})
            return True
        else:
            return False


async def conversation_answer_response(
    bot: commands.AutoShardedBot, message: discord.Message, lang: str
):
    if message.reference:
        if message.reference.resolved.embeds:
            original_embed = message.reference.resolved.embeds[0]
            if (
                original_embed.author.name == "Baxi AI"
                and message.reference.resolved.author == bot.user
            ):
                try:
                    conversation_id: str = original_embed.footer.text
                except:
                    conversation_id = None

                if conversation_id in ai_conversations or conversation_id is None:
                    embed = discord.Embed(
                        title=await tr.baxi_translate(de.Ai.title, lang),
                        description=await tr.baxi_translate(
                            f"{de.Ai.Waiting.content}\n-# {message.content}",
                            lang,
                        ),
                        color=config.Discord.color,
                    )
                    embed.set_thumbnail(url=config.Icons.loading)
                    embed.set_author(name="Baxi AI")
                    embed.set_footer(text=str(conversation_id))
                    msg_resp = await message.reply(embed=embed)
                    ai_conversations[conversation_id].append(
                        {f"{message.author.name}": f"{message.content}"}
                    )

                    def make_request():
                        headers = {
                            "Authorization": f"Bearer {auth.Ai.api_key}",
                            "Content-Type": "application/json",
                        }
                        data = {
                            "model": "llama3.2:latest",
                            "messages": [
                                {
                                    "role": "user",
                                    "content": f"Username: {message.author.name}\nConversation history:\n{ai_conversations[conversation_id]}\nUser input: {message.content}",
                                }
                            ],
                        }
                        response = requests.post(
                            auth.Ai.uri, headers=headers, json=data
                        )

                        return response

                    response = await asyncio.to_thread(make_request)

                    answer = response.json()["choices"][0]["message"]["content"]
                    embed_new = discord.Embed(
                        title=await tr.baxi_translate(de.Ai.title, lang),
                        description=f"-# {message.content}\n\n{answer}",
                        color=config.Discord.color,
                    )
                    embed_new.set_thumbnail(url=config.Icons.chatbot)
                    embed_new.set_author(name="Baxi AI")
                    embed_new.set_footer(text=str(conversation_id))
                    await msg_resp.edit(content=None, embed=embed_new)
                    ai_conversations[str(conversation_id)].append(
                        {"Baxi (you)": f"{answer}"}
                    )
                else:
                    await message.reply(
                        content=await tr.baxi_translate(de.Ai.Error.id_not_found, lang)
                    )
                return True

            elif (
                original_embed.author.name == "Baxi AI - Web"
                and message.reference.resolved.author == bot.user
            ):
                await message.reply(
                    content=await tr.baxi_translate(
                        de.Ai.Error.model_unable_to_chat, lang
                    )
                )
                return True
            else:
                return False
