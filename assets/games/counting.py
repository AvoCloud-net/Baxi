import ast
import operator
import re

import discord
from discord.ext import commands
import assets.data as datasys
import config.config as cfg
from reds_simple_logger import Logger

logger = Logger()


def _is_milestone(n: int) -> bool:
    """Hardcoded milestones: 10, 50, then every 100 (100, 200, 300, ...)."""
    if n < 10:
        return False
    if n == 10 or n == 50:
        return True
    return n >= 100 and n % 100 == 0


_MATH_RE = re.compile(r"^[\d\s+\-*/().^]+$")

_SUPERSCRIPT = str.maketrans({
    "⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4",
    "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9",
})

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def _safe_eval(node):
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError("bad constant")
    if isinstance(node, ast.BinOp):
        op = _BIN_OPS.get(type(node.op))
        if op is None:
            raise ValueError("bad op")
        left = _safe_eval(node.left)
        right = _safe_eval(node.right)
        if isinstance(node.op, ast.Pow):
            if abs(right) > 32 or abs(left) > 10**6:
                raise ValueError("pow too big")
        return op(left, right)
    if isinstance(node, ast.UnaryOp):
        op = _UNARY_OPS.get(type(node.op))
        if op is None:
            raise ValueError("bad unary")
        return op(_safe_eval(node.operand))
    raise ValueError("bad node")


def _normalize_expression(content: str) -> str:
    content = re.sub(r"([⁰¹²³⁴⁵⁶⁷⁸⁹]+)", lambda m: "**" + m.group(1).translate(_SUPERSCRIPT), content)
    content = content.replace("^", "**")
    return content


def _parse_count_expression(content: str):
    """Return positive int result of arithmetic expression, or None if not parseable."""
    if not content:
        return None
    content = _normalize_expression(content)
    if not _MATH_RE.match(content):
        return None
    try:
        tree = ast.parse(content, mode="eval")
        value = _safe_eval(tree)
    except (ValueError, SyntaxError, ZeroDivisionError, TypeError, OverflowError):
        return None
    if isinstance(value, float):
        if not value.is_integer():
            return None
        value = int(value)
    if not isinstance(value, int) or value <= 0:
        return None
    return value


async def check_counting(message: discord.Message, bot: commands.AutoShardedBot) -> bool:
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

    user_number = _parse_count_expression(content)
    if user_number is None:
        if data.get("react_wrong", True):
            try:
                await message.add_reaction(cfg.Icons.cross)
            except (discord.Forbidden, discord.HTTPException):
                pass
        return True
    current_count = int(data.get("current_count", 0))
    expected = current_count + 1

    if data.get("no_double_count", True):
        last_user_id = int(data.get("last_user_id", 0))
        if last_user_id != 0 and last_user_id == message.author.id:
            if data.get("react_wrong", True):
                try:
                    await message.add_reaction(cfg.Icons.cross)
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
        old_hs = int(data.get("high_score", 0))
        if expected > old_hs:
            data["high_score"] = expected

        data["current_count"] = expected
        data["last_user_id"] = message.author.id
        datasys.save_data(message.guild.id, "counting", data)

        if data.get("react_correct", True):
            try:
                await message.add_reaction(cfg.Icons.check)
            except (discord.Forbidden, discord.HTTPException):
                pass

        if _is_milestone(expected):
            ms_embed = discord.Embed(
                description=t["milestone"].format(count=expected),
                color=cfg.Discord.warn_color,
            )
            ms_embed.set_footer(text=t["footer"])
            await message.channel.send(embed=ms_embed)
    else:
        old_hs = int(data.get("high_score", 0))
        was_record = current_count > 0 and current_count >= old_hs

        if data.get("react_wrong", True):
            try:
                await message.add_reaction(cfg.Icons.cross)
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
        if was_record:
            embed.add_field(
                name=f"{cfg.Icons.trophy} Neuer Highscore!",
                value=f"**{current_count}** – gut gemacht!",
                inline=False,
            )
        embed.set_footer(text=t["footer"])
        await message.channel.send(embed=embed)

    return True