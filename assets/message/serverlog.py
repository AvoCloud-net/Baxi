import discord

import assets.data as datasys
import config.config as config


_FOOTER = "Baxi · Audit Log"


def _trunc(text, limit: int = 1000):
    """Truncate a string to `limit` chars, appending an ellipsis if cut."""
    if text is None:
        return "*(empty)*"
    text = str(text)
    if not text:
        return "*(empty)*"
    if len(text) > limit:
        return text[: limit - 1] + "…"
    return text


def _base_embed(title: str, color) -> discord.Embed:
    embed = discord.Embed(title=title, color=color, timestamp=discord.utils.utcnow())
    embed.set_footer(text=_FOOTER)
    return embed


def _channel_type_name(channel) -> str:
    try:
        return str(channel.type).replace("_", " ").title()
    except Exception:
        return "Channel"


async def send_log(bot, guild_id, event_type: str, embed: discord.Embed):
    """Send an audit-log embed to the configured serverlog channel.

    Never raises into the caller (event handlers must stay alive).
    """
    try:
        cfg = dict(datasys.load_data(guild_id, "serverlog"))
        if not cfg.get("enabled", False):
            return
        events = cfg.get("events", {})
        if not events.get(event_type, False):
            return
        channel_id = cfg.get("channel", "")
        if not channel_id:
            return
        try:
            channel = bot.get_channel(int(channel_id))
        except (ValueError, TypeError):
            return
        if not isinstance(channel, discord.TextChannel):
            return
        await channel.send(embed=embed)
    except (discord.Forbidden, discord.HTTPException):
        pass
    except Exception:
        pass


# ----------------------------------------------------------------------------
# Embed builders
# ----------------------------------------------------------------------------

def build_message_edit(before: discord.Message, after: discord.Message) -> discord.Embed:
    embed = _base_embed("✏️ Message Edited", config.Discord.info_color)
    embed.add_field(name="Author", value=f"{after.author.mention} (`{after.author.id}`)", inline=False)
    embed.add_field(name="Channel", value=f"{after.channel.mention}", inline=False)
    embed.add_field(name="Before", value=_trunc(before.content), inline=False)
    embed.add_field(name="After", value=_trunc(after.content), inline=False)
    try:
        embed.add_field(name="Jump", value=f"[Go to message]({after.jump_url})", inline=False)
    except Exception:
        pass
    return embed


def build_message_delete(message: discord.Message) -> discord.Embed:
    embed = _base_embed("🗑️ Message Deleted", config.Discord.danger_color)
    embed.add_field(name="Author", value=f"{message.author.mention} (`{message.author.id}`)", inline=False)
    embed.add_field(name="Channel", value=f"{message.channel.mention}", inline=False)
    embed.add_field(name="Content", value=_trunc(message.content), inline=False)
    return embed


def build_voice_join(member: discord.Member, channel) -> discord.Embed:
    embed = _base_embed("🔊 Voice Channel Joined", config.Discord.success_color)
    embed.add_field(name="Member", value=f"{member.mention} (`{member.id}`)", inline=False)
    embed.add_field(name="Channel", value=f"{channel.mention} (`{channel.name}`)", inline=False)
    return embed


def build_voice_leave(member: discord.Member, channel) -> discord.Embed:
    embed = _base_embed("🔇 Voice Channel Left", config.Discord.warn_color)
    embed.add_field(name="Member", value=f"{member.mention} (`{member.id}`)", inline=False)
    embed.add_field(name="Channel", value=f"{channel.mention} (`{channel.name}`)", inline=False)
    return embed


def build_voice_move(member: discord.Member, before_channel, after_channel) -> discord.Embed:
    embed = _base_embed("↔️ Voice Channel Moved", config.Discord.info_color)
    embed.add_field(name="Member", value=f"{member.mention} (`{member.id}`)", inline=False)
    embed.add_field(name="From", value=f"{before_channel.mention} (`{before_channel.name}`)", inline=True)
    embed.add_field(name="To", value=f"{after_channel.mention} (`{after_channel.name}`)", inline=True)
    return embed


def build_channel_create(channel) -> discord.Embed:
    embed = _base_embed("📁 Channel Created", config.Discord.success_color)
    embed.add_field(name="Channel", value=f"{getattr(channel, 'mention', channel.name)} (`{channel.id}`)", inline=False)
    embed.add_field(name="Name", value=f"`{channel.name}`", inline=True)
    embed.add_field(name="Type", value=_channel_type_name(channel), inline=True)
    category = getattr(channel, "category", None)
    if category is not None:
        embed.add_field(name="Category", value=f"`{category.name}`", inline=True)
    return embed


def build_channel_delete(channel) -> discord.Embed:
    embed = _base_embed("📁 Channel Deleted", config.Discord.danger_color)
    embed.add_field(name="Name", value=f"`{channel.name}` (`{channel.id}`)", inline=True)
    embed.add_field(name="Type", value=_channel_type_name(channel), inline=True)
    category = getattr(channel, "category", None)
    if category is not None:
        embed.add_field(name="Category", value=f"`{category.name}`", inline=True)
    return embed


