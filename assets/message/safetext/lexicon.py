"""Curated DE/EN phrase lists for the rule stages of the SafeText pipeline.

All lists are matched through `normalize.compile_phrases`, so leetspeak, spacing,
homoglyphs and umlaut spellings are covered automatically - write each entry
once, in plain lower case. A trailing `*` on a word allows any suffix
("hurens*hn" is not needed, "wichser*" covers "wichsers").

Why lexicons next to the model: the toxicity model scores *language* (it rates
"scheiße, verloren" as toxic as "du hurensohn") and cannot tell an insult from a
curse, nor produce categories. The lexicons supply what it lacks: who is
addressed, which insults are severe, threats, slurs, sexual content and the
difference between "kys" (harassment) and "i want to die" (a cry for help).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from reds_simple_logger import Logger

from assets.message.safetext.normalize import compile_phrases, search

logger = Logger()

# ── self-harm ────────────────────────────────────────────────────────────────
# Telling someone else to hurt themselves -> harassment, message is removed.
SELF_HARM_INCITE = [
    # en
    "kill yourself", "kill your self", "kill urself", "kill ur self", "kys", "kysm",
    "neck yourself", "neck urself", "rope yourself", "get the rope", "catch the rope",
    "hang yourself", "hang urself", "off yourself", "off urself", "an hero",
    "go commit suicide", "commit suicide already", "end your life", "end ur life",
    "end yourself", "go die", "just go die", "go die in a hole", "you should die",
    "you deserve to die", "i hope you die", "i hope you kill yourself",
    "drink bleach", "jump off a bridge", "jump off a cliff", "slit your wrists",
    "slit your throat", "go cut yourself", "unalive yourself", "unalive urself",
    "do everyone a favor and die", "do us all a favor and die",
    "the world would be better without you", "nobody would miss you",
    "no one would miss you",
    # de
    "bring dich um", "bringt dich um", "bring dich doch um", "bring dich endlich um",
    "töte dich selbst", "erhäng dich", "häng dich auf", "geh dich aufhängen",
    "geh sterben", "geh doch sterben", "stirb endlich", "verreck", "verrecke",
    "verreck doch", "spring von der brücke", "spring vor den zug",
    "leg dich vor einen zug", "geh vor den zug", "ritz dich", "ritz dich auf",
    "trink bleichmittel", "niemand würde dich vermissen", "niemand vermisst dich",
    "die welt wäre besser ohne dich", "keiner würde dich vermissen",
    "mach schluss mit deinem leben",
]

# Talking about hurting oneself -> not removed; the author gets a support DM.
SELF_HARM_SELF = [
    # en
    "i want to die", "i wanna die", "i want to kill myself", "i wanna kill myself",
    "i'm going to kill myself", "im going to kill myself", "i'm gonna kill myself",
    "im gonna kill myself", "kms", "i want to kms", "i want to end it all",
    "i want to end my life", "i don't want to live", "i dont want to live",
    "i want to hang myself", "i want to slit my wrists", "unalive myself",
    "i'm suicidal", "im suicidal", "i am suicidal", "suicidal thoughts",
    "i wish i was dead", "i wish i were dead", "i'd be better off dead",
    "id be better off dead", "i'm better off dead", "im better off dead",
    "i can't go on anymore", "i cant go on anymore", "i hurt myself", "i cut myself",
    # de
    "ich will mich umbringen", "ich möchte mich umbringen", "ich bring mich um",
    "ich bringe mich um", "ich will sterben", "ich möchte sterben",
    "ich will nicht mehr leben", "ich möchte nicht mehr leben", "ich will tot sein",
    "ich wäre besser tot", "ich häng mich auf", "ich ritz mich", "ich ritze mich",
    "ich will mein leben beenden", "ich mach schluss mit meinem leben",
    "ich bin suizidal", "ich bin suizidgefährdet", "suizidgedanken",
    "selbstmordgedanken", "ich denke an selbstmord", "ich denke an suizid",
    "ich halte das nicht mehr aus", "ich verletze mich selbst",
]

# ── threats (always directed at someone) ─────────────────────────────────────
THREATS = [
    "i know where you live", "i will find you", "i'll find you", "ill find you",
    "i will kill you", "i'll kill you", "ill kill you", "i'm going to kill you",
    "im going to kill you", "i'm gonna kill you", "im gonna kill you",
    "i will rape you", "i hope you get raped", "i'll beat you up", "i will beat you up",
    "ich weiß wo du wohnst", "ich weiß wo du wohnst", "ich finde dich",
    "ich bring dich um", "ich bringe dich um", "ich töte dich", "ich mach dich kalt",
    "ich stech dich ab", "ich schlag dich tot", "ich vergewaltige dich",
    "ich hau dir auf die fresse", "ich box dich", "ich werde dich finden",
    "wir finden dich", "ich krieg dich", "wir kriegen dich", "you're dead", "youre dead meat",
]

# ── insults ──────────────────────────────────────────────────────────────────
# Severe: flagged even when nobody is explicitly addressed (medium sensitivity).
INSULTS_SEVERE = [
    "hurensohn*", "hurensöhne", "hurenkind*", "huso", "missgeburt*", "fotze*",
    "wichser*", "wixxer*", "schlampe*", "nutte*", "drecksau", "drecksack",
    "fick dich", "fick deine mutter", "deine mutter ist eine hure", "spast", "spasti",
    "spacko", "cunt*", "motherfucker*", "son of a bitch", "whore*", "slut*",
    "fuck you", "go fuck yourself", "fuck off", "piece of shit",
]
# Mild: flagged only when directed at someone.
INSULTS_MILD = [
    "idiot*", "vollidiot*", "depp*", "trottel*", "dumm", "dummer", "dumme", "dummen",
    "dummkopf", "blöd", "blöde", "blöder", "blödmann", "opfer", "lappen", "penner",
    "versager*", "loser*", "arsch", "arschloch*", "arschgeige", "hohlkopf",
    "schwachkopf", "pisser", "hackfresse", "behindert", "behinderter", "mongo",
    "bastard*", "halt die klappe", "moron*", "stupid", "dumb", "dumbass", "retard*", "bitch*", "asshole*",
    "jerk", "prick", "dickhead*", "twat*", "wanker*", "tosser", "douche*",
    "scumbag*", "shut up", "ugly", "hässlich", "verpiss dich", "piss off",
    "ich hasse dich", "hasse euch", "hass auf dich", "verachte dich", "verabscheue dich",
    "i hate you", "i despise you", "i detest you", "i loathe you", "despise you",
]
# Rude commands - addressed at the reader by their nature, no "du"/"you" needed.
INSULTS_DIRECTED = [
    "halt die fresse", "halts maul", "halt dein maul", "halt die schnauze",
    "halt deine fresse", "fresse halten", "hdf", "stfu", "shut the fuck up",
    "fick euch", "fickt euch", "verpisst euch", "fuck off",
]
# Violent intent: first-person plan + killing verb, aimed at a person (not "the boss").
_INTENT = (r"(?:ich werde|ich will|ich moechte|ich mach|ich bring|ich erschiess\w*|lass uns|wir sollten|"
           r"i will|i'll|ill|i'm going to|im going to|i'm gonna|im gonna|i want to|let's|lets|"
           r"we should)")
_KILL = (r"(?:umbringen|umbring\w*|toeten|abstechen|erschiessen|abknallen|vergewaltigen|kaltmachen|"
         r"kill|murder|shoot|stab|rape|slaughter|lynch|hang|end\s+(?:every|all|your|his|her|their)"
         r"(?:\s+\w+){0,2}\s+lives?|end\s+\w+'s\s+life)")
_PERSON = (r"(?:dich|euch|ihn|sie|diese[nrm]?\s+\w+|den\s+naechsten|die\s+naechste|jede[nrm]?\s+\w+|"
           r"alle\s+\w+|you|him|her|them|every\s+\w+|all\s+\w+|those\s+\w+|these\s+\w+|"
           r"that\s+(?:woman|man|girl|boy|kid|person)|the\s+next\s+\w+)")
VIOLENT_INTENT = re.compile(
    r"(?<![a-z])" + _INTENT + r"(?:\s+[a-z']+){0,4}?\s+" + _PERSON +
    r"(?:\s+[a-z']+){0,4}?\s+" + _KILL + r"(?![a-z])"
    r"|(?<![a-z])" + _INTENT + r"(?:\s+[a-z']+){0,2}?\s+" + _KILL + r"(?:\s+[a-z']+){0,1}?\s+" + _PERSON
)
# Accusing someone of bigotry is counter speech, not an insult: masked before re-scoring.
CONDEMN_TERMS = [
    "bigot*", "rassist*", "racist*", "sexist*", "homophob*", "transphob*", "antisemit*",
    "misogyn*", "frauenfeind*", "hater*",
]
# Curse words that make the model score "toxic" without insulting anyone.
PROFANITY = [
    "fuck", "fucking", "fucked", "fck", "shit", "shitty", "damn", "crap", "hell",
    "scheiße", "scheiss", "scheiß", "kacke", "verdammt", "mist", "wtf", "omfg",
    "bullshit", "bs",
]

# ── hate ─────────────────────────────────────────────────────────────────────
HATE_SLURS = [
    "nigger*", "nigga", "niggas", "sandnigger*", "neger", "negern", "negerin",
    "faggot*", "tranny", "trannies", "kike", "kikes", "chink", "chinks", "spic",
    "spics", "wetback*", "gook*", "towelhead*", "raghead*", "kanake*", "kanacke*",
    "schwuchtel*", "judensau", "untermensch*", "kameltreiber*", "polacke*",
    "ziegenficker*", "muselpack", "tunte", "tunten", "mongos", "spastis", "spasten",
    "shemale*", "muzzie*", "pakis", "wogs", "towelheads",
]
HATE_PHRASES = [
    "sieg heil", "heil hitler", "juden ins gas", "gas the jews", "vergast die juden",
    "hitler hatte recht", "hitler was right", "kill all jews", "white power", "1488",
]
# Protected groups: a highly toxic message about one of these is hate, not an insult.
GROUPS_DE = [
    "ausländer*", "flüchtling*", "migrant*", "asylant*", "jude", "juden", "jüdin*",
    "muslim*", "moslem*", "schwule*", "schwuler", "lesben", "homosexuelle*", "transen",
    "transmensch*", "transfrau*", "transleute", "türken", "roma", "zigeuner", "araber",
    "afrikaner", "asiaten", "frauen", "weiber", "schwarze", "schwarzen",
    "behinderte", "behinderten",
]
GROUPS_EN = [
    "foreigners", "immigrant*", "refugee*", "jew", "jews", "jewish people", "blacks",
    "black people", "black person", "gays", "gay people", "gay men", "gay person",
    "lesbians", "trans people", "trans person", "trans women", "trans men",
    "transgender*", "arabs", "mexicans", "asians", "women", "females", "muslims",
    "disabled people", "disabled person", "the disabled",
]
GROUPS = GROUPS_DE + GROUPS_EN
# Hostility next to a protected group makes a message hate speech even without a
# swear word ("I absolutely loathe immigrants"). Strong terms (dehumanising,
# exterminating) count within a few words of the group; weak ones (hate, disgust,
# kill) only directly next to it, so "ich hasse es, wenn meine Schwester..." stays fine.
HOSTILE_STRONG = [
    "abschaum", "ungeziefer", "parasit*", "ratten", "kakerlaken", "untermensch*",
    "minderwertig*", "ausrotten", "ausgerottet", "vernichte*", "vergas*", "abschlachten",
    "hinrichten", "hingerichtet", "ausmerzen", "tod allen", "tod den", "gesindel",
    "scum*", "vermin", "parasites", "rats", "cockroaches", "subhuman*", "inferior",
    "exterminate*", "eradicate*", "slaughter*", "execute*", "execution", "wipe out",
    "gassed", "lynch*", "plague", "should die", "must die", "sollten sterben",
    "müssen sterben", "gehören vergast", "gehören hingerichtet", "gehören erschossen",
    "nicht ausstehen", "nicht leiden", "can't stand", "cannot stand", "detest*",
    "verabscheue*", "gehören in einen zoo", "belong in a zoo", "gehören in die küche",
    "belong in the kitchen", "zurück in die küche", "back to the kitchen",
]
HOSTILE_WEAK = [
    "hasse", "hasst", "hassen", "verachte*", "abscheu", "ekel*", "widerlich*",
    "wertlos*", "töten", "umbringen", "loswerden", "kotzen", "dreckig*", "drecks*",
    "tiere", "viecher", "pack", "verrecken", "abknallen", "erschießen",
    "hate", "hates", "loathe*", "despise*", "contempt", "disgust*", "filth*",
    "worthless", "animals", "kill", "murder", "get rid of", "trash", "garbage",
    # curse words glued to a group noun: "scheiß flüchtlinge", "schwule sind mist"
    "scheiß", "scheiss", "scheiße", "scheisse", "mist", "kacke", "verdammte*",
    "shit", "shitty", "crap", "fucking", "damn",
]

# ── sexual ───────────────────────────────────────────────────────────────────
SEXUAL = [
    "blowjob*", "handjob*", "deepthroat*", "cumshot*", "creampie*", "gangbang*",
    "send nudes", "send me nudes", "schick nudes", "schick mir nudes", "nacktbilder",
    "nacktfotos", "dick pic*", "dickpic*", "tittenbilder", "porno*", "pornhub",
    "xvideos", "xhamster", "hentai", "rule34", "wichsen", "blas mir einen",
    "lutsch meinen", "fick mich",
]

# ── addressing someone ───────────────────────────────────────────────────────
_SECOND_PERSON = re.compile(
    r"(?<![a-z])(?:du|dich|dir|dein|deine|deinen|deinem|deiner|deines|euch|eure|euer|"
    r"euren|you|your|youre|yours|yourself|ur|u|ya|yall)(?![a-z])"
)


# People present in the chat, addressed without "du"/"you".
PEOPLE_TARGETS = [
    "ihr seid", "seid ihr", "ihr alle", "ihr hier", "euch", "alle hier", "jeder hier",
    "leute hier", "die mods", "den mods", "der mod", "die admins", "den admins",
    "der admin", "der owner", "dieser typ", "der typ", "die typen", "dieser kerl",
    "you guys", "u guys", "y'all", "yall", "you all", "all of you", "you people",
    "everyone here", "everybody here", "the mods", "the admins", "the owner", "mods",
    "admins", "this guy", "that guy", "these guys", "those guys",
]
# Second person in other languages the model understands (es, fr, it, pt, tr, pl, ru, uk).
_SECOND_PERSON_INTL = re.compile(
    r"(?<!\w)(?:tú|eres|vosotros|toi|vous|tu es|t'es|sei|siete|você|voce|vocês|"
    r"sen|seni|senin|sana|ty|ciebie|cię|jesteś|ты|тебя|тебе|твой|твоя|вы|ти|тобі)(?!\w)",
    re.IGNORECASE,
)


def addresses_someone(norm) -> bool:
    """Is the message aimed at someone present - second person, plural address,
    or naming people in the chat ("die mods", "everyone here")?"""
    if any(_SECOND_PERSON.search(v) for v in norm.variants):
        return True
    if search(patterns().people_targets, norm):
        return True
    return bool(_SECOND_PERSON_INTL.search(norm.ml_text))


# "nicht dumm", "keiner hier ist ein opfer", "nobody is stupid" - negated insults.
_NEGATION = (r"(?<![a-z])(?:nicht|kein|keine|keiner|keinen|niemand|not|no|never|nie|nobody|"
             r"no one|noone|isn'?t|aren'?t|ain'?t)")


def _negated(pattern: re.Pattern | None) -> re.Pattern | None:
    if pattern is None:
        return None
    return re.compile(_NEGATION + r"(?:\s+[a-z']+){0,3}?\s+" + pattern.pattern)


# Set phrases that use an insult word about a thing, not a person.
IDIOMS = [
    "dumme frage*", "blöde frage*", "dumm gelaufen", "dummer fehler", "dummen fehler",
    "dumme sache", "blöd gelaufen", "stupid question*", "dumb question*", "idiot move",
    "stupid amount", "stupid mistake", "dumb mistake", "stupidly good", "loser bracket",
    "losers bracket", "halt mal", "halt kurz",
    "shut up and take my money", "no way shut up",
]


# "ich bin so ein idiot", "i'm such a dumbass", "ich depp" - calling oneself names.
_SPEAKER = r"(?<![a-z])(?:ich|i|i'm|im|me|mich|mir|myself)"
_NOT_YOU = r"(?!(?:du|dich|dir|dein\w*|you|your|ur|u|ihr|euch)(?![a-z]))"


def _self_directed(pattern: re.Pattern | None) -> re.Pattern | None:
    if pattern is None:
        return None
    return re.compile(_SPEAKER + r"(?:[\W_]+" + _NOT_YOU + r"[a-z']+){0,4}?[\W_]+"
                      + pattern.pattern)


def _infinitive(pattern: re.Pattern | None) -> re.Pattern | None:
    """"told to fuck off", "got to fuck off" - an infinitive, not a command."""
    if pattern is None:
        return None
    return re.compile(r"(?<![a-z])(?:to|zu)[\W_]+" + pattern.pattern)


def search_unnegated(pattern: re.Pattern | None, maskers, norm) -> str | None:
    """Like normalize.search, but ignores occurrences that are negated ("nicht dumm")
    or aimed at the speaker ("ich bin so ein idiot")."""
    if pattern is None:
        return None
    if not isinstance(maskers, (list, tuple)):
        maskers = [maskers]
    for v in norm.variants:
        for masker in maskers:
            if masker is not None:
                v = masker.sub(" ", v)
        if m := pattern.search(v):
            return m.group(0)
    return None


# ── compiled patterns (optional override file merged into self-harm) ─────────
_OVERRIDE_FILE = Path("data/safetext/suicide_words.json")
_FIRST_PERSON = re.compile(
    r"^(?:i|i'm|im|i'd|id|ich|mir|mich)\b|\bmyself\b|\bmein\w*\b|\bmich\b"
)


def _load_self_harm() -> tuple[list[str], list[str]]:
    """Merge data/safetext/suicide_words.json ({lang: [phrases]} or
    {lang: {"incite": [...], "self": [...]}}) into the built-in lists. Legacy flat
    lists are split by a first-person heuristic."""
    incite, self_ = list(SELF_HARM_INCITE), list(SELF_HARM_SELF)
    try:
        data = json.loads(_OVERRIDE_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return incite, self_
    except (OSError, json.JSONDecodeError) as e:
        logger.warn(f"SafeText | suicide_words override ignored: {e}")
        return incite, self_
    known = set(incite) | set(self_)   # the shipped file repeats the defaults
    for entry in data.values():
        if isinstance(entry, dict):
            incite += [str(p) for p in entry.get("incite", [])]
            self_ += [str(p) for p in entry.get("self", [])]
        elif isinstance(entry, list):
            for p in map(str, entry):
                if p not in known:
                    (self_ if _FIRST_PERSON.search(p.lower()) else incite).append(p)
    return incite, self_


_DETERMINER = r"(?:all|alle|allen|die|diese|diesen|those|these|the|such|solche|solchen|jeden|jede|every|any|of)"
_COPULA = r"(?:sind|are|is|ist|waren|were|seien)"
_GAP = r"(?:[\W_]+[a-z']+)"
_NEGATION_BEFORE = re.compile(
    r"(?<![a-z])(?:nicht|kein\w*|nie|niemals|niemand|gegenteil|alles andere als|"
    r"not|no|never|nobody|no one|opposite|anything but|far from|"
    r"don'?t|doesn'?t|isn'?t|aren'?t|shouldn'?t|won'?t|wouldn'?t)(?![a-z])"
)


def _group_hate_pattern(groups, strong, weak) -> re.Pattern | None:
    if groups is None or strong is None or weak is None:
        return None
    g, st, wk = groups.pattern, strong.pattern, weak.pattern
    return re.compile("|".join([
        # strong term within six words of the group, either order
        rf"{g}{_GAP}{{0,6}}?[\W_]+{st}", rf"{st}{_GAP}{{0,6}}?[\W_]+{g}",
        # weak term directly on the group: "ich verachte (alle) Schwule", "hate immigrants"
        rf"{wk}[\W_]+(?:{_DETERMINER}[\W_]+){{0,2}}{g}",
        # "Frauen sind (einfach) widerlich", "immigrants are (just) trash"
        rf"{g}[\W_]+{_COPULA}{_GAP}{{0,2}}?[\W_]+{wk}",
    ]))


def _clause_before(v: str, pos: int) -> str:
    """Text from the start of the clause containing *pos* up to *pos*."""
    cut = max(v.rfind(c, 0, pos) for c in ".,;!?:")
    return v[cut + 1:pos]


_NEG_EXEMPT = re.compile(r"nicht ausstehen|nicht leiden|can'?t stand|cannot stand")


def _clause_around(v: str, start: int, end: int) -> str:
    left = max(v.rfind(c, 0, start) for c in ".,;!?:") + 1
    rights = [i for i in (v.find(c, end) for c in ".,;!?:") if i != -1]
    return v[left:min(rights) if rights else len(v)]


def find_group_hate(norm) -> str | None:
    """Hostility aimed at a protected group, unless the clause negates it
    ("Juden sind nicht minderwertig", "Ich hasse Frauen nicht",
    "I will never tolerate the murder of women")."""
    pat = patterns().group_hate
    if pat is None:
        return None
    for v in norm.variants:
        for m in pat.finditer(v):
            clause = _NEG_EXEMPT.sub(" ", _clause_around(v, m.start(), m.end()))
            if _NEGATION_BEFORE.search(clause):
                continue
            return m.group(0)
    return None


def find_violent_intent(norm) -> str | None:
    """"Ich werde diese Frau umbringen", "I want to end every woman's life"."""
    for v in norm.variants:
        for m in VIOLENT_INTENT.finditer(v):
            if not _NEGATION_BEFORE.search(_clause_around(v, m.start(), m.end())):
                return m.group(0)
    return None


def negated_near_group(norm) -> bool:
    """Does a clause that names a protected group also contain a negation?
    ("Kein Jude verdient den Tod", "women are the opposite of stupid")."""
    pats = patterns()
    if pats.groups is None:
        return False
    for v in norm.variants:
        for m in pats.groups.finditer(v):
            start = max(v.rfind(c, 0, m.start()) for c in ".,;!?:") + 1
            ends = [i for i in (v.find(c, m.end()) for c in ".,;!?:") if i != -1]
            if _NEGATION_BEFORE.search(v[start:min(ends) if ends else len(v)]):
                return True
    return False


def hostile_unnegated(norm) -> str | None:
    """Any hostile term in the message that its clause does not negate."""
    pats = patterns()
    for pat in (pats.hostile_strong, pats.hostile_weak):
        if pat is None:
            continue
        for v in norm.variants:
            for m in pat.finditer(v):
                if not _NEGATION_BEFORE.search(_clause_before(v, m.start())):
                    return m.group(0)
    return None


_NATURAL_FOLD = {"ä": "(?:ä|ae)", "ö": "(?:ö|oe)", "ü": "(?:ü|ue)", "ß": "(?:ß|ss)"}


def _natural_regex(words) -> re.Pattern:
    """Case-insensitive regex over natural (unfolded) text, for masking words
    before re-scoring with the model."""
    parts = []
    for w in words:
        body = "".join(_NATURAL_FOLD.get(c, re.escape(c)) for c in w.lower().rstrip("*"))
        body = body.replace(r"\ ", r"\s+")
        parts.append(body + (r"\w*" if w.endswith("*") else ""))
    parts.sort(key=len, reverse=True)
    return re.compile(r"(?<!\w)(?:" + "|".join(parts) + r")(?!\w)", re.IGNORECASE)


class _Patterns:
    def __init__(self) -> None:
        incite, self_ = _load_self_harm()
        self.self_harm_incite = compile_phrases(incite)
        self.self_harm_self = compile_phrases(self_)
        self.threats = compile_phrases(THREATS)
        self.insults_severe = compile_phrases(INSULTS_SEVERE)
        self.insults_mild = compile_phrases(INSULTS_MILD)
        self.insults_mild_negated = _negated(self.insults_mild)
        self.insults_mild_self = _self_directed(self.insults_mild)
        self.idioms = compile_phrases(IDIOMS)
        self.insults_directed = compile_phrases(INSULTS_DIRECTED)
        self.insults_directed_inf = _infinitive(self.insults_directed)
        self.insults_severe_self = _self_directed(self.insults_severe)
        self.condemn_terms = _natural_regex(CONDEMN_TERMS)
        self.people_targets = compile_phrases(PEOPLE_TARGETS)
        # "fick die mods", "fuck the admins", "fuck you guys" - but not "fick die schule"
        self.curse_at_people = re.compile(
            r"(?<![a-z])(?:fick\w*|fuck\w*|scheiss auf|scheiß auf|screw)[\W_]+"
            r"(?:(?:die|den|the|all|alle|diese|these|you|dich)[\W_]+)?"
            + self.people_targets.pattern
        )
        self.hostile_strong = compile_phrases(HOSTILE_STRONG)
        self.hostile_weak = compile_phrases(HOSTILE_WEAK)
        self.hate = compile_phrases(HATE_SLURS + HATE_PHRASES)
        self.groups = compile_phrases(GROUPS)
        self.group_hate = _group_hate_pattern(self.groups, self.hostile_strong, self.hostile_weak)
        self.sexual = compile_phrases(SEXUAL)
        # Masked in the *natural* ML text before re-scoring: curse words (the model
        # over-reacts to them) and group names (identity-term bias: "we should look
        # up to these Muslims" scores 0.999 toxic).
        self.profanity = _natural_regex(PROFANITY)
        self.groups_natural = _natural_regex(GROUPS)
        self.groups_natural_de = _natural_regex(GROUPS_DE)


_patterns: _Patterns | None = None


def patterns() -> _Patterns:
    global _patterns
    if _patterns is None:
        _patterns = _Patterns()
    return _patterns


def reload() -> None:
    global _patterns
    _patterns = None
