"""Doxxing detection: email, phone, IBAN, credit card, postal address.

Every detector validates its match, because false positives here delete normal
messages:
  * IBAN        - country length + ISO 7064 mod-97 checksum
  * credit card - issuer prefix + Luhn; Discord IDs (17-20 digit runs) are skipped
  * phone       - must start with +, 00 or 0 and have 9-15 digits
  * address     - street + number only counts with a postal code + town after it
  * email       - role/service addresses (support@, info@, noreply@ ...) are ignored
URLs and Discord mention tokens are stripped first so IDs inside them never match.
"""
import re
from typing import Optional

from assets.message.safetext.normalize import strip_noise

_EMAIL_RE = re.compile(r"\b([A-Za-z0-9._%+\-]+)@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
_ROLE_MAILBOXES = {
    "support", "info", "contact", "kontakt", "admin", "noreply", "no-reply", "help",
    "hello", "hallo", "office", "service", "team", "sales", "abuse", "privacy",
    "legal", "press", "presse", "security", "billing", "jobs", "mail", "webmaster",
    "postmaster", "datenschutz", "hilfe",
}

_PHONE_RE = re.compile(
    r"(?<![\w+])(?:\+|00)\d[\d \-/().]{7,20}\d(?!\d)"   # international
    r"|(?<![\w.])0\d{2,5}[ \-/]?\d[\d \-/]{4,14}\d(?![\d.])"  # national, leading 0
)

_IBAN_RE = re.compile(r"\b([A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,7}(?:[ ]?[A-Z0-9]{1,4})?)\b")
_IBAN_LENGTHS = {
    "AT": 20, "BE": 16, "CH": 21, "CZ": 24, "DE": 22, "DK": 18, "ES": 24, "FI": 18,
    "FR": 27, "GB": 22, "HR": 21, "HU": 28, "IE": 22, "IT": 27, "LI": 21, "LU": 20,
    "NL": 18, "NO": 15, "PL": 28, "PT": 25, "SE": 24, "SI": 19, "SK": 24,
}

_CC_RE = re.compile(r"(?<!\d)(?:\d[ \-]?){12,18}\d(?!\d)")
_CC_PREFIX = re.compile(r"^(?:4|5[1-5]|2[2-7]|3[47]|6011|65|35)")

_STREET_RE = re.compile(
    r"\b[A-ZÄÖÜ][a-zäöüß\-]{2,}(?:straße|strasse|str\.|weg|gasse|platz|allee|ring|damm)"
    r"\s+\d{1,4}[a-z]?\b[^\n]{0,40}?\b\d{4,5}\s+[A-ZÄÖÜ][a-zäöüß]+",
)


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def _iban_valid(raw: str) -> bool:
    iban = raw.replace(" ", "")
    expected = _IBAN_LENGTHS.get(iban[:2])
    if expected is not None and len(iban) != expected:
        return False
    if not 15 <= len(iban) <= 34:
        return False
    rearranged = iban[4:] + iban[:4]
    numeric = "".join(str(int(c, 36)) for c in rearranged)
    return int(numeric) % 97 == 1


def _luhn_valid(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def _is_card(match: str) -> bool:
    digits = _digits(match)
    if not 13 <= len(digits) <= 19:
        return False
    if match.isdigit() and len(digits) >= 17:
        return False  # contiguous 17+ digits = Discord snowflake, not a card
    return bool(_CC_PREFIX.match(digits)) and _luhn_valid(digits)


def detect(text: str) -> Optional[dict]:
    """Return {kind, match} on first hit, else None."""
    text = strip_noise(text)

    for m in _EMAIL_RE.finditer(text):
        if m.group(1).lower() not in _ROLE_MAILBOXES:
            return {"kind": "email", "match": m.group(0)}

    for m in _IBAN_RE.finditer(text):
        if _iban_valid(m.group(1)):
            return {"kind": "iban", "match": m.group(0)}

    if m := _STREET_RE.search(text):
        return {"kind": "address", "match": m.group(0)}

    for m in _CC_RE.finditer(text):
        if _is_card(m.group(0)):
            return {"kind": "credit_card", "match": m.group(0)}

    for m in _PHONE_RE.finditer(text):
        if 9 <= len(_digits(m.group(0))) <= 15:
            return {"kind": "phone", "match": m.group(0)}

    return None
