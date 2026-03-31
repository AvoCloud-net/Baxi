import discord
from discord.ext import commands
import assets.data as datasys
import config.config as cfg
from reds_simple_logger import Logger

logger = Logger()


async def check_counting(message: discord.Message, bot: commands.AutoShardedBot) -> bool:
    """
    Handle the counting game for the given message.
    Returns True if the message was in the counting channel (consumed),
    False otherwise.
    """
    if message.guild is None or message.author.bot:
        return False

    data: dict = dict(datasys.load_data(message.guild.id, "counting"))

    if not data.get("enabled", False):
        return False

    channel_raw = str(data.get("channel", "") or "")
    if not channel_raw or not channel_raw.isdigit():
        return False
    channel_id = int(channel_raw)
    if message.channel.id != channel_id:
        return False

    lang = datasys.load_lang_file(message.guild.id)
    t: dict = lang["games"]["counting"]

    content = message.content.strip()

    # Non-numeric messages in the counting channel → ❌ reaction, no count change
    if not content.isdigit() or int(content) == 0:
        if data.get("react_wrong", True):
            try:
                await message.add_reaction("❌")
            except (discord.Forbidden, discord.HTTPException):
                pass
        return True

    user_number = int(content)
    current_count = int(data.get("current_count", 0))
    expected = current_count + 1

    # No-double-count rule: same user cannot count twice in a row
    # → reject with reaction + embed, do NOT reset the counter
    if data.get("no_double_count", True):
        last_user_id = int(data.get("last_user_id", 0))
        if last_user_id != 0 and last_user_id == message.author.id:
            if data.get("react_wrong", True):
                try:
                    await message.add_reaction("❌")
                except (discord.Forbidden, discord.HTTPException):
                    pass
            embed = discord.Embed(
                description=str(t["double_count"]).format(
                    user=message.author.display_name,
                    count=current_count,
                ),
                color=cfg.Discord.danger_color,
            )
            embed.set_footer(text=t["footer"])
            await message.channel.send(embed=embed)
            return True

    if user_number == expected:
        # Correct number
        data["current_count"] = expected
        data["last_user_id"] = message.author.id
        if expected > int(data.get("high_score", 0)):
            data["high_score"] = expected
        datasys.save_data(message.guild.id, "counting", data)

        if data.get("react_correct", True):
            try:
                await message.add_reaction("✅")
            except (discord.Forbidden, discord.HTTPException):
                pass
    else:
        # Wrong number → reset
        if data.get("react_wrong", True):
            try:
                await message.add_reaction("❌")
            except (discord.Forbidden, discord.HTTPException):
                pass
        data["current_count"] = 0
        data["last_user_id"] = 0
        datasys.save_data(message.guild.id, "counting", data)
        embed = discord.Embed(
            description=str(t["wrong_number"]).format(
                user=message.author.display_name,
                sent=user_number,
                expected=expected,
                count=current_count,
            ),
            color=cfg.Discord.danger_color,
        )
        embed.set_footer(text=t["footer"])
        await message.channel.send(embed=embed)

    return True
