# Update-Plan November / Dezember 2026

Stand: 01.11.2026. Entscheidungen aus dem Brainstorming; offene Punkte stehen am Ende.

## Leitlinie für alle Features: einfach

Jedes Feature muss für User und Staff ohne Erklärung verständlich sein.

- **Funktioniert sofort.** Einschalten reicht, die Standardwerte sind sinnvoll. Weitere Einstellungen sind optional.
- **Wenige Einstellungen sichtbar.** Pro Karte höchstens 3–4 Felder, alles Weitere unter „Erweitert“.
- **Ein Klick statt Syntax.** Buttons und Kontextmenüs („Rechtsklick → Apps“) statt Befehle mit vielen Optionen.
- **Ein Staff-Kanal.** Ein zentraler Kanal für alles, was Staff wissen muss (Mod-Queue, Einsprüche, Gate-Alerts), nicht ein Log-Kanal pro Feature. Bestehende `log_channel`-Felder dienen als Fallback.
- **Ein Satz Erklärung** pro Karte im Dashboard, was das Feature tut.
- Gibt es zwei Wege, wird der einfachere gebaut.

---

## 1. Zitat-Reactions

Neue Zitate im Quotes-Kanal bekommen Reaction-Buttons. Die Stimmen sind die Datenbasis für „Zitat des Jahres“ im Wrapped.

- **Standard:** jedes Zitat startet mit einem Button `😂 0` und einem Icon-Button `+`.
- Ein Klick auf ein Emoji setzt die Reaction, ein zweiter nimmt sie zurück. Pro User eine Reaction pro Emoji.
- `+` öffnet ein Dropdown (nur für den Klickenden sichtbar) mit einer festen Auswahl von etwa 12 gängigen Emojis. Die Wahl erscheint als neuer Button mit Zähler.
- **Höchstens 4 verschiedene Emojis** pro Zitat. Sind es 4, verschwindet `+`. 4 Emojis + `+` = 5 Buttons, das passt in eine Discord-Reihe.
- Fällt ein zusätzliches Emoji auf 0, verschwindet sein Button wieder, und der Platz wird frei. `😂` bleibt immer.
- Persistente View (`custom_id` mit Quote-ID), funktioniert auch nach einem Neustart.
- Neue Tabelle `quote_reactions (guild_id, quote_id, user_id, emoji)`, neue Spalte `quotes.post_message_id`, damit Baxi den Post später findet und die Zähler aktualisieren kann.
- Alte Zitate: Ihr Post im Kanal ist nicht gespeichert, deshalb bekommen sie keine Buttons. Bei der Abstimmung zum Zitat des Jahres sind sie trotzdem dabei.
- Die Zähler auf dem Post werden höchstens alle paar Sekunden aktualisiert (Rate Limits).

## 2. Mod-Queue für Grenzfälle im Chatfilter

- Neuer Typ `chatfilter_borderline` in der bestehenden `mod_review_queue`. Grenzfall = Score knapp unter der Löschschwelle der eingestellten Stufe (low/medium/high, `pipeline.py`).
- **Die Nachricht bleibt stehen** (Variante a). Der User merkt nichts.
- **Meldung im Staff-Kanal:** ein Embed „Neuer Fall in der Mod-Queue“ mit Kanal und Auszug der Nachricht, dazu ein Button **„Mod-Queue öffnen“**, der auf die Dashboard-Sektion `#mod_review` des Servers verlinkt.
  - Damit der Kanal nicht zugespammt wird: **eine** Sammelmeldung („3 offene Fälle“), die Baxi aktualisiert, statt einer Nachricht pro Fall. Neu gesendet wird sie erst, wenn die Queue zwischendurch leer war.
- Im Dashboard stehen die Buttons **OK** / **Löschen** / **Löschen + Warn**. Jede Entscheidung ist gleichzeitig ein Label für den SafeText-Trainingsloop.
- Entscheidet nach 24 h niemand, läuft der Fall ab: keine Aktion, kein Label.

## 3. Leveling: ein Rang, zwei XP-Quellen

