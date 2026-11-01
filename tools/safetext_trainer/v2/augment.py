"""Erzeugt Trainingsbeispiele aus Vorlagen: Drohungen und Gruppenhass ohne Stichwort, plus harmlose Gegenstücke.

    python tools/safetext_trainer/v2/augment.py --out <datei.jsonl>

Warum: Öffentliche Datensätze enthalten fast nur ausdrückliche Drohungen ("I will kill you"). Die harmlosen
Gegenstücke (Besuch ankündigen, Spielgewalt, Gegenrede, freundliche Neckerei) verhindern, dass das Modell nur auf
Wörter wie "vorbei", "Adresse" oder Gruppennamen reagiert. Reine Vorlagen-Daten (src="template"), Sprachen: Deutsch, Englisch.
Die Vorlagen wurden unabhängig vom eingefrorenen Testset holdout_v2.jsonl geschrieben, überschneiden sich aber
thematisch (Drohungen, Gruppenhass). Das ist in der Auswertung zu berücksichtigen.
"""
import argparse
import itertools
import json
import random
from pathlib import Path

SEED = 7
rnd = random.Random(SEED)


def pick(*opts):
    return rnd.choice(opts)


# ── Deutsch ──────────────────────────────────────────────────────────────────
OPEN_DE = ["", "", "", "Hör zu: ", "Letzte Warnung: ", "Ich sag's nur einmal: ", "Merk dir das: ", "Hey, "]
KNOW_DE = ["deine Adresse", "wo du wohnst", "welche Schule du besuchst", "wo deine Familie lebt", "dein Auto",
           "wo du arbeitest", "wo deine Eltern wohnen", "wann du alleine heimgehst"]
CONSEQ_DE = ["es bereuen", "dafür bezahlen", "bald nicht mehr lachen", "im Krankenhaus landen", "dich noch wundern",
             "dir wünschen, du hättest nie geschrieben", "Schmerzen haben"]
VIOLENT_DE = ["brech ich dir die Knochen", "schlag ich dich zusammen", "mach ich dich fertig", "zünde ich dein Auto an",
              "verprügle ich dich vor allen", "trete ich dir die Tür ein", "sorge ich dafür, dass es wehtut"]
TIME_DE = ["morgen", "heute Nacht", "nach der Schule", "am Wochenende", "gleich nach dem Unterricht"]
PLACE_DE = ["vor deiner Tür", "am Schultor", "an der Bushaltestelle", "bei dir zu Hause", "auf dem Heimweg"]
HURT_DE = ["zusammenschlagen", "verprügeln", "abstechen", "aus dem Fenster werfen", "in den Keller sperren und vergessen"]
GROUPS_DE = ["Juden", "Muslime", "Moslems", "Schwarze", "Asiaten", "Türken", "Syrer", "Roma", "Schwule", "Lesben",
             "Transmenschen", "Behinderte", "Frauen", "Migranten", "Flüchtlinge", "Ausländer", "Araber", "Polen",
             "Homosexuelle", "Rollstuhlfahrer", "Afrikaner", "Christen", "Atheisten", "Senioren"]
HOSTILE_DE = ["sind weniger wert als wir", "sind von Natur aus kriminell", "gehören nicht in unser Land",
              "sind eine Krankheit für die Gesellschaft", "haben keine Rechte verdient", "gehören weggesperrt",
              "sind alle Betrüger", "sind dümmer als andere", "zerstören unsere Kultur",
              "kosten nur Geld und bringen nichts", "gehören abgeschoben", "sind keine richtigen Menschen",
              "würde ich in meiner Nähe nicht dulden", "sind eine Gefahr für unsere Kinder", "sollte man loswerden",
              "haben hier nichts zu suchen und sollen verschwinden", "sind Ballast für alle anderen"]
BENIGN_GROUP_DE = ["sind bei uns herzlich willkommen", "sind in meiner Klasse und wir verstehen uns gut",
                   "werden leider oft diskriminiert, das ist nicht in Ordnung", "sind Menschen wie du und ich",
                   "haben die gleichen Rechte wie alle anderen", "feiern am Wochenende ein großes Fest",
                   "engagieren sich in unserem Verein", "waren Thema in unserer Geschichtsstunde",
                   "haben in der Stadt eine tolle Aktion organisiert", "sind oft sehr hilfsbereit"]
QUOTE_DE = ["Der Satz '{g} {h}' ist ein Vorurteil und wird hier nicht geduldet.",
            "Wer schreibt, dass {g} {h}, bekommt von uns eine Verwarnung.",
            "Mich hat jemand angeschrieben, {g} {h}. Das hat mich schockiert, ich habe es gemeldet.",
            "Im Video behauptet einer, {g} {h}. Das ist falsch und menschenverachtend."]
