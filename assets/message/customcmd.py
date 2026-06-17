import discord
from discord.ext import commands
from reds_simple_logger import Logger

import assets.data as datasys
import config.config as config

logger = Logger()

# Discord permissions exposed for command gating. Keep in sync with the
# whitelist in assets/dash/dash.py and the checkbox list in dash.html.
GATE_PERMS = {
    "manage_messages",
    "manage_roles",
    "kick_members",
    "ban_members",
    "manage_channels",
    "manage_guild",
    "moderate_members",
    "mention_everyone",
}


class _SafeDict(dict):
    """format_map helper: leave unknown {placeholders} untouched instead of raising."""

    def __missing__(self, key):
        return "{" + key + "}"


def _fmt(text: str, ctx: dict) -> str:
    if not text:
        return text
    try:
        return text.format_map(_SafeDict(ctx))
    except (ValueError, IndexError, KeyError):
        return text


def _legacy_actions(cmd_data: dict) -> list:
    """Build an actions list from a pre-actions (legacy) command record."""
    return [{
        "type": "text",
        "response": str(cmd_data.get("response", "")),
        "reply": False,
        "embed": cmd_data.get("embed", True),
        "embed_color": cmd_data.get("embed_color", ""),
        "embed_title": cmd_data.get("embed_title", ""),
        "embed_footer": cmd_data.get("embed_footer", ""),
    }]


def _passes_gate(member: discord.Member, gate: dict) -> bool:
    if not gate:
        return True

    # Server owner and administrators always pass.
    if member.guild_permissions.administrator or member.id == member.guild.owner_id:
        return True

    roles: list = gate.get("roles", []) or []
    if roles:
        member_role_ids = {str(r.id) for r in member.roles}
        if not member_role_ids.intersection({str(r) for r in roles}):
            return False

    perms: list = gate.get("perms", []) or []
    if perms:
        member_perms = member.guild_permissions
        for perm in perms:
            if perm in GATE_PERMS and not getattr(member_perms, perm, False):
                return False

    return True


def _resolve_target(message: discord.Message, target: str):
    """author -> the invoker, mentioned -> first @mentioned member (or None)."""
    if target == "mentioned":
        for m in message.mentions:
            return m
        return None
    return message.author


def _build_embed(action: dict, response: str, ctx: dict) -> discord.Embed:
    embed_color = config.Discord.color
    color_hex = action.get("embed_color", "")
    if color_hex and isinstance(color_hex, str) and len(color_hex) == 7:
        try:
            r, g, b = int(color_hex[1:3], 16), int(color_hex[3:5], 16), int(color_hex[5:7], 16)
            embed_color = discord.Color.from_rgb(r, g, b)
        except ValueError:
            pass

    embed = discord.Embed(description=response, color=embed_color)

    embed_title = _fmt(str(action.get("embed_title", "")), ctx)
    if embed_title:
        embed.title = embed_title

    embed_footer = _fmt(str(action.get("embed_footer", "")), ctx)
    if embed_footer:
        embed.set_footer(text=embed_footer)

    return embed


async def _run_action(message: discord.Message, bot: commands.AutoShardedBot, action: dict, ctx: dict) -> None:
    atype = action.get("type", "text")

    try:
        if atype == "text":
            response = _fmt(str(action.get("response", "")), ctx)
            if not response and not action.get("embed", True):
                return
            reply = bool(action.get("reply", False))
            if action.get("embed", True):
                embed = _build_embed(action, response, ctx)
                if reply:
                    await message.reply(embed=embed, mention_author=False)
                else:
                    await message.channel.send(embed=embed)
            else:
                if reply:
                    await message.reply(response, mention_author=False)
                else:
                    await message.channel.send(response)

        elif atype in ("add_role", "remove_role"):
            target = _resolve_target(message, action.get("target", "author"))
            if target is None:
                return
            role = message.guild.get_role(int(action.get("role", 0) or 0))
            if role is None:
                return
            if atype == "add_role":
                await target.add_roles(role, reason="Custom command action")
            else:
                await target.remove_roles(role, reason="Custom command action")

        elif atype == "delete_messages":
            count = action.get("count", 10)
            try:
                count = max(1, min(100, int(count)))
            except (TypeError, ValueError):
                count = 10
            await message.channel.purge(limit=count)

        elif atype == "react":
            emoji = str(action.get("emoji", "")).strip()
            if emoji:
                await message.add_reaction(emoji)

        elif atype == "dm":
            target = _resolve_target(message, action.get("target", "author"))
            if target is None:
                return
            response = _fmt(str(action.get("response", "")), ctx)
            if response:
                await target.send(response)

    except discord.Forbidden:
        logger.warning(f"Custom command action '{atype}' forbidden in {message.guild.id}")
    except discord.HTTPException as e:
        logger.warning(f"Custom command action '{atype}' failed: {e}")


async def check_custom_command(message: discord.Message, bot: commands.AutoShardedBot) -> bool:
    if message.guild is None:
        return False

    custom_commands: dict = dict(datasys.load_data(message.guild.id, "custom_commands"))
    if not custom_commands:
        return False

    content = message.content.strip().lower()

    for trigger, cmd_data in custom_commands.items():
        if content != trigger.lower():
            continue

        # Permission gate. Matched-but-denied is consumed silently.
        if not _passes_gate(message.author, cmd_data.get("gate", {})):
            return True

        actions = cmd_data.get("actions")
        if not isinstance(actions, list) or not actions:
            actions = _legacy_actions(cmd_data)

        mentioned = _resolve_target(message, "mentioned")
        ctx = {
            "user": message.author.mention,
            "username": message.author.name,
            "server": message.guild.name,
            "membercount": message.guild.member_count,
            "target": (mentioned or message.author).mention,
        }

        for action in actions:
            if isinstance(action, dict):
                await _run_action(message, bot, action, ctx)

        return True

    return False
