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

Process: in the bot the model runs in its own process (model_worker.py), started
on the first message that needs a score - so a bot whose guilds all have the
chatfilter off, or set to rules-only, never loads it - and stopped after
SAFETEXT_IDLE_UNLOAD seconds without use (default 15 min, 0 = keep it). Stopping
the process returns all of its memory to the OS and the bot never imports torch.
Scripts that call preload() run the model in-process instead.

Stability: until the process is ready (or if starting fails - retried every 10
minutes) `toxicity()` returns None and the pipeline runs on its rules alone
instead of queueing messages. Each inference has a timeout. Long messages are
scored in overlapping chunks (max score wins), so abuse after the first 256
tokens is not cut off.

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
import sys
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
WORKER      = Path(__file__).with_name("model_worker.py")
IDLE_UNLOAD = int(os.environ.get("SAFETEXT_IDLE_UNLOAD") or 900)
_START_TIMEOUT = 900   # the first start may download the model (~1 GB)

_model = None
_tokenizer = None
_toxic_index = 1
_load_lock = threading.Lock()
_infer_lock = threading.Lock()
_failed_at: float | None = None
_cache: "OrderedDict[str, float]" = OrderedDict()
_loaded_from: str | None = None
_active_mtime: float | None = None
_active_checked_at = 0.0
_inprocess = False          # preload() was called: score in this process (scripts)

# model process (bot)
_proc: asyncio.subprocess.Process | None = None
_proc_source: str | None = None
_proc_lock = asyncio.Lock()
_starting: asyncio.Task | None = None
_generation = 0             # bumped by reload_models(); a process started for an older one is dropped
_next_id = 0
_last_used = 0.0


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
    return _loaded_from or _proc_source


def is_loaded() -> bool:
    return _model is not None or _proc is not None


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


# ── model process ────────────────────────────────────────────────────────────
def _kill(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is None:
        try:
            proc.terminate()
        except ProcessLookupError:
            pass
    try:
        asyncio.get_running_loop().create_task(proc.wait())   # reap
    except RuntimeError:
        pass


def stop_worker(reason: str = "") -> bool:
    """Stop the model process (all of its memory goes back to the OS). The next
    message that needs a score starts it again. Returns False if none was running."""
    global _proc, _proc_source
    proc, _proc, _proc_source = _proc, None, None
    if proc is None:
        return False
    _kill(proc)
    logger.info(f"SafeText | model process stopped{f' ({reason})' if reason else ''}")
    return True


async def _start_worker(generation: int) -> None:
    global _proc, _proc_source, _failed_at, _last_used
    logger.working(f"SafeText | starting model process ({_resolve_source()})")
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, str(WORKER),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, cwd=os.getcwd(),
        )
    except OSError as e:
        _failed_at = time.monotonic()
        logger.error(f"SafeText | could not start model process, running rules-only "
                     f"(retry in {_RETRY_AFTER // 60} min): {e}")
        return
    try:
        line = await asyncio.wait_for(proc.stdout.readline(), _START_TIMEOUT)
        msg = json.loads(line) if line else {"error": f"exited with code {await proc.wait()}"}
    except (asyncio.TimeoutError, ValueError) as e:
        msg = {"error": f"{type(e).__name__}: {e}"}
    if not msg.get("ready"):
        _kill(proc)
        _failed_at = time.monotonic()
        logger.error(f"SafeText | model load failed, running rules-only "
                     f"(retry in {_RETRY_AFTER // 60} min): {msg.get('error')}")
        return
    if generation != _generation:   # reload_models() ran while it was loading
        _kill(proc)
        return
    _proc, _proc_source, _failed_at = proc, msg.get("source"), None
    _last_used = time.monotonic()
    logger.info(f"SafeText | toxicity model ready in process {proc.pid} ({_proc_source})")
    if IDLE_UNLOAD > 0:
        asyncio.get_running_loop().create_task(_idle_watch(proc))


async def _idle_watch(proc: asyncio.subprocess.Process) -> None:
    while _proc is proc:
        await asyncio.sleep(60)
        if _proc is proc and time.monotonic() - _last_used >= IDLE_UNLOAD:
            stop_worker(f"unused for {IDLE_UNLOAD // 60} min")


def _ensure_worker() -> bool:
    """True if the model process is ready; otherwise start it (once) and return False."""
    global _starting
    if _proc is not None:
        if _proc.returncode is None:
            return True
        stop_worker("exited")
    if _failed_at is not None and time.monotonic() - _failed_at < _RETRY_AFTER:
        return False
    if _starting is None or _starting.done():
        _starting = asyncio.get_running_loop().create_task(_start_worker(_generation))
    return False


async def _score_in_worker(text: str) -> float | None:
    global _next_id, _last_used, _failed_at
    async with _proc_lock:
        proc = _proc
        if proc is None:
            return None
        _next_id += 1
        rid = _next_id
        try:
            proc.stdin.write((json.dumps({"id": rid, "text": text}) + "\n").encode())
            await proc.stdin.drain()
            # A reply to a request that timed out earlier may still be queued: skip it.
            while (line := await proc.stdout.readline()):
                msg = json.loads(line)
                if msg.get("id") == rid:
                    break
            else:
                raise ConnectionResetError("model process closed its output")
        except (ConnectionError, ValueError) as e:
            if _proc is proc:
                stop_worker(f"crashed: {e}")
                _failed_at = time.monotonic()
            return None
    _last_used = time.monotonic()
    if "error" in msg:
        logger.warn(f"SafeText | inference failed - rules only for this message: {msg['error']}")
        return None
    return float(msg["score"])


async def toxicity(text: str) -> float | None:
    """Probability (0..1) that *text* is toxic language, or None while the model
    is unavailable. Cached per exact text."""
    _check_active()
    if (hit := _cache.get(text)) is not None:
        _cache.move_to_end(text)
        return hit
    if _inprocess:
        if _model is None:
            await asyncio.to_thread(_load)
        job = asyncio.to_thread(_run, text)
    elif _ensure_worker():
        job = _score_in_worker(text)
    else:
        return None
    try:
        score = await asyncio.wait_for(job, TIMEOUT)
    except asyncio.TimeoutError:
        logger.warn(f"SafeText | inference timed out after {TIMEOUT}s - rules only for this message")
        return None
    if score is None:
        return None
    _cache[text] = score
    if len(_cache) > _CACHE_SIZE:
        _cache.popitem(last=False)
    return score


def preload() -> None:
    """Blocking in-process load (scripts / tests); scoring then stays in this process."""
    global _inprocess
    _inprocess = True
    _load()


def reload_models() -> None:
    """Drop the loaded model so the next call re-reads it (unload first: never two
    copies in RAM; rules-only for the few seconds the reload takes)."""
    global _model, _tokenizer, _failed_at, _loaded_from, _generation
    _generation += 1
    stop_worker("reload")
    with _load_lock:
        _model = None
        _tokenizer = None
        _loaded_from = None
        _failed_at = None
    _cache.clear()
    logger.info("SafeText | model unloaded; will reload on next use")
