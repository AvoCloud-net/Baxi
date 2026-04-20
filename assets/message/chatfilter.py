"""Chatfilter entry point.

Thin wrapper over the local SafeText pipeline. External HTTP calls to the
legacy SafeText keyword API and Ollama AI are gone — all classification now
happens in-process via transformers models plus local regex stages.

The `Chatfilter.check` signature is preserved so callers in events.py do not
need to change. The `history` kwarg is accepted but unused (kept for API
compatibility; the classifier is stateless).
"""
from typing import Any, Dict

from reds_simple_logger import Logger

import assets.data as datasys
from assets.message.safetext import check as pipeline_check

logger = Logger()


# Category labels retained for dashboard parity with the old Ollama prompt.
AI_CATEGORIES: Dict[str, str] = {
    "1": "NSFW / Explicit Content",
    "2": "Insults / Toxicity",
    "3": "Hate Speech / Discrimination",
    "4": "Doxxing / Personal Data",
    "5": "Suicide / Self-Harm",
}


class Chatfilter:
    async def check(
        self,
        message:  str,
        gid:      int,
        cid:      int,
        user_id:  int = 0,
        history:  list[dict] | None = None,   # unused, kept for compat
    ) -> Dict[str, Any]:

        chatfilter_data: dict = dict(datasys.load_data(gid, "chatfilter"))

        # Channel bypass whitelist
        bypass = [str(c) for c in chatfilter_data.get("bypass", [])]
        if bypass and str(cid) in bypass:
            return {"code": "safe", "flagged": False, "distance": None,
                    "reason": "no_issues_detected", "json": {}}

        guild_lang: str = str(datasys.load_data(gid, "lang") or "en")

        raw_categories: dict = chatfilter_data.get(
            "ai_categories",
            {k: True for k in AI_CATEGORIES},
        )
        enabled_categories: set[str] = {k for k, v in raw_categories.items() if v}

        # "AI" (default) = rule-based + ML models. "SafeText" = rule-based only.
        system = str(chatfilter_data.get("system", "AI"))
        if system != "AI":
            enabled_categories -= {"1", "2", "3"}

        return await pipeline_check(
            message=message,
            gid=gid,
            cid=cid,
            user_id=user_id,
            chatfilter_data=chatfilter_data,
            guild_lang=guild_lang,
            enabled_categories=enabled_categories,
        )
