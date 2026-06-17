"""Baxi admin console — one command set, two front-ends.

  * In-process: `run_console(bot)` is added to the asyncio.gather in main.py, so you
    can type commands straight into the running bot's terminal (help, add_bot_admin,
    run_task, …). Reads stdin off-loop via run_in_executor so it never blocks the bot.
  * Standalone: `baxi_cli.py` imports this module and drives the same commands when
    the bot is NOT running (one-shot or REPL).

Talks to the same ``baxi_data.db`` (SQLite WAL → safe alongside the live bot).

Add a command: write `cmd_<name>(args)` (sync) or `async def cmd_<name>(args)` and
register it in COMMANDS. Async handlers run on the bot's loop, so they may touch
discord state / schedule tasks.
"""
from __future__ import annotations

import asyncio
import shlex
import sys
from typing import Callable

import assets.db as db
import assets.repo as repo
import assets.data as datasys
import assets.share as share


# ── output helpers ────────────────────────────────────────────────────────────

def _ok(msg: str) -> None:
    print(f"  \033[32m✓\033[0m {msg}", flush=True)


def _err(msg: str) -> None:
    print(f"  \033[31m✗\033[0m {msg}", flush=True)


def _info(msg: str) -> None:
    print(f"  {msg}", flush=True)


def _parse_id(raw: str) -> int | None:
    raw = raw.strip().lstrip("@")
    if not raw.isdigit():
        _err(f"'{raw}' is not a numeric Discord ID.")
        return None
    return int(raw)


# ── commands ──────────────────────────────────────────────────────────────────

def cmd_help(args: list[str]) -> None:
    print("\nBaxi console commands:\n", flush=True)
    width = max(len(f"{n} {m['usage']}".strip()) for n, m in COMMANDS.items())
    for name, meta in COMMANDS.items():
        sig = f"{name} {meta['usage']}".strip()
        print(f"  {sig:<{width + 2}}  {meta['help']}", flush=True)
    print("\n  exit / quit                  (standalone) leave · (live bot) Ctrl+C stops bot\n", flush=True)


def cmd_list_bot_admins(args: list[str]) -> None:
    admins = repo.load_admins()
    if not admins:
        _info("No bot admins set.")
        return
    _info(f"{len(admins)} bot admin(s):")
    for a in admins:
        print(f"    - {a}", flush=True)


def cmd_add_bot_admin(args: list[str]) -> None:
    if not args:
        _err("Usage: add_bot_admin <user_id>")
        return
    uid = _parse_id(args[0])
    if uid is None:
        return
    admins = list(repo.load_admins())
    if uid in admins:
        _info(f"{uid} is already a bot admin.")
        return
    admins.append(uid)
    repo.save_admins(admins)
    _ok(f"Added bot admin {uid}. Now {len(admins)} total. Access /admin/ now.")


def cmd_remove_bot_admin(args: list[str]) -> None:
    if not args:
        _err("Usage: remove_bot_admin <user_id>")
        return
    uid = _parse_id(args[0])
    if uid is None:
        return
    admins = list(repo.load_admins())
    if uid not in admins:
        _info(f"{uid} is not a bot admin.")
        return
    admins = [a for a in admins if a != uid]
    repo.save_admins(admins)
    _ok(f"Removed bot admin {uid}. Now {len(admins)} left.")


def cmd_list_guilds(args: list[str]) -> None:
    rows = db.query(
        "SELECT guild_id, guild_name, lang, prism_enabled FROM guilds ORDER BY guild_id"
    )
    if not rows:
        _info("No guilds in DB.")
        return
    _info(f"{len(rows)} guild(s):")
    for r in rows:
        name = r["guild_name"] or "(unknown)"
        prism = "prism" if r["prism_enabled"] else "no-prism"
        print(f"    {r['guild_id']}  {name}  [{r['lang']}, {prism}]", flush=True)


