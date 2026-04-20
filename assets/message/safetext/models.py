"""Model loader + async inference for toxic/hate + NSFW classifiers.

Models are lazy-loaded on first use and kept in memory. Inference runs in a
thread via asyncio.to_thread so the event loop stays responsive.

LoRA adapters (if present under data/safetext/model/lora/) are applied to
the toxic model at load time.
"""
import asyncio
import threading
from pathlib import Path
from typing import Dict, Optional

from reds_simple_logger import Logger

logger = Logger()

TOXIC_MODEL = "unitary/multilingual-toxic-xlm-roberta"
NSFW_MODEL  = "michellejieli/NSFW_text_classifier"

MODEL_DIR    = Path("data/safetext/model")
LORA_DIR     = MODEL_DIR / "lora"
MAX_LEN      = 256
NUM_THREADS  = 4

_toxic_pipe = None
_nsfw_pipe  = None
_load_lock  = threading.Lock()
_loaded     = False


def _load() -> None:
    global _toxic_pipe, _nsfw_pipe, _loaded
    if _loaded:
        return
    with _load_lock:
        if _loaded:
            return
        import torch
        from transformers import (
            AutoModelForSequenceClassification,
            AutoTokenizer,
            pipeline,
        )

        torch.set_num_threads(NUM_THREADS)

        logger.working(f"SafeText | loading toxic model: {TOXIC_MODEL}")
        toxic_tok   = AutoTokenizer.from_pretrained(TOXIC_MODEL)
        toxic_model = AutoModelForSequenceClassification.from_pretrained(TOXIC_MODEL)

        if LORA_DIR.exists() and any(LORA_DIR.iterdir()):
            try:
                from peft import PeftModel
                logger.working(f"SafeText | applying LoRA adapter from {LORA_DIR}")
                toxic_model = PeftModel.from_pretrained(toxic_model, str(LORA_DIR))
            except Exception as e:
                logger.error(f"SafeText | LoRA load failed, using base model: {e}")

        _toxic_pipe = pipeline(
            "text-classification",
            model=toxic_model,
            tokenizer=toxic_tok,
            top_k=None,
            device=-1,
            function_to_apply="sigmoid",
        )

        logger.working(f"SafeText | loading NSFW model: {NSFW_MODEL}")
        _nsfw_pipe = pipeline(
            "text-classification",
            model=NSFW_MODEL,
            tokenizer=NSFW_MODEL,
            device=-1,
        )

        _loaded = True
        logger.info("SafeText | models loaded")


def _run_toxic(text: str) -> Dict[str, float]:
    out = _toxic_pipe(text, truncation=True, max_length=MAX_LEN)
    # top_k=None returns list[list[dict]] in newer transformers, list[dict] in older.
    rows = out[0] if out and isinstance(out[0], list) else out
    return {d["label"].lower(): float(d["score"]) for d in rows}


def _run_nsfw(text: str) -> Dict[str, float]:
    out = _nsfw_pipe(text, truncation=True, max_length=MAX_LEN)
    d = out[0] if out else {"label": "SFW", "score": 0.0}
    return {"label": str(d["label"]).upper(), "score": float(d["score"])}


async def classify_toxic(text: str) -> Dict[str, float]:
    _load()
    return await asyncio.to_thread(_run_toxic, text)


async def classify_nsfw(text: str) -> Dict[str, float]:
    _load()
    return await asyncio.to_thread(_run_nsfw, text)


def preload() -> None:
    """Blocking preload. Call from bot startup to avoid first-message latency."""
    _load()


def reload_models() -> None:
    """Drop loaded models so the next classify call re-reads disk (e.g. after finetune)."""
    global _toxic_pipe, _nsfw_pipe, _loaded
    with _load_lock:
        _toxic_pipe = None
        _nsfw_pipe  = None
        _loaded     = False
    logger.info("SafeText | models unloaded; will reload on next use")
