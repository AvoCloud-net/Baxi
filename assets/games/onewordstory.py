import re

import discord
from discord.ext import commands
import assets.data as datasys
import config.config as cfg
from reds_simple_logger import Logger

logger = Logger()

_WORD_RE = re.compile(r"^\S+$")
_HELP_WORDS = {"help", "hilfe"}
_MAX_WORD_LEN = 30


def _parse_word(content: str):
    """Return the single word if content is exactly one token, else None."""
    content = content.strip()
    if not content or " " in content or "\n" in content:
        return None
    if len(content) > _MAX_WORD_LEN:
        return None
    if not _WORD_RE.match(content):
        return None
    return content


async def check_onewordstory(message: discord.Message, bot: commands.AutoShardedBot) -> bool:
    if message.guild is None or message.author.bot:
        return False

    data: dict = dict(datasys.load_data(message.guild.id, "one_word_story"))

    if not data.get("enabled", False):
        return False

    channel_raw = str(data.get("channel", "") or "")
    if not channel_raw or not channel_raw.isdigit():
        return False
    if message.channel.id != int(channel_raw):
        return False

    lang = datasys.load_lang_file(message.guild.id)
    t: dict = lang["games"]["one_word_story"]

    content = message.content.strip()

    if content.lower() in _HELP_WORDS:
        help_embed = discord.Embed(
            title=t["help_title"],
            description=t["help_description"],
            color=cfg.Discord.info_color,
        )
        help_embed.set_footer(text=t["footer"])
        await message.channel.send(embed=help_embed)
        return True

    word = _parse_word(content)
    if word is None:
        if data.get("react_wrong", True):
            try:
                await message.add_reaction(cfg.Icons.cross)
            except (discord.Forbidden, discord.HTTPException):
                pass
        return True

    if data.get("no_double_turn", True):
        last_user_id = int(data.get("last_user_id", 0))
        if last_user_id != 0 and last_user_id == message.author.id:
            if data.get("react_wrong", True):
                try:
                    await message.add_reaction(cfg.Icons.cross)
                except (discord.Forbidden, discord.HTTPException):
                    pass
            embed = discord.Embed(
                description=str(t["double_turn"]).format(user=message.author.display_name),
                color=cfg.Discord.danger_color,
            )
            embed.set_footer(text=t["footer"])
            await message.channel.send(embed=embed)
            return True

    words: list = list(data.get("words", []))
    words.append(word)
    data["words"] = words
    data["last_user_id"] = message.author.id
    if len(words) > int(data.get("high_score", 0)):
        data["high_score"] = len(words)
    datasys.save_data(message.guild.id, "one_word_story", data)

    if data.get("react_correct", True):
        try:
            await message.add_reaction(cfg.Icons.check)
        except (discord.Forbidden, discord.HTTPException):
            pass

    return True
