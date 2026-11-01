"""Toxicity model process. Started by models.py on demand, never imported by the bot.

Keeping torch in its own process is what makes idle cheap: when this process
exits, all of its ~1.5 GB goes back to the OS. Unloading inside the bot cannot do
that (torch itself and the allocator keep most of it).

Protocol, one JSON object per line:
  child  -> parent  {"ready": true, "source": "<model>"}  or  {"ready": false, "error": "..."}
  parent -> child   {"id": 1, "text": "..."}
  child  -> parent  {"id": 1, "score": 0.97}  or  {"id": 1, "error": "..."}
The process exits when its stdin closes, so it never outlives the bot.
"""
import importlib.util
import json
import os
import sys

# The original stdout carries the protocol; anything else printed (logger,
# transformers warnings) goes to stderr so it cannot corrupt a reply.
_proto = os.fdopen(os.dup(1), "w", buffering=1, encoding="utf-8")
os.dup2(2, 1)
sys.stdout = sys.stderr

# Load models.py by path: importing the package would pull in the whole pipeline,
# and this script's folder on sys.path would shadow modules like "context".
_here = os.path.dirname(os.path.abspath(__file__))
sys.path = [p for p in sys.path if os.path.abspath(p or ".") != _here]
_spec = importlib.util.spec_from_file_location("safetext_models", os.path.join(_here, "models.py"))
models = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(models)


def _send(obj: dict) -> None:
    _proto.write(json.dumps(obj) + "\n")
    _proto.flush()


def main() -> int:
    try:
        models._load()
    except Exception as e:
        _send({"ready": False, "error": f"{type(e).__name__}: {e}"})
        return 1
    _send({"ready": True, "source": models.current_source()})
    while line := sys.stdin.readline():
        try:
            req = json.loads(line)
        except ValueError:
            continue
        try:
            _send({"id": req.get("id"), "score": models._run(str(req.get("text", "")))})
        except Exception as e:
            _send({"id": req.get("id"), "error": f"{type(e).__name__}: {e}"})
    return 0


if __name__ == "__main__":
    sys.exit(main())
