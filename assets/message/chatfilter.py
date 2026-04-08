import aiohttp
import asyncio
import re
import time
from collections import deque
from typing import Dict, Any

from reds_simple_logger import Logger
from assets.translate import translate_api
from assets.share import phishing_url_list, admin_log as _admin_log
import config.config as config
import config.auth as auth
import assets.data as datasys

logger = Logger()


# ── AI concurrency limiter ──────────────────────────────────────────────────
# Max 5 simultaneous AI requests; additional requests queue and wait up to
# _AI_QUEUE_TIMEOUT seconds before falling back to SafeText.
_AI_MAX_CONCURRENT  = 5
_AI_QUEUE_TIMEOUT   = 3.0   # seconds to wait for a free AI slot
_ai_semaphore       = asyncio.Semaphore(_AI_MAX_CONCURRENT)

# ── Per-user rapid-sender detection ─────────────────────────────────────────
# Users sending faster than _SPAM_ROUTE_THRESH messages within _SPAM_WINDOW_SECS
# are routed to SafeText only, to avoid flooding the AI with spam traffic.
_SPAM_WINDOW_SECS   = 5.0
_SPAM_ROUTE_THRESH  = 4
_user_msg_times: dict[str, deque] = {}

# ── AI category metadata ─────────────────────────────────────────────────────
AI_CATEGORIES: dict[str, str] = {
    "1": "NSFW / Explicit Content",
    "2": "Insults / Toxicity",
    "3": "Hate Speech / Discrimination",
    "4": "Doxxing / Personal Data",
    "5": "Suicide / Self-Harm",
}


def _is_rapid_sender(user_id: int) -> bool:
    """Return True if user is sending messages faster than the spam threshold."""
    uid  = str(user_id)
    now  = time.monotonic()
    dq   = _user_msg_times.setdefault(uid, deque())
    dq.append(now)
    while dq and dq[0] < now - _SPAM_WINDOW_SECS:
        dq.popleft()
    return len(dq) >= _SPAM_ROUTE_THRESH


def _safe_result() -> Dict[str, Any]:
    return {
        "code":     "safe",
        "flagged":  False,
        "distance": None,
        "reason":   "no_issues_detected",
        "json":     {},
    }


