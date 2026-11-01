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


# Set by run_console: stdin is owned by its reader thread there, so interactive prompts must
# take the next line from this queue instead of calling input().
_live_queue: "asyncio.Queue[str | None] | None" = None


async def _ask(prompt: str) -> str:
    print(prompt, end="", flush=True)
    if _live_queue is None:
        return await asyncio.to_thread(input)
    line = await _live_queue.get()
    return "q" if line is None else line


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
    "Pulse":            "tick",
    "Starboard":        "tick",
    "Capsule":          "tick",
    "Birthdays":        "tick",
    "Wrapped":          "tick",
    "RestMode":         "watch",
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


async def cmd_wrapped(args: list[str]) -> None:
    import assets.wrapped as wrapped
    if args and len(args) > 1 and args[1] in ("preview", "vote") and not share.task_instances:
        _err("preview/vote need the running bot (use the live console).")
        return
    for line in await wrapped.admin_command(datasys.bot_instance, args):
        _info(line)


async def cmd_backup(args: list[str]) -> None:
    import assets.backup as backup
    problem = backup.config_problem()
    if problem:
        _err(f"Backup server not configured: {problem} (config/auth.py -> class Backup, or BACKUP_* env vars)")
        return
    _info("Creating DB snapshot and uploading to the backup server...")
    meta = await asyncio.to_thread(backup.backup_now, "manual, console")
    replicas = ", ".join(f"{r['target']}: {r['status']}" for r in meta.get("replicas", [])) or "none"
    _ok(f"Uploaded {meta['filename']} (id {meta['id']}, {meta['size'] / 1024:.0f} KiB) · replicas: {replicas}")


async def cmd_restore(args: list[str]) -> None:
    import datetime
    import tempfile
    import assets.backup as backup
    from assets.backup_client import BackupError

    live = _live_queue is not None
    if args and args[0].lower() == "cancel":
        _ok("Staged restore removed.") if backup.cancel_staged() else _info("No restore is staged.")
        return
    problem = backup.config_problem()
    if problem:
        _err(f"Backup server not configured: {problem} (config/auth.py -> class Backup, or BACKUP_* env vars)")
        return
    skip_confirm = "--yes" in args
    args = [a for a in args if a != "--yes"]

    _info("Fetching backup list from the backup server...")
    backups = await asyncio.to_thread(backup.list_backups)
    if not backups:
        _err("The backup server has no backups for this project.")
        return

    if args:
        want = args[0].lower()
        if want == "latest":
            chosen = backups[0]
        elif want.isdigit() and any(b["id"] == int(want) for b in backups):
            chosen = next(b for b in backups if b["id"] == int(want))
        else:
            _err(f"No backup '{args[0]}'. Use 'latest' or one of the IDs: {', '.join(str(b['id']) for b in backups)}")
            return
    else:
        for i, b in enumerate(backups, start=1):
            when = datetime.datetime.fromtimestamp(b["created_at"]).strftime("%Y-%m-%d %H:%M:%S")
            tag = "  (latest)" if i == 1 else ""
            print(f"  [{i:>2}] {when}  {b['size'] / 1024:>7.0f} KiB  id {b['id']:<5} {b.get('note') or ''}{tag}", flush=True)
        raw = (await _ask(f"Restore which backup? [1-{len(backups)}, Enter = 1 latest, q = cancel]: ")).strip().lower()
        if raw in ("q", "quit", "n"):
            _info("Cancelled.")
            return
        if raw == "":
            raw = "1"
        if not raw.isdigit() or not 1 <= int(raw) <= len(backups):
            _err(f"'{raw}' is not a number between 1 and {len(backups)}.")
            return
        chosen = backups[int(raw) - 1]

    when = datetime.datetime.fromtimestamp(chosen["created_at"]).strftime("%Y-%m-%d %H:%M:%S")
    with tempfile.TemporaryDirectory(prefix="baxi-restore-") as tmp:
        _info(f"Downloading {chosen['filename']} ({when}, {chosen['size'] / 1024:.0f} KiB)...")
        try:
            snapshot = await asyncio.to_thread(backup.download_snapshot, chosen, tmp)
        except BackupError as e:
            _err(str(e))
            return
        _ok("Downloaded, checksum and integrity check passed.")
        if not skip_confirm:
            if live:
                _info("The restore is applied when the bot starts the next time (restart it afterwards).")
            _info(f"This REPLACES the current database ({db._DB_PATH}); the old one is kept as a .pre-restore-<timestamp> copy.")
            if (await _ask("Type 'yes' to restore: ")).strip().lower() != "yes":
                _info("Cancelled.")
                return
        await asyncio.to_thread(backup.stage_snapshot, snapshot)

    if live:
        _ok(f"Restore of the backup from {when} is staged.")
        _info("Restart the bot now to apply it (panel: Restart). Until then nothing has changed.")
        _info("Changed your mind? Run 'restore cancel' before restarting.")
    else:
        db.close()
        kept = await asyncio.to_thread(db.apply_pending_restore, db._DB_PATH)
        _ok(f"Restored backup from {when} into {db._DB_PATH}.")
        if kept:
            _info(f"Previous DB saved as {kept}")
        _info("Start the bot again to use the restored data.")


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
    "wrapped":          {"fn": cmd_wrapped,          "usage": "<guild_id> [status|preview|vote [min]|reset]", "help": "Server Wrapped: status, or a test run for one guild (staff preview / quote vote) before December"},
    "backup":           {"fn": cmd_backup,          "usage": "",                  "help": "snapshot the DB and upload it to the backup server now"},
    "restore":          {"fn": cmd_restore,          "usage": "[id|latest|cancel] [--yes]", "help": "download a backup from the backup server and restore the DB (live bot: applied on next start; default: pick from list)"},
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

    global _live_queue
    loop = asyncio.get_running_loop()
    queue: "asyncio.Queue[str | None]" = asyncio.Queue()
    _live_queue = queue

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
