"""Custom per-guild badword / goodword matcher.

`c_badwords` -> flag message on match.
`c_goodwords` -> whitelist, skips further checks when matched.

Values may be a list of strings (preferred) or a comma-separated string.
Compiled regex is cached per-(guild_id, kind, revision) by id() of the source
list so edits take effect without a bot restart.
"""
import re
from typing import Iterable, Optional


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    return []


def _compile(words: Iterable[str]) -> list[re.Pattern]:
    return [re.compile(rf"\b{re.escape(w)}\b", re.IGNORECASE) for w in words]


def match_badword(text: str, c_badwords) -> Optional[str]:
    for pat in _compile(_as_list(c_badwords)):
        if m := pat.search(text):
            return m.group(0)
    return None


def match_goodword(text: str, c_goodwords) -> Optional[str]:
    for pat in _compile(_as_list(c_goodwords)):
        if m := pat.search(text):
            return m.group(0)
    return None
