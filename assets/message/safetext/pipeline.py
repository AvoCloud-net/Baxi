"""SafeText pipeline orchestrator.

Stages in order:
  1. phishing URL match                   -> code "phishing"
  2. custom c_goodwords (whitelist)       -> short-circuit SAFE
  3. custom c_badwords                    -> code "custom"
  4. doxxing regex                        -> category 4
  5. suicide phrase list                  -> category 5
  6. NSFW model                           -> category 1
  7. multilingual toxic / hate model      -> category 2 or 3

Returns chatfilter-compatible dict:
  {code, flagged, distance, reason, json}
"""
import re
from typing import Any, Dict, Optional

from reds_simple_logger import Logger

from assets.message.safetext import custom, doxxing, models, suicide_words
from assets.message.safetext.logstore import record
from assets.share import admin_log as _admin_log, phishing_url_list

logger = Logger()


# ── thresholds ───────────────────────────────────────────────────────────────
TOXIC_THRESHOLD       = 0.60
HATE_THRESHOLD        = 0.55
NSFW_THRESHOLD        = 0.75

TOXIC_LABELS          = {"toxic", "severe_toxic", "obscene", "insult", "threat"}
HATE_LABELS           = {"identity_hate"}


# ── result helpers ───────────────────────────────────────────────────────────
def _safe() -> Dict[str, Any]:
    return {"code": "safe", "flagged": False, "distance": None,
            "reason": "no_issues_detected", "json": {}}


def _flagged(code: str, reason: str, cat: str, extra: dict) -> Dict[str, Any]:
    payload = {"status": "unsafe", "category": cat, **extra}
    return {"code": code, "flagged": True, "distance": None,
            "reason": reason, "json": payload}


# ── phishing ─────────────────────────────────────────────────────────────────
_URL_PATTERN = re.compile(
    r"https?://([^\s/]+)"
    r"|(?<![.\w])([a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z]{2,})+)(?![.\w])"
)


def _check_phishing(text: str) -> Optional[Dict[str, Any]]:
    if not phishing_url_list:
        return None
    for m in _URL_PATTERN.finditer(text):
        raw = (m.group(1) or m.group(2)).lower()
        domain = raw.split("/")[0].split(":")[0].lstrip("www.")
        if domain in phishing_url_list:
            return {"code": "phishing", "flagged": True, "distance": None,
                    "reason": "phishing", "json": {"domain": domain}}
    return None


# ── main entry ───────────────────────────────────────────────────────────────
async def check(
    message: str,
    gid: int,
    cid: int,
    user_id: int,
    chatfilter_data: dict,
    guild_lang: str,
    enabled_categories: set[str],
) -> Dict[str, Any]:
    """Run the full SafeText pipeline. Returns a chatfilter result dict."""

    nsfw_score: float | None = None
    toxic_scores: dict[str, float] = {}

    # 1. phishing
    if chatfilter_data.get("phishing_filter", False):
        if res := _check_phishing(message):
            return _finalize(gid, user_id, "phishing", res, message=message)

    # 2. goodword whitelist — short-circuit to safe
    goodword_hit = custom.match_goodword(message, chatfilter_data.get("c_goodwords"))
    if goodword_hit:
        res = _safe()
        res["reason"] = f"goodword:{goodword_hit}"
        return _finalize(gid, user_id, "goodword", res, message=message)

    # 3. custom badwords
    if badword := custom.match_badword(message, chatfilter_data.get("c_badwords")):
        res = {
            "code": "safetext-filter",
            "flagged": True,
            "distance": "0",
            "reason": "custom",
            "json": {"word": badword, "code": "custom"},
        }
        return _finalize(gid, user_id, "custom", res, message=message)

    # 4. doxxing (category 4)
    if "4" in enabled_categories:
        if dox := doxxing.detect(message):
            res = _flagged("ai-4", "4", "4", {"kind": dox["kind"]})
            return _finalize(gid, user_id, "doxxing", res, message=message)

    # 5. suicide (category 5)
    if "5" in enabled_categories:
        if sui := suicide_words.detect(message, lang=guild_lang):
            res = _flagged("ai-5", "5", "5", {"match": sui["match"], "lang": sui["lang"]})
            return _finalize(gid, user_id, "suicide_keyword", res, message=message)

    # 6. NSFW model (category 1)
    if "1" in enabled_categories:
        try:
            nsfw = await models.classify_nsfw(message)
        except Exception as e:
            logger.error(f"SafeText | NSFW model error: {e}")
            nsfw = None
        if nsfw:
            nsfw_score = nsfw["score"] if nsfw["label"] == "NSFW" else 0.0
            if nsfw["label"] == "NSFW" and nsfw["score"] >= NSFW_THRESHOLD:
                res = _flagged("ai-1", "1", "1", {"confidence": round(nsfw["score"], 4)})
                return _finalize(gid, user_id, "nsfw", res, confidence=nsfw["score"], message=message)

    # 7. toxic / hate model (categories 2, 3)
    wants_toxic = "2" in enabled_categories
    wants_hate  = "3" in enabled_categories
    if wants_toxic or wants_hate:
        try:
            toxic_scores = await models.classify_toxic(message)
        except Exception as e:
            logger.error(f"SafeText | toxic model error: {e}")
            toxic_scores = {}

        hate_score  = max((toxic_scores.get(l, 0.0) for l in HATE_LABELS), default=0.0)
        toxic_score = max((toxic_scores.get(l, 0.0) for l in TOXIC_LABELS), default=0.0)

        if wants_hate and hate_score >= HATE_THRESHOLD:
            top = max(HATE_LABELS, key=lambda l: toxic_scores.get(l, 0.0))
            res = _flagged("ai-3", "3", "3", {
                "label": top, "confidence": round(hate_score, 4), "scores": toxic_scores
            })
            return _finalize(gid, user_id, "hate", res, confidence=hate_score, message=message)

        if wants_toxic and toxic_score >= TOXIC_THRESHOLD:
            top = max(TOXIC_LABELS, key=lambda l: toxic_scores.get(l, 0.0))
            res = _flagged("ai-2", "2", "2", {
                "label": top, "confidence": round(toxic_score, 4), "scores": toxic_scores
            })
            return _finalize(gid, user_id, "toxic", res, confidence=toxic_score, message=message)

    res = _safe()
    res["json"] = {"nsfw": nsfw_score, "toxic_scores": toxic_scores}
    return _finalize(gid, user_id, "clean", res, message=message)


# ── logging shims ────────────────────────────────────────────────────────────
def _finalize(gid: int, user_id: int, stage: str, res: Dict[str, Any],
              confidence: float | None = None, message: str | None = None) -> Dict[str, Any]:
    flagged = bool(res.get("flagged"))
    verdict = "unsafe" if flagged else "safe"
    reason = res.get("reason", "?")
    conf_str = f" conf={round(confidence,4)}" if confidence is not None else ""
    logger.info(
        f"SafeText | model: classified ({verdict}), stage={stage} reason={reason} "
        f"user={user_id} guild={gid}{conf_str}"
    )
    if flagged:
        _admin_log("warning",
            f"SafeText [{stage}] flagged - user={user_id} guild={gid} reason={reason} conf={confidence}",
            source="Chatfilter")
    log_id = record(gid=gid, user_id=user_id, stage=stage, flagged=flagged,
                    result=res, confidence=confidence, message=message)
    res.setdefault("json", {})["log_id"] = log_id
    return res
