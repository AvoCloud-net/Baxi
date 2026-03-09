import time
from collections import defaultdict

import discord
from discord.ext import commands
from reds_simple_logger import Logger

import assets.data as datasys
import config.config as config

logger = Logger()


class AntiSpam:
    def __init__(self):
        # {guild_id: {user_id: [timestamps]}}
        self.message_timestamps: dict[int, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
        # {guild_id: {user_id: [message_contents]}}
        self.message_contents: dict[int, dict[int, list[str]]] = defaultdict(lambda: defaultdict(list))

    async def check(self, message: discord.Message, bot: commands.AutoShardedBot) -> bool:
        """Check a message for spam. Returns True if the message is spam."""
        if message.guild is None:
            return False

        antispam_config: dict = dict(datasys.load_data(message.guild.id, "antispam"))
        if not antispam_config.get("enabled", False):
            return False

        guild_id = message.guild.id
        user_id = message.author.id
        now = time.time()

        max_messages = int(antispam_config.get("max_messages", 5))
        interval = int(antispam_config.get("interval", 5))
        max_duplicates = int(antispam_config.get("max_duplicates", 3))
        action = str(antispam_config.get("action", "mute"))

        # Clean old timestamps
        self.message_timestamps[guild_id][user_id] = [
            t for t in self.message_timestamps[guild_id][user_id]
            if now - t < interval
        ]
        self.message_timestamps[guild_id][user_id].append(now)

        # Clean old message contents (keep last max_duplicates + 1)
        self.message_contents[guild_id][user_id].append(message.clean_content)
        if len(self.message_contents[guild_id][user_id]) > max_duplicates + 2:
            self.message_contents[guild_id][user_id] = self.message_contents[guild_id][user_id][-(max_duplicates + 2):]

        lang = datasys.load_lang_file(guild_id)
        is_spam = False

        # Rate limit check
        if len(self.message_timestamps[guild_id][user_id]) > max_messages:
            is_spam = True
            embed = discord.Embed(
                title=lang["systems"]["antispam"]["title"],
                description=str(lang["systems"]["antispam"]["triggered"]).format(user=message.author.mention),
                color=config.Discord.warn_color,
            )
            await message.channel.send(embed=embed)

        # Duplicate check
        recent = self.message_contents[guild_id][user_id]
        if len(recent) >= max_duplicates:
            last_msgs = recent[-max_duplicates:]
            if len(set(last_msgs)) == 1 and last_msgs[0] != "":
                is_spam = True
                embed = discord.Embed(
                    title=lang["systems"]["antispam"]["title"],
                    description=str(lang["systems"]["antispam"]["duplicate"]).format(user=message.author.mention),
                    color=config.Discord.warn_color,
                )
                await message.channel.send(embed=embed)

        if is_spam:
            await self._take_action(message, action, lang, bot)
            self.message_timestamps[guild_id][user_id].clear()
            self.message_contents[guild_id][user_id].clear()

        return is_spam

    async def _take_action(self, message: discord.Message, action: str, lang: dict, bot: commands.AutoShardedBot):
        assert message.guild is not None
        member = message.guild.get_member(message.author.id)
        if member is None:
            return

        try:
            if action == "mute":
                await member.timeout(discord.utils.utcnow() + __import__("datetime").timedelta(minutes=5))
                embed = discord.Embed(
                    title=lang["systems"]["antispam"]["title"],
                    description=str(lang["systems"]["antispam"]["muted"]).format(user=message.author.mention),
                    color=config.Discord.danger_color,
                )
                await message.channel.send(embed=embed)
            elif action == "warn":
                from assets.message.warnings import add_warning
                await add_warning(
                    guild_id=message.guild.id,
                    user=member,
                    moderator=bot.user,
                    reason="Anti-Spam",
                    bot=bot,
                    channel=message.channel,
                )
            elif action == "kick":
                await member.kick(reason="Anti-Spam")
            elif action == "ban":
                await member.ban(reason="Anti-Spam")
        except discord.Forbidden:
            logger.error(f"AntiSpam: Missing permissions to {action} {member.name} in {message.guild.name}")
        except Exception as e:
            logger.error(f"AntiSpam action error: {e}")
