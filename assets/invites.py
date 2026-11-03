"""Invite leaderboard - who brought how many members to the server.

Tracking works by diffing the server's invite use counts on every join (needs Manage Server).
Only the pair (joined member -> inviter, code) is stored. Joins through the vanity URL, OAuth
or when the bot lacks the permission stay unattributed. History starts when the bot sees the
server's invites for the first time.
"""
from __future__ import annotations

import time

import discord
from discord import app_commands
from discord.ext import commands

import assets.data as datasys
import assets.db as db
import config.config as config
from reds_simple_logger import Logger

logger = Logger()

TOP_LIMIT = 10

# guild_id -> {code: (uses, inviter_id)}
_cache: dict[int, dict[str, tuple[int, int]]] = {}


# ── Cache ────────────────────────────────────────────────────────────────────

async def _fetch(guild: discord.Guild) -> dict[str, tuple[int, int]] | None:
    if not guild.me or not guild.me.guild_permissions.manage_guild:
        return None
    try:
        invites = await guild.invites()
    except (discord.Forbidden, discord.HTTPException):
        return None
    return {i.code: (i.uses or 0, i.inviter.id if i.inviter else 0) for i in invites}


def enabled(guild_id: int) -> bool:
    return bool(dict(datasys.load_data(guild_id, "invites") or {}).get("enabled", False))


async def prime(guild: discord.Guild) -> None:
    snap = await _fetch(guild)
    if snap is not None:
        _cache[guild.id] = snap


async def prime_all(bot: commands.AutoShardedBot) -> None:
    for guild in bot.guilds:
        if enabled(guild.id):
            await prime(guild)


# ── Storage ──────────────────────────────────────────────────────────────────

def record_join(guild_id: int, user_id: int, inviter_id: int, code: str) -> None:
    db.ensure_guild(guild_id)
    db.execute(
        "INSERT OR REPLACE INTO invite_joins (guild_id,user_id,inviter_id,code,joined_at) VALUES (?,?,?,?,?)",
        (guild_id, str(user_id), str(inviter_id), code, int(time.time())),
    )


def leaderboard(guild_id: int, limit: int = TOP_LIMIT) -> list:
    return db.query(
        "SELECT inviter_id, COUNT(*) AS total FROM invite_joins WHERE guild_id=? AND inviter_id!='0' "
        "GROUP BY inviter_id ORDER BY total DESC, MIN(joined_at) ASC LIMIT ?",
        (guild_id, limit),
    )


def invited_ids(guild_id: int, inviter_id: int) -> list[str]:
    return [r["user_id"] for r in db.query(
        "SELECT user_id FROM invite_joins WHERE guild_id=? AND inviter_id=?", (guild_id, str(inviter_id)),
    )]


def _t(guild_id: int) -> dict:
    return datasys.load_lang_file(guild_id)["invites"]


# ── Events ───────────────────────────────────────────────────────────────────

async def on_member_join(member: discord.Member) -> None:
    if member.bot or not enabled(member.guild.id):
        return
    guild = member.guild
    before = _cache.get(guild.id)
    after = await _fetch(guild)
    if after is None:
        return
    _cache[guild.id] = after
    if before is None:
        return
    used = [c for c, (uses, _) in after.items() if uses > before.get(c, (0, 0))[0]]
    # an invite that vanished (max uses reached) was the one used if nothing else grew
    if not used:
        used = [c for c in before if c not in after]
    if len(used) != 1:
        return  # ambiguous (parallel joins) or vanity/unknown: do not guess
    code = used[0]
    inviter = (after.get(code) or before.get(code))[1]
    if inviter and inviter != member.id:
        record_join(guild.id, member.id, inviter, code)


def register(bot: commands.AutoShardedBot) -> None:
    async def _ready():
        await prime_all(bot)

    async def _guild_join(guild: discord.Guild):
        if enabled(guild.id):
            await prime(guild)

    async def _guild_remove(guild: discord.Guild):
        _cache.pop(guild.id, None)

    async def _invite_create(invite: discord.Invite):
        if invite.guild is None or invite.guild.id not in _cache:
            return
        snap = _cache.setdefault(invite.guild.id, {})
        snap[invite.code] = (invite.uses or 0, invite.inviter.id if invite.inviter else 0)

    async def _invite_delete(invite: discord.Invite):
        if invite.guild is not None:
            _cache.get(invite.guild.id, {}).pop(invite.code, None)

    # add_listener is additive; @bot.event would replace the handlers in events.py
    bot.add_listener(_ready, "on_ready")
    bot.add_listener(_guild_join, "on_guild_join")
    bot.add_listener(_guild_remove, "on_guild_remove")
    bot.add_listener(_invite_create, "on_invite_create")
    bot.add_listener(_invite_delete, "on_invite_delete")
    bot.add_listener(on_member_join, "on_member_join")


# ── Commands ─────────────────────────────────────────────────────────────────

def _present(guild: discord.Guild, ids: list[str]) -> int:
    return sum(1 for i in ids if i.isdigit() and guild.get_member(int(i)) is not None)


def invite_commands(bot: commands.AutoShardedBot):
    group = app_commands.Group(name="invites", description="Invite leaderboard", guild_only=True)

    async def _gate(interaction: discord.Interaction, t: dict) -> bool:
        """Enabled check; starts the invite cache on first use after enabling."""
        if not enabled(interaction.guild.id):
            await interaction.followup.send(t["disabled"], ephemeral=True)
            return False
        if interaction.guild.id not in _cache:
            await prime(interaction.guild)
        return True

    @group.command(name="top", description="Top inviters")
    async def top(interaction: discord.Interaction):
        await interaction.response.defer()
        guild = interaction.guild
        t = _t(guild.id)
        if not await _gate(interaction, t):
            return
        rows = leaderboard(guild.id)
        embed = discord.Embed(title=t["title"].format(guild=guild.name), color=config.Discord.color)
        if not rows:
            embed.description = t["empty"]
        else:
            medals = ["🥇", "🥈", "🥉"]
            lines = []
            for i, r in enumerate(rows):
                uid = int(r["inviter_id"])
                still = _present(guild, invited_ids(guild.id, uid))
                prefix = medals[i] if i < 3 else f"`{i + 1}.`"
                lines.append(f"{prefix} <@{uid}> -  " + t["line"].format(total=r["total"], active=still))
            embed.description = "\n".join(lines)
        embed.set_footer(text=t["footer"])
        await interaction.followup.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @group.command(name="user", description="Invites of a member")
    @app_commands.describe(member="Member (default: you)")
    async def user(interaction: discord.Interaction, member: discord.Member | None = None):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        t = _t(guild.id)
        if not await _gate(interaction, t):
            return
        target = member or interaction.user
        ids = invited_ids(guild.id, target.id)
        embed = discord.Embed(
            description=t["user"].format(user=target.mention, total=len(ids), active=_present(guild, ids)),
            color=config.Discord.color,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    bot.tree.add_command(group)
