"""SafeText pipeline orchestrator.

Stages in order (first hit wins):
  1. phishing (blocklist incl. parent domains, IDN spoof, typosquat) -> "phishing"
  2. guild goodwords are masked, text is normalised (anti-evasion)
  3. confirmed feedback for this exact (normalised) message (guild, then global)
  4. guild badwords                                              -> "custom"
  5. doxxing                                                     -> cat 4
  6. context: clauses that only *mention* abuse are set aside (victim reports,
     counter speech, questions about words - see context.py)
  7. self-harm: inciting others -> cat 5 (removed)
                about oneself  -> support DM, message stays      -> "5s"
  8. threats                                                     -> cat 2
  9. slurs / extremist phrases, hostility against a group        -> cat 3
 10. explicit sexual content                                     -> cat 1
 11. severe insults, rude commands ("halt die fresse")           -> cat 2
 12. toxicity model + context signals                            -> cat 3 / cat 2

Stage 12 never trusts the model score alone. The model rates any rough language
as toxic ("scheiße, verloren" ~ "du hurensohn"), so a message is only flagged when
the score is backed by *who it is aimed at* (second person, plural address,
people in the chat, reply, mention), an insult from the lexicon, or a protected
group. Insults that are negated ("du bist nicht dumm") or aimed at the speaker
("ich bin so ein idiot") do not count. Curse words are masked, together with
group names (the model rates "we should look up to these Muslims" as toxic), and
the text re-scored before a score-only decision, so "you're fucking awesome" passes.
Joke markers ("haha", "jk", "xD") excuse mild banter at low/medium sensitivity,
praise markers ("genial", "gg", "wie hast du das geschafft", 🔥) at every level
("bist du dumm, das ist ja genial!") - never severe insults, slurs, threats or hate.

Sensitivity (per guild: low / medium / high) picks the thresholds; the author's
risk standing moves it one level up (risky) or down (trusted).

Returns the chatfilter result dict: {code, flagged, distance, reason, json[, support]}.
"""
from __future__ import annotations

import re
from typing import Any, Dict

from reds_simple_logger import Logger

from assets.message.safetext import (
    context, custom, doxxing, feedback, lexicon, mildwords, models, phishing,
)
from assets.message.safetext.logstore import record
from assets.message.safetext.normalize import Normalized, normalize, search
from assets.share import admin_log as _admin_log

logger = Logger()

LEVELS = ("low", "medium", "high")

# Model thresholds per sensitivity (toxic probability, see models.py).
# targeted:  score needed when the message addresses someone
# profanity: score needed for a curse word with nobody addressed (None = allowed).
#            Only high sensitivity filters cursing - and only real curse words, never
#            "any high score" (the model scores "kill den healer zuerst" as toxic).
# group:     score needed when a protected group is referenced -> hate
THRESHOLDS = {
    "low":    {"targeted": 0.99, "profanity": None,  "group": 0.99},
    "medium": {"targeted": 0.95, "profanity": None,  "group": 0.97},
    "high":   {"targeted": 0.90, "profanity": 0.90,  "group": 0.90},
}
# Score the counterfactual ("... people ...") must keep for group hate.
_COUNTERFACTUAL = {"low": 0.9, "medium": 0.7, "high": 0.5}
_LETTER = re.compile(r"[^\W\d_]")


# ── result helpers ───────────────────────────────────────────────────────────
def _safe(reason: str = "no_issues_detected", **extra) -> Dict[str, Any]:
    return {"code": "safe", "flagged": False, "distance": None, "reason": reason, "json": extra}


def _flagged(cat: str, **extra) -> Dict[str, Any]:
    return {"code": f"ai-{cat}", "flagged": True, "distance": None, "reason": cat,
            "json": {"status": "unsafe", "category": cat, **extra}}