def cmd_twitter(args: list[str]) -> None:
    if not args:
        _err("Usage: twitter <guild_id>")
        return
    gid = _parse_id(args[0])
    if gid is None:
        return
    cfg = dict(datasys.load_data(gid, "twitter"))
    _info(f"twitter @ {gid}: enabled={cfg.get('enabled')} "
          f"alert_channel={cfg.get('alert_channel') or '-'} "
          f"ping_role={cfg.get('ping_role') or '-'}")
    channels = cfg.get("channels", [])
    if not channels:
        _info("  no tracked accounts.")
        return
    for c in channels:
        seeded = "seeded" if c.get("last_post_id") else "NOT seeded"
        print(f"    @{c.get('username')}  last_post_id={c.get('last_post_id') or '∅'} "
              f"({seeded})  alert_channel={c.get('alert_channel') or '(global)'}", flush=True)


def cmd_twitter_reseed(args: list[str]) -> None:
    if len(args) < 1:
        _err("Usage: twitter_reseed <guild_id> [username]   (clears last_post_id → next poll re-seeds)")
        return
    gid = _parse_id(args[0])
    if gid is None:
        return
    target = args[1].lstrip("@") if len(args) > 1 else None
    cfg = dict(datasys.load_data(gid, "twitter"))
    channels = cfg.get("channels", [])
    hit = 0
    for c in channels:
        if target is None or c.get("username") == target:
            c["last_post_id"] = ""
            c["last_post_published"] = ""
            hit += 1
    if not hit:
        _err("No matching tracked account.")
        return
    cfg["channels"] = channels
    datasys.save_data(gid, "twitter", cfg)
    _ok(f"Cleared seed on {hit} account(s). Next TwitterPosts poll re-seeds silently.")


def cmd_query(args: list[str]) -> None:
    if not args:
        _err("Usage: query <SELECT ...>   (read-only)")
        return
    sql = " ".join(args)
    if not sql.lstrip().lower().startswith("select"):
        _err("Only SELECT queries allowed.")
        return
    try:
        rows = db.query(sql)
    except Exception as e:
        _err(f"SQL error: {e}")
        return
    if not rows:
        _info("(0 rows)")
        return
    cols = rows[0].keys()
    print("  " + " | ".join(cols), flush=True)
    for r in rows[:100]:
        print("  " + " | ".join(str(r[c]) for c in cols), flush=True)
    if len(rows) > 100:
        _info(f"... {len(rows) - 100} more rows")


# ── live-bot-only commands (need the running bot's task instances) ─────────────

_TASK_METHODS = {
    "GCDH":             "sync_globalchat_message_data",
    "UpdateStats":      "update_stats",
    "Livestream":       "check_streams",
    "StatsChannels":    "update_stats_channels",
    "TempActions":      "check_temp_actions",
    "PhishingList":     "update_phishing_list",
    "TrustScore":       "recalculate_scores",
    "GarbageCollector": "collect",
    "YouTubeVideos":    "check_videos",
    "TikTokVideos":     "check_videos",
    "TwitterPosts":     "check_posts",
    "Instagram":        "check_posts",
    "McLinkSync":       "sync_links",
}


def cmd_tasks(args: list[str]) -> None:
    insts = share.task_instances or {}
    status = getattr(share, "task_status", {}) or {}
    if not insts:
        _info("No running tasks (standalone mode or bot not ready).")
        return
    _info(f"{len(insts)} running task(s):")
    for key in insts:
        st = status.get(key, {})
        state = st.get("status", "?") if isinstance(st, dict) else "?"
        detail = st.get("detail", "") if isinstance(st, dict) else ""
        print(f"    {key:<18} [{state}] {detail}", flush=True)


async def cmd_run_task(args: list[str]) -> None:
    if not args:
        _err(f"Usage: run_task <key>   keys: {', '.join(_TASK_METHODS)}")
        return
    key = args[0]
    if key not in _TASK_METHODS:
        _err(f"Unknown task '{key}'. Keys: {', '.join(_TASK_METHODS)}")
        return
    instance = (share.task_instances or {}).get(key)
    if not instance:
        _err("Task not running (standalone mode, or bot not ready yet).")
        return
    loop = asyncio.get_running_loop()
    method = getattr(instance, _TASK_METHODS[key])
    loop.create_task(method.coro(instance))
    _ok(f"Triggered task '{key}'. Watch the log for its output.")


# ── registry ──────────────────────────────────────────────────────────────────

