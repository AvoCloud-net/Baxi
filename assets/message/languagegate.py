"""Language gate: a server (or channel set) speaks only the chosen language(s); messages in
another language are removed, like the chat filter does.

Detection is local and dependency-free: non-Latin scripts by character class, Latin-script
languages by function words (plus a few typed letters). It errs on the side of leaving a
message alone: short texts, mixed texts and loanword-heavy chat are never touched.
"""
from __future__ import annotations

import re
import time

import discord
from discord.ext import commands

import assets.data as datasys
from reds_simple_logger import Logger

logger = Logger()

DEFAULTS: dict = {
    "enabled": False,
    "languages": ["de"],   # languages that stay allowed
    "exempt_staff": True,
    "channels": [],        # channel ids where the gate does not apply
}

# Languages a server can allow: the ones the chat filter covers too (German, English).
# Everything else is detected only to be removed.
LANGUAGES: dict[str, str] = {"de": "Deutsch", "en": "English"}

MIN_LETTERS = 12      # shorter messages are never judged
MIN_WORDS = 4         # Latin script: fewer words are never judged
MIN_HITS = 3          # function words the foreign language must match
MIN_MARGIN = 2        # ... and by how much it must beat every allowed language
MIN_SHARE = 0.3       # ... and what share of all words they must make up
NOTICE_COOLDOWN = 20  # seconds between two notices to the same member

_W = lambda s: frozenset(s.split())  # noqa: E731

_STOPWORDS: dict[str, frozenset[str]] = {
    "de": _W("der die das und ist nicht ich du er sie wir ihr ein eine einen einem einer mit für auf von zu den dem des "
             "auch aber oder wenn dass wie was wer wo warum noch schon nur mal doch ja nein hab habe hat haben bin bist "
             "sind war waren wird werden kann können muss will wollen gut bitte danke hallo heute morgen jetzt hier da "
             "dann also mein dein sein ihre mich dich mir dir sich nach bei aus über um sehr viel mehr kein keine "
             "eigentlich vielleicht immer nie gar geht gibt machen mache moin servus genau halt eben mal weil denn "
             "dieser diese dieses ganz wirklich echt schön lange gestern"),
    "en": _W("the and is are was were be been you he she it we they of to for on with that this have has had not but or "
             "if what who where why when how just very really can could would should do does did my your his her our "
             "their me him them there here now then like get got going know think want need good thanks please hello "
             "yeah yes dont cant wont isnt thats youre ive about from because been some any more much too out up "
             "your into than only other which these those"),
    "fr": _W("le la les un une des et est pas je tu il elle nous vous ils elles ce cette ces que qui quoi pour dans sur "
             "avec sans mais ou donc car ne plus très bien oui non merci bonjour salut suis sont être avoir ai as "
             "avons ont fait faire mon ma mes ton ta tes son sa ses notre votre leur comme tout tous aussi encore déjà "
             "jamais toujours peu beaucoup cest jai nest quil dun dune pourquoi quand comment"),
    "es": _W("el la los las un una unos y son que de en por para con sin pero como muy bien si sí hola gracias yo tú él "
             "ella nosotros ellos soy eres somos tengo tiene tienen hay está están estoy fue ser estar hacer esto eso "
             "esta ese este mi su mis más ya también todo todos nada algo cuando donde porque quiero puedo vale "
             "pues entonces ahora aquí allí"),
    "it": _W("il lo la le gli un una uno è sono non che di del della con per su ma molto bene sì ciao grazie io lui lei "
             "noi voi loro mio tuo suo questo quello questa anche tutto tutti niente qualcosa quando dove perché "
             "voglio posso ho hai ha abbiamo hanno fare essere cosa sei era allora adesso qui"),
    "pt": _W("os as um uma são não que de do da dos das em no na nos nas por para com sem mas como muito bem sim olá "
             "obrigado obrigada eu ele ela nós vocês eles sou estou está estão tenho tem têm foi ser estar fazer isso "
             "isto esta esse este meu minha seu sua mais já também tudo nada algo quando onde porque quero posso vou "
             "então agora aqui"),
    "nl": _W("de het een en is niet ik jij je hij zij ze wij we jullie dat dit dus maar of als dan ook nog wel geen wat "
             "wie waar waarom hoe met voor van op aan te naar uit bij om heel veel meer goed dank bedankt hallo "
             "vandaag nu hier daar zijn ben bent waren heb hebt heeft hebben kan kunnen moet wil willen mijn jouw "
             "haar ons onze gaan gaat doen doe gewoon eigenlijk misschien altijd nooit"),
    "tr": _W("bir ve bu da de için ile ama çok evet hayır merhaba teşekkürler ben sen biz siz onlar değil var yok ne "
             "neden nasıl nerede kim gibi daha en her şey şu ki mi mı mu mü olarak ise çünkü hadi tamam lütfen "
             "günaydın selam abi kardeş yani sadece bence benim senin bunu şunu"),
    "pl": _W("nie na się to że jest do co jak ale tak czy po za od przez dla tylko już jeszcze bardzo dobrze dzień "
             "cześć dzięki proszę ja ty on ona my wy oni jestem jesteś są był była było mam masz ma mamy chcę mogę "
             "dziś teraz tutaj tam bo więc też"),
}

