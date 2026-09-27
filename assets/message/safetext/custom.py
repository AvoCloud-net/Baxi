"""Per-guild custom badwords / goodwords.

`c_badwords`  -> message is flagged on match. Matched on the normalised text,
                 so "b a d", "b4d" and zero-width tricks no longer slip through.
`c_goodwords` -> words the guild considers harmless. They are *masked* before the
                 lexicon and model stages run - they no longer whitelist the whole
                 message (previously "<goodword> kys" passed unchecked).

Values may be a list of strings (preferred) or a comma-separated string.
"""
import re
from functools import lru_cache
from typing import Optional

from assets.message.safetext.normalize import Normalized, compile_phrases, search


def _as_tuple(value) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        value = value.split(",")
    if isinstance(value, (list, tuple)):
        return tuple(sorted({str(v).strip() for v in value if str(v).strip()}))
    return ()


@lru_cache(maxsize=512)
def _compiled(words: tuple[str, ...]) -> Optional[re.Pattern]:
    return compile_phrases(words)


@lru_cache(maxsize=512)
def _raw_compiled(words: tuple[str, ...]) -> Optional[re.Pattern]:
    if not words:
        return None
    body = "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))
    return re.compile(rf"\b(?:{body})\b", re.IGNORECASE)


def match_badword(norm: Normalized, c_badwords) -> Optional[str]:
    return search(_compiled(_as_tuple(c_badwords)), norm)


def mask_goodwords(text: str, c_goodwords) -> str:
    """Remove guild-whitelisted words from *text* (case-insensitive, whole words)."""
    pattern = _raw_compiled(_as_tuple(c_goodwords))
    return pattern.sub(" ", text) if pattern else text
