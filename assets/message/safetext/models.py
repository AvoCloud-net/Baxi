"""Toxicity classifier: loader + async inference.

Model: textdetox/xlmr-large-toxicity-classifier (XLM-R, 278M parameters, binary
neutral/toxic, F1 de 0.88 / en 0.97). It replaced
unitary/multilingual-toxic-xlm-roberta, which exposes a single "toxic" logit
(so the obscene/hate categories never fired) and missed most German insults.

Runs in fp32 on CPU (~15 ms per message with 4 threads). Dynamic int8
quantisation was measured and rejected: it shifts scores by up to 0.95 on
German insults. Needs ~1 GB RAM (process with torch: ~1.5 GB, measured).

The model scores *toxic language*, not *insults* - "scheiße, verloren" gets the
same score as "du hurensohn". The pipeline combines the score with lexicon
signals (who is addressed, insult severity, profanity masking) to decide.

Stability: the model loads in the background; until it is ready (or if loading
fails - retried every 10 minutes) `toxicity()` returns None and the pipeline
runs on its rules alone instead of queueing messages. Each inference has a
timeout. Long messages are scored in overlapping chunks (max score wins), so
abuse after the first 256 tokens is not cut off.

Versions: fine-tuned versions (built offline by tools/safetext_trainer) live in
data/safetext/models/<version>/ with a manifest.json of SHA-256 hashes.
data/safetext/models/active.json names the version in use; the bot notices a
change within a minute and reloads. A version whose files do not match its
manifest is refused and the previous model keeps running. SAFETEXT_MODEL
overrides everything (path or Hugging Face id).
"""
import asyncio
import hashlib
import json
import os
import threading
import time
from collections import OrderedDict
from pathlib import Path

from reds_simple_logger import Logger

logger = Logger()

BASE_MODEL  = "textdetox/xlmr-large-toxicity-classifier"
TOXIC_MODEL = os.environ.get("SAFETEXT_MODEL", BASE_MODEL)
DEVICE      = os.environ.get("SAFETEXT_DEVICE", "cpu")   # "cuda" for offline evaluation
MODELS_DIR  = Path("data/safetext/models")
ACTIVE_FILE = MODELS_DIR / "active.json"
_ACTIVE_CHECK_EVERY = 60
MAX_LEN     = 256
NUM_THREADS = int(os.environ.get("SAFETEXT_THREADS", "4"))
TIMEOUT     = float(os.environ.get("SAFETEXT_TIMEOUT", "5"))
_RETRY_AFTER = 600
_CACHE_SIZE = 2048
_CHUNK_WORDS, _CHUNK_STEP, _MAX_CHUNKS = 120, 100, 4

_model = None
_tokenizer = None
_toxic_index = 1
_load_lock = threading.Lock()
_infer_lock = threading.Lock()
_loading: asyncio.Task | None = None
_failed_at: float | None = None
_cache: "OrderedDict[str, float]" = OrderedDict()
_loaded_from: str | None = None
_active_mtime: float | None = None
_active_checked_at = 0.0


