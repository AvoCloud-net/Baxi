"""Chatfilter entry point: resolves the guild config and runs the SafeText pipeline.

All classification happens in-process (see assets/message/safetext/pipeline.py).
"""
from typing import Any, Dict

from reds_simple_logger import Logger

import assets.data as datasys
from assets.message.safetext import check as pipeline_check

logger = Logger()


# Category labels shown in the dashboard.
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
        message:       str,
        gid:           int,
        cid:           int,
        user_id:       int = 0,
        strictness:    float = 1.0,     # risk-weight from RiskContext
        parent_id:     int | None = None,  # parent channel of a thread
        targeted_hint: bool = False,    # reply or member mention
        is_globalchat: bool = False,
    ) -> Dict[str, Any]:

        chatfilter_data: dict = dict(datasys.load_data(gid, "chatfilter"))

        raw_categories: dict = chatfilter_data.get(
            "ai_categories",
            {k: True for k in AI_CATEGORIES},
        )
        enabled_categories: set[str] = {k for k, v in raw_categories.items() if v}

        if is_globalchat:
            # The global chat is shared by every server: no guild may weaken it.
            chatfilter_data = {**chatfilter_data, "phishing_filter": True}
            enabled_categories = set(AI_CATEGORIES)
        else:
            bypass = {str(c) for c in chatfilter_data.get("bypass", [])}
            if str(cid) in bypass or (parent_id is not None and str(parent_id) in bypass):
                return {"code": "safe", "flagged": False, "distance": None,
                        "reason": "no_issues_detected", "json": {}}

        guild_lang: str = str(datasys.load_data(gid, "lang") or "en")

        # "AI" (default) = rules + toxicity model. "SafeText" = rules only.
        use_ml = is_globalchat or str(chatfilter_data.get("system", "AI")) == "AI"

        return await pipeline_check(
            message=message,
            gid=gid,
            cid=cid,
            user_id=user_id,
            chatfilter_data=chatfilter_data,
            guild_lang=guild_lang,
            enabled_categories=enabled_categories,
            strictness=strictness,
            use_ml=use_ml,
            targeted_hint=targeted_hint,
        )