def _level(chatfilter_data: dict, strictness: float) -> str:
    base = str(chatfilter_data.get("sensitivity", "medium")).lower()
    idx = LEVELS.index(base) if base in LEVELS else 1
    if strictness > 1.2:
        idx += 1
    elif strictness < 0.9:
        idx -= 1
    return LEVELS[max(0, min(len(LEVELS) - 1, idx))]


# ── rule stages shared by check() and is_insult() ────────────────────────────
def _rule_stage(norm: Normalized, level: str, targeted: bool, joke: bool,
                enabled: set[str]) -> Dict[str, Any] | None:
    pats = lexicon.patterns()

    if "2" in enabled and (hit := search(pats.threats, norm)):
        return _flagged("2", label="threat", match=hit)
    if enabled & {"2", "3"} and (hit := lexicon.find_violent_intent(norm)):
        cat = "3" if "3" in enabled and search(pats.groups, norm) else "2"
        if cat in enabled:
            return _flagged(cat, label="violent_intent", match=hit)

    if "3" in enabled:
        if hit := search(pats.hate, norm):
            return _flagged("3", label="slur", match=hit)
        if hit := lexicon.find_group_hate(norm):
            return _flagged("3", label="group_hostility", match=hit)

    if "1" in enabled and level != "low" and (hit := search(pats.sexual, norm)):
        return _flagged("1", label="sexual", match=hit)

    if "2" in enabled:
        # Severe insults count without a target, except at low sensitivity - but not
        # when the speaker calls themselves one ("ich war früher echt ein wichser").
        hit = lexicon.search_unnegated(pats.insults_severe, [pats.insults_severe_self], norm)
        if hit and (level != "low" or targeted):
            return _flagged("2", label="severe_insult", match=hit)
        # Rude commands address the reader by themselves; a joke excuses them at low.
        # "told to fuck off" / "got to fuck off" is an infinitive, not a command.
        hit = lexicon.search_unnegated(pats.insults_directed, [pats.insults_directed_inf], norm)
        if hit and not (level == "low" and joke):
            return _flagged("2", label="rude_command", match=hit)
        if (hit := search(pats.curse_at_people, norm)) and not (level == "low" and joke):
            return _flagged("2", label="curse_at_people", match=hit)
    return None


# ── lexicon insults (work with or without the model) ─────────────────────────
def _mild_insult(norm: Normalized, level: str, targeted: bool, lenient: bool,
                 tox: float | None) -> tuple[str | None, bool]:
    """(insult word if it counts, whether an insult was excused as negated/self-aimed/idiom)."""
    pats = lexicon.patterns()
    maskers = [pats.insults_mild_negated, pats.insults_mild_self, pats.idioms]
    mild = lexicon.search_unnegated(pats.insults_mild, maskers, norm)
    excused = not mild and any(
        m is not None and any(m.search(v) for v in norm.variants) for m in maskers
    )
    if not mild or lenient:
        return None, excused
    # Aimed at someone; at low sensitivity the model must agree (without it: skip).
    if targeted and (level != "low" or (tox is not None and tox >= 0.9)):
        return mild, excused
    if level == "high":
        return mild, excused
    return None, excused


def _insult_result(match: str, tox: float | None, signals: dict) -> Dict[str, Any]:
    extra = {"confidence": round(tox, 4)} if tox is not None else {}
    return _flagged("2", label="insult", match=match, **extra, **signals)


