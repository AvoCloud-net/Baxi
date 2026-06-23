"""On-join gating -  assess a joining member's risk live and alert the team.

Notifies the server team for any risky join (new account, active warnings here, locally
flagged, or on the opt-in network safety list). Risk is computed live (no stored score, no
cross-server profile). Enforcement (kick/quarantine) applies only to concrete signals — a
human-set network/local flag — never to a merely-new account.
"""
from __future__ import annotations

import datetime

import discord
from discord.ext import commands
from reds_simple_logger import Logger

import assets.data as datasys
import config.config as config
import assets.repo as repo
from assets.share import admin_log
from .risk import assess

logger = Logger()


async def check_join(member: discord.Member, bot: commands.AutoShardedBot) -> bool:
    """Evaluate a joining member's live risk; alert / act per the guild's mod_gate policy.
    Returns True if the join was risky."""
    guild = member.guild
    try:
        cfg = dict(datasys.load_data(guild.id, "mod_gate"))
    except Exception:
        return False
    if not cfg.get("enabled", False) or member.bot:
        return False

    account_age_days = (datetime.datetime.now(datetime.timezone.utc) - member.created_at).days
    # Consume the network safety list only if the guild participates AND opted in via mod_gate.
    participates = datasys.load_data(guild.id, "prism_enabled") is not False
    consume = participates and bool(cfg.get("use_safety_list", True))
    sig = assess(member.id, guild.id, account_age_days=account_age_days, consume_safety_list=consume)

    if not sig.reasons:
        return False  # normal member — no alert spam

    # Enforce only on concrete human-set flags (network safety list or local flag).
    enforce = sig.safety_category is not None or sig.guild_flagged
    action = str(cfg.get("action", "quarantine"))
    context = {
        "account_age_days": account_age_days,
        "warnings": sig.warnings,
        "guild_flagged": sig.guild_flagged,
        "safety_category": sig.safety_category,
        "reasons": sig.reasons,
        "action": action if enforce else "notify",
        "joined_at": datetime.datetime.utcnow().isoformat(),
    }

    acted = False
    if enforce:
        try:
            if action == "kick":
                await member.kick(reason="Baxi mod-gate: on safety list / flagged")
                acted = True
            elif action in ("quarantine", "approve"):
                role_id = int(cfg.get("quarantine_role", 0) or 0)
                if role_id:
                    role = guild.get_role(role_id)
                    if role:
                        await member.add_roles(role, reason="Baxi mod-gate quarantine")
                        acted = True
            # action == "notify" → alert only
        except discord.Forbidden:
            logger.error(f"[ModGate] Missing permissions to {action} {member.name} in {guild.name}")
        except Exception as e:
            logger.error(f"[ModGate] action error: {e}")

    try:
        repo.add_review_item(guild.id, member.id, member.name, "join_gate", context)
    except Exception as e:
        logger.error(f"[ModGate] review enqueue failed: {e}")

    await _alert(member, bot, cfg, context)
    admin_log(
        "warning",
        f"Mod-Gate: risky join {member.name} ({member.id}) @ {guild.name} -  "
        f"{'; '.join(sig.reasons)}" + (f" → {action}" if acted else " → notified"),
        source="ModGate",
    )
    return True


async def _alert(member: discord.Member, bot: commands.AutoShardedBot, cfg: dict, context: dict) -> None:
    """Send a staff alert to the configured channel (best-effort)."""
    channel = None
    try:
        ch_id = int(cfg.get("log_channel", 0) or 0)
        if ch_id:
            channel = member.guild.get_channel(ch_id)
        if channel is None:
            notif = datasys.load_data(member.guild.id, "notification_channel")
            if notif:
                channel = member.guild.get_channel(int(notif))
    except Exception:
        channel = None
    if channel is None:
        return
    action = context.get("action", "notify")
    outcome = "flagged for review (no action taken)" if action == "notify" else f"**{action}d**"
    reasons = context.get("reasons", []) or ["–"]
    try:
        embed = discord.Embed(
            title=config.Icons.messageexclamation + " Mod-Gate · Risky join",
            description=(
                f"{member.mention} (`{member.id}`) joined and was {outcome}.\n\n"
                f"**Why:**\n" + "\n".join(f"• {r}" for r in reasons) + "\n\n"
                f"**Account age:** {context.get('account_age_days', '?')} days\n"
                f"Pending in the moderation review queue."
            ),
            color=config.Discord.danger_color,
        ).set_footer(text="Baxi · avocloud.net")
        embed.set_thumbnail(url=member.display_avatar.url)
        await channel.send(embed=embed)
    except Exception:
        pass
