"""Suicide / self-harm phrase detector. Multi-language keyword list."""
import json
import re
from pathlib import Path
from typing import Optional

from reds_simple_logger import Logger

logger = Logger()

_WORDS_FILE = Path("data/safetext/suicide_words.json")
_compiled: dict[str, list[re.Pattern]] | None = None

# Built-in defaults so detection works even without the (runtime, not deployed) JSON file.
# The file, when present, is merged on top to extend/override per language.
_DEFAULT_WORDS: dict[str, list[str]] = {
    "en": [
        "kill yourself", "kill your self", "kill urself", "kill ur self", "killyourself",
        "go kill yourself", "you should kill yourself", "you should just kill yourself",
        "kys", "kys now", "kys already", "just kys", "kysm", "kill yourself already",
        "neck yourself", "neck urself", "go neck yourself", "rope yourself",
        "go rope yourself", "get the rope", "catch the rope", "hang yourself",
        "hang urself", "go hang yourself", "off yourself", "off urself", "an hero",
        "commit suicide", "go commit suicide", "end your life", "end ur life",
        "end yourself", "go die", "go die already", "go die in a hole", "just go die",
        "you should die", "you deserve to die", "i hope you die", "i hope you kill yourself",
        "drink bleach", "go drink bleach", "drink bleach and die", "jump off a bridge",
        "go jump off a bridge", "jump off a cliff", "slit your wrists", "slit your throat",
        "cut yourself", "go cut yourself", "unalive yourself", "unalive urself",
        "go unalive yourself", "do everyone a favor and die", "do us all a favor and die",
        "the world would be better without you", "nobody would miss you",
        "no one would miss you", "i want to die", "i wanna die", "i want to kill myself",
        "i wanna kill myself", "i'm going to kill myself", "im going to kill myself",
        "i'm gonna kill myself", "im gonna kill myself", "kms", "i want to kms",
        "i want to end it all", "i want to end my life", "i want to end it",
        "i don't want to live", "i dont want to live", "i don't want to live anymore",
        "i dont want to live anymore", "i want to hang myself", "i want to slit my wrists",
        "unalive myself", "i'm suicidal", "im suicidal", "i am suicidal",
        "suicidal thoughts", "i want to disappear forever", "i wish i was dead",
        "i wish i were dead", "i'd be better off dead", "id be better off dead",
        "i'm better off dead", "im better off dead", "i can't go on anymore",
        "i cant go on anymore",
    ],
    "de": [
        "bring dich um", "bringt dich um", "bring dich doch um", "bring dich endlich um",
        "töte dich", "toete dich", "töte dich selbst", "toete dich selbst", "erhäng dich",
        "erhaeng dich", "erhäng dich doch", "häng dich auf", "haeng dich auf",
        "geh dich aufhängen", "geh dich aufhaengen", "geh sterben", "geh doch sterben",
        "stirb endlich", "verreck", "verrecke", "verreck doch", "spring von der brücke",
        "spring von der bruecke", "spring vor den zug", "leg dich vor einen zug",
        "geh vor den zug", "ritz dich", "ritz dich auf", "schneid dich", "schneide dich",
        "trink bleichmittel", "niemand würde dich vermissen", "niemand wuerde dich vermissen",
        "niemand vermisst dich", "die welt wäre besser ohne dich",
        "die welt waere besser ohne dich", "keiner würde dich vermissen",
        "ich will mich umbringen", "ich möchte mich umbringen", "ich moechte mich umbringen",
        "ich bring mich um", "ich bringe mich um", "ich will sterben", "ich möchte sterben",
        "ich moechte sterben", "ich will nicht mehr leben", "ich möchte nicht mehr leben",
        "ich moechte nicht mehr leben", "ich will tot sein", "ich wäre besser tot",
        "ich waere besser tot", "ich häng mich auf", "ich haeng mich auf", "ich ritz mich",
        "ich will mein leben beenden", "mach schluss mit deinem leben",
        "ich mach schluss mit meinem leben", "ich bin suizidal", "ich bin suizidgefährdet",
        "suizidgedanken", "selbstmordgedanken", "ich denke an selbstmord",
        "ich denke an suizid", "ich will einfach verschwinden", "ich halte das nicht mehr aus",
    ],
}


def _load() -> dict[str, list[re.Pattern]]:
    global _compiled
    if _compiled is not None:
        return _compiled

    # Start from built-in defaults, then merge the optional override file if present.
    raw: dict[str, list[str]] = {k: list(v) for k, v in _DEFAULT_WORDS.items()}
    try:
        with _WORDS_FILE.open("r", encoding="utf-8") as fh:
            file_raw: dict[str, list[str]] = json.load(fh)
        for lang, phrases in file_raw.items():
            base = raw.get(lang, [])
            raw[lang] = base + [p for p in phrases if p not in base]
    except FileNotFoundError:
        pass  # no override file → defaults only (expected on fresh deploys)
    except (OSError, json.JSONDecodeError) as e:
        logger.warn(f"SafeText | suicide_words override load failed (using defaults): {e}")

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
