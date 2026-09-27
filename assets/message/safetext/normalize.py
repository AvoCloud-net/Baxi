"""Text normalisation against filter evasion.

Everything that matches words or phrases (custom badwords, lexicons, feedback
overrides) runs on the *folded* variants produced here, and every pattern is
folded the same way, so both sides always agree. Handles:

  * zero-width / bidi / soft-hyphen characters        "k\u200bys"   -> "kys"
  * NFKC compatibility forms (fullwidth, math fonts)   "ｋｙｓ", "𝓀𝓎𝓈" -> "kys"
  * Cyrillic/Greek homoglyphs in Latin text             "kуs" (Cyrillic у) -> "kys"
  * leetspeak inside words                              "k1ll y0urs3lf" -> "kill yourself"
  * letter-by-letter spacing                            "k y s", "k.y.s" -> "kys"
  * stretched letters                                   "kyyyyys" -> "kys"
  * umlauts / accents                                   "töte" == "toete", "é" -> "e"

The ML model gets `ml_text` instead: only invisible characters, homoglyphs and
letter spacing are repaired there, the rest of the text stays natural.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

# Invisible / formatting characters used to split words without a visible gap.
_INVISIBLE = re.compile(
    "[\u00ad\u034f\u061c\u115f\u1160\u17b4\u17b5\u180e\u200b-\u200f\u202a-\u202e"
    "\u2060-\u2064\u2066-\u206f\u3164\ufe00-\ufe0f\ufeff\uffa0]"
)

_HOMOGLYPHS = str.maketrans({
    # Cyrillic
    "а": "a", "в": "b", "е": "e", "ё": "e", "к": "k", "м": "m", "н": "h", "о": "o",
    "р": "p", "с": "c", "т": "t", "у": "y", "х": "x", "ѕ": "s", "і": "i", "ї": "i",
    "ј": "j", "ԁ": "d", "ӏ": "l", "ԛ": "q", "ԝ": "w", "ɡ": "g",
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O", "Р": "P",
    "С": "C", "Т": "T", "У": "Y", "Х": "X", "Ѕ": "S", "І": "I", "Ј": "J",
    # Greek
    "α": "a", "β": "b", "ε": "e", "ι": "i", "κ": "k", "ν": "v", "ο": "o", "ρ": "p",
    "τ": "t", "υ": "u", "χ": "x", "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H",
    "Ι": "I", "Κ": "K", "Μ": "M", "Ν": "N", "Ο": "O", "Ρ": "P", "Τ": "T", "Υ": "Y",
    "Χ": "X",
})
_LOOKALIKE_CHARS = frozenset(chr(c) for c in _HOMOGLYPHS)

_LEET = {"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "8": "b",
         "@": "a", "$": "s", "!": "i", "|": "i", "€": "e"}
_LEET_TOKEN = re.compile(r"[\w@$!|€]+")

_UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
                          "Ä": "ae", "Ö": "oe", "Ü": "ue", "ẞ": "ss"})

# Three or more single letters separated by spacing punctuation: "k y s", "k.y.s", "k-y-s".
_SPACED_LETTERS = re.compile(
    r"(?<![^\W\d_])(?:[^\W\d_][ \t.\-_*,/\\|~+:]+){2,}[^\W\d_](?![^\W\d_])"
)
_SPACING = re.compile(r"[ \t.\-_*,/\\|~+:]+")

# Filler particles dropped in one extra variant, so "häng dich doch auf" and
# "ich will einfach sterben" hit the phrases "häng dich auf" / "ich will sterben".
_FILLERS = re.compile(
    r"(?<![a-z])(?:doch|einfach|endlich|mal|bitte|jetzt|halt|eh|nur|echt|schon|"
    r"just|please|pls|plz|already|now|really|fucking|verdammt)(?![a-z]) ?"
)

_URL = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_DISCORD_TOKENS = re.compile(r"<a?:\w+:\d+>|<[@#][!&]?\d+>|<t:\d+(?::\w)?>")
_WS = re.compile(r"\s+")


def _is_latin_letter(ch: str) -> bool:
    return ch.isascii() and ch.isalpha()


def _repair_homoglyphs(text: str) -> str:
    """Map lookalike letters to Latin - but only where they are used to disguise
    Latin text, so genuinely Cyrillic/Greek messages stay untouched."""
    if not any(ch in _LOOKALIKE_CHARS for ch in text):
        return text
    letters = [ch for ch in text if ch.isalpha()]
    latin = sum(1 for ch in letters if _is_latin_letter(ch))
    if letters and latin / len(letters) > 0.5:
        return text.translate(_HOMOGLYPHS)
    # Mostly non-Latin text: only repair mixed-script words ("kуs" inside Russian text).
    def fix(m: re.Match) -> str:
        w = m.group(0)
        if any(_is_latin_letter(c) for c in w) and any(c in _LOOKALIKE_CHARS for c in w):
            return w.translate(_HOMOGLYPHS)
        return w
    return re.sub(r"\w+", fix, text)


_WORD_GAP = re.compile(r"[ \t]{2,}")


_ONLY_SPACED = re.compile(r"(?:[^\W\d_][ .\-_*]+)+[^\W\d_]")


def _despace(text: str) -> str:
    # A double space separates words in "d u  o p f e r" -> "du opfer"; there even a
    # two-letter segment ("d u") is one spaced-out word.
    parts = _WORD_GAP.split(text)
    if len(parts) > 1:
        parts = [_SPACING.sub("", p) if _ONLY_SPACED.fullmatch(p.strip()) else p for p in parts]
    return " ".join(_SPACED_LETTERS.sub(lambda m: _SPACING.sub("", m.group(0)), p) for p in parts)


def _deleet(text: str) -> str:
    def fix(m: re.Match) -> str:
        tok = m.group(0)
        if not any(c.isalpha() for c in tok) or not any(c in _LEET for c in tok):
            return tok
        body = tok.rstrip("!|")          # "die!!" stays "die", not "dieii"
        tail = tok[len(body):]
        return "".join(_LEET.get(c, c) for c in body) + tail
    return _LEET_TOKEN.sub(fix, text)


def _strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def clean(text: str) -> str:
    """Invisible chars removed, NFKC applied, homoglyphs repaired. Case preserved."""
    text = _INVISIBLE.sub("", text or "")
    text = unicodedata.normalize("NFKC", text)
    return _repair_homoglyphs(text)


def strip_noise(text: str) -> str:
    """Remove URLs and Discord mention/emoji/timestamp tokens. Spacing is kept
    (double spaces carry word boundaries for _despace)."""
    return _DISCORD_TOKENS.sub(" ", _URL.sub(" ", text)).strip()


def fold(text: str, *, max_repeat: int = 2) -> str:
    """Canonical matching form: lower-case ASCII-ish letters, leet and accents
    folded, spaced-out letters joined, runs of the same char shortened."""
    text = clean(text).translate(_UMLAUTS).lower()
    text = _strip_accents(text)
    text = _deleet(text)
    text = _despace(text)
    text = re.sub(r"(.)\1{%d,}" % max_repeat, r"\1" * max_repeat, text)
    return _WS.sub(" ", text).strip()


@dataclass(frozen=True)
class Normalized:
    raw: str
    ml_text: str               # natural text for the classifier
    variants: tuple[str, ...]  # folded forms to run phrase patterns against
    key: str                   # stable identity for caches / feedback overrides


@lru_cache(maxsize=4096)
def normalize(text: str) -> Normalized:
    cleaned = strip_noise(clean(text))
    v2 = fold(cleaned, max_repeat=2)   # "kill" survives, "kyyys" -> "kyys"
    v1 = fold(cleaned, max_repeat=1)   # "kyyys" -> "kys"
    no_fillers = _WS.sub(" ", _FILLERS.sub("", v2)).strip()
    variants = tuple(dict.fromkeys((v2, v1, no_fillers)))
    ml_text = _WS.sub(" ", _despace(cleaned)).strip()
    return Normalized(raw=text, ml_text=ml_text, variants=variants, key=v1)


# ── phrase matching ──────────────────────────────────────────────────────────
def _phrase_regex(phrase: str) -> str | None:
    """Folded phrase -> regex. A trailing `*` on a word allows any letter suffix."""
    parts: list[str] = []
    for raw_word in phrase.split():
        wildcard = raw_word.endswith("*")
        subwords = [w for w in re.split(r"[^\w]+", fold(raw_word.rstrip("*"))) if w]
        if not subwords:
            continue
        parts.extend(re.escape(w) for w in subwords)
        if wildcard:
            parts[-1] += "[a-z]*"
    if not parts:
        return None
    # Any (or no) punctuation/space between the words: "kill-yourself", "killyourself".
    return r"[\W_]*".join(parts)


def compile_phrases(phrases) -> re.Pattern | None:
    """One alternation regex over folded phrases, anchored at word boundaries."""
    parts = {p for p in (_phrase_regex(str(x)) for x in phrases) if p}
    if not parts:
        return None
    body = "|".join(sorted(parts, key=len, reverse=True))
    return re.compile(rf"(?<![a-z0-9])(?:{body})(?![a-z0-9])")


def search(pattern: re.Pattern | None, norm: Normalized) -> str | None:
    """Return the first matched text across all folded variants, else None."""
    if pattern is None:
        return None
    for v in norm.variants:
        if m := pattern.search(v):
            return m.group(0)
    return None
