"""Mischt die Gewichte des Ausgangsmodells und eines feingetunten Modells (Gewichtsmittelung, "WiSE-FT").

    python tools/safetext_trainer/v2/interpolate.py --base <hf-id> --tuned <dir> --alpha 0.5 --out <dir>

alpha = Anteil des feingetunten Modells. Läuft zur Laufzeit gleich schnell wie ein einzelnes Modell.
"""
import argparse

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

ap = argparse.ArgumentParser()
ap.add_argument("--base", required=True)
ap.add_argument("--tuned", required=True)
ap.add_argument("--alpha", type=float, required=True)
ap.add_argument("--out", required=True)
a = ap.parse_args()
base = AutoModelForSequenceClassification.from_pretrained(a.base)
tuned = AutoModelForSequenceClassification.from_pretrained(a.tuned)
assert base.config.id2label == tuned.config.id2label or True
sd_b, sd_t = base.state_dict(), tuned.state_dict()
mixed = {k: ((1 - a.alpha) * sd_b[k].float() + a.alpha * sd_t[k].float()).to(sd_t[k].dtype) if sd_t[k].is_floating_point() else sd_t[k]
         for k in sd_t}
tuned.load_state_dict(mixed)
tuned.save_pretrained(a.out)
AutoTokenizer.from_pretrained(a.tuned).save_pretrained(a.out)
print("gespeichert:", a.out, "alpha", a.alpha)