- **Ein Level / Rang.** Er steigt durch Text-XP **und** Voice-XP zusammen: `level = f(text_xp + voice_xp)`.
- Beide XP-Werte werden **getrennt gespeichert und angezeigt**: Rank-Card und `/rank` zeigen, wie viel aus Text und wie viel aus Voice kommt. Rangliste gesamt, optional gefiltert nach Text / Voice.
- Rollen-Belohnungen (`cfg_leveling_reward`) bleiben wie sie sind und hängen am Gesamt-Level.
- **Rank-Card als PNG** im Kartenmuster von `mc_link_card.py`: Avatar, Level, Fortschrittsbalken, Anteil Text/Voice.

### Farming verhindern
- **Text:** Heute gibt es **keinen Cooldown**, und lange Nachrichten geben 50 XP. Wer spammt, levelt also schnell. Neu: XP höchstens einmal pro 60 s pro User. Nachrichten, die Anti-Spam oder Chatfilter treffen, geben keine XP.
- **Voice:** 5 XP pro voller Minute, nur wenn
  - der User nicht taub geschaltet ist (selbst oder vom Server; nur stumm geschaltet ist okay, viele hören nur zu),
  - mindestens **ein weiterer echter Mensch** im Kanal ist, der selbst nicht taub geschaltet ist,
  - der Kanal nicht der AFK-Kanal ist.
- **Kein Tageslimit** (entschieden). Bewusst in Kauf genommen: Zwei Leute, die nicht taub geschaltet über Nacht im Kanal bleiben, sammeln weiter XP.
- Voice-XP wird im bestehenden 5-Minuten-Reconcile von `voice_activity.py` gutgeschrieben, ohne eigenen Task. Die Zeitmessung für Insights bleibt davon unberührt.

### Speichern und Laden
- Heute lädt und speichert `process_xp` **bei jeder Nachricht alle User des Servers** (`load_data("leveling_users")` → `save_data`). Neu: einzelne Zeilen per `SELECT`/`UPSERT` auf `leveling_users`, Index auf `(guild_id, total_xp)` für die Rangliste.
- Migration: bisheriges `xp` → `text_xp`, `voice_xp` = 0. Kein rückwirkendes Voice-XP aus `voice_by_day`, weil die Farming-Regeln für die alten Daten nicht prüfbar sind. Das Level kann dadurch nicht sinken.

## 4. Geburtstage

- **Das Datum gehört dem User:** nur Tag und Monat, ohne Jahr, einmal gespeichert für alle Server (`user_birthdays`).
- **Der Server entscheidet über die Anzeige:** Feature an/aus, Kanal, Nachrichtentext (mit Variablen-Picker), optionale Geburtstags-Rolle für 24 h, Zeitzone (Standard Europe/Vienna).
- Der User kann den Geburtstag **pro Server ausblenden**.
- Befehle: `/birthday set` (Modal mit Tag + Monat), `/birthday remove`, `/birthday hide` (auf diesem Server), `/birthday upcoming` (nächste Geburtstage auf diesem Server).
- 29. Februar → in Nicht-Schaltjahren am 28. Februar.
- Ruhemodus-konform: Der Task fragt nur Server mit aktivem Feature ab und nur die User, die heute dran sind. Die Rolle läuft über das bestehende System für zeitlich begrenzte Aktionen ab.
- `privacy.html` ergänzen: welche Daten gespeichert werden und wie man sie löscht.

## 5. Moderation: Fälle, Fallakte, Notizen, Einsprüche, Statistik

Grundlage für alles: **Fallnummern.** Jede Mod-Aktion (Warn, Mute, Kick, Ban, Löschung durch den Chatfilter) bekommt eine fortlaufende Nummer pro Server (`#123`). Sie steht in der DM an den User, im Log und in der Fallakte. Basis ist `mod_events.pos`.

