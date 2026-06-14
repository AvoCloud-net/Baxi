"""Global mild-word guard.

The multilingual toxic model false-positives on common mild interjections
("damn", "hell", "crap", "verdammt", …), flagging them as category 2
(insults / toxicity). A bare expletive is not an insult, and because the PRISM
silent scan runs this same pipeline on servers with the chatfilter disabled,
those false positives leak into network-wide trust scoring.

`is_only_mild(text)` returns True when, after removing the known mild words plus
all non-letter characters, nothing meaningful remains. That suppresses the
toxic/hate model for a message that is *only* a mild expletive, without opening a
bypass for real insults: "damn idiot" still has "idiot" left over, so it is False
and the model runs as usual.

This is intentionally a small, conservative, hard-coded set of clearly-mild
interjections. Per-guild `c_goodwords` remains the place to whitelist anything
else.
"""
import re

# Lower-cased, letters only. Keep this list to genuinely mild interjections —
# anything that could be a real slur/insult must NOT live here.
MILD_WORDS: frozenset[str] = frozenset({
    # English
    "damn", "damned", "damnit", "dammit", "goddamn", "goddamnit",
    "hell", "heck", "crap", "crappy", "darn", "darned", "bloody",
    "freaking", "frigging", "frick", "frickin", "freakin", "dang",
    # German
    "verdammt", "verdammtnochmal", "mist", "verflixt", "verflucht",
})

# Split on anything that is not a unicode letter (handles punctuation, digits,
# emoji, whitespace). Empty tokens are dropped.
_TOKEN_SPLIT = re.compile(r"[^a-zA-ZÀ-ÿ]+")


def is_only_mild(text: str) -> bool:
    """True if the message consists solely of mild words / punctuation."""
    if not text:
        return False
    tokens = [t for t in _TOKEN_SPLIT.split(text.lower()) if t]
    if not tokens:
        return False  # punctuation/emoji only — not our concern here
    return all(t in MILD_WORDS for t in tokens)
