# SafeText Trainer

Trainiert das Chatfilter-Modell auf einem Rechner mit GPU (z. B. RTX 4060) mit den
Labels, die Bot-Admins im Admin-Panel vergeben haben, und lädt es nach deiner
Bestätigung auf den Baxi-Server. Der Bot-Server selbst trainiert nie – das neue
Modell ist gleich groß und gleich schnell wie das alte.

## Ablauf

1. **Server:** Server mit Opt-in („Help improve the filter“ im Dashboard) liefern
   auffällige Nachrichten anonymisiert in die Queue (`data/safetext/samples.jsonl`).
2. **Admin-Panel → SafeText → Training Queue:** Samples labeln
   (`S` okay · `1`–`5` Kategorie · `D` verwerfen · `Leertaste` überspringen).
3. **Laptop:** `python tools/safetext_trainer/train.py`
   - lädt Samples + Labels herunter
   - trainiert (LoRA auf dem Basis-Modell, ~10–40 Min je nach Datenmenge)
   - misst Basis-Modell und neues Modell über die komplette Filter-Pipeline:
     HateCheck DE/EN, Discord-Testsatz, eure zurückgehaltenen Labels
   - zeigt die Tabelle „erkannt / falsch gelöscht“ und geänderte Entscheidungen
   - lädt **nur nach deiner Bestätigung** hoch – und nur, wenn das neue Modell
     nirgends schlechter ist (`--force` überstimmt das)
4. **Server:** Der Bot prüft die Prüfsummen und wechselt innerhalb einer Minute.
   Rollback: Admin-Panel → SafeText → Model Versions → *Activate* / *Use base model*.

## Einrichtung (einmalig)

```bash
python -m venv .venv-trainer
source .venv-trainer/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cu124
pip install -r tools/safetext_trainer/requirements.txt
cp tools/safetext_trainer/config.example.toml tools/safetext_trainer/config.toml
# config.toml ausfüllen: Server, Benutzer, remote_dir = Pfad zu data/safetext
```

Verbindung: `sftp` (empfohlen) oder `ftps`. Unverschlüsseltes `ftp` ist gesperrt,
außer du setzt `allow_insecure_ftp = true` – die Samples sind Chat-Nachrichten.
Das Passwort wird beim Start abgefragt, wenn es weder in der Config noch in
`BAXI_TRAINER_PASSWORD` steht.

## Wichtig

- Es wird immer vom Basis-Modell aus auf **allen** Labels trainiert – Fehler
  summieren sich nicht über Versionen, jede Version ist reproduzierbar.
- Jedes 5. Label (fest nach Nachrichtentext) wird nie trainiert, sondern nur
  zum Testen genutzt. Aussagekräftig ab ~30 Test-Labels.
- Unter 50 Trainings-Labels bricht das Skript ab – vorher lohnt es sich nicht.
- Der Discord-Testsatz liegt in `eval/discord.jsonl` (`keep` = muss stehen
  bleiben, `remove` = muss gelöscht werden). Neue Fälle dort ergänzen, wenn der
  Filter etwas falsch macht – aber nie Fälle, auf denen trainiert wird.
- Arbeitsdaten (Downloads, Kandidaten, je ~2 GB) liegen in `~/.cache/baxi-safetext-trainer`
  – bewusst außerhalb des Repos, damit Nextcloud keine Modelle synchronisiert (`--work` ändert das).
- Test ohne Server: `--local <ordner>` mit einer Kopie von `data/safetext`.
