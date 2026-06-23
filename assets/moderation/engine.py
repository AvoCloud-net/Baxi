"""ModerationEngine -  the central orchestrator.

Replaces the previous chain of independent ``on_message`` checks. For each message it
builds one shared :class:`RiskContext`, runs the rules against it, and enforces the
single worst action. Detection lives in the rule modules; deciding and acting live here.

Phase 1 routes Anti-Spam through the engine. Chatfilter detection still runs in
``events.py`` (it is entangled with terms / global-chat routing) but reuses the same
RiskContext via :meth:`context_for`, so risk-weighted filtering can hook in later.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass

import discord
from discord.ext import commands

from assets.message.antispam import AntiSpam
from .context import RiskContext
from .enforce import enforce_antispam


@dataclass
class ModerationResult:
    stop: bool                 # True → message fully handled (deleted); halt pipeline
    ctx:  RiskContext


def _account_age_days(user: discord.abc.User) -> int:
    return (datetime.datetime.now(datetime.timezone.utc) - user.created_at).days


class ModerationEngine:
    def __init__(self):
        # AntiSpam holds in-memory sliding windows; keep one instance for engine lifetime.
        self.antispam = AntiSpam()

    def context_for(self, message: discord.Message) -> RiskContext:
        """Build (or reuse the cached) RiskContext for this message's author."""
        return RiskContext.build(
            user_id=message.author.id,
            guild_id=message.guild.id,
            account_age_days=_account_age_days(message.author),
        )

    async def process(self, message: discord.Message, bot: commands.AutoShardedBot) -> ModerationResult:
        """Run the early, blocking moderation stage (currently Anti-Spam).

        Returns a ModerationResult; ``stop=True`` means the message was actioned and the
        rest of the ``on_message`` pipeline should not run.
        """
        ctx = self.context_for(message)

        verdict = self.antispam.evaluate(message, ctx)
        if verdict.flagged:
            ctx.add(verdict)
            await enforce_antispam(message, verdict, bot)
            return ModerationResult(stop=True, ctx=ctx)

        return ModerationResult(stop=False, ctx=ctx)
