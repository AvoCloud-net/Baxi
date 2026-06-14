"""
assets/repo/global_store.py — sid-1001 bag: admins, ba_ban, gc_ban,
globalchat, updates, feature_access.
"""
from __future__ import annotations

import json

import assets.db as db

_GID_1001 = 1001


def _ensure_1001() -> None:
    db.ensure_guild(_GID_1001)


# ── Bot admins ────────────────────────────────────────────────────────────────

def load_admins() -> list:
    rows = db.query("SELECT admin_id FROM bot_admins ORDER BY pos")
    return [r["admin_id"] for r in rows]


def save_admins(data: list) -> None:
    with db.transaction() as cx:
        cx.execute("DELETE FROM bot_admins")
        for pos, aid in enumerate(data):
            cx.execute(
                "INSERT INTO bot_admins (pos,admin_id) VALUES (?,?)", (pos, str(aid))
            )


# ── Global bans (ba_ban) ──────────────────────────────────────────────────────

def load_global_bans() -> dict:
    rows = db.query("SELECT user_id, data_json FROM global_bans")
    return {r["user_id"]: json.loads(r["data_json"]) for r in rows}


def save_global_bans(data: dict) -> None:
    with db.transaction() as cx:
        cx.execute("DELETE FROM global_bans")
        for uid, v in data.items():
            cx.execute(
                "INSERT INTO global_bans (user_id,data_json) VALUES (?,?)",
                (str(uid), json.dumps(v)),
            )


# ── Globalchat bans (gc_ban) ──────────────────────────────────────────────────

def load_globalchat_bans() -> dict:
    rows = db.query("SELECT user_id, data_json FROM globalchat_bans")
    return {r["user_id"]: json.loads(r["data_json"]) for r in rows}


def save_globalchat_bans(data: dict) -> None:
    with db.transaction() as cx:
        cx.execute("DELETE FROM globalchat_bans")
        for uid, v in data.items():
            cx.execute(
                "INSERT INTO globalchat_bans (user_id,data_json) VALUES (?,?)",
                (str(uid), json.dumps(v)),
            )


# ── Globalchat guild configs ──────────────────────────────────────────────────

def load_globalchat() -> dict:
    rows = db.query("SELECT guild_id, config_json FROM globalchat_guilds")
    return {r["guild_id"]: json.loads(r["config_json"]) for r in rows}


def save_globalchat(data: dict) -> None:
    with db.transaction() as cx:
        cx.execute("DELETE FROM globalchat_guilds")
        for gid, v in data.items():
            cx.execute(
                "INSERT INTO globalchat_guilds (guild_id,config_json) VALUES (?,?)",
                (str(gid), json.dumps(v)),
            )


# ── Updates channels ──────────────────────────────────────────────────────────

def load_updates() -> dict:
    rows = db.query("SELECT guild_id, config_json FROM updates_channels")
    return {r["guild_id"]: json.loads(r["config_json"]) for r in rows}


def save_updates(data: dict) -> None:
    with db.transaction() as cx:
        cx.execute("DELETE FROM updates_channels")
        for gid, v in data.items():
            cx.execute(
                "INSERT INTO updates_channels (guild_id,config_json) VALUES (?,?)",
                (str(gid), json.dumps(v)),
            )


# ── Feature access ────────────────────────────────────────────────────────────

def load_feature_access() -> dict:
    rows = db.query("SELECT feature, config_json FROM feature_access")
    return {r["feature"]: json.loads(r["config_json"]) for r in rows}


def save_feature_access(data: dict) -> None:
    with db.transaction() as cx:
        cx.execute("DELETE FROM feature_access")
        for feat, v in data.items():
            cx.execute(
                "INSERT INTO feature_access (feature,config_json) VALUES (?,?)",
                (str(feat), json.dumps(v)),
            )


# ── Helpers to route 1001 keys ────────────────────────────────────────────────

_1001_KEY_MAP = {
    "admins":         (load_admins,         save_admins),
    "ba_ban":         (load_global_bans,     save_global_bans),
    "gc_ban":         (load_globalchat_bans, save_globalchat_bans),
    "globalchat":     (load_globalchat,      save_globalchat),
    "updates":        (load_updates,         save_updates),
    "feature_access": (load_feature_access,  save_feature_access),
}


def is_1001_key(sys: str) -> bool:
    return sys in _1001_KEY_MAP


def load_1001_key(sys: str):
    return _1001_KEY_MAP[sys][0]()


def save_1001_key(sys: str, data) -> None:
    _1001_KEY_MAP[sys][1](data)


# ── Full 1001 bag — used by migration ─────────────────────────────────────────

def save_1001_bag(bag: dict) -> None:
    """Write the full data/1001/conf.json bag into the global tables."""
    _ensure_1001()
    if "admins" in bag:
        save_admins(bag["admins"])
    if "ba_ban" in bag:
        save_global_bans(bag["ba_ban"])
    if "gc_ban" in bag:
        save_globalchat_bans(bag["gc_ban"])
    if "globalchat" in bag:
        save_globalchat(bag["globalchat"])
    if "updates" in bag:
        save_updates(bag["updates"])
    if "feature_access" in bag:
        save_feature_access(bag["feature_access"])
