"""Server-specific settings come from the environment / a `.env` file.

`.env` lives in the project root (next to main.py), NOT inside config/, so the config
folder can be copied over to the server on every update without touching secrets, channel
ids or URLs. Real environment variables win over the file. A missing value falls back to
the harmless default given in config/auth.py / config/config.py.
"""
import os
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def _load() -> None:
    if not ENV_FILE.is_file():
        return
    for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key.strip().removeprefix("export "), value)


_load()


def get(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def get_int(name: str, default: int = 0) -> int:
    try:
        return int(os.environ.get(name, "").strip())
    except ValueError:
        return default
