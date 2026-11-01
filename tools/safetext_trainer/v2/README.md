# SafeText Klassifikator v2 (Experiment vom 16.10.2026)

Ziel: Drohungen und Gruppenhass ohne Stichwort besser erkennen, ohne mehr Fehlsperren. Sprachen: nur Deutsch und Englisch.
Aufgabe des Modells bleibt: Wahrscheinlichkeit "ein Moderator würde entfernen" (1) gegen "harmlos" (0). Die Pipeline
(Regeln, Kontext, Adressat, Gegenprobe, Schwellen) ist unverändert, nur das Modell wird getauscht
(`SAFETEXT_MODEL=<ordner>`).

## Vorgehen

1. `build_mix.py`: Trainingsgemisch aus öffentlichen Daten.
2. `augment.py`: Vorlagen für implizite Drohungen und Gruppenhass plus harmlose Gegenstücke (Besuch, Spielgewalt,
   Gegenrede, Neckerei, neutrale Gruppennennung).
3. `train_v2.py`: Feintuning ab `textdetox/xlmr-large-toxicity-classifier` (3 Epochen, AdamW, Lernrate 2e-5, Batch 16, Seed 42).
4. `interpolate.py`: Gewichte von Ausgangsmodell und Feintuning mischen (alpha = Anteil neu). Laufzeit und Speicher bleiben gleich.
5. `grid_eval.py`: Auswertung durch die komplette Pipeline (Sensitivity medium) auf acht Testsets.
6. `package_version.py`: Paket mit Prüfsummen-Manifest im Format der Modellverwaltung. Nichts wird hochgeladen oder aktiviert.

## Daten (nur Deutsch und Englisch)

| Quelle | Sprache | Lizenz | Verwendung |
|---|---|---|---|
| GermEval 2018 Train | de | CC BY 4.0 | 4007 Train, 1002 Val. "PROFANITY" ohne Adressat gilt als harmlos |
| Jigsaw Toxic Comments (Kaggle-Spiegel Heliosoph) | en | CC0 laut Spiegel, Text aus Wikipedia (CC BY-SA 3.0) | Drohung, Identitätshass, schwere Beleidigung, Beleidigung; harmlos; reines Fluchen als harmlos |
| Measuring Hate Speech (UC Berkeley D-Lab) | en | CC BY 4.0 | Score > 0,5 hasserfüllt; Score < -1 harmlos, davon 1500 mit Gruppennennung |
| Maschinelle Übersetzung ins Deutsche (Helsinki-NLP/opus-mt-en-de, CC BY 4.0) | de | s. o. | 5397 Trainingsbeispiele aus den englischen Quellen; die Übersetzungen sind teils holprig und die Labels verrauscht |
| Vorlagen (`augment.py`, selbst geschrieben) | de, en | eigene | ca. 2470 Beispiele |

Nicht zum Training benutzt: HateCheck (Test), GermEval 2021 (Lizenz der Originaldaten unklar, Test), `holdout_v2.jsonl`
(eingefroren, SHA-256 in `eval/holdout_v2.sha256`), `discord.jsonl` (früher zur Kalibrierung genutzt).
HASOC wurde nicht benutzt (nicht kommerziell). Das Jigsaw-Paket liegt bei Kaggle hinter Wettbewerbsregeln: Lizenz vor einem
öffentlichen Release des Modells noch einmal prüfen.

## Ergebnisse (Pipeline, Sensitivity medium; Recall / Fehlsperren in Prozent)

| Testset (n) | Alt (Basismodell, mit Lexikon-Änderung) | A: Feintuning ohne Vorlagen | A2: mit Vorlagen | **Mix 0,7** | Mix 0,5 |
|---|---|---|---|---|---|
| holdout_v2 (90, frisch geschrieben) | 45,7 / 2,3 | 56,5 / 6,8 | 82,6 / 2,3 | **73,9 / 2,3** | 67,4 / 2,3 |
| HateCheck DE (3580) | 48,7 / 10,4 | 53,3 / 11,1 | 53,4 / 10,9 | **56,6 / 10,4** | 56,2 / 11,1 |
| HateCheck EN (3666) | 56,2 / 8,6 | 50,6 / 8,6 | 51,7 / 8,0 | **54,1 / 8,7** | 55,5 / 8,8 |
| Synthetisch Discord (160) | 73,5 / 3,3 | 72,1 / 2,2 | 76,5 / 3,3 | **73,5 / 2,2** | 72,1 / 2,2 |
| GermEval 2018 Test (3532) | 11,0 / 2,4 | 11,1 / 1,5 | 10,5 / 1,7 | **11,2 / 1,8** | 11,5 / 1,6 |
| GermEval 2021 Test (942) | 3,1 / 1,9 | 2,0 / 0,8 | 2,3 / 1,0 | **2,0 / 1,2** | 2,3 / 1,2 |
| Fairness, harmlos (282) | - / 1,4 | - / 0,4 | - / 0,7 | **- / 1,1** | - / 1,8 |
| discord.jsonl (309, Kalibrierset) | 99,0 / 0,0 | 100 / 0,0 | 100 / 0,0 | **100 / 0,0** | 100 / 0,0 |

Rohdaten: `results/*.json`. Je HateCheck-Funktion (Drohung, Beleidigung ...) enthalten sie die Aufschlüsselung.

**Gewählt: Mix 0,7** (`SAFETEXT_MODEL` = gemischtes Modell). Begründung: Beste Recall-Werte auf HateCheck DE bei gleichen
Fehlsperren, auf Englisch nur 2 Punkte unter dem Alt-Modell, Fehlsperren auf GermEval und Fairness nicht höher.
Deutsche Drohungen (HateCheck `threat_dir_h` 47 % auf 68 %, `threat_norm_h` 40 % auf 58 %) deutlich besser.

## Einschränkungen (bitte lesen)

* **holdout_v2 ist nicht vollständig unabhängig.** Ich habe das Testset geschrieben, bevor ich Trainingsdaten sah, aber
  die Vorlagen danach, mit Kenntnis des Testsets. Die Sprünge dort (46 % auf 74 bis 83 %) überzeichnen den echten Gewinn.
  Belastbarer sind HateCheck (nie im Training), GermEval und der Fairness-Test.
* **Englisch wird nicht besser, eher leicht schlechter** (HateCheck EN: derogierende Aussagen, Zeichen-Tausch, Drohungen
  gegen Gruppen). Das ungemischte Feintuning (A2) verliert dort 4 bis 5 Punkte, die Mischung 2 Punkte.
* **Auf GermEval ändert sich der Recall nicht** (11 %), weil die Pipeline weiter nur klare Verstöße entfernt.
* **Noch offen:** Implizite Drohungen ohne Bezug zu Gewalt ("Schlaf besser nicht ein, wir kommen heute Nacht vorbei"),
  entmenschlichende Aussagen ohne Reizwort, Neckerei im Dialekt ("du Spinner" mit Emoji) werden teils noch falsch behandelt.
* Fehlsperren in den Aufschlüsselungen haben große Konfidenzintervalle (n=282 und n=90).
* Modellgewichte sind unter OpenRAIL++ (Basismodell) und den Datenlizenzen oben zu betrachten.
* Aktiviert ist nichts. Vor einem Einsatz: Paket hochladen, in der Admin-Oberfläche prüfen, durch einen Menschen bestätigen.