# Letters that mark a language (one point per word that contains one).
_MARKERS: dict[str, str] = {
    "de": "äöüß", "tr": "ışğ", "pl": "ąęłśżźćń", "es": "ñ", "pt": "ãõ", "fr": "èêàâœ",
}

_NOISE = re.compile(
    r"```.*?```|`[^`]*`|https?://\S+|www\.\S+|<a?:\w+:\d+>|<[@#!&]\d+>|[@#]\w+|:\w+:",
    re.S,
)
_WORD = re.compile(r"[^\W\d_]+")


def _script_of(ch: str) -> str | None:
    o = ord(ch)
    if o < 0x250 or 0x1E00 <= o <= 0x1EFF:
        return "latin"
    if 0x400 <= o <= 0x52F:
        return "ru"
    if 0x600 <= o <= 0x6FF or 0x750 <= o <= 0x77F:
        return "ar"
    if 0x3040 <= o <= 0x30FF:
        return "ja"
    if 0x4E00 <= o <= 0x9FFF:
        return "han"
    if 0xAC00 <= o <= 0xD7AF or 0x1100 <= o <= 0x11FF:
        return "ko"
    return "other"


def detect(text: str, allowed: set[str]) -> str | None:
    """The language code of *text* if it is confidently NOT one of *allowed*, else None."""
    text = _NOISE.sub(" ", text).lower().replace("'", "").replace("’", "")
    letters = [c for c in text if c.isalpha()]
    if len(letters) < MIN_LETTERS:
        return None

    counts: dict[str, int] = {}
    for c in letters:
        s = _script_of(c)
        if s:
            counts[s] = counts.get(s, 0) + 1
    total = len(letters)

    for script in ("ru", "ar", "ko"):
        if counts.get(script, 0) / total > 0.6:
            return None if script in allowed else script
    cjk = counts.get("han", 0) + counts.get("ja", 0)
    if cjk / total > 0.6:
        code = "ja" if counts.get("ja", 0) else "zh"
        return None if code in allowed or (code == "zh" and "ja" in allowed) else code
    if counts.get("latin", 0) / total < 0.6:
        return None

    words = _WORD.findall(text)
    if len(words) < MIN_WORDS:
        return None
    scores: dict[str, int] = {}
    for code, stop in _STOPWORDS.items():
        marks = _MARKERS.get(code, "")
        scores[code] = sum(
            (w in stop) + (1 if marks and any(m in w for m in marks) else 0)
            for w in words if len(w) > 1 or w in stop
        )
    best = max(scores, key=lambda k: scores[k])
    if best in allowed:
        return None
    best_allowed = max((scores[c] for c in allowed if c in scores), default=0)
    if (
        scores[best] >= MIN_HITS
        and scores[best] >= best_allowed + MIN_MARGIN
        and scores[best] / len(words) >= MIN_SHARE
    ):
        return best
    return None


def settings(guild_id: int) -> dict:
    stored = datasys.load_data(guild_id, "language_gate")
    cfg = {**DEFAULTS, **(stored if isinstance(stored, dict) else {})}
    cfg["languages"] = [c for c in cfg.get("languages", []) if c in LANGUAGES] or list(DEFAULTS["languages"])
    return cfg


_last_notice: dict[tuple[int, int], float] = {}


async def check(
    message: discord.Message,
    bot: commands.AutoShardedBot,
    *,
    is_globalchat: bool = False,
) -> bool:
    """Remove *message* if it is in a language the server does not allow.
    Returns True when it was removed."""
    guild = message.guild
    if guild is None or message.author.bot or is_globalchat:
        return False
    cfg = settings(guild.id)
    if not cfg["enabled"]:
        return False
    if not datasys.load_data(guild.id, "terms"):
        return False
    channel = message.channel
    skip = {str(c) for c in cfg["channels"]}
    if str(channel.id) in skip or str(getattr(channel, "parent_id", None)) in skip:
        return False
    if str(channel.id) in dict(datasys.load_data(guild.id, "open_tickets")):
        return False
    if (
        cfg["exempt_staff"] and isinstance(message.author, discord.Member)
        and message.author.guild_permissions.manage_messages
    ):
        return False
    if not message.content.strip():
        return False

    allowed = set(cfg["languages"])
    if detect(message.clean_content, allowed) is None:
        return False

    try:
        await message.delete()
    except discord.NotFound:
        return True
    except (discord.Forbidden, discord.HTTPException) as err:
        logger.error(f"[LanguageGate] cannot delete in {guild.id}: {err}")
        return False

    key = (guild.id, message.author.id)
    now = time.monotonic()
    if now - _last_notice.get(key, 0.0) >= NOTICE_COOLDOWN:
        _last_notice[key] = now
        lang = datasys.load_lang_file(guild.id)
        names = ", ".join(LANGUAGES[c] for c in cfg["languages"])
        try:
            await channel.send(
                str(lang["systems"]["language_gate"]["notice"]).format(
                    user=message.author.mention, languages=names),
                delete_after=10,
                allowed_mentions=discord.AllowedMentions(users=[message.author]),
            )
        except (discord.Forbidden, discord.HTTPException):
            pass
    return True