- **Fallakte** pro User und Server: `/case @user` (nur für Staff sichtbar) und dieselbe Ansicht im Dashboard. Eine Zeitleiste, neueste zuerst: Fälle, Treffer im Chatfilter, Notizen, Einsprüche. Darüber eine Zeile Zusammenfassung („3 Warns, 1 Mute, letzte Aktion vor 12 Tagen“). Trust Score nur, wenn Prism aktiv ist.
- **Mod-Notizen:** über das Kontextmenü (Rechtsklick auf User → Apps → „Notiz hinzufügen“, mit Modal) oder `/note`. Für den User nie sichtbar.
- **Einsprüche:**
  - In der DM nach einer Aktion steht ein Button **„Einspruch einlegen“** → Modal mit einem Textfeld.
  - Dazu eine Einspruchsseite im Dashboard (Discord-Login) für alle, die die DM nicht bekommen haben.
  - **Für alle Aktionen** (Warn, Mute, Kick, Ban, Löschung durch den Chatfilter), immer gleich: Button → Modal → Queue.
  - Ein Einspruch pro Fall, möglich bis 14 Tage nach der Aktion. Er landet in der Mod-Queue (Typ `appeal`) und erscheint in der Sammelmeldung im Staff-Kanal.
  - Ein erfolgreicher Einspruch gegen eine Löschung durch den Chatfilter wird zusätzlich als Fehlalarm-Label an den SafeText-Trainingsloop gegeben.
  - Staff entscheidet „Aufheben“ oder „Bleibt“. Der User bekommt das Ergebnis per DM. Bei „Aufheben“ macht Baxi die Aktion rückgängig (Unban, Unmute, Warn entfernen).
- **Statistik** (Dashboard): Aktionen pro Mod in den letzten 30 Tagen, mittlere Bearbeitungszeit in der Queue, offene Einsprüche. Bewusst **ohne Rangliste**: Moderation soll kein Wettbewerb um die meisten Bans werden.

## 6. Server Wrapped 2026

- **Läuft automatisch auf allen Servern**, kein Einschalten nötig.
- **Server-Rückblick:** Baxi schickt ihn zuerst in den **Staff-Kanal**, als Vorschau mit Button **„Teilen“**.
  - „Teilen“ (nur mit „Server verwalten“) → Kanal-Auswahl → Baxi sendet eine öffentliche Version dorthin.
  - Ohne Staff-Kanal geht die Vorschau per DM an den Server-Owner.
- **Persönliches Wrapped** per `/wrapped` (nur für den User sichtbar), ab dem Release für alle.
- Mehrere Karten zum Durchklicken (Weiter-Button).
- Karten: Nachrichten und Voice-Stunden, aktivster Tag und aktivste Stunde, Mitgliederwachstum, Top-Schreiber und Top in Voice, **Nachricht des Jahres** (meiste Sterne im Starboard), **Zitat des Jahres** (Abstimmung), meistzitierte Person.
- Zitat des Jahres: Abstimmung Anfang Dezember über das Poll-System. Kandidaten: die Zitate mit den meisten Reactions (Punkt 1) bzw. ein zufälliger Ausschnitt, wenn es noch keine gibt.
- Fehlt eine Quelle (kein Starboard, keine Zitate), wird die Karte weggelassen.
- Alles Veröffentlichte läuft durch `text_is_clean`. User, die nicht namentlich in Top-Listen auftauchen wollen, können das abschalten.

---

## Vorgeschlagene Reihenfolge

| # | Feature | Warum hier |
|---|---|---|
| 1 | Zitat-Reactions | Klein. Muss früh laufen, damit bis Dezember Reactions zusammenkommen. |
| 2 | Mod-Queue + Staff-Kanal | Klein. Der Staff-Kanal wird später für die Einsprüche gebraucht. |
| 3 | Leveling-Umbau | Mittel. Unabhängig von den anderen. |
| 4 | Server Wrapped | Fester Termin: Bau bis ca. 30.11., Abstimmung 1.–7.12., Release ca. 15.12. |
| 5 | Geburtstage | Klein, kein Termin. |
| 6 | Fälle, Fallakte, Notizen, Einsprüche, Statistik | Größter Brocken. Lieber in Ruhe nach dem Wrapped. |

## Entschieden (01.11.)

1. Zitat-Reactions: Standard `😂`, plus `+` mit Dropdown, höchstens 4 verschiedene Emojis.
2. Voice-XP: kein Tageslimit.
3. Wrapped: automatisch auf allen Servern, Vorschau im Staff-Kanal mit „Teilen“.
4. Einsprüche: für alle Aktionen.
5. Voice-XP: 5 XP pro voller Minute (300 XP/h, etwa ein Viertel von Dauerschreiben mit Cooldown).
6. `+`-Dropdown: feste Auswahl an Standard-Emojis, keine Custom-Emojis des Servers.
