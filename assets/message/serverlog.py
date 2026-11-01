import asyncio

import discord

import assets.data as datasys
import config.config as config
from reds_simple_logger import Logger


logger = Logger()
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


def should_log(guild_id, event_type: str) -> bool:
    """Cheap pre-check so callers can skip expensive audit-log lookups when the
    event is disabled / unconfigured. Mirrors the gate inside send_log."""
    try:
        cfg = dict(datasys.load_data(guild_id, "serverlog"))
        if not cfg.get("enabled", False):
            return False
        if not cfg.get("channel", ""):
            return False
        return bool(cfg.get("events", {}).get(event_type, False))
    except Exception:
        return False


# ----------------------------------------------------------------------------
# Audit-log actor lookup ("who did it")
# ----------------------------------------------------------------------------

# Audit entries already attributed to a gateway event. Discord writes one entry per
# action, so an entry may explain exactly one event; without this a later, unrelated
# event (e.g. a channel drag, which has no entry) would inherit the previous actor.
_consumed: dict = {}
# Batched entries (message deletes, member moves) are *reused* by Discord: the entry keeps
# its original id/timestamp and only its `count` grows. entry.id -> increments already
# attributed to an event, so each event consumes exactly one increment.
_seen_counts: dict = {}
_lookup_lock = asyncio.Lock()
_CACHE_MAX = 2000


def _prune(cache: dict):
    if len(cache) > _CACHE_MAX:
        for key in list(cache)[: _CACHE_MAX // 2]:
            cache.pop(key, None)


def audit_available(guild) -> bool:
    """True when Baxi may read the audit log (otherwise 'no entry' proves nothing)."""
    try:
        me = guild.me
        return me is not None and me.guild_permissions.view_audit_log
    except Exception:
        return False


async def fetch_actor(
    guild,
    action,
    target_id=None,
    *,
    delay: float = 1.2,
    max_age: float = 20.0,
    channel_id=None,
    counted: bool = False,
    retries: int = 0,
    retry_delay: float = 2.0,
):
    """Return ``(executor, reason)`` for the audit-log entry that caused the current
    gateway event, or ``(None, None)``.

    ``action`` may be one ``AuditLogAction`` or a tuple of them (the newest unclaimed
    match wins). ``target_id`` / ``channel_id`` narrow the match (``channel_id`` is the
    channel stored in ``entry.extra`` for message deletes and member moves).

    Discord populates audit logs a beat after the gateway event, so ``delay`` is applied
    first. Entries are claimed once (see ``_consumed``). With ``counted=True`` the entry
    is a batched one and an event only matches when its ``count`` grew since the last
    event that used it, regardless of how old the entry itself is. ``retries`` repeats the
    lookup (after ``retry_delay``) when Discord has not written the entry yet. Never raises.
    """
    if guild is None or action is None or not audit_available(guild):
        return None, None
    actions = action if isinstance(action, (tuple, list, set)) else (action,)
    for attempt in range(retries + 1):
        wait = delay if attempt == 0 else retry_delay
        if wait:
            try:
                await asyncio.sleep(wait)
            except Exception:
                pass
        try:
            async with _lookup_lock:
                found = await _scan(guild, actions, target_id, channel_id, counted, max_age)
        except (discord.Forbidden, discord.HTTPException) as err:
            logger.warn(f"[ServerLog] audit-log lookup failed in guild {guild.id}: {err}")
            return None, None
        except Exception as err:
            logger.error(f"[ServerLog] audit-log lookup error in guild {guild.id}: {type(err).__name__}: {err}")
            return None, None
        if found is not None:
            return found
    return None, None


async def _scan(guild, actions, target_id, channel_id, counted, max_age):
    entries = []
    for act in actions:
        async for entry in guild.audit_logs(limit=15, action=act):
            entries.append(entry)
    entries.sort(key=lambda e: e.id, reverse=True)
    now = discord.utils.utcnow()
    for entry in entries:
        if target_id is not None:
            tid = getattr(entry.target, "id", None)
            if tid is None or int(tid) != int(target_id):
                continue
        extra = getattr(entry, "extra", None)
        if channel_id is not None:
            cid = getattr(getattr(extra, "channel", None), "id", None)
            if cid is None or int(cid) != int(channel_id):
                continue
        age = (now - entry.created_at).total_seconds()
        if counted:
            count = int(getattr(extra, "count", 1) or 1)
            prior = _seen_counts.get(entry.id)
            if prior is None:
                if age > max_age:
                    # Unknown history of an old batched entry: remember where it
                    # stands, but don't guess that this event belongs to it.
                    _seen_counts[entry.id] = count
                    _prune(_seen_counts)
                    continue
                prior = 0
            if count <= prior:
                continue
            _seen_counts[entry.id] = prior + 1
            _prune(_seen_counts)
        else:
            if age > max_age or entry.id in _consumed:
                continue
            _consumed[entry.id] = now
            _prune(_consumed)
        return entry.user, getattr(entry, "reason", None)
    return None


async def prime_counts(bot):
    """Record the current `count` of batched audit entries (member moves, message
    deletes) for every guild that has the server log on, so the first event after a
    restart can tell a fresh increment from history. Never raises."""
    for guild in list(bot.guilds):
        try:
            if not (should_log(guild.id, "voice_move") or should_log(guild.id, "message_delete")):
                continue
            if not audit_available(guild):
                continue
            for act in (discord.AuditLogAction.member_move, discord.AuditLogAction.message_delete):
                async for entry in guild.audit_logs(limit=15, action=act):
                    count = int(getattr(getattr(entry, "extra", None), "count", 1) or 1)
                    _seen_counts.setdefault(entry.id, count)
            _prune(_seen_counts)
        except Exception:
            pass
        await asyncio.sleep(0.5)


def add_actor(embed: discord.Embed, actor, reason=None, label: str = "Performed by") -> discord.Embed:
    """Append an actor field (default 'Performed by') and an optional 'Reason'."""
    if actor is not None:
        mention = getattr(actor, "mention", str(actor))
        embed.add_field(name=label, value=f"{mention} (`{actor.id}`)", inline=False)
    if reason:
        embed.add_field(name="Reason", value=_trunc(reason, 500), inline=False)
    return embed


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

    # Permission overwrite diff (role/member specific perms)
    try:
        before_ow = getattr(before, "overwrites", {}) or {}
        after_ow = getattr(after, "overwrites", {}) or {}
        for target in set(before_ow) | set(after_ow):
            b_ov = before_ow.get(target)
            a_ov = after_ow.get(target)
            tname = getattr(target, "mention", getattr(target, "name", str(target)))
            if b_ov is None and a_ov is not None:
                changes.append(f"**Perms added** for {tname}")
            elif a_ov is None and b_ov is not None:
                changes.append(f"**Perms removed** for {tname}")
            elif b_ov != a_ov:
                diffs = []
                for perm in discord.Permissions.VALID_FLAGS:
                    bv = getattr(b_ov, perm)
                    av = getattr(a_ov, perm)
                    if bv != av:
                        state = "✅" if av is True else ("❌" if av is False else "➖")
                        diffs.append(f"{perm} {state}")
                if diffs:
                    changes.append(f"**Perms** for {tname}: " + ", ".join(diffs))
    except Exception:
        pass

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


def build_member_kick(member) -> discord.Embed:
    embed = _base_embed("👢 Member Kicked", config.Discord.danger_color)
    embed.add_field(name="Member", value=f"{member} (`{member.id}`)", inline=False)
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
