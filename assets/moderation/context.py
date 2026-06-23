"""RiskContext -  the shared per-message risk view.

Built once per message and handed to every moderation rule so enforcement can adapt to a
user's standing. Standing is computed LIVE (account age + this guild's own history + opt-in
network safety flag) — never read from a stored cross-server profile (removed for Discord
Developer Policy compliance; see assets/trust.py and assets/moderation/risk.py).

A tiny TTL cache avoids recomputing for every message during a burst from the same user.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from .risk import assess, RiskSignals
from .verdict import Verdict, worst

# ── Context cache ───────────────────────────────────────────────────────────────
_CACHE_TTL = 5.0   # seconds; covers a spam burst, stays fresh enough
_cache: dict[tuple[int, int], "RiskContext"] = {}


@dataclass
class RiskContext:
    user_id:   int
    guild_id:  int
    signals:   RiskSignals = field(default_factory=RiskSignals)
    _built_at: float = 0.0
    verdicts:  list[Verdict] = field(default_factory=list)

    # ── Standing (delegated to live signals) ─────────────────────────────────────
    @property
    def is_trusted(self) -> bool:
        return self.signals.is_trusted

    @property
    def is_risky(self) -> bool:
        return self.signals.is_risky

    @property
    def strictness(self) -> float:
        return self.signals.strictness

    # ── Verdict collection ───────────────────────────────────────────────────────
    def add(self, verdict: Verdict) -> Verdict:
        self.verdicts.append(verdict)
        return verdict

    @property
    def worst(self) -> Verdict | None:
        return worst(self.verdicts)

    # ── Construction ─────────────────────────────────────────────────────────────
    @classmethod
    def build(cls, user_id: int, guild_id: int, account_age_days: int | None = None) -> "RiskContext":
        key = (guild_id, user_id)
        now = time.time()
        cached = _cache.get(key)
        if cached is not None and (now - cached._built_at) < _CACHE_TTL:
            cached.verdicts = []   # fresh verdict list for this message; reuse standing
            return cached

        signals = assess(user_id, guild_id, account_age_days=account_age_days)
        ctx = cls(user_id=user_id, guild_id=guild_id, signals=signals, _built_at=now)
        _cache[key] = ctx
        return ctx
