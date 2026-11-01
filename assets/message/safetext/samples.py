"""Training-sample queue for the chatfilter (opt-in per guild).

Guilds that enable "help improve the filter" contribute messages where the
model score actually mattered: removed ones, messages the context stage excused, and high-scoring messages that address someone or
name a group (the model's decisions there are the ones worth correcting).
Untargeted cursing and ordinary chat are not collected - the rules decide those.
Messages about the author's own self-harm are never collected (health data).
At most MAX_PER_GUILD_DAY samples per guild and day.

Privacy:
  * no user id / name is stored - only the text, the filter's verdict and the
    guild id (so a guild's samples can be deleted when it opts out)
  * mentions, e-mail addresses, phone numbers, IBANs and card numbers are
    replaced with placeholders before storing
  * unlabelled samples are deleted after RETENTION_DAYS; opting out deletes
    all samples of that guild

Bot admins label samples in the admin panel (safe / category 1-5 / discard).
The offline trainer (tools/safetext_trainer) downloads samples.jsonl +
labels.jsonl, trains, evaluates and uploads a new model version.

Files (append-only, pruned by the daily garbage collector):
  data/safetext/samples.jsonl  {id, ts, gid, text, lang, verdict, reason, stage, toxicity}
  data/safetext/labels.jsonl   {id, ts, label, admin}   label: SAFE | 1..5 | DISCARD
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Optional

from reds_simple_logger import Logger

from assets.message.safetext.normalize import normalize

logger = Logger()

SAMPLES_FILE = Path("data/safetext/samples.jsonl")
LABELS_FILE = Path("data/safetext/labels.jsonl")
# Server-mod decisions from the mod queue are only *suggestions*: {id, ts, label}.
# Never downloaded by the trainer and ignored by _labels(); a bot admin confirms them
# in the labelling queue, where the suggestion is shown as a hint.
SUGGESTIONS_FILE = Path("data/safetext/suggestions.jsonl")
RETENTION_DAYS = 30
MAX_UNLABELLED = 20_000
REVIEW_SCORE = 0.50          # model score from which a targeted / group message counts
MAX_PER_GUILD_DAY = 200
LABELS = {"SAFE", "1", "2", "3", "4", "5", "DISCARD"}

_lock = threading.Lock()
_known_keys: set[str] | None = None
_daily: dict[tuple[str, int], int] = {}

_PII = [
    (re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"), "<email>"),
    (re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,7}(?:[ ]?[A-Z0-9]{1,4})?\b"), "<iban>"),
    (re.compile(r"(?<!\d)(?:\d[ \-]?){12,18}\d(?!\d)"), "<number>"),
    (re.compile(r"(?<![\w+])(?:\+|00)?\d[\d \-/().]{7,20}\d(?!\d)"), "<phone>"),
    (re.compile(r"https?://\S+"), "<link>"),
    (re.compile(r"<@[!&]?\d+>|@[\w.\-]{2,32}"), "@user"),
]


def scrub(text: str) -> str:
    """Replace personal data in *text* with placeholders."""
    for pattern, placeholder in _PII:
        text = pattern.sub(placeholder, text)
    return text.strip()


def is_noteworthy(result: dict) -> bool:
    """Did the model score matter for this message (so a human label helps)?"""
    if result.get("support"):
        return False    # someone talking about self-harm: health data, never stored
    if result.get("flagged"):
        return True
    j = result.get("json") or {}
    if j.get("mentions_only"):
        return True     # the context stage excused something - was it right?
    tox = j.get("toxicity")
    scored = isinstance(tox, (int, float)) and tox >= REVIEW_SCORE
    return scored and bool(j.get("targeted") or j.get("group"))


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return out


def _append(path: Path, entry: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _rewrite(path: Path, entries: list[dict]) -> None:
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for e in entries:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    tmp.replace(path)


def record(*, gid: int, text: str, lang: str, result: dict) -> Optional[str]:
    """Store a sample if it is noteworthy and not a duplicate. Returns its id."""
    global _known_keys
    if not text.strip() or not is_noteworthy(result):
        return None
    clean = scrub(text)[:1000]
    if len(clean) < 2:
        return None
    key = normalize(clean).key
    sample_id = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    j = result.get("json") or {}
    entry = {
        "id": sample_id,
        "ts": int(time.time()),
        "gid": str(gid),
        "text": clean,
        "lang": lang,
        "verdict": "unsafe" if result.get("flagged") else ("support" if result.get("support") else "safe"),
        "reason": str(result.get("reason", "")),
        "stage": str(j.get("label") or ""),
        "toxicity": j.get("toxicity", j.get("confidence")),
    }
    return _store(entry, gid)


def record_report(*, gid: int, text: str, lang: str, category: str) -> Optional[str]:
    """Store a user-reported message as a sample (only for opted-in guilds, see caller).

    Skipped for self-harm reports (health data). The category the reporter picked is
    kept as a hint (`stage`) for the labeller; the label itself stays a human decision.
    """
    if category == "selfharm" or not text.strip():
        return None
    clean = scrub(text)[:1000]
    if len(clean) < 2:
        return None
    sample_id = hashlib.sha256(normalize(clean).key.encode("utf-8")).hexdigest()[:16]
    return _store({
        "id": sample_id, "ts": int(time.time()), "gid": str(gid), "text": clean,
        "lang": lang, "verdict": "reported", "reason": "user report",
        "stage": category, "toxicity": None,
    }, gid)


def _store(entry: dict, gid: int) -> Optional[str]:
    global _known_keys
    sample_id = entry["id"]
    day = int(time.time() // 86400)
    try:
        with _lock:
            if _known_keys is None:
                _known_keys = {s["id"] for s in _read_jsonl(SAMPLES_FILE)}
            if sample_id in _known_keys:
                return sample_id
            if _daily.get((str(gid), day), 0) >= MAX_PER_GUILD_DAY:
                return None
            _append(SAMPLES_FILE, entry)
            _known_keys.add(sample_id)
            _daily[(str(gid), day)] = _daily.get((str(gid), day), 0) + 1
            for k in [k for k in _daily if k[1] < day]:
                del _daily[k]
    except OSError as e:
        logger.error(f"SafeText samples | write failed: {e}")
        return None
    return sample_id


def _labels() -> dict[str, dict]:
    """Latest label per sample id."""
    out: dict[str, dict] = {}
    for e in _read_jsonl(LABELS_FILE):
        out[str(e.get("id"))] = e
    return out


def next_unlabelled(skip: set[str] | None = None) -> Optional[dict]:
    """Newest unlabelled sample first, so the queue shows current cases."""
    labels = _labels()
    skip = skip or set()
    for s in reversed(_read_jsonl(SAMPLES_FILE)):
        if s["id"] not in labels and s["id"] not in skip:
            if hint := _suggestions().get(s["id"]):
                s = {**s, "suggested": hint["label"]}   # shown as "suggested by server mods"
            return s
    return None


def _suggestions() -> dict[str, dict]:
    """Latest server-mod suggestion per sample id."""
    return {str(e.get("id")): e for e in _read_jsonl(SUGGESTIONS_FILE)}


def suggest(sample_id: str, value: str) -> bool:
    """Record a server-mod decision as a hint for the bot-admin labeller. Not a label:
    the trainer never sees it; it counts only once a bot admin labels the sample."""
    value = value.strip().upper().removeprefix("AI-")
    if value not in LABELS - {"DISCARD"}:
        return False
    if not any(s["id"] == sample_id for s in _read_jsonl(SAMPLES_FILE)):
        return False
    with _lock:
        _append(SUGGESTIONS_FILE, {"id": sample_id, "ts": int(time.time()), "label": value})
    return True


def label(sample_id: str, value: str, admin: str) -> dict:
    value = value.strip().upper().removeprefix("AI-")
    if value not in LABELS:
        return {"ok": False, "error": f"label must be one of {sorted(LABELS)}"}
    sample = next((s for s in _read_jsonl(SAMPLES_FILE) if s["id"] == sample_id), None)
    if sample is None:
        return {"ok": False, "error": "sample not found"}
    with _lock:
        _append(LABELS_FILE, {"id": sample_id, "ts": int(time.time()), "label": value,
                              "admin": admin})
    return {"ok": True, "sample": sample, "label": value}


def stats() -> dict:
    samples = _read_jsonl(SAMPLES_FILE)
    labels = _labels()
    labelled = [labels[s["id"]] for s in samples if s["id"] in labels]
    counts: dict[str, int] = {}
    for l in labelled:
        counts[l["label"]] = counts.get(l["label"], 0) + 1
    return {
        "total": len(samples),
        "unlabelled": len(samples) - len(labelled),
        "labelled": len(labelled),
        "by_label": counts,
    }


LABEL_NAMES = {"SAFE": "safe", "1": "nsfw", "2": "insult_toxic", "3": "hate",
               "4": "personal_data", "5": "self_harm_incite"}


def export_rows(kind: str) -> list[dict]:
    """Rows for the admin download.

    kind="unlabelled": samples still waiting for a label (for labelling elsewhere).
    kind="labelled":   training set - one row per sample with its newest label,
                       DISCARD left out. `y` is the binary target the trainer uses
                       (0 = okay, 1 = must be removed), `label` the AI-1..5 class.
    Rows carry no guild or user id.
    """
    samples = _read_jsonl(SAMPLES_FILE)
    labels = _labels()
    rows: list[dict] = []
    for s in samples:
        lab = labels.get(s["id"])
        base = {"id": s["id"], "text": s["text"], "lang": s.get("lang", ""),
                "filter_verdict": s.get("verdict", ""), "filter_stage": s.get("stage", ""),
                "toxicity": s.get("toxicity")}
        if kind == "unlabelled":
            if lab is None:
                rows.append(base)
        elif lab is not None and lab["label"] in LABEL_NAMES:
            rows.append({**base, "label": lab["label"], "label_name": LABEL_NAMES[lab["label"]],
                         "y": int(lab["label"] != "SAFE")})
    return rows


def delete_guild(gid: int) -> int:
    """Remove every sample of a guild (opt-out). Returns the number removed."""
    global _known_keys
    with _lock:
        samples = _read_jsonl(SAMPLES_FILE)
        keep = [s for s in samples if s.get("gid") != str(gid)]
        removed = len(samples) - len(keep)
        if removed:
            _rewrite(SAMPLES_FILE, keep)
            _known_keys = None
    if removed:
        logger.info(f"SafeText samples | removed {removed} samples of guild {gid} (opt-out)")
    return removed


def prune() -> int:
    """Drop unlabelled samples older than RETENTION_DAYS and cap the queue size."""
    global _known_keys
    cutoff = time.time() - RETENTION_DAYS * 86400
    with _lock:
        samples = _read_jsonl(SAMPLES_FILE)
        if not samples:
            return 0
        labels = _labels()
        keep = [s for s in samples if s["id"] in labels or s.get("ts", 0) >= cutoff]
        unlabelled = [s for s in keep if s["id"] not in labels]
        if len(unlabelled) > MAX_UNLABELLED:
            drop = {s["id"] for s in unlabelled[:len(unlabelled) - MAX_UNLABELLED]}
            keep = [s for s in keep if s["id"] not in drop]
        removed = len(samples) - len(keep)
        if removed:
            _rewrite(SAMPLES_FILE, keep)
            _known_keys = None
        # suggestions only make sense while their sample waits for a label
        sugg = _read_jsonl(SUGGESTIONS_FILE)
        open_ids = {s["id"] for s in keep if s["id"] not in labels}
        if sugg and any(e.get("id") not in open_ids for e in sugg):
            _rewrite(SUGGESTIONS_FILE, [e for e in sugg if e.get("id") in open_ids])
    return removed


def enabled_for(chatfilter_data: dict) -> bool:
    return bool(chatfilter_data.get("training_opt_in", False)) and \
        os.environ.get("SAFETEXT_COLLECT", "1") != "0"