class Chatfilter:
    def __init__(self):
        self.timeout = aiohttp.ClientTimeout(total=10)

    async def check(
        self,
        message:  str,
        gid:      int,
        cid:      int,
        user_id:  int = 0,
        history:  list[dict] | None = None,
    ) -> Dict[str, Any]:
        chatfilter_data: dict = dict(datasys.load_data(gid, "chatfilter"))

        # ── 0. Channel bypass (whitelist) ────────────────────────────────────
        bypass = [str(c) for c in chatfilter_data.get("bypass", [])]
        if bypass and str(cid) in bypass:
            return _safe_result()

        # ── 1. Phishing (local, zero-cost) ──────────────────────────────────
        if chatfilter_data.get("phishing_filter", False):
            phishing_result = self._check_phishing_urls(message)
            if phishing_result.get("flagged"):
                logger.warn(
                    f"Chatfilter | Phishing detected — user={user_id} guild={gid} "
                    f"domain={phishing_result.get('json', {}).get('domain', '?')}"
                )
                _admin_log("warning",
                    f"Phishing detected — user={user_id} guild={gid} "
                    f"domain={phishing_result.get('json', {}).get('domain', '?')}",
                    source="Chatfilter"
                )
                return phishing_result

        preferred_system = chatfilter_data.get("system", "SafeText").lower()

        # ── 2. Guild language ────────────────────────────────────────────────
        guild_lang: str = str(datasys.load_data(gid, "lang") or "en")

        # ── 3. Rapid-sender routing ──────────────────────────────────────────
        rapid = _is_rapid_sender(user_id) if user_id else False
        if rapid:
            logger.warn(
                f"Chatfilter | Rapid sender detected — user={user_id} guild={gid} "
                f"→ routing to SafeText only (AI skipped)"
            )
            _admin_log("warning",
                f"Rapid sender → SafeText only — user={user_id} guild={gid}",
                source="Chatfilter"
            )

        # ── 4. SafeText pre-screen (always, fast) ───────────────────────────
        safetext_result = await self._try_safetext_check(
            message, gid, cid, chatfilter_data, guild_lang
        )

        # Custom keyword hit → return immediately, no AI needed
        if safetext_result and safetext_result.get("reason") == "custom":
            logger.info(
                f"Chatfilter | SafeText [custom keyword] — user={user_id} guild={gid} "
                f"reason={safetext_result.get('reason')}"
            )
            _admin_log("warning",
                f"SafeText [custom keyword] flagged — user={user_id} guild={gid}",
                source="Chatfilter"
            )
            return safetext_result

        # SafeText flagged → content clearly bad, skip AI
        if safetext_result and safetext_result.get("flagged"):
            _st_json = safetext_result.get("json", {})
            logger.info(
                f"Chatfilter | SafeText [flagged] — user={user_id} guild={gid} "
                f"reason={safetext_result.get('reason')} distance={safetext_result.get('distance')} "
                f"word={_st_json.get('word', '—')} → AI skipped"
            )
            _admin_log("warning",
                f"SafeText flagged — user={user_id} guild={gid} | "
                f"reason={safetext_result.get('reason')} distance={safetext_result.get('distance')} "
                f"word={_st_json.get('word', '—')} full={_st_json}",
                source="Chatfilter"
            )
            return safetext_result

        # ── 5. Routing decision ─────────────────────────────────────────────
        if rapid or preferred_system == "safetext":
            logger.info(
                f"Chatfilter | SafeText [clean] — user={user_id} guild={gid} "
                f"system={preferred_system}{' rapid' if rapid else ''}"
            )
            return safetext_result or _safe_result()

        # ── 6. Resolve enabled AI categories ────────────────────────────────
        raw_categories: dict = chatfilter_data.get(
            "ai_categories",
            {k: True for k in AI_CATEGORIES},
        )
        enabled_categories: set[str] = {k for k, v in raw_categories.items() if v}

        # ── 7. AI via queue (preferred = AI, SafeText said clean) ───────────
        logger.working(
            f"Chatfilter | Queuing AI check — user={user_id} guild={gid} "
            f"slots_free={_ai_semaphore._value}/{_AI_MAX_CONCURRENT}"
        )
        _admin_log("info",
            f"AI check queued — user={user_id} guild={gid} "
            f"slots={_ai_semaphore._value}/{_AI_MAX_CONCURRENT}",
            source="Chatfilter"
        )
        ai_result = await self._try_ai_check_queued(
            message,
            history=history,
            enabled_categories=enabled_categories,
            skip_translation=guild_lang in {"de", "en"},
        )

        if ai_result is not None:
            _raw = ai_result.get("_raw", "?")
            if ai_result.get("flagged"):
                logger.info(
                    f"Chatfilter | AI [flagged] — user={user_id} guild={gid} "
                    f"reason={ai_result.get('reason')} raw=\"{_raw}\""
                )
                _admin_log("warning",
                    f"AI flagged — user={user_id} guild={gid} "
                    f"reason={ai_result.get('reason')} | raw: \"{_raw}\"",
                    source="Chatfilter"
                )
            else:
                logger.info(
                    f"Chatfilter | AI [clean] — user={user_id} guild={gid} raw=\"{_raw}\""
                )
                _admin_log("info",
                    f"AI clean — user={user_id} guild={gid} | raw: \"{_raw}\"",
                    source="Chatfilter"
                )
            return ai_result

        # AI failed or timed out → SafeText fallback
        logger.warn(
            f"Chatfilter | AI unavailable, falling back to SafeText — user={user_id} guild={gid}"
        )
        _admin_log("warning",
            f"AI unavailable → SafeText fallback — user={user_id} guild={gid}",
            source="Chatfilter"
        )
        return safetext_result or _safe_result()

    # ── AI with semaphore queue ──────────────────────────────────────────────

    async def _try_ai_check_queued(
        self,
        message: str,
        history: list[dict] | None = None,
        enabled_categories: set[str] | None = None,
        skip_translation: bool = False,
    ) -> Dict[str, Any] | None:
        """Acquire a semaphore slot (queue), run AI, release. Falls back to None
        if no slot becomes available within _AI_QUEUE_TIMEOUT seconds."""
        try:
            async with asyncio.timeout(_AI_QUEUE_TIMEOUT):
                async with _ai_semaphore:
                    return await self._try_ai_check(
                        message,
                        history=history,
                        enabled_categories=enabled_categories,
                        skip_translation=skip_translation,
                    )
        except asyncio.TimeoutError:
            logger.warn(
                f"Chatfilter | AI queue full (>{_AI_QUEUE_TIMEOUT}s wait) — degrading to SafeText"
            )
            _admin_log("warning",
                f"AI queue full (>{_AI_QUEUE_TIMEOUT}s wait) — degrading to SafeText",
                source="Chatfilter"
            )
            return None

    # ── SafeText ─────────────────────────────────────────────────────────────

    async def _try_safetext_check(
        self, message: str, gid: int, cid: int, chatfilter_data: dict, guild_lang: str = "en"
    ) -> Dict[str, Any] | None:
        json_data = {
            "message":    message,
            "gid":        gid,
            "cid":        cid,
            "lang":       guild_lang if guild_lang in {"de", "en"} else "en",
            "c_badwords": chatfilter_data.get("c_badwords"),
            "c_goodwords": chatfilter_data.get("c_goodwords"),
            "key":        auth.Chatfilter.api_key,
        }

        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(
                    config.Chatfilter.chatfilter_url, json=json_data
                ) as response:
                    if response.status == 200:
                        data = await response.json()

                        if not data:
                            logger.info(f"Chatfilter | SafeText raw → (empty / clean)")
                            _admin_log("info", "SafeText raw → (empty / clean)", source="Chatfilter")
                            return {
                                "code":     "safe",
                                "flagged":  False,
                                "distance": None,
                                "reason":   None,
                                "json":     {},
                            }

                        logger.info(
                            f"Chatfilter | SafeText raw → code={data.get('code')} "
                            f"distance={data.get('distance')} word={data.get('word', '—')} "
                            f"full={data}"
                        )
                        _admin_log("warning",
                            f"SafeText raw → code={data.get('code')} distance={data.get('distance')} "
                            f"word={data.get('word', '—')} full={data}",
                            source="Chatfilter"
                        )
                        return {
                            "code":     "safetext-filter",
                            "flagged":  True,
                            "distance": str(data.get("distance", "0")),
                            "reason":   f"{data.get('code')}",
                            "json":     data,
                        }

        except (aiohttp.ClientError, asyncio.TimeoutError, KeyError) as e:
            logger.error(f"Chatfilter | SafeText request failed: {e}")
            _admin_log("error", f"SafeText request failed: {e}", source="Chatfilter")
            return None

    # ── AI ───────────────────────────────────────────────────────────────────

    async def _try_ai_check(
        self,
        message: str,
        history: list[dict] | None = None,
        enabled_categories: set[str] | None = None,
        skip_translation: bool = False,
    ) -> Dict[str, Any] | None:
        try:
            translated_message = message if skip_translation else await translate_api(message)

            # Build message content: prepend conversation history if available
            if history:
                history_text = "\n".join(
                    f"[{h['author']}]: {h['content']}" for h in history
                )
                user_content = (
                    f"[Conversation history]\n{history_text}\n\n"
                    f"[Current message]\n{translated_message}"
                )
            else:
                user_content = translated_message

            payload = {
                "model":       "ai_chatsafety_baxi_v2.1:latest",
                "messages":    [{"role": "user", "content": user_content}],
                "temperature": 0.1,
                "max_tokens":  10,
            }
            headers = {
                "Content-Type":  "application/json",
                "Authorization": f"Bearer {auth.Chatfilter.ai_key}",
            }

            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(
                    config.Chatfilter.ai_url, json=payload, headers=headers
                ) as ai_response_raw:
                    ai_response_json = await ai_response_raw.json()

            content = ai_response_json["choices"][0]["message"]["content"].strip()
            # Model may return "safe", "1"–"5", or "UNSAFE:1"–"UNSAFE:5"
            raw_code = content.split()[0].upper()
            if raw_code.startswith("UNSAFE:"):
                code = raw_code.split(":", 1)[1].strip()
            else:
                code = raw_code.lower()  # "safe" or bare digit

            flagged = code in AI_CATEGORIES
            # Suppress flag if this category is disabled for the guild
            if flagged and enabled_categories is not None:
                flagged = code in enabled_categories

            return {
                "code":     f"ai-{code}" if flagged else "safe",
                "flagged":  flagged,
                "distance": None,
                "reason":   code if flagged else "safe",
                "_raw":     content,
                "json":     {
                    "status":   "unsafe" if flagged else "safe",
                    "category": code,
                },
            }

        except (aiohttp.ClientError, asyncio.TimeoutError, KeyError) as e:
            logger.error(f"Chatfilter | AI request failed: {e}")
            _admin_log("error", f"AI request failed: {e}", source="Chatfilter")
            return None

    # ── Phishing ─────────────────────────────────────────────────────────────

    _URL_PATTERN = re.compile(
        r"https?://([^\s/]+)"
        r"|(?<![.\w])([a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z]{2,})+)(?![.\w])"
    )

    def _check_phishing_urls(self, message: str) -> Dict[str, Any]:
        if not phishing_url_list:
            return {"code": "safe", "flagged": False, "distance": None, "reason": None, "json": {}}

        for match in self._URL_PATTERN.finditer(message):
            raw    = (match.group(1) or match.group(2)).lower()
            domain = raw.split("/")[0].split(":")[0].lstrip("www.")
            if domain in phishing_url_list:
                return {
                    "code":     "phishing",
                    "flagged":  True,
                    "distance": None,
                    "reason":   "phishing",
                    "json":     {"domain": domain},
                }
        return {"code": "safe", "flagged": False, "distance": None, "reason": None, "json": {}}