# ── versions ─────────────────────────────────────────────────────────────────
def read_active() -> dict:
    try:
        return json.loads(ACTIVE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def verify_version(version: str) -> tuple[bool, str]:
    """Check a version folder against its manifest. Returns (ok, reason)."""
    folder = MODELS_DIR / version
    try:
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return False, f"manifest unreadable: {e}"
    for name, digest in manifest.get("files", {}).items():
        f = folder / name
        if not f.is_file():
            return False, f"missing file {name}"
        if _sha256(f) != digest:
            return False, f"checksum mismatch in {name}"
    return True, "ok"


def list_versions() -> list[dict]:
    out = []
    if not MODELS_DIR.exists():
        return out
    for folder in sorted(MODELS_DIR.iterdir(), reverse=True):
        manifest = folder / "manifest.json"
        if folder.is_dir() and not folder.name.endswith(".partial") and manifest.exists():
            try:
                m = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            out.append({"version": folder.name, "created_at": m.get("created_at"),
                        "samples": m.get("samples"), "metrics": m.get("metrics", {})})
    return out


def activate(version: str | None, by: str = "") -> dict:
    """Point active.json at *version* (None = base model). The bot reloads within a minute."""
    if version is not None:
        ok, reason = verify_version(version)
        if not ok:
            return {"ok": False, "error": reason}
    current = read_active()
    data = {"version": version, "previous": current.get("version"),
            "activated_at": int(time.time()), "activated_by": by}
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = ACTIVE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(ACTIVE_FILE)
    return {"ok": True, **data}


def _resolve_source() -> str:
    """Model to load: SAFETEXT_MODEL override, else the verified active version, else base."""
    if "SAFETEXT_MODEL" in os.environ:
        return TOXIC_MODEL
    version = read_active().get("version")
    if version:
        ok, reason = verify_version(version)
        if ok:
            return str(MODELS_DIR / version)
        logger.error(f"SafeText | active version {version} rejected ({reason}) - using base model")
    return BASE_MODEL


def current_source() -> str | None:
    return _loaded_from


def _load() -> None:
    global _model, _tokenizer, _toxic_index, _loaded_from
    if _model is not None:
        return
    with _load_lock:
        if _model is not None:
            return
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        torch.set_num_threads(NUM_THREADS)
        source = _resolve_source()
        logger.working(f"SafeText | loading toxicity model: {source}")
        try:
            tokenizer = AutoTokenizer.from_pretrained(source)
            model = AutoModelForSequenceClassification.from_pretrained(source).eval().to(DEVICE)
        except Exception as e:
            if source == BASE_MODEL or "SAFETEXT_MODEL" in os.environ:
                raise
            logger.error(f"SafeText | loading {source} failed ({e}) - falling back to base model")
            source = BASE_MODEL
            tokenizer = AutoTokenizer.from_pretrained(source)
            model = AutoModelForSequenceClassification.from_pretrained(source).eval().to(DEVICE)
        labels = {str(v).lower(): int(k) for k, v in model.config.id2label.items()}
        _toxic_index = labels.get("toxic", 1)
        _tokenizer, _model, _loaded_from = tokenizer, model, source
        logger.info(f"SafeText | toxicity model loaded ({source})")


def _check_active() -> None:
    """Reload when active.json changed (new version uploaded, rollback)."""
    global _active_mtime, _active_checked_at
    now = time.monotonic()
    if now - _active_checked_at < _ACTIVE_CHECK_EVERY:
        return
    _active_checked_at = now
    try:
        mtime = ACTIVE_FILE.stat().st_mtime
    except OSError:
        mtime = None
    if _active_mtime is None:
        _active_mtime = mtime or 0.0
        return
    if (mtime or 0.0) != _active_mtime:
        _active_mtime = mtime or 0.0
        logger.info("SafeText | active model changed - reloading")
        reload_models()


async def _load_in_background() -> None:
    global _failed_at
    try:
        await asyncio.to_thread(_load)
        _failed_at = None
    except Exception as e:
        _failed_at = time.monotonic()
        logger.error(f"SafeText | model load failed, running rules-only "
                     f"(retry in {_RETRY_AFTER // 60} min): {type(e).__name__}: {e}")


def _ensure_loading() -> bool:
    """True if the model is ready; otherwise start loading it (once) and return False."""
    global _loading
    if _model is not None:
        return True
    if _failed_at is not None and time.monotonic() - _failed_at < _RETRY_AFTER:
        return False
    if _loading is None or _loading.done():
        _loading = asyncio.get_running_loop().create_task(_load_in_background())
    return False


def _chunks(text: str) -> list[str]:
    words = text.split()
    if len(words) <= _CHUNK_WORDS:
        return [text]
    starts = range(0, len(words) - _CHUNK_WORDS + _CHUNK_STEP, _CHUNK_STEP)
    return [" ".join(words[i:i + _CHUNK_WORDS]) for i in list(starts)[:_MAX_CHUNKS]]


def _run(text: str) -> float:
    import torch
    with _infer_lock, torch.inference_mode():
        enc = _tokenizer(_chunks(text), return_tensors="pt", truncation=True,
                         max_length=MAX_LEN, padding=True).to(DEVICE)
        probs = torch.softmax(_model(**enc).logits, dim=-1)[:, _toxic_index]
        return float(probs.max())


async def toxicity(text: str) -> float | None:
    """Probability (0..1) that *text* is toxic language, or None while the model
    is unavailable. Cached per exact text."""
    _check_active()
    if (hit := _cache.get(text)) is not None:
        _cache.move_to_end(text)
        return hit
    if not _ensure_loading():
        return None
    try:
        score = await asyncio.wait_for(asyncio.to_thread(_run, text), TIMEOUT)
    except asyncio.TimeoutError:
        logger.warn(f"SafeText | inference timed out after {TIMEOUT}s - rules only for this message")
        return None
    _cache[text] = score
    if len(_cache) > _CACHE_SIZE:
        _cache.popitem(last=False)
    return score


async def warmup() -> None:
    """Load the model in the background at bot start (non-blocking for callers)."""
    _ensure_loading()
    if _loading is not None:
        await _loading


def preload() -> None:
    """Blocking preload (scripts / tests)."""
    _load()


def reload_models() -> None:
    """Drop the loaded model so the next call re-reads it (unload first: never two
    copies in RAM; rules-only for the few seconds the reload takes)."""
    global _model, _tokenizer, _failed_at, _loaded_from
    with _load_lock:
        _model = None
        _tokenizer = None
        _loaded_from = None
        _failed_at = None
    _cache.clear()
    logger.info("SafeText | model unloaded; will reload on next use")
