"""
assets/repo/__init__.py — dispatch registry: sys_key -> (load_fn, save_fn).

REGISTRY covers:
- 38 conf keys (all keys in config.datasys.default_data)
- Standalone per-guild stores: globalchat_message_data, chatfilter_log,
  transcripts, users, open_tickets, stats
- Runtime keys: polls, sticky_messages, giveaways, warnings, custom_commands,
  suggestion_votes, flag_quiz_active, audit_log
- 1001-bag keys: admins, ba_ban, gc_ban, globalchat, updates, feature_access
- Read-only event lists: mod_events, filter_events

Also exposes load_full_conf / save_full_conf for the "all" branch.
"""
from __future__ import annotations

import copy
import json
from typing import Callable

import config.config as config

from assets.repo.config_simple import (
    load_welcomer, save_welcomer,
    load_chatfilter, save_chatfilter,
    load_ticket, save_ticket,
    load_serverlog, save_serverlog,
    load_warn_config, save_warn_config,
    load_antispam, save_antispam,
    load_stats_channels, save_stats_channels,
    load_auto_roles, save_auto_roles,
    load_temp_voice_cfg, save_temp_voice_cfg,
    load_verify, save_verify,
    load_auto_slowmode, save_auto_slowmode,
    load_counting, save_counting,
    load_reaction_roles, save_reaction_roles,
    load_suggestions, save_suggestions,
    load_leveling_cfg, save_leveling_cfg,
    load_auto_release, save_auto_release,
    load_mc_link_cfg, save_mc_link_cfg,
    load_music, save_music,
    load_donations, save_donations,
    load_flag_quiz, save_flag_quiz,
)
from assets.repo.social import (
    load_twitter, save_twitter,
    load_youtube_videos, save_youtube_videos,
    load_tiktok, save_tiktok,
    load_instagram, save_instagram,
    load_livestream, save_livestream,
)
from assets.repo.moderation import (
    load_warnings, save_warnings,
    load_mod_events, save_mod_events,
    load_filter_events, save_filter_events,
)
from assets.repo.engagement import (
    load_giveaways, save_giveaways,
    load_polls, save_polls,
    load_suggestion_votes, save_suggestion_votes,
    load_flag_quiz_active, save_flag_quiz_active,
)
from assets.repo.tickets import (
    load_open_tickets, save_open_tickets,
    load_transcripts, save_transcripts,
)
from assets.repo.runtime import (
    load_sticky_messages, save_sticky_messages,
    load_custom_commands, save_custom_commands,
    load_audit_log, save_audit_log,
    load_activity, save_activity,
    load_temp_actions, save_temp_actions,
)
from assets.repo.entities import (
    load_users, save_users,
    load_stats, save_stats,
    load_chatfilter_log, save_chatfilter_log,
    load_globalchat_message_data, save_globalchat_message_data,
    load_leveling_users, save_leveling_users,
    upsert_leveling_user,
)
from assets.repo.global_store import (
    load_admins, save_admins,
    load_global_bans, save_global_bans,
    load_globalchat_bans, save_globalchat_bans,
    load_globalchat, save_globalchat,
    load_updates, save_updates,
    load_feature_access, save_feature_access,
    is_1001_key, load_1001_key, save_1001_key,
)

# Re-export targeted helpers
from assets.repo.moderation import add_warning, remove_warning
from assets.repo.moderation import append_mod_event, append_filter_event

import assets.db as db

_DD = config.datasys.default_data

# Type alias
_FnPair = tuple[Callable, Callable]


# ── REGISTRY ──────────────────────────────────────────────────────────────────

