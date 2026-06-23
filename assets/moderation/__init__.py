"""Baxi unified moderation engine.

A central orchestrator that builds one shared per-message user-risk view
(:class:`RiskContext`) and runs all moderation rules against it -  turning the old set of
isolated checks (chatfilter, antispam, ...) into one cooperating, risk-aware system.
"""
from .context import RiskContext
from .engine import ModerationEngine, ModerationResult
from .verdict import Verdict, safe, worst

__all__ = ["RiskContext", "ModerationEngine", "ModerationResult", "Verdict", "safe", "worst"]