VISIT_DE = ["{w} komme ich bei dir vorbei und bringe {x} mit", "Wir kommen {w} vorbei, {x} ist dabei",
            "{w} stehen wir bei dir {p}, wir bringen {x} mit"]
THING_DE = ["Pizza", "Kuchen", "Getränke", "das Spiel", "die Hausaufgaben", "Snacks", "einen Film"]
GAME_DE = ["{w} mach ich den Boss fertig", "{w} zerstören wir die gegnerische Basis", "Ich knöpf mir {w} den Drachen vor",
           "{w} erledigen wir das andere Team", "Den Endgegner hau ich {w} um, der hat keine Chance"]
CARE_DE = ["Pass auf, dass du nicht stolperst", "Pass auf, dass du beim Zocken nicht einschläfst",
           "Du wirst das Spiel lieben, glaub mir", "Du wirst dich wundern, wie gut das neue Update ist",
           "Wir wissen noch nicht, wo das Treffen stattfindet", "Wir wissen nicht, wer das Turnier gewonnen hat",
           "Ich weiß, wie man das Rätsel löst, schau her"]
BANTER_DE = ["{y} {n}, das war richtig gut gespielt {e}", "Geh weida, du {n}, des hast guad gmacht {e}",
             "{y} {n}, ich lach mich tot {e}", "Na du {n}, wieder die ganze Nacht gezockt? Respekt {e}",
             "Mei, du bist a echter {n}, jetzt hast mi überrascht {e}"]
NOUN_BANTER = ["Gauner", "Hund", "Spinner", "Zocker", "Hammer", "Schlawiner", "Lausbub", "Verrückter"]

# ── Englisch ─────────────────────────────────────────────────────────────────
THREAT_EN = ["You're going to regret this, we know where you live", "Watch your back, someone will come for you tonight",
             "I will make you pay for what you wrote", "We know your address and your school",
             "Keep talking and you'll end up in the hospital", "I'll be waiting outside your house after class",
             "Someone should teach you a lesson with a baseball bat", "If I see you again I'll break your nose",
             "You won't be laughing when we find you", "Sleep with one eye open from now on",
             "Your family will hear about this, and you'll be sorry", "I know which bus you take home, be careful"]
GROUPS_EN = ["Jews", "Muslims", "Black people", "Asians", "Mexicans", "gay people", "lesbians", "trans people",
             "disabled people", "women", "immigrants", "refugees", "foreigners", "Arabs", "Roma", "Christians"]
HOSTILE_EN = ["are worth less than us", "are criminals by nature", "don't belong in our country",
              "are a disease to society", "don't deserve any rights", "should be locked away", "are all frauds",
              "are less intelligent than others", "are destroying our culture", "should be deported",
              "are not real people", "are a danger to our kids", "have no business being here"]
BENIGN_GROUP_EN = ["are very welcome in our community", "are in my class and we get along great",
                   "are often discriminated against, which is wrong", "are people just like you and me",
                   "have the same rights as everyone else", "organised a great event this weekend"]
QUOTE_EN = ["The sentence '{g} {h}' is a prejudice and we don't tolerate it here.",
            "Somebody wrote that {g} {h}. I reported it because it is hateful.",
            "He claimed in the video that {g} {h}. That is false and dehumanizing."]
VISIT_EN = ["I'll come over {w} and bring {x}", "We'll drop by {w}, {x} included", "{w} we're at your place with {x}"]
THING_EN = ["pizza", "snacks", "the game", "drinks", "a movie"]
GAME_EN = ["I'm going to crush the boss {w}", "We'll destroy their base {w}", "{w} I'll take down the dragon",
           "Tonight we kill the final boss, no chance for him"]
CARE_EN = ["Watch out so you don't trip on the cable", "You'll love this game, trust me",
           "We don't know where the meeting is yet", "I know how to solve the puzzle, look"]
TIME_EN = ["tomorrow", "tonight", "after school", "this weekend"]
EMOJI = ["", "", "😂", "😄", "xD", "haha"]
YOU = ["Ey", "Alter", "Na", "Hey"]


