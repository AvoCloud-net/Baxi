"""Live, stateless risk assessment.

Replaces the removed cross-server trust score. Risk is computed on the fly from data Discord
already exposes (account age) plus *this guild's own* moderation history, and an opt-in,
human-gated network safety flag. Nothing here is stored as a per-user profile — the result is
used for the on-join alert / adaptive strictness and then discarded.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import assets.data as datasys
import assets.trust as safety
from assets.message.warnings import get_warnings

# Account younger than this many days is a risk signal on its own (throwaway/raid accounts).
NEW_ACCOUNT_DAYS = 7
# This-guild warning count at/above which the user is treated as risky locally.
RISKY_WARN_COUNT = 2


@dataclass
class RiskSignals:
    account_age_days: int | None = None
    warnings:         int = 0
    guild_flagged:    bool = False          # flagged in THIS guild's local users table
    safety_category:  str | None = None     # coarse category from opt-in network safety list
    reasons:          list[str] = field(default_factory=list)

    @property
    def is_new_account(self) -> bool:
        return self.account_age_days is not None and self.account_age_days < NEW_ACCOUNT_DAYS

    @property
    def is_risky(self) -> bool:
        return bool(
            self.is_new_account
            or self.warnings >= RISKY_WARN_COUNT
            or self.guild_flagged
            or self.safety_category is not None
        )

    @property
    def is_trusted(self) -> bool:
        return not self.is_risky and (self.account_age_days is None or self.account_age_days >= 90) and self.warnings == 0

    @property
    def strictness(self) -> float:
        """Detector sensitivity multiplier. >1 stricter (risky), <1 lenient (trusted)."""
        if self.is_risky:
            return 1.5
        if self.is_trusted:
            return 0.75
        return 1.0


def assess(user_id: int, guild_id: int, account_age_days: int | None = None,
           consume_safety_list: bool = True) -> RiskSignals:
    """Compute live risk signals for a user in a guild. No storage, no profile."""
    sig = RiskSignals(account_age_days=account_age_days)

    # This guild's own warning history (per-guild, not aggregated across servers).
    try:
        sig.warnings = len(get_warnings(guild_id, user_id))
    except Exception:
        sig.warnings = 0

    # This guild's local flag (per-guild users table).
    try:
        users = dict(datasys.load_data(guild_id, "users"))
        entry = users.get(str(user_id))
        sig.guild_flagged = bool(entry and entry.get("flagged"))
    except Exception:
        sig.guild_flagged = False

    # Opt-in network safety list (human-gated denylist) — coarse category only.
    if consume_safety_list:
        try:
            flag = safety.get_flag(user_id)
            if flag:
                sig.safety_category = flag.get("category", "other")
        except Exception:
            sig.safety_category = None

    # Human-readable reasons (for staff alerts).
    if sig.is_new_account:
        sig.reasons.append(f"New account ({sig.account_age_days}d old)")
    if sig.warnings >= RISKY_WARN_COUNT:
        sig.reasons.append(f"{sig.warnings} active warnings in this server")
    if sig.guild_flagged:
        sig.reasons.append("Flagged in this server")
    if sig.safety_category:
        sig.reasons.append(f"On network safety list ({sig.safety_category})")

    return sig
