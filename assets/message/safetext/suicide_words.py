"""Suicide / self-harm phrase detector. Multi-language keyword list."""
import json
import re
from pathlib import Path
from typing import Optional

from reds_simple_logger import Logger

logger = Logger()

_WORDS_FILE = Path("data/safetext/suicide_words.json")
_compiled: dict[str, list[re.Pattern]] | None = None


def _load() -> dict[str, list[re.Pattern]]:
    global _compiled
    if _compiled is not None:
        return _compiled
    try:
        with _WORDS_FILE.open("r", encoding="utf-8") as fh:
            raw: dict[str, list[str]] = json.load(fh)
    except (OSError, json.JSONDecodeError) as e:
        logger.warn(f"SafeText | suicide_words load failed: {e}")
        raw = {}

    out: dict[str, list[re.Pattern]] = {}
    for lang, phrases in raw.items():
        out[lang] = [
            re.compile(rf"\b{re.escape(p)}\b", re.IGNORECASE) for p in phrases
        ]
    _compiled = out
    return out


def detect(text: str, lang: str = "en") -> Optional[dict]:
    """Return {lang, match} if any configured phrase hits, else None.
    Checks both requested lang and English as fallback."""
    compiled = _load()
    for probe_lang in {lang, "en"}:
        for pat in compiled.get(probe_lang, []):
            if m := pat.search(text):
                return {"lang": probe_lang, "match": m.group(0)}
    return None


def reload_words() -> None:
    global _compiled
    _compiled = None
