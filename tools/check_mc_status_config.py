#!/usr/bin/env python3
"""Round-trip check for the status-board config columns:

    python3 tools/check_mc_status_config.py

Uses a throwaway SQLite file, never the live DB. Covers the case that actually
bites on deploy: an existing cfg_mc_link table created before status_channel
existed, which CREATE TABLE IF NOT EXISTS will not alter.
"""
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import assets.db as db
from assets.repo.config_simple import load_mc_link_cfg, save_mc_link_cfg

checks = 0


def check(cond, what):
    global checks
    checks += 1
    if not cond:
        raise AssertionError(f"FAILED: {what}")


tmp = tempfile.mktemp(suffix=".db")
GID = 424242

# ── simulate a PRE-EXISTING database from before the status board shipped ────
pre = sqlite3.connect(tmp)
pre.executescript(
    """
    CREATE TABLE guilds (guild_id INTEGER PRIMARY KEY);
    CREATE TABLE cfg_mc_link (
        guild_id INTEGER PRIMARY KEY,
        enabled INTEGER DEFAULT 0, api_url TEXT DEFAULT '', api_secret TEXT DEFAULT '',
        role_id TEXT DEFAULT '', announce_channel TEXT DEFAULT '', dm_on_link INTEGER DEFAULT 0,
        allow_self_unlink INTEGER DEFAULT 1, announcement_channel TEXT DEFAULT '',
        dm_announcements INTEGER DEFAULT 0, chat_enabled INTEGER DEFAULT 0,
        chat_channel TEXT DEFAULT '', chat_webhook_url TEXT DEFAULT ''
    );
    """
)
pre.execute("INSERT INTO guilds VALUES (?)", (GID,))
pre.execute(
    "INSERT INTO cfg_mc_link (guild_id,enabled,api_url,api_secret,chat_channel) VALUES (?,1,?,?,?)",
    (GID, "http://mc.example:4321", "s3cret", "111111111111111111"),
)
pre.commit()
pre.close()

cols = lambda: {r[1] for r in sqlite3.connect(tmp).execute("PRAGMA table_info(cfg_mc_link)")}
check("status_channel" not in cols(), "old schema genuinely lacks status_channel")

# ── init() must migrate the column in ────────────────────────────────────────
db.init(tmp)
check("status_channel" in cols(), "init() migrates status_channel onto an old table")
check("status_message_id" in cols(), "init() migrates status_message_id onto an old table")

# Pre-existing settings must survive the migration untouched.
cfg = load_mc_link_cfg(GID)
check(cfg["api_url"] == "http://mc.example:4321", "existing api_url survives migration")
check(cfg["chat_channel"] == "111111111111111111", "existing chat_channel survives migration")
check(cfg["status_channel"] == "", "migrated row defaults status_channel to empty")
check(cfg["status_message_id"] == "", "migrated row defaults status_message_id to empty")

# ── admin picks a channel in the dashboard ───────────────────────────────────
cfg["status_channel"] = "222222222222222222"
save_mc_link_cfg(GID, cfg)
check(load_mc_link_cfg(GID)["status_channel"] == "222222222222222222", "status_channel persists")

# ── the task posts a board and stores its message id ─────────────────────────
cfg = load_mc_link_cfg(GID)
cfg["status_message_id"] = "333333333333333333"
save_mc_link_cfg(GID, cfg)
check(load_mc_link_cfg(GID)["status_message_id"] == "333333333333333333", "status_message_id persists")

# Snowflakes must stay exact strings — as ints they exceed JS Number.MAX_SAFE_INTEGER
# and the dashboard's <select> would no longer match its option.
check(isinstance(load_mc_link_cfg(GID)["status_channel"], str), "status_channel stays a string")
check(load_mc_link_cfg(GID)["status_channel"] == "222222222222222222", "snowflake is not rounded")

# ── a save that omits the keys entirely must not explode ─────────────────────
save_mc_link_cfg(GID, {"enabled": True, "api_url": "http://x:1"})
check(load_mc_link_cfg(GID)["status_channel"] == "", "absent keys fall back to empty")

# ── a guild with no row at all gets the defaults ─────────────────────────────
fresh = load_mc_link_cfg(999999)
check(fresh["status_channel"] == "", "unknown guild defaults status_channel")
check("status_message_id" in fresh, "defaults expose status_message_id")

os.unlink(tmp)
print(f"mc status config OK — {checks} checks passed")
