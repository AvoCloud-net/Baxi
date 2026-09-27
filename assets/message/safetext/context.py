"""Use vs. mention: which parts of a message are actually said *to* someone.

A word list or a toxicity model cannot tell "du hurensohn" from
"er hat mich hurensohn genannt" or from "'Juden sind Abschaum' zu schreiben ist
widerlich". This module finds the parts of a message that only *mention*
abusive language and removes them before the lexicon and model stages run:

  * victim reports        "er hat mich X genannt", "he called me X", "sagte zu mir X"
  * counter speech        quoting / referring to abuse while condemning it
                          ("zu sagen, dass du X hasst, zeigt...", "if you say 'X' you're a bigot")
  * questions about words "was bedeutet kys?", "is 'X' a slur?"
  * pointing at hatred    "es reicht mit deinem Abscheu für Frauen", "your contempt for X"

It works per clause, so "du hast mich idiot genannt, du idiot" still flags the
second clause. It also reports joke markers ("haha", "jk", "xD", 😂), which the
pipeline uses to go easy on mild banter - never on severe abuse, slurs or threats.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from assets.message.safetext.normalize import fold

# Clause boundaries: sentence ends, commas, colons, semicolons, dashes, line breaks.
_CLAUSE_SEP = re.compile(r"[.!?;\n]+\s*|,\s+|:\s+|\s+[-–—]\s+")
_QUOTED = re.compile(
    r"\"[^\"\n]{1,300}\"|„[^“”\"\n]{1,300}[“”\"]|“[^”\n]{1,300}”|«[^»\n]{1,300}»"
    r"|‚[^‘’\n]{1,300}[‘’]|(?<!\w)'[^'\n]{3,300}'(?!\w)|`[^`\n]{1,300}`"
)


def _rx(*parts: str) -> re.Pattern:
    return re.compile(r"(?<![a-z])(?:" + "|".join(parts) + r")(?![a-z])")


# Someone else said / called *me* something.
_VICTIM_REPORT = re.compile("|".join([
    r"(?<![a-z])(?:hat|haben|hatte|hatten)\s+mich\b.{0,60}?\b(?:genannt|beleidigt|beschimpft|bezeichnet)(?![a-z])",
    r"(?<![a-z])(?:nannte|nennt|nennen|beschimpfte|beschimpft|beleidigte|beleidigt|bezeichnete)\s+(?:mich|uns)(?![a-z])",
    r"(?<![a-z])(?:hat|haben|hatte|hatten)\s+(?:zu\s+)?(?:mir|uns)\b.{0,50}?\b(?:gesagt|geschrieben|geschickt)(?![a-z])",
    r"(?<![a-z])(?:sagte|sagt|schrieb|schreibt|meinte)\s+(?:zu\s+)?(?:mir|uns)(?![a-z])",
    r"(?<![a-z])(?:called|calls|calling|call)\s+(?:me|us)(?![a-z])",
    r"(?<![a-z])(?:said|says|told|tells|wrote|writes|sent|dmed)\s+(?:to\s+)?(?:me|us)(?![a-z])",
    r"(?<![a-z])(?:been|was|were|got|get)\s+(?:told|called)(?![a-z])",
    r"(?<![a-z])(?:wurde|wurden|werde|bin)\s+(?:\w+\s+){0,3}?(?:genannt|beschimpft|beleidigt)(?![a-z])",
]))

# Talking *about* words or statements.
_SPEECH_FRAME = _rx(
    r"zu sagen", r"sagen,? dass", r"sagt,? dass", r"sagst", r"sagt man", r"wenn man sagt",
    r"zu schreiben", r"schreiben,? dass", r"schreibt,? dass", r"schreibst", r"zu bezeichnen",
    r"bezeichnet", r"zu nennen", r"nennt", r"nennen", r"aussagen?", r"sprueche?",
    r"kommentare?", r"dinge wie", r"sachen wie", r"begriffe? wie", r"woerter wie",
    r"das wort", r"die aussage", r"to say", r"saying", r"say that", r"says that",
    r"said that", r"if you say", r"to call", r"calling", r"call people", r"called people",
    r"writing that", r"to write", r"statements?", r"comments?", r"remarks?",
    r"the word", r"words like", r"stuff like", r"things like", r"posting",
    r"gesagt hast", r"gesagt habt", r"geschrieben hast", r"bezeichnest", r"nennst",
    r"drohst", r"drohungen?", r"beitraege? wie", r"kommentare? wie", r"nachrichten wie",
    r"hass wie", r"wie \W*[\"„“«']", r"you said", r"when you said", r"you say",
    r"makes you say", r"he said", r"she said", r"they said", r"er sagte", r"sie sagte",
    r"threats? like", r"messages? like", r"posts? like", r"comments? like",
    r"for wishing", r"for saying", r"like \W*[\"“«']",
    r"glauben,? dass", r"glaubst,? dass", r"denkst,? dass", r"believe that", r"think that",
)

# A clause starting like this continues the reported statement of the clause before.
_CONTINUATION = re.compile(r"^\W*(?:dass|that|ob|whether|wie|like)(?![a-z])")

# The speaker condemns what they quote / refer to.
_CONDEMN = _rx(
    r"rassist\w*", r"sexist\w*", r"homophob\w*", r"transphob\w*", r"antisemit\w*",
    r"hetze", r"hassrede", r"extremer hass", r"nicht ok(?:ay)?", r"nicht in ordnung",
    r"inakzeptabel", r"zeigt", r"falsch", r"schlimm", r"schrecklich", r"entmenschlich\w*",
    r"melde\w*", r"es reicht", r"diskriminier\w*", r"discriminat\w*",
    r"nicht ernsthaft", r"can'?t seriously", r"cannot seriously",
    r"respektlos", r"schaem\w*", r"widerwaertig", r"abscheulich", r"kein gutes licht",
    r"ist widerlich", r"ist ekelhaft", r"ist hass", r"is disgusting", r"is vile", r"is hate",
    r"verurteil\w*", r"geht gar nicht", r"unangebracht", r"gericht", r"anzeige",
    r"melden", r"gemeldet", r"hoer auf", r"hoert auf", r"sag nicht", r"sagt nicht",
    r"schreib nicht", r"nicht sagen", r"nicht schreiben", r"lass das",
    r"bigot\w*", r"racis\w*", r"sexis\w*", r"hateful", r"hate speech", r"not ok(?:ay)?",
    r"unacceptable", r"shows how", r"shows that", r"reflect well", r"horrible", r"terrible",
    r"awful", r"disgusting thing", r"wrong", r"misguided", r"dehumani[sz]\w*", r"offensive",
    r"ashamed", r"report(?:ed)?", r"call(?:ed)? out", r"stop saying", r"don'?t say",
    r"stop calling", r"shouldn'?t say", r"not cool", r"inappropriate", r"hurtful",
    r"respekt", r"tut weh", r"gefaengnis", r"gebannt", r"blockier\w*", r"dulden",
    r"rausgeworfen", r"laecherlich", r"aufhoeren", r"minderbemittelt",
    r"respect", r"prison", r"jail", r"banned", r"blocked", r"tolerate", r"kicked",
    r"ridiculous", r"has to stop", r"must stop", r"small-minded", r"bigoted",
)

# Pointing at someone else's hatred: "dein Abscheu für Frauen", "your contempt for women".
_THEIR_HATRED = re.compile(
    r"(?<![a-z])(?:dein|deine|deinem|deinen|deiner|euer|eure|sein|seine|seinem|ihr|ihre|ihrem|"
    r"your|his|her|their)(?:\s+[a-z]+){0,2}\s+(?:abscheu|hass|verachtung|ekel|hetze|rassismus|"
    r"contempt|hatred|hate|disdain|disgust|racism|bigotry)(?![a-z])"
)

# Asking about a word.
_META_QUESTION = _rx(
    r"bedeutet", r"heisst", r"meint man", r"was ist", r"was sind", r"schimpfwort",
    r"beleidigung", r"abkuerzung", r"steht fuer", r"darf man", r"ist es ok",
    r"what does", r"what is", r"means?", r"meaning", r"slur", r"insult",
    r"abbreviation", r"stands for", r"can i say", r"is it ok",
)

# A third party is quoted: 'der Bösewicht sagt "ich bring dich um"'.
_ATTRIBUTED_QUOTE = re.compile(
    r"(?<![a-zäöü])(?!ich\b|i\b)(?:[a-zäöüß]+\s+){0,3}?(?:sagt|sagte|meint|meinte|schreibt|schrieb|"
    r"ruft|rief|schreit|brüllt|says|said|goes|yells|screams|shouts|writes|wrote)\b[^\"„“«\n]{0,30}[\"„“«]",
    re.IGNORECASE,
)
_FIRST_PERSON_SPEAKER = re.compile(r"(?<![a-z])(?:ich|i)\s+(?:\w+\s+)?(?:sag|sage|schreib|schreibe|say|write)", re.IGNORECASE)

# Praise: "du bist verrückt, wie hast du das geschafft", "you're a monster in ranked".
_POSITIVE = re.compile(
    r"(?<![a-z])(?:genial\w*|geil\w*|krass\w*|mega|stark|nice|geschafft|respekt|legend\w*|goat|"
    r"amazing|awesome|incredible|insane at|cracked|clutch|carry|best|beste\w*|so gut|so good|"
    r"love (?:you|u|it)|lieb dich|liebe dich|wie hast du|how did you|at this game|in ranked|gg|wp|"
    r"proud|stolz|congrats|glueckwunsch)(?![a-z])|[❤🥰😍🔥🤯👏🙌💪]"
)

_JOKE = re.compile(
    r"(?<![a-z])(?:ha(?:ha)+h?|he(?:he)+|hi(?:hi)+|lol+|lmf?ao+|rofl|xd+|jk|j/k|"
    r"just kidding|kidding|nur spa(?:ss|ß)|spa(?:ss|ß) bei ?seite|scherz\w*|:d|:p|xp|;\))(?![a-z])"
    r"|[😂🤣😆😹😜😝😛😁]",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Context:
    eval_text: str          # text left to judge (mentions removed)
    dropped: tuple[str, ...]  # clauses that only mention abuse
    joke: bool              # joke marker: mild banter is excused (not at high sensitivity)
    praise: bool = False    # praise marker: "du bist verrückt, wie hast du das geschafft"


def _clauses(text: str) -> list[tuple[int, int]]:
    spans, pos = [], 0
    for m in _CLAUSE_SEP.finditer(text):
        if m.start() > pos:
            spans.append((pos, m.end()))
        pos = m.end()
    if pos < len(text):
        spans.append((pos, len(text)))
    return spans


@lru_cache(maxsize=4096)
def analyze(text: str) -> Context:
    folded = fold(text)
    joke = bool(_JOKE.search(text))
    praise = bool(_POSITIVE.search(folded)) or bool(_POSITIVE.search(text))
    counter = bool(_SPEECH_FRAME.search(folded)) and (
        bool(_CONDEMN.search(folded)) or "?" in text
    )
    if _ATTRIBUTED_QUOTE.search(text) and not _FIRST_PERSON_SPEAKER.search(text):
        counter = True   # quoting a third party: the quote is not the speaker's own words

    dropped: list[str] = []
    work = text
    if counter:
        dropped.extend(m.group(0) for m in _QUOTED.finditer(text))
        work = _QUOTED.sub(lambda m: " " * len(m.group(0)), text)
    spans = _clauses(work)
    drop = [False] * len(spans)
    for i, (start, end) in enumerate(spans):
        fc = fold(work[start:end])
        if not fc:
            continue
        is_question = "?" in text[start:end]
        if (
            _VICTIM_REPORT.search(fc)
            or _THEIR_HATRED.search(fc)
            or (counter and _SPEECH_FRAME.search(fc))
            or (is_question and _META_QUESTION.search(fc))
        ):
            drop[i] = True
        elif counter and i > 0 and drop[i - 1] and _CONTINUATION.search(fc):
            drop[i] = True   # "als du gesagt hast, | dass Frauen ... sind"
    for i in reversed(range(len(spans))):
        if drop[i]:
            start, end = spans[i]
            dropped.append(text[start:end].strip())
            work = work[:start] + " " * (end - start) + work[end:]

    if work == text:
        return Context(eval_text=text, dropped=(), joke=joke, praise=praise)
    return Context(eval_text=" ".join(work.split()), dropped=tuple(reversed(dropped)),
                   joke=joke, praise=praise)