def build() -> list[dict]:
    out: list[dict] = []

    def add(text, label, typ, lang):
        out.append({"text": " ".join(text.split()), "label": label, "type": typ, "lang": lang, "src": "template"})

    for _ in range(260):   # Drohungen DE
        k = rnd.randrange(6)
        o = pick(*OPEN_DE)
        if k == 0:
            t = f"{o}{pick('Wir', 'Ich')} {pick('wissen', 'kennen')} {pick(*KNOW_DE)}."
        elif k == 1:
            t = f"{o}Du wirst {pick(*CONSEQ_DE)}. {pick('', 'Das verspreche ich.', 'Glaub mir.', 'Wir wissen, wo du bist.')}"
        elif k == 2:
            t = f"{o}Pass auf, wenn du nicht aufhörst, {pick(*VIOLENT_DE)}."
        elif k == 3:
            t = f"{o}{pick('Ich warte', 'Wir warten')} {pick(*TIME_DE)} {pick(*PLACE_DE)} auf dich, {pick('dann gibt es Ärger', 'und du vergisst es nie', 'bring Verstärkung mit')}."
        elif k == 4:
            t = f"{o}Wenn ich dich {pick('sehe', 'erwische', 'finde')}, {pick('bist du dran', 'wirst du es spüren', 'gibt es Blut', 'siehst du kein Licht mehr')}."
        else:
            t = f"{o}Jemand sollte dich {pick(*HURT_DE)}."
        add(t, 1, "drohung", "de")
    for _ in range(140):   # Drohungen EN
        add(pick(*THREAT_EN) + pick("", ".", "!"), 1, "drohung", "en")
    for _ in range(480):   # Gruppenhass DE
        g, h = pick(*GROUPS_DE), pick(*HOSTILE_DE)
        t = f"{g} {h}" if rnd.random() < 0.6 else f"{pick('Ganz ehrlich:', 'Mal ehrlich,', 'Ist doch so:')} {g} {h}"
        add(t + pick(".", "!", ""), 1, "gruppenhass", "de")
    for _ in range(240):   # Gruppenhass EN
        add(f"{pick(*GROUPS_EN)} {pick(*HOSTILE_EN)}" + pick(".", "!", ""), 1, "gruppenhass", "en")
    # harmlose Gegenstücke
    for _ in range(300):
        t = pick(*VISIT_DE).format(w=pick(*TIME_DE), x=pick(*THING_DE), p=pick(*PLACE_DE))
        add(t.capitalize() if rnd.random() < 0.5 else t, 0, "besuch", "de")
    for _ in range(160):
        add(pick(*VISIT_EN).format(w=pick(*TIME_EN), x=pick(*THING_EN)), 0, "besuch", "en")
    for _ in range(320):
        tgt = pick("den Boss", "den Endgegner", "den Drachen", "das gegnerische Team", "die Basis", "den Tank",
                   "den Gegner", "den Raid-Boss", "die Wache", "das Monster")
        verb = pick("mach ich", "hau ich", "erledige ich", "zerstöre ich", "knöpf ich mir", "schlag ich")
        w = pick(*TIME_DE)
        add(rnd.choice([f"{w.capitalize()} {verb} {tgt} {pick('fertig', 'um', 'platt', 'weg', 'locker')}",
                        f"{pick(*GAME_DE).format(w=w)}"]), 0, "gaming", "de")
    for _ in range(160):
        tgt = pick("the boss", "their base", "the dragon", "the other team", "the final boss", "the tank", "that monster")
        add(f"{pick(*TIME_EN).capitalize()} I'll {pick('crush', 'destroy', 'kill', 'take down', 'smash')} {tgt}"
            + pick("", " easily", ", no chance for it"), 0, "gaming", "en")
    for t in CARE_DE * 4:
        add(t + pick(".", "!"), 0, "alltag", "de")
    for t in CARE_EN * 4:
        add(t + pick(".", "!"), 0, "alltag", "en")
    for _ in range(420):
        add(f"{pick(*GROUPS_DE)} {pick(*BENIGN_GROUP_DE)}" + pick(".", "!", ""), 0, "gruppe_harmlos", "de")
    for _ in range(200):
        add(f"{pick(*GROUPS_EN)} {pick(*BENIGN_GROUP_EN)}" + pick(".", "!", ""), 0, "gruppe_harmlos", "en")
    for _ in range(300):   # Zitat/Gegenrede
        add(pick(*QUOTE_DE).format(g=pick(*GROUPS_DE), h=pick(*HOSTILE_DE)), 0, "gegenrede", "de")
    for _ in range(140):
        add(pick(*QUOTE_EN).format(g=pick(*GROUPS_EN), h=pick(*HOSTILE_EN)), 0, "gegenrede", "en")
    for _ in range(260):   # freundliche Neckerei / Dialekt
        add(pick(*BANTER_DE).format(y=pick(*YOU), n=pick(*NOUN_BANTER), e=pick(*EMOJI)), 0, "neckerei", "de")
    seen, uniq = set(), []
    for r in out:
        if r["text"] not in seen:
            seen.add(r["text"]); uniq.append(r)
    rnd.shuffle(uniq)
    return uniq


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    rows = build()
    Path(a.out).write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    import collections
    print(len(rows), collections.Counter((r["type"], r["label"]) for r in rows))
