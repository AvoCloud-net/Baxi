"""Doxxing detection via regex: email, phone, IBAN, credit card, street address.

Conservative thresholds: only flag high-confidence matches to avoid false
positives on ordinary numeric content.
"""
import re
from typing import Optional

# Email
_EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"
)

# Phone: +49 170 1234567, 0170-1234567, (030) 12345678, etc. Min 9 digits total.
_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?\d{1,3}[\s\-\.]?)?(?:\(?\d{2,5}\)?[\s\-\.]?)?\d{3,5}[\s\-\.]?\d{3,6}(?!\d)"
)

# IBAN: DE89 3704 0044 0532 0130 00 etc. (country code + check + 11-30 alphanum)
_IBAN_RE = re.compile(
    r"\b[A-Z]{2}\d{2}(?:[ \-]?[A-Z0-9]{4}){3,7}(?:[ \-]?[A-Z0-9]{1,4})?\b"
)

# Credit card (Visa/MC/Amex rough) — 13-19 digits in 4-digit groups
_CC_RE = re.compile(
    r"\b(?:\d[ \-]?){13,19}\b"
)

# German-style street address: "Straßename 12" / "Musterweg 1a"
_STREET_RE = re.compile(
    r"\b[A-ZÄÖÜ][a-zäöüß\-]{2,}(?:straße|strasse|weg|gasse|platz|allee|ring)\s+\d{1,4}[a-z]?\b",
    re.IGNORECASE,
)


def _phone_has_enough_digits(match: str) -> bool:
    digits = re.sub(r"\D", "", match)
    return 9 <= len(digits) <= 15


def _luhn_valid(digits: str) -> bool:
    digits = re.sub(r"\D", "", digits)
    if not (13 <= len(digits) <= 19):
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def detect(text: str) -> Optional[dict]:
    """Return {kind, match} on first hit, else None."""
    if m := _EMAIL_RE.search(text):
        return {"kind": "email", "match": m.group(0)}

    if m := _IBAN_RE.search(text):
        return {"kind": "iban", "match": m.group(0)}

    if m := _STREET_RE.search(text):
        return {"kind": "address", "match": m.group(0)}

    for m in _CC_RE.finditer(text):
        if _luhn_valid(m.group(0)):
            return {"kind": "credit_card", "match": m.group(0)}

    for m in _PHONE_RE.finditer(text):
        if _phone_has_enough_digits(m.group(0)):
            return {"kind": "phone", "match": m.group(0)}

    return None
