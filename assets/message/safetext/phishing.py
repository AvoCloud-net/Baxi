"""Phishing / scam link detection.

Three checks per link:
  1. blocklist   - the domain *or any parent domain* is on the phishing list
                   (catches "login.steam-scam.com" when "steam-scam.com" is listed)
  2. spoof       - IDN/homoglyph domain that renders like an official one
                   ("dіscord.com" with a Cyrillic і, punycode "xn--...")
  3. typosquat   - one edit away from an official brand ("dlscord.gift",
                   "steamcomunity.com"), which is how new Nitro/Steam scams look
                   before they reach any blocklist
"""
from __future__ import annotations

import re
from typing import Optional

from assets.message.safetext.normalize import clean
from assets.share import phishing_url_list

_URL = re.compile(
    r"https?://([^\s/<>\"')\]]+)"
    # Bare domains; unicode letters allowed so homoglyph hosts ("dіscord.com") are seen.
    r"|(?<![.\w@])((?:[^\W_](?:[\w\-]{0,61}[^\W_])?\.)+[^\W\d_]{2,})(?![.\w])",
    re.IGNORECASE,
)

OFFICIAL_DOMAINS = {
    "discord.com", "discord.gg", "discordapp.com", "discordapp.net", "discord.media",
    "discord.gift", "discordstatus.com", "steamcommunity.com", "steampowered.com",
    "steamstatic.com", "store.steampowered.com", "twitch.tv", "youtube.com",
    "epicgames.com", "roblox.com", "paypal.com",
}
# Second-level labels that scams imitate, plus legitimate look-alikes to ignore.
_BRANDS = {"discord", "discordapp", "steamcommunity", "steampowered", "roblox", "epicgames"}
_LEGIT_LOOKALIKES = {"discords", "disboard", "discordbee", "discordapps"}


def _domains(text: str) -> list[str]:
    out = []
    for m in _URL.finditer(text):
        host = (m.group(1) or m.group(2) or "").lower()
        host = host.split("/")[0].split(":")[0].split("@")[-1].strip(".")
        host = host.removeprefix("www.")
        if "." in host:
            out.append(host)
    return out


def _parents(domain: str) -> list[str]:
    parts = domain.split(".")
    return [".".join(parts[i:]) for i in range(len(parts) - 1)]


def _registrable_label(domain: str) -> str:
    parts = domain.split(".")
    return parts[-2] if len(parts) >= 2 else parts[0]


def _damerau1(a: str, b: str) -> bool:
    """True if a and b differ by exactly one edit (incl. one transposition)."""
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        diff = [i for i in range(len(a)) if a[i] != b[i]]
        if len(diff) == 1:
            return True
        return (len(diff) == 2 and diff[1] == diff[0] + 1
                and a[diff[0]] == b[diff[1]] and a[diff[1]] == b[diff[0]])
    short, long_ = (a, b) if len(a) < len(b) else (b, a)
    for i in range(len(long_)):
        if long_[:i] + long_[i + 1:] == short:
            return True
    return False


def _decode_idn(domain: str) -> str:
    try:
        return domain.encode("ascii").decode("idna") if "xn--" in domain else domain
    except UnicodeError:
        return domain


def check(text: str) -> Optional[dict]:
    """Return {kind, domain} for the first suspicious link, else None."""
    for domain in _domains(text):
        if any(d in phishing_url_list for d in _parents(domain)):
            return {"kind": "blocklist", "domain": domain}

        if any(d in OFFICIAL_DOMAINS for d in _parents(domain)):
            continue

        # Non-ASCII / punycode host that folds to an official domain.
        unicode_host = _decode_idn(domain)
        if not unicode_host.isascii():
            folded = clean(unicode_host).lower()
            if any(d in OFFICIAL_DOMAINS for d in _parents(folded)) or \
                    _registrable_label(folded) in _BRANDS:
                return {"kind": "spoof", "domain": domain}

        label = _registrable_label(domain)
        if label not in _LEGIT_LOOKALIKES and len(label) >= 6 and \
                any(_damerau1(label, brand) for brand in _BRANDS):
            return {"kind": "typosquat", "domain": domain}
    return None
