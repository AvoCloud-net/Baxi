import time
from collections import defaultdict

import discord
from reds_simple_logger import Logger

import assets.data as datasys
from assets.moderation.verdict import Verdict, safe

logger = Logger()

# Map the dashboard's antispam "action" setting to an engine enforcement action.
_ACTION_MAP = {"mute": "timeout", "warn": "warn", "kick": "kick", "ban": "ban"}


class AntiSpam:
    """Spam detector. Pure detection -  produces a :class:`Verdict`; enforcement and
    user-facing embeds are handled centrally by the moderation engine/enforce layer."""

    def __init__(self):
        # {guild_id: {user_id: [timestamps]}}
        self.message_timestamps: dict[int, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
        # {guild_id: {user_id: [(content, timestamp)]}}
        self.message_contents: dict[int, dict[int, list[tuple[str, float]]]] = defaultdict(lambda: defaultdict(list))

    def evaluate(self, message: discord.Message, ctx=None) -> Verdict:
        """Inspect *message* for spam and return a Verdict.

        When *ctx* is a RiskContext, the sliding-window limits are scaled by the user's
        standing (risky users get tighter limits, trusted users a little slack).
        """
        if message.guild is None:
            return safe("antispam")

        antispam_config: dict = dict(datasys.load_data(message.guild.id, "antispam"))
        if not antispam_config.get("enabled", False):
            return safe("antispam")

        # Channel whitelist
        whitelisted_channels = [str(c) for c in antispam_config.get("whitelisted_channels", [])]
        if whitelisted_channels and str(message.channel.id) in whitelisted_channels:
            return safe("antispam")

        # Role whitelist
        if isinstance(message.author, discord.Member):
            whitelisted_roles = [str(r) for r in antispam_config.get("whitelisted_roles", [])]
            if whitelisted_roles and any(str(role.id) in whitelisted_roles for role in message.author.roles):
                return safe("antispam")

        guild_id = message.guild.id
        user_id = message.author.id
        now = time.time()

        max_messages = int(antispam_config.get("max_messages", 5))
        interval = int(antispam_config.get("interval", 5))
        max_duplicates = int(antispam_config.get("max_duplicates", 3))
        duplicate_window = int(antispam_config.get("duplicate_window", 60))
        action = str(antispam_config.get("action", "mute"))

        # Adaptive limits: tighten for risky users, loosen slightly for trusted ones.
        if ctx is not None:
            strict = ctx.strictness
            if strict != 1.0:
                max_messages = max(2, round(max_messages / strict))
                max_duplicates = max(2, round(max_duplicates / strict))

        # Clean old timestamps
        self.message_timestamps[guild_id][user_id] = [
            t for t in self.message_timestamps[guild_id][user_id]
            if now - t < interval
        ]
        self.message_timestamps[guild_id][user_id].append(now)

        # Drop entries older than duplicate_window, then append current
        self.message_contents[guild_id][user_id] = [
            (c, t) for c, t in self.message_contents[guild_id][user_id]
            if now - t < duplicate_window
        ]
        self.message_contents[guild_id][user_id].append((message.clean_content, now))
        if len(self.message_contents[guild_id][user_id]) > max_duplicates + 2:
            self.message_contents[guild_id][user_id] = self.message_contents[guild_id][user_id][-(max_duplicates + 2):]

        kind: str | None = None

        # Rate limit check
        if len(self.message_timestamps[guild_id][user_id]) > max_messages:
            kind = "triggered"

        # Duplicate check (only msgs within duplicate_window)
        if kind is None:
            recent = self.message_contents[guild_id][user_id]
            if len(recent) >= max_duplicates:
                last_msgs = [c for c, _ in recent[-max_duplicates:]]
                if len(set(last_msgs)) == 1 and last_msgs[0] != "":
                    kind = "duplicate"

        if kind is None:
            return safe("antispam")

        # Spam confirmed -  reset windows so a single burst counts once.
        self.message_timestamps[guild_id][user_id].clear()
        self.message_contents[guild_id][user_id].clear()

        return Verdict(
            rule="antispam",
            flagged=True,
            action=_ACTION_MAP.get(action, "timeout"),
            delete=True,
            reason=f"Anti-Spam ({kind})",
            event_type="antispam",
            severity="low",
            meta={"kind": kind, "config_action": action},
        )