REGISTRY: dict[str, _FnPair] = {
    # Guild scalar fields — stored in the guilds table itself, but accessed via
    # the "all" aggregation.  Individual saves go to guild_misc if called alone.
    # (lang / guild_name / guild_id / owner_id / owner_name / terms /
    #  prism_enabled / notification_channel are handled inline in data.py)

    # Config systems
    "chatfilter":       (load_chatfilter,       save_chatfilter),
    "ticket":           (load_ticket,            save_ticket),
    "audit_log":        (load_audit_log,         save_audit_log),
    "serverlog":        (load_serverlog,          save_serverlog),
    "warnings":         (load_warnings,           save_warnings),
    "warn_config":      (load_warn_config,        save_warn_config),
    "antispam":         (load_antispam,           save_antispam),
    "welcomer":         (load_welcomer,           save_welcomer),
    "custom_commands":  (load_custom_commands,    save_custom_commands),
    "livestream":       (load_livestream,          save_livestream),
    "youtube_videos":   (load_youtube_videos,     save_youtube_videos),
    "tiktok":           (load_tiktok,             save_tiktok),
    "twitter":          (load_twitter,            save_twitter),
    "instagram":        (load_instagram,          save_instagram),
    "stats_channels":   (load_stats_channels,     save_stats_channels),
    "auto_roles":       (load_auto_roles,         save_auto_roles),
    "temp_voice":       (load_temp_voice_cfg,     save_temp_voice_cfg),
    "prism_enabled":    (None, None),  # stored on guilds row; handled inline
    "notification_channel": (None, None),  # same
    "verify":           (load_verify,             save_verify),
    "reaction_roles":   (load_reaction_roles,     save_reaction_roles),
    "auto_slowmode":    (load_auto_slowmode,      save_auto_slowmode),
    "counting":         (load_counting,           save_counting),
    "flag_quiz":        (load_flag_quiz,          save_flag_quiz),
    "flag_quiz_active": (load_flag_quiz_active,   save_flag_quiz_active),
    "suggestions":      (load_suggestions,        save_suggestions),
    "suggestion_votes": (load_suggestion_votes,   save_suggestion_votes),
    "giveaways":        (load_giveaways,          save_giveaways),
    "leveling":         (load_leveling_cfg,       save_leveling_cfg),
    "auto_release":     (load_auto_release,       save_auto_release),
    "mc_link":          (load_mc_link_cfg,        save_mc_link_cfg),
    "music":            (load_music,              save_music),
    "donations":        (load_donations,          save_donations),
    "polls":            (load_polls,              save_polls),
    "sticky_messages":  (load_sticky_messages,    save_sticky_messages),

    # Standalone per-guild stores
    "globalchat_message_data": (load_globalchat_message_data, save_globalchat_message_data),
    "chatfilter_log":          (load_chatfilter_log,          save_chatfilter_log),
    "transcripts":             (load_transcripts,             save_transcripts),
    "users":                   (load_users,                   save_users),
    "open_tickets":            (load_open_tickets,            save_open_tickets),
    "stats":                   (load_stats,                   save_stats),

    # Runtime event lists
    "mod_events":    (load_mod_events,    save_mod_events),
    "filter_events": (load_filter_events, save_filter_events),

    # Per-guild stores reachable via load_data after call-site conversion
    "activity":       (load_activity,       save_activity),
    "leveling_users": (load_leveling_users, save_leveling_users),

    # 1001-bag keys (loader/saver take no gid; routed specially in data.py)
    "admins":         (load_admins,          save_admins),
    "ba_ban":         (load_global_bans,     save_global_bans),
    "gc_ban":         (load_globalchat_bans, save_globalchat_bans),
    "globalchat":     (load_globalchat,      save_globalchat),
    "updates":        (load_updates,         save_updates),
    "feature_access": (load_feature_access,  save_feature_access),
}

# Keys whose loaders/savers take no gid argument (global tables)
_GLOBAL_KEYS = {"admins", "ba_ban", "gc_ban", "globalchat", "updates", "feature_access"}

# Scalar guilds-row keys that don't have their own table
_GUILDS_SCALAR_KEYS = {
    "lang", "guild_name", "guild_id", "owner_id", "owner_name",
    "terms", "prism_enabled", "notification_channel",
}

# All conf keys from default_data (used for load_full_conf)
_CONF_KEYS = list(_DD.keys())


# ── Guilds-row helpers ─────────────────────────────────────────────────────────