# ── model stage ──────────────────────────────────────────────────────────────
async def _model_stage(norm: Normalized, level: str, targeted: bool, joke: bool,
                       enabled: set[str], praise: bool = False,
                       ) -> tuple[Dict[str, Any] | None, float | None]:
    pats = lexicon.patterns()
    text = norm.ml_text
    if len(_LETTER.findall(text)) < 2 or mildwords.is_only_mild(text):
        return None, None

    lenient = praise or (joke and level != "high")
    tox = await models.toxicity(text)
    if tox is None:          # model unavailable -> lexicon insults only
        if "2" in enabled and (mild := _mild_insult(norm, level, targeted, lenient, None)[0]):
            return _insult_result(mild, None, {"targeted": targeted, "level": level}), None
        return None, None
    thr = THRESHOLDS[level]
    # An insult that is negated or self-aimed explains a high score by itself, so the
    # score-only path must not flag it either ("du bist kein idiot", "i'm such an idiot").
    mild, excused_insult = _mild_insult(norm, level, targeted, lenient, tox)
    group = search(pats.groups, norm)

    neutral_word = "Menschen" if pats.groups_natural_de.search(text) else "people"

    async def neutralized() -> float:
        """Score with curse words removed and group names swapped for a neutral noun -
        what is left is the attitude, not the vocabulary."""
        masked = pats.groups_natural.sub(
            neutral_word, pats.condemn_terms.sub(" ", pats.profanity.sub(" ", text)))
        if masked == text:
            return tox
        if len(_LETTER.findall(masked)) < 2:
            return 0.0
        return await models.toxicity(masked) or 0.0

    signals = {"toxicity": round(tox, 4), "targeted": targeted, "level": level}

    # Hate: the model reacts to group names themselves ("we should look up to these
    # Muslims" scores 0.999), so a high score is only trusted if it survives a
    # counterfactual - the same sentence about "people" in general is still hostile
    # ("Alle Schwarzen sind abstoßend" -> "Alle Menschen sind abstoßend").
    if "3" in enabled and group and tox >= thr["group"] and not lexicon.negated_near_group(norm):
        cf = await neutralized()
        if cf >= _COUNTERFACTUAL[level]:
            return _flagged("3", label="group_hate", group=group, confidence=round(tox, 4),
                            counterfactual=round(cf, 4), **signals), tox

    if "2" not in enabled:
        return None, tox

    if mild:
        return _insult_result(mild, tox, signals), tox

    # Score-only decisions: re-score without curse words first.
    if targeted and not lenient and not excused_insult and tox >= thr["targeted"]:
        eff = await neutralized()
        if eff >= thr["targeted"]:
            return _flagged("2", label="toxic_targeted", confidence=round(eff, 4),
                            **signals), tox
    if thr["profanity"] is not None and tox >= thr["profanity"] and pats.profanity.search(text):
        return _flagged("2", label="profanity", confidence=round(tox, 4), **signals), tox

    return None, tox


