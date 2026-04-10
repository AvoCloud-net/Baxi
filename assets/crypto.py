"""Symmetric encryption helpers for sensitive values stored at rest.

Uses Fernet (AES-128-CBC + HMAC-SHA256) from the `cryptography` library.
The master key lives in `config/auth.py` (Donations.master_key) and must
NEVER be changed once credentials have been saved — doing so would render
all previously encrypted values unreadable.

Storage format: encrypted values are stored with a literal `enc:` prefix,
so plaintext values (from older installs or manual edits) can still be
read back until the next save upgrades them to encrypted form.
"""

from cryptography.fernet import Fernet, InvalidToken

import config.auth as _auth

_ENC_PREFIX = "enc:"
_PLACEHOLDER_KEY = "GENERATE-A-FERNET-KEY"
_fernet: Fernet | None = None


def _get_fernet() -> Fernet | None:
    """Return the cached Fernet instance, or None if no key is configured."""
    global _fernet
    if _fernet is not None:
        return _fernet
    key = getattr(_auth.Donations, "master_key", "") or ""
    if not key or key == _PLACEHOLDER_KEY:
        return None
    try:
        _fernet = Fernet(key.encode() if isinstance(key, str) else key)
    except Exception as e:
        print(f"[crypto] Invalid Donations.master_key: {e}")
        return None
    return _fernet


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a plaintext secret. Returns `enc:<ciphertext>`.

    If no master key is configured, the value is returned unchanged as a
    safety fallback for development — a warning is printed so the operator
    knows secrets are not being encrypted.
    """
    if not plaintext:
        return ""
    f = _get_fernet()
    if f is None:
        print("[crypto] WARNING: Donations.master_key not configured — storing secret as plaintext.")
        return plaintext
    token = f.encrypt(plaintext.encode("utf-8")).decode("ascii")
    return _ENC_PREFIX + token


def decrypt_secret(value: str) -> str:
    """Decrypt a stored secret. Accepts both `enc:...` and legacy plaintext values."""
    if not value:
        return ""
    if not value.startswith(_ENC_PREFIX):
        # Legacy plaintext — return as-is. Will be re-encrypted on next save.
        return value
    f = _get_fernet()
    if f is None:
        print("[crypto] WARNING: Donations.master_key not configured — cannot decrypt stored secret.")
        return ""
    token = value[len(_ENC_PREFIX):]
    try:
        return f.decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken:
        print("[crypto] ERROR: Fernet token invalid — wrong master_key or corrupted value.")
        return ""