def load_guild_scalars(gid: int) -> dict:
    rows = db.query("SELECT * FROM guilds WHERE guild_id=?", (gid,))
    if not rows:
        return {
            "lang":                 _DD.get("lang", "en"),
            "guild_name":           _DD.get("guild_name", ""),
            "guild_id":             int(_DD.get("guild_id", 0)),
            "owner_id":             int(_DD.get("owner_id", 0)),
            "owner_name":           _DD.get("owner_name", ""),
            "terms":                bool(_DD.get("terms", False)),
            "prism_enabled":        bool(_DD.get("prism_enabled", True)),
            "notification_channel": _DD.get("notification_channel", ""),
        }
    r = rows[0]
    return {
        "lang":                 str(r["lang"] or "en"),
        "guild_name":           str(r["guild_name"] or ""),
        "guild_id":             int(r["discord_guild_id"] or 0),
        "owner_id":             int(r["owner_id"] or 0),
        "owner_name":           str(r["owner_name"] or ""),
        "terms":                bool(r["terms"]),
        "prism_enabled":        bool(r["prism_enabled"]),
        "notification_channel": str(r["notification_channel"] or ""),
    }


# conf key -> (db column, converter). Only keys PRESENT in the incoming dict are
# updated, so saving one scalar never clobbers the others.
_GUILDS_COL = {
    "lang":                 ("lang", str),
    "guild_name":           ("guild_name", str),
    "guild_id":             ("discord_guild_id", lambda v: int(v or 0)),
    "owner_id":             ("owner_id", lambda v: int(v or 0)),
    "owner_name":           ("owner_name", str),
    "terms":                ("terms", lambda v: int(bool(v))),
    "prism_enabled":        ("prism_enabled", lambda v: int(bool(v))),
    "notification_channel": ("notification_channel", str),
}


def save_guild_scalars(gid: int, data: dict) -> None:
    db.ensure_guild(gid)
    sets, params = [], []
    for key, (col, conv) in _GUILDS_COL.items():
        if key in data:
            sets.append(f"{col}=?")
            params.append(conv(data[key]))
    if not sets:
        return
    params.append(gid)
    db.execute(f"UPDATE guilds SET {', '.join(sets)} WHERE guild_id=?", tuple(params))


# ── load_full_conf / save_full_conf ───────────────────────────────────────────

def load_full_conf(gid: int) -> dict:
    """Load every conf key for a guild, falling back to defaults when absent."""
    out: dict = {}

    # 1. Scalar guilds-row fields
    scalars = load_guild_scalars(gid)
    out.update(scalars)

    # 2. Per-feature loaders from registry
    for key in _CONF_KEYS:
        if key in _GUILDS_SCALAR_KEYS:
            continue  # already handled above
        pair = REGISTRY.get(key)
        if pair is None or pair[0] is None:
            # Not in registry or inline-only — use default
            out[key] = copy.deepcopy(_DD[key])
            continue
        try:
            out[key] = pair[0](gid)
        except Exception:
            out[key] = copy.deepcopy(_DD[key])
    return out


def save_full_conf(gid: int, conf: dict) -> None:
    """Decompose a full conf dict into the DB (used during migration)."""
    db.ensure_guild(gid)

    # 1. Scalar guilds-row fields
    scalar_data = {k: conf[k] for k in _GUILDS_SCALAR_KEYS if k in conf}
    if scalar_data:
        save_guild_scalars(gid, scalar_data)

    # 2. Per-feature savers
    for key in _CONF_KEYS:
        if key in _GUILDS_SCALAR_KEYS or key not in conf:
            continue
        pair = REGISTRY.get(key)
        if pair is None or pair[1] is None:
            # Catch-all: guild_misc
            _save_misc(gid, key, conf[key])
            continue
        try:
            pair[1](gid, conf[key])
        except Exception as exc:
            import sys
            print(f"[repo] save_full_conf: failed to save {key} for guild {gid}: {exc}", file=sys.stderr)


def _save_misc(gid: int, key: str, data) -> None:
    db.ensure_guild(gid)
    db.execute(
        "INSERT INTO guild_misc (guild_id,key,data_json) VALUES (?,?,?) "
        "ON CONFLICT(guild_id,key) DO UPDATE SET data_json=excluded.data_json",
        (gid, key, json.dumps(data)),
    )


def load_misc(gid: int, key: str):
    rows = db.query("SELECT data_json FROM guild_misc WHERE guild_id=? AND key=?", (gid, key))
    if not rows:
        return None
    return json.loads(rows[0]["data_json"])