# ── main entry ───────────────────────────────────────────────────────────────
async def check(
    message: str,
    gid: int,
    cid: int,
    user_id: int,
    chatfilter_data: dict,
    guild_lang: str,
    enabled_categories: set[str],
    strictness: float = 1.0,
    use_ml: bool = True,
    targeted_hint: bool = False,
) -> Dict[str, Any]:
    """Run the full SafeText pipeline and return a chatfilter result dict.

    *targeted_hint*: the message is a reply or mentions a member (known only to
    the caller). *use_ml*: False for the rules-only "SafeText" system."""
    enabled = set(enabled_categories)
    level = _level(chatfilter_data, strictness)
    pats = lexicon.patterns()

    def done(stage: str, res: Dict[str, Any], confidence: float | None = None):
        return _finalize(gid, user_id, stage, res, confidence=confidence, message=message)

    # 1. phishing
    if chatfilter_data.get("phishing_filter", False):
        if hit := phishing.check(message):
            return done("phishing", {"code": "phishing", "flagged": True, "distance": None,
                                     "reason": "phishing", "json": hit})

    # 2. goodwords masked, then normalise
    text = custom.mask_goodwords(message, chatfilter_data.get("c_goodwords"))
    full = normalize(text)

    # 3. confirmed verdict for this exact message
    if override := feedback.override_for(full.key, gid):
        if override == "SAFE":
            return done("override", _safe("override"))
        if override in enabled:
            return done("override", _flagged(override, label="override"))

    # 4. guild badwords (explicit guild rule - applies even inside quotes)
    if badword := custom.match_badword(full, chatfilter_data.get("c_badwords")):
        return done("custom", {"code": "safetext-filter", "flagged": True, "distance": "0",
                               "reason": "custom", "json": {"word": badword, "code": "custom"}})

    # 5. doxxing
    if "4" in enabled and (dox := doxxing.detect(text)):
        return done("doxxing", _flagged("4", kind=dox["kind"]))

    # 6. context: judge only what is actually said, not what is quoted or reported
    ctx = context.analyze(text)
    norm = normalize(ctx.eval_text) if ctx.eval_text != text else full
    extra = {"mentions_only": list(ctx.dropped)} if ctx.dropped else {}

    # 7. self-harm
    if "5" in enabled:
        if hit := search(pats.self_harm_incite, norm):
            return done("self_harm_incite", _flagged("5", label="incite", match=hit))
        if hit := search(pats.self_harm_self, full):
            res = _safe("5s", match=hit)
            res["support"] = True
            return done("self_harm_support", res)

    targeted = targeted_hint or lexicon.addresses_someone(norm)

    # 8.-11. rules
    if res := _rule_stage(norm, level, targeted, ctx.joke, enabled):
        res["json"].update(extra)
        return done(res["json"].get("label", "rules"), res)

    # 12. model (rules-only "SafeText" system: lexicon insults without the model)
    tox: float | None = None
    if not use_ml and "2" in enabled:
        lenient = ctx.praise or (ctx.joke and level != "high")
        if mild := _mild_insult(norm, level, targeted, lenient, None)[0]:
            res = _insult_result(mild, None, {"targeted": targeted, "level": level})
            res["json"].update(extra)
            return done("insult", res)
    if use_ml and enabled & {"2", "3"} and norm.ml_text:
        try:
            res, tox = await _model_stage(norm, level, targeted, ctx.joke, enabled, ctx.praise)
        except Exception as e:
            logger.error(f"SafeText | model stage error: {type(e).__name__}: {e}")
            res = None
        if res is not None:
            res["json"].update(extra)
            return done("model", res, confidence=tox)

    group = bool(search(pats.groups, norm))
    return done("clean", _safe(toxicity=tox, targeted=targeted, group=group, level=level,
                               joke=ctx.joke, **extra), confidence=tox)


async def is_insult(text: str, level: str = "medium") -> bool:
    """Is *text* an insult / threat / hate aimed at the addressee? For messages that
    are directed at someone by construction (e.g. talking to the assistant). No
    logging, no guild config."""
    pats = lexicon.patterns()
    ctx = context.analyze(text)
    norm = normalize(ctx.eval_text)
    enabled = {"2", "3"}
    if search(pats.self_harm_incite, norm) or _rule_stage(norm, level, True, ctx.joke, enabled):
        return True
    res, _ = await _model_stage(norm, level, True, ctx.joke, enabled, ctx.praise)
    return res is not None


# ── logging ──────────────────────────────────────────────────────────────────
def _finalize(gid: int, user_id: int, stage: str, res: Dict[str, Any],
              confidence: float | None = None, message: str | None = None) -> Dict[str, Any]:
    flagged = bool(res.get("flagged"))
    reason = res.get("reason", "?")
    if flagged or res.get("support"):
        conf_str = f" conf={round(confidence, 4)}" if confidence is not None else ""
        logger.info(f"SafeText | {'unsafe' if flagged else 'support'} stage={stage} "
                    f"reason={reason} user={user_id} guild={gid}{conf_str}")
    if flagged:
        _admin_log("warning",
                   f"SafeText [{stage}] flagged - user={user_id} guild={gid} reason={reason} "
                   f"conf={confidence}", source="Chatfilter")
    log_id = record(gid=gid, user_id=user_id, stage=stage, flagged=flagged,
                    result=res, confidence=confidence, message=message)
    res.setdefault("json", {})["log_id"] = log_id
    return res
