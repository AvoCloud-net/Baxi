"""Verdict -  the unit of moderation decision.

Each moderation rule (AntiSpam, Chatfilter, ...) inspects a message together with
the shared :class:`~assets.moderation.context.RiskContext` and returns a ``Verdict``.
The engine collects all verdicts and enforces the single worst action ("worst wins").
"""
from __future__ import annotations

from dataclasses import dataclass

# Enforcement actions ordered from lightest to heaviest. The engine enforces the
# highest-ranked action across all verdicts for a message.
ACTION_ORDER: dict[str, int] = {
    "none":    0,
    "delete":  1,
    "warn":    2,
    "timeout": 3,
    "kick":    4,
    "ban":     5,
}


@dataclass
class Verdict:
    """The outcome of a single rule evaluation.

    Attributes:
        rule:        Name of the rule that produced this verdict ("antispam", "chatfilter").
        flagged:     Whether the rule considers the message a violation.
        action:      Suggested enforcement action (key of :data:`ACTION_ORDER`).
        delete:      Whether the offending message should be removed.
        reason:      Human-readable reason / raw category code.
        event_type:  Prism event type to record (None = do not record).
        severity:    Coarse severity label for logging ("low"/"medium"/"high"/...).
        confidence:  Detector confidence 0..1 (0 if not applicable).
        meta:        Free-form extra payload (raw detector result, etc.).
    """

    rule:        str
    flagged:     bool = False
    action:      str = "none"
    delete:      bool = False
    reason:      str = ""
    event_type:  str | None = None
    severity:    str = "low"
    confidence:  float = 0.0
    meta:        dict | None = None

    @property
    def rank(self) -> int:
        return ACTION_ORDER.get(self.action, 0)


def safe(rule: str) -> Verdict:
    """Convenience: a non-flagged verdict for *rule*."""
    return Verdict(rule=rule, flagged=False)


def worst(verdicts: list[Verdict]) -> Verdict | None:
    """Return the verdict carrying the heaviest action, or None if list empty."""
    flagged = [v for v in verdicts if v.flagged]
    if not flagged:
        return None
    return max(flagged, key=lambda v: v.rank)