COMMANDS: dict[str, dict[str, object]] = {
    "help":             {"fn": cmd_help,             "usage": "",                  "help": "list all commands"},
    "list_bot_admins":  {"fn": cmd_list_bot_admins,  "usage": "",                  "help": "show all bot admins"},
    "add_bot_admin":    {"fn": cmd_add_bot_admin,    "usage": "<user_id>",         "help": "grant bot-admin (web /admin/) to a Discord user"},
    "remove_bot_admin": {"fn": cmd_remove_bot_admin, "usage": "<user_id>",         "help": "revoke bot-admin from a Discord user"},
    "list_guilds":      {"fn": cmd_list_guilds,      "usage": "",                  "help": "list guilds known to the DB"},
    "twitter":          {"fn": cmd_twitter,          "usage": "<guild_id>",        "help": "show X/Twitter config + seed state"},
    "twitter_reseed":   {"fn": cmd_twitter_reseed,   "usage": "<guild_id> [user]", "help": "clear last_post_id so the next poll re-seeds"},
    "tasks":            {"fn": cmd_tasks,            "usage": "",                  "help": "list running background tasks + status"},
    "run_task":         {"fn": cmd_run_task,         "usage": "<key>",             "help": "trigger a background task now (e.g. run_task TwitterPosts)"},
    "query":            {"fn": cmd_query,            "usage": "<SELECT ...>",      "help": "run a read-only SQL SELECT"},
}


async def dispatch(name: str, args: list[str]) -> None:
    meta = COMMANDS.get(name)
    if not meta:
        _err(f"Unknown command '{name}'. Type 'help'.")
        return
    fn: Callable = meta["fn"]  # type: ignore[assignment]
    try:
        if asyncio.iscoroutinefunction(fn):
            await fn(args)
        else:
            fn(args)
    except Exception as e:
        _err(f"{type(e).__name__}: {e}")


# ── in-process front-end (live bot) ───────────────────────────────────────────

async def run_console(bot=None) -> None:
    """Read commands from the bot's stdin and dispatch them on the event loop.

    stdin is read on a dedicated *daemon* thread that feeds an asyncio.Queue, so
    the bot is never blocked AND a thread parked in a blocking readline can never
    keep the process alive at shutdown (a non-daemon executor thread would — it
    gets joined at interpreter exit and readline only returns on EOF, which a
    pterodactyl stdin pipe never sends → hang). EOF disables the console cleanly.
    """
    import threading

    loop = asyncio.get_running_loop()
    queue: "asyncio.Queue[str | None]" = asyncio.Queue()

    def _reader() -> None:
        try:
            for raw in sys.stdin:                       # blocks here, off-loop
                loop.call_soon_threadsafe(queue.put_nowait, raw)
        except Exception:
            pass
        loop.call_soon_threadsafe(queue.put_nowait, None)  # EOF sentinel

    threading.Thread(target=_reader, name="baxi-console-stdin", daemon=True).start()

    print("[console] ready — type 'help' (Ctrl+C stops the bot).", flush=True)
    while True:
        line = await queue.get()
        if line is None:  # EOF — no interactive console available
            print("[console] stdin closed — console disabled.", flush=True)
            return
        line = line.strip()
        if not line:
            continue
        if line.lower() in ("exit", "quit"):
            print("[console] bot keeps running. Use Ctrl+C to stop it.", flush=True)
            continue
        try:
            parts = shlex.split(line)
        except ValueError as e:
            _err(f"parse error: {e}")
            continue
        await dispatch(parts[0], parts[1:])


# ── standalone front-end (bot not running) ────────────────────────────────────

async def _repl() -> None:
    loop = asyncio.get_running_loop()
    print("Baxi CLI — type 'help', or 'exit' to quit.", flush=True)
    while True:
        try:
            line = (await loop.run_in_executor(None, lambda: input("baxi> "))).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not line:
            continue
        if line.lower() in ("exit", "quit"):
            return
        try:
            parts = shlex.split(line)
        except ValueError as e:
            _err(f"parse error: {e}")
            continue
        await dispatch(parts[0], parts[1:])


def main_standalone() -> None:
    db.init()
    if len(sys.argv) > 1:
        asyncio.run(dispatch(sys.argv[1], sys.argv[2:]))
    else:
        asyncio.run(_repl())