def build_channel_update(before, after) -> discord.Embed:
    embed = _base_embed("📝 Channel Updated", config.Discord.warn_color)
    embed.add_field(name="Channel", value=f"{getattr(after, 'mention', after.name)} (`{after.id}`)", inline=False)

    changes = []
    if getattr(before, "name", None) != getattr(after, "name", None):
        changes.append(f"**Name:** `{before.name}` → `{after.name}`")
    if getattr(before, "topic", None) != getattr(after, "topic", None):
        changes.append(
            f"**Topic:** {_trunc(getattr(before, 'topic', None), 300)} → {_trunc(getattr(after, 'topic', None), 300)}"
        )
    if getattr(before, "position", None) != getattr(after, "position", None):
        changes.append(f"**Position:** `{before.position}` → `{after.position}`")
    if getattr(before, "nsfw", None) != getattr(after, "nsfw", None):
        changes.append(f"**NSFW:** `{getattr(before, 'nsfw', None)}` → `{getattr(after, 'nsfw', None)}`")
    if getattr(before, "slowmode_delay", None) != getattr(after, "slowmode_delay", None):
        changes.append(
            f"**Slowmode:** `{getattr(before, 'slowmode_delay', None)}s` → `{getattr(after, 'slowmode_delay', None)}s`"
        )

    embed.add_field(name="Changes", value=_trunc("\n".join(changes)) if changes else "*(no tracked changes)*", inline=False)
    return embed


def build_role_create(role: discord.Role) -> discord.Embed:
    embed = _base_embed("🏷️ Role Created", config.Discord.success_color)
    embed.add_field(name="Role", value=f"{role.mention} (`{role.id}`)", inline=False)
    embed.add_field(name="Name", value=f"`{role.name}`", inline=True)
    return embed


def build_role_delete(role: discord.Role) -> discord.Embed:
    embed = _base_embed("🏷️ Role Deleted", config.Discord.danger_color)
    embed.add_field(name="Name", value=f"`{role.name}` (`{role.id}`)", inline=True)
    return embed


def build_role_update(before: discord.Role, after: discord.Role) -> discord.Embed:
    embed = _base_embed("🏷️ Role Updated", config.Discord.warn_color)
    embed.add_field(name="Role", value=f"{after.mention} (`{after.id}`)", inline=False)

    changes = []
    if before.name != after.name:
        changes.append(f"**Name:** `{before.name}` → `{after.name}`")
    if before.color != after.color:
        changes.append(f"**Color:** `{before.color}` → `{after.color}`")
    if before.permissions != after.permissions:
        try:
            before_perms = {p for p, v in before.permissions if v}
            after_perms = {p for p, v in after.permissions if v}
            added = after_perms - before_perms
            removed = before_perms - after_perms
            if added:
                changes.append("**Permissions added:** " + ", ".join(f"`{p}`" for p in sorted(added)))
            if removed:
                changes.append("**Permissions removed:** " + ", ".join(f"`{p}`" for p in sorted(removed)))
        except Exception:
            changes.append("**Permissions changed**")

    embed.add_field(name="Changes", value=_trunc("\n".join(changes)) if changes else "*(no tracked changes)*", inline=False)
    return embed


def build_member_join(member: discord.Member) -> discord.Embed:
    embed = _base_embed("📥 Member Joined", config.Discord.success_color)
    embed.add_field(name="Member", value=f"{member.mention} (`{member.id}`)", inline=False)
    try:
        embed.add_field(
            name="Account Created",
            value=discord.utils.format_dt(member.created_at, style="R"),
            inline=True,
        )
    except Exception:
        pass
    try:
        embed.set_thumbnail(url=member.display_avatar.url)
    except Exception:
        pass
    return embed


def build_member_leave(member: discord.Member) -> discord.Embed:
    embed = _base_embed("📤 Member Left", config.Discord.warn_color)
    embed.add_field(name="Member", value=f"{member} (`{member.id}`)", inline=False)
    try:
        if member.joined_at is not None:
            embed.add_field(
                name="Joined",
                value=discord.utils.format_dt(member.joined_at, style="R"),
                inline=True,
            )
    except Exception:
        pass
    return embed


def build_member_ban(user) -> discord.Embed:
    embed = _base_embed("🔨 Member Banned", config.Discord.danger_color)
    embed.add_field(name="User", value=f"{user} (`{user.id}`)", inline=False)
    return embed


def build_member_unban(user) -> discord.Embed:
    embed = _base_embed("♻️ Member Unbanned", config.Discord.success_color)
    embed.add_field(name="User", value=f"{user} (`{user.id}`)", inline=False)
    return embed


def build_member_update(before: discord.Member, after: discord.Member) -> discord.Embed:
    embed = _base_embed("👤 Member Updated", config.Discord.info_color)
    embed.add_field(name="Member", value=f"{after.mention} (`{after.id}`)", inline=False)

    changes = []
    if before.nick != after.nick:
        changes.append(f"**Nickname:** `{before.nick}` → `{after.nick}`")

    before_roles = set(before.roles)
    after_roles = set(after.roles)
    added = after_roles - before_roles
    removed = before_roles - after_roles
    if added:
        changes.append("**Roles added:** " + ", ".join(r.mention for r in added))
    if removed:
        changes.append("**Roles removed:** " + ", ".join(r.mention for r in removed))

    embed.add_field(name="Changes", value=_trunc("\n".join(changes)) if changes else "*(no tracked changes)*", inline=False)
    return embed
