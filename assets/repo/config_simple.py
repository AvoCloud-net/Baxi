"""
assets/repo/config_simple.py — factory for simple scalar-only config tables.

Also contains mappers for tables that have child rows (ticket buttons, antispam
whitelists, serverlog events, warn steps, welcomer channel type handling, etc.)
"""
from __future__ import annotations

import json
from typing import Any

import assets.db as db
import config.config as config

_DD = config.datasys.default_data

# The repo mappers reassemble each config system from its default shape, so
# default_data MUST contain every config key. A stale config/config.py (e.g. only
# config/auth.py kept on a server, config.py not updated) would otherwise crash
# deep in the import chain with a cryptic KeyError. Fail fast with a clear message.
_REQUIRED_CONF_KEYS = [
    "chatfilter", "ticket", "serverlog", "warn_config", "antispam", "welcomer",
    "livestream", "youtube_videos", "tiktok", "twitter", "instagram", "stats_channels",
    "auto_roles", "temp_voice", "verify", "reaction_roles", "auto_slowmode", "counting",
    "flag_quiz", "suggestions", "leveling", "auto_release", "mc_link", "music", "donations",
]
_missing_conf_keys = [k for k in _REQUIRED_CONF_KEYS if k not in _DD]
if _missing_conf_keys:
    raise RuntimeError(
        "config/config.py is out of date: config.datasys.default_data is missing "
        f"key(s): {_missing_conf_keys}. Upload the current config/config.py "
        "(only config/auth.py needs to stay server-local for secrets), then restart."
    )


# ── Generic helpers ───────────────────────────────────────────────────────────

def _int(v, default: int = 0) -> int:
    """Coerce to int, tolerating real-world '' / None / junk (returns default).

    The dashboard and legacy configs store int-typed fields as '' when unset, so a
    bare int('') would crash the mapper. Always route int coercions through here.
    """
    try:
        return int(v)
    except (TypeError, ValueError):
        return default

def _bool(v: Any) -> bool:
    return bool(v)


def _int_or_str(col_val: Any, default_val: Any) -> Any:
    """Return int if the default for this field is int, else str."""
    if isinstance(default_val, int):
        return _int(col_val) if col_val is not None else default_val
    return str(col_val) if col_val is not None else default_val


def _row_to_dict(row, cols: list[str], bools: set[str], ints: set[str], defaults: dict) -> dict:
    out = {}
    for c in cols:
        v = row[c]
        if c in bools:
            out[c] = bool(v) if v is not None else defaults.get(c, False)
        elif c in ints:
            out[c] = _int(v) if v is not None else defaults.get(c, 0)
        else:
            out[c] = str(v) if v is not None else defaults.get(c, "")
    return out


def _upsert_row(table: str, cols: list[str], bools: set[str], gid: int, data: dict) -> None:
    vals = []
    for c in cols:
        v = data.get(c, False if c in bools else "")
        vals.append(int(v) if c in bools else v)
    placeholders = ",".join(["?"] * (len(cols) + 1))
    set_clause = ",".join(f"{c}=excluded.{c}" for c in cols)
    db.execute(
        f"INSERT INTO {table} (guild_id,{','.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(guild_id) DO UPDATE SET {set_clause}",
        [gid, *vals],
    )


def _load_list_col(table: str, gid: int, order: str = "pos") -> list:
    """Load a list column. Values are JSON-encoded so dicts/ints/strings round-trip
    faithfully (a suggestions channel is a dict {id,topic,votes_enabled}, not a str).
    Falls back to the raw value for any legacy non-JSON row."""
    rows = db.query(f"SELECT value FROM {table} WHERE guild_id=? ORDER BY {order}", (gid,))
    out: list = []
    for r in rows:
        raw = r["value"]
        try:
            out.append(json.loads(raw))
        except (TypeError, ValueError):
            out.append(raw)
    return out


def _save_list_col(table: str, gid: int, items: list) -> None:
    with db.transaction() as cx:
        cx.execute(f"DELETE FROM {table} WHERE guild_id=?", (gid,))
        for pos, v in enumerate(items):
            cx.execute(f"INSERT INTO {table} (guild_id,pos,value) VALUES (?,?,?)", (gid, pos, json.dumps(v)))


# ── Welcomer ──────────────────────────────────────────────────────────────────

_WELCOMER_DEF = _DD["welcomer"]
_WELCOMER_COLS = [
    "enabled", "channel", "message", "leave_enabled", "leave_channel",
    "leave_message", "color", "image_mode", "card_color", "has_custom_bg", "leave_color",
]
_WELCOMER_BOOLS = {"enabled", "leave_enabled", "has_custom_bg"}
# channel / leave_channel default is int 0 in default_data; stored as TEXT but read back
# as int 0 when value is exactly "0" (or 0) to match the default type.


def _coerce_channel(v: Any, default_val: Any) -> Any:
    """Welcomer channel fields: return int 0 when stored as 0/'0', else str."""
    if v is None or str(v) == "0":
        return default_val  # preserves int 0 from default
    return str(v)


def load_welcomer(gid: int) -> dict:
    rows = db.query("SELECT * FROM cfg_welcomer WHERE guild_id=?", (gid,))
    if not rows:
        return dict(_WELCOMER_DEF)
    r = rows[0]
    return {
        "enabled":       bool(r["enabled"]),
        "channel":       _coerce_channel(r["channel"], _WELCOMER_DEF["channel"]),
        "message":       str(r["message"]),
        "leave_enabled": bool(r["leave_enabled"]),
        "leave_channel": _coerce_channel(r["leave_channel"], _WELCOMER_DEF["leave_channel"]),
        "leave_message": str(r["leave_message"]),
        "color":         str(r["color"]),
        "image_mode":    str(r["image_mode"]),
        "card_color":    str(r["card_color"]),
        "has_custom_bg": bool(r["has_custom_bg"]),
        "leave_color":   str(r["leave_color"]),
    }


def save_welcomer(gid: int, data: dict) -> None:
    db.ensure_guild(gid)
    ch = data.get("channel", 0)
    lch = data.get("leave_channel", 0)
    db.execute(
        "INSERT INTO cfg_welcomer "
        "(guild_id,enabled,channel,message,leave_enabled,leave_channel,"
        "leave_message,color,image_mode,card_color,has_custom_bg,leave_color) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(guild_id) DO UPDATE SET "
        "enabled=excluded.enabled,channel=excluded.channel,message=excluded.message,"
        "leave_enabled=excluded.leave_enabled,leave_channel=excluded.leave_channel,"
        "leave_message=excluded.leave_message,color=excluded.color,"
        "image_mode=excluded.image_mode,card_color=excluded.card_color,"
        "has_custom_bg=excluded.has_custom_bg,leave_color=excluded.leave_color",
        (
            gid,
            _int(data.get("enabled", False)),
            str(ch),
            str(data.get("message", _WELCOMER_DEF["message"])),
            _int(data.get("leave_enabled", False)),
            str(lch),
            str(data.get("leave_message", _WELCOMER_DEF["leave_message"])),
            str(data.get("color", _WELCOMER_DEF["color"])),
            str(data.get("image_mode", "none")),
            str(data.get("card_color", _WELCOMER_DEF["card_color"])),
            _int(data.get("has_custom_bg", False)),
            str(data.get("leave_color", _WELCOMER_DEF["leave_color"])),
        ),
    )


# ── Chatfilter ────────────────────────────────────────────────────────────────

_CF_DEF = _DD["chatfilter"]
_CF_CATS_DEF = {str(k): True for k in range(1, 6)}


def load_chatfilter(gid: int) -> dict:
    rows = db.query("SELECT * FROM cfg_chatfilter WHERE guild_id=?", (gid,))
    if not rows:
        return dict(_CF_DEF)
    r = rows[0]
    cat_rows = db.query(
        "SELECT cat_key, enabled FROM cfg_chatfilter_ai_category WHERE guild_id=?", (gid,)
    )
    cats: dict = dict(_CF_CATS_DEF)
    for cr in cat_rows:
        cats[cr["cat_key"]] = bool(cr["enabled"])
    return {
        "enabled":          bool(r["enabled"]),
        "system":           str(r["system"]),
        "phishing_filter":  bool(r["phishing_filter"]),
        "warn_on_violation": bool(r["warn_on_violation"]),
        "ai_categories":    cats,
    }


def save_chatfilter(gid: int, data: dict) -> None:
    db.ensure_guild(gid)
    with db.transaction() as cx:
        cx.execute(
            "INSERT INTO cfg_chatfilter (guild_id,enabled,system,phishing_filter,warn_on_violation) "
            "VALUES (?,?,?,?,?) ON CONFLICT(guild_id) DO UPDATE SET "
            "enabled=excluded.enabled,system=excluded.system,"
            "phishing_filter=excluded.phishing_filter,warn_on_violation=excluded.warn_on_violation",
            (
                gid,
                _int(data.get("enabled", False)),
                str(data.get("system", "AI")),
                _int(data.get("phishing_filter", False)),
                _int(data.get("warn_on_violation", False)),
            ),
        )
        cx.execute("DELETE FROM cfg_chatfilter_ai_category WHERE guild_id=?", (gid,))
        cats = data.get("ai_categories", _CF_CATS_DEF)
        for k, v in cats.items():
            cx.execute(
                "INSERT INTO cfg_chatfilter_ai_category (guild_id,cat_key,enabled) VALUES (?,?,?)",
                (gid, str(k), int(bool(v))),
            )


# ── Ticket ────────────────────────────────────────────────────────────────────

_TKT_DEF = _DD["ticket"]


def load_ticket(gid: int) -> dict:
    rows = db.query("SELECT * FROM cfg_ticket WHERE guild_id=?", (gid,))
    if not rows:
        return dict(_TKT_DEF)
    r = rows[0]
    btn_rows = db.query(
        "SELECT * FROM cfg_ticket_button WHERE guild_id=? ORDER BY pos", (gid,)
    )
    buttons = [
        {"id": b["btn_id"], "label": b["label"], "emoji": b["emoji"], "style": b["style"]}
        for b in btn_rows
    ]
    if not buttons:
        buttons = list(_TKT_DEF["buttons"])
    return {
        "enabled":              bool(r["enabled"]),
        "channel":              str(r["channel"]),
        "transcript":           str(r["transcript"]),
        "catid":                str(r["catid"]),
        "role":                 str(r["role"]),
        "color":                str(r["color"]),
        "message":              str(r["message"]),
        "channel_name_template": str(r["channel_name_template"]),
        "panel_message_id":     str(r["panel_message_id"]),
        "buttons":              buttons,
    }


def save_ticket(gid: int, data: dict) -> None:
    db.ensure_guild(gid)
    with db.transaction() as cx:
        cx.execute(
            "INSERT INTO cfg_ticket "
            "(guild_id,enabled,channel,transcript,catid,role,color,message,"
            "channel_name_template,panel_message_id) VALUES (?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(guild_id) DO UPDATE SET "
            "enabled=excluded.enabled,channel=excluded.channel,transcript=excluded.transcript,"
            "catid=excluded.catid,role=excluded.role,color=excluded.color,"
            "message=excluded.message,channel_name_template=excluded.channel_name_template,"
            "panel_message_id=excluded.panel_message_id",
            (
                gid,
                _int(data.get("enabled", False)),
                str(data.get("channel", "")),
                str(data.get("transcript", "")),
                str(data.get("catid", "")),
                str(data.get("role", "")),
                str(data.get("color", "#FF6B4A")),
                str(data.get("message", _TKT_DEF["message"])),
                str(data.get("channel_name_template", "{button}-{user}")),
                str(data.get("panel_message_id", "")),
            ),
        )
        cx.execute("DELETE FROM cfg_ticket_button WHERE guild_id=?", (gid,))
        for pos, btn in enumerate(data.get("buttons", [])):
            cx.execute(
                "INSERT INTO cfg_ticket_button (guild_id,pos,btn_id,label,emoji,style) "
                "VALUES (?,?,?,?,?,?)",
                (gid, pos, btn.get("id", ""), btn.get("label", ""), btn.get("emoji", ""),
                 btn.get("style", "primary")),
            )


# ── Serverlog ─────────────────────────────────────────────────────────────────

_SL_DEF = _DD["serverlog"]
_SL_EVENTS_DEF = _SL_DEF["events"]


def load_serverlog(gid: int) -> dict:
    rows = db.query("SELECT * FROM cfg_serverlog WHERE guild_id=?", (gid,))
    if not rows:
        return dict(_SL_DEF)
    r = rows[0]
    ev_rows = db.query(
        "SELECT event_key, enabled FROM cfg_serverlog_event WHERE guild_id=?", (gid,)
    )
    events: dict = dict(_SL_EVENTS_DEF)
    for ev in ev_rows:
        events[ev["event_key"]] = bool(ev["enabled"])
    return {
        "enabled": bool(r["enabled"]),
        "channel": str(r["channel"]),
        "events":  events,
    }


def save_serverlog(gid: int, data: dict) -> None:
    db.ensure_guild(gid)
    with db.transaction() as cx:
        cx.execute(
            "INSERT INTO cfg_serverlog (guild_id,enabled,channel) VALUES (?,?,?) "
            "ON CONFLICT(guild_id) DO UPDATE SET enabled=excluded.enabled,channel=excluded.channel",
            (gid, _int(data.get("enabled", False)), str(data.get("channel", ""))),
        )
        cx.execute("DELETE FROM cfg_serverlog_event WHERE guild_id=?", (gid,))
        for k, v in data.get("events", _SL_EVENTS_DEF).items():
            cx.execute(
                "INSERT INTO cfg_serverlog_event (guild_id,event_key,enabled) VALUES (?,?,?)",
                (gid, str(k), int(bool(v))),
            )


# ── Warn config ───────────────────────────────────────────────────────────────

_WC_DEF = _DD["warn_config"]


def load_warn_config(gid: int) -> dict:
    rows = db.query("SELECT * FROM cfg_warn WHERE guild_id=?", (gid,))
    if not rows:
        return dict(_WC_DEF)
    r = rows[0]
    step_rows = db.query(
        "SELECT * FROM cfg_warn_step WHERE guild_id=? ORDER BY pos", (gid,)
    )
    steps = [
        {"warns": s["warns"], "action": s["action"],
         "duration": s["duration"], "dm": bool(s["dm"])}
        for s in step_rows
    ]
    if not steps:
        steps = list(_WC_DEF["steps"])
    return {
        "enabled":     bool(r["enabled"]),
        "expiry_days": _int(r["expiry_days"]),
        "steps":       steps,
    }


def save_warn_config(gid: int, data: dict) -> None:
    db.ensure_guild(gid)
    with db.transaction() as cx:
        cx.execute(
            "INSERT INTO cfg_warn (guild_id,enabled,expiry_days) VALUES (?,?,?) "
            "ON CONFLICT(guild_id) DO UPDATE SET enabled=excluded.enabled,expiry_days=excluded.expiry_days",
            (gid, _int(data.get("enabled", True)), _int(data.get("expiry_days", 0))),
        )
        cx.execute("DELETE FROM cfg_warn_step WHERE guild_id=?", (gid,))
        for pos, s in enumerate(data.get("steps", [])):
            cx.execute(
                "INSERT INTO cfg_warn_step (guild_id,pos,warns,action,duration,dm) VALUES (?,?,?,?,?,?)",
                (gid, pos, _int(s.get("warns", 0)), str(s.get("action", "")),
                 _int(s.get("duration", 0)), int(bool(s.get("dm", True)))),
            )


# ── Antispam ──────────────────────────────────────────────────────────────────

_AS_DEF = _DD["antispam"]


def load_antispam(gid: int) -> dict:
    rows = db.query("SELECT * FROM cfg_antispam WHERE guild_id=?", (gid,))
    if not rows:
        return dict(_AS_DEF)
    r = rows[0]
    wl_ch = _load_list_col("cfg_antispam_wl_channel", gid)
    wl_ro = _load_list_col("cfg_antispam_wl_role", gid)
    return {
        "enabled":              bool(r["enabled"]),
        "max_messages":         _int(r["max_messages"]),
        "interval":             _int(r["interval"]),
        "max_duplicates":       _int(r["max_duplicates"]),
        "duplicate_window":     _int(r["duplicate_window"]),
        "action":               str(r["action"]),
        "whitelisted_channels": wl_ch,
        "whitelisted_roles":    wl_ro,
    }


def save_antispam(gid: int, data: dict) -> None:
    db.ensure_guild(gid)
    with db.transaction() as cx:
        cx.execute(
            "INSERT INTO cfg_antispam (guild_id,enabled,max_messages,interval,"
            "max_duplicates,duplicate_window,action) VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT(guild_id) DO UPDATE SET "
            "enabled=excluded.enabled,max_messages=excluded.max_messages,"
            "interval=excluded.interval,max_duplicates=excluded.max_duplicates,"
            "duplicate_window=excluded.duplicate_window,action=excluded.action",
            (
                gid,
                _int(data.get("enabled", False)),
                _int(data.get("max_messages", 5)),
                _int(data.get("interval", 5)),
                _int(data.get("max_duplicates", 3)),
                _int(data.get("duplicate_window", 60)),
                str(data.get("action", "mute")),
            ),
        )
        cx.execute("DELETE FROM cfg_antispam_wl_channel WHERE guild_id=?", (gid,))
        for pos, v in enumerate(data.get("whitelisted_channels", [])):
            cx.execute(
                "INSERT INTO cfg_antispam_wl_channel (guild_id,pos,value) VALUES (?,?,?)",
                (gid, pos, json.dumps(v)),
            )
        cx.execute("DELETE FROM cfg_antispam_wl_role WHERE guild_id=?", (gid,))
        for pos, v in enumerate(data.get("whitelisted_roles", [])):
            cx.execute(
                "INSERT INTO cfg_antispam_wl_role (guild_id,pos,value) VALUES (?,?,?)",
                (gid, pos, json.dumps(v)),
            )


# ── Stats channels ────────────────────────────────────────────────────────────

_SC_DEF = _DD["stats_channels"]
_SC_STAT_KEYS = ["members", "humans", "bots", "channels", "roles"]


def load_stats_channels(gid: int) -> dict:
    rows = db.query("SELECT * FROM cfg_stats_channels WHERE guild_id=?", (gid,))
    if not rows:
        return dict(_SC_DEF)
    r = rows[0]
    item_rows = db.query(
        "SELECT * FROM cfg_stats_channel_item WHERE guild_id=?", (gid,)
    )
    stats: dict = {k: dict(_SC_DEF["stats"][k]) for k in _SC_STAT_KEYS}
    for ir in item_rows:
        k = ir["stat_key"]
        if k in stats:
            stats[k] = {"enabled": bool(ir["enabled"]),
                        "channel_id": str(ir["channel_id"]),
                        "template": str(ir["template"])}
    return {
        "enabled":     bool(r["enabled"]),
        "category_id": str(r["category_id"]),
        "stats":       stats,
    }


def save_stats_channels(gid: int, data: dict) -> None:
    db.ensure_guild(gid)
    with db.transaction() as cx:
        cx.execute(
            "INSERT INTO cfg_stats_channels (guild_id,enabled,category_id) VALUES (?,?,?) "
            "ON CONFLICT(guild_id) DO UPDATE SET enabled=excluded.enabled,category_id=excluded.category_id",
            (gid, _int(data.get("enabled", False)), str(data.get("category_id", ""))),
        )
        cx.execute("DELETE FROM cfg_stats_channel_item WHERE guild_id=?", (gid,))
        for k, v in data.get("stats", {}).items():
            cx.execute(
                "INSERT INTO cfg_stats_channel_item (guild_id,stat_key,enabled,channel_id,template) "
                "VALUES (?,?,?,?,?)",
                (gid, str(k), int(bool(v.get("enabled", False))),
                 str(v.get("channel_id", "")), str(v.get("template", ""))),
            )


# ── Auto roles ────────────────────────────────────────────────────────────────

_AR_DEF = _DD["auto_roles"]


def load_auto_roles(gid: int) -> dict:
    rows = db.query("SELECT * FROM cfg_auto_roles WHERE guild_id=?", (gid,))
    if not rows:
        return dict(_AR_DEF)
    r = rows[0]
    roles = _load_list_col("cfg_auto_role", gid)
    return {"enabled": bool(r["enabled"]), "roles": roles}


def save_auto_roles(gid: int, data: dict) -> None:
    db.ensure_guild(gid)
    with db.transaction() as cx:
        cx.execute(
            "INSERT INTO cfg_auto_roles (guild_id,enabled) VALUES (?,?) "
            "ON CONFLICT(guild_id) DO UPDATE SET enabled=excluded.enabled",
            (gid, _int(data.get("enabled", False))),
        )
        cx.execute("DELETE FROM cfg_auto_role WHERE guild_id=?", (gid,))
        for pos, v in enumerate(data.get("roles", [])):
            cx.execute(
                "INSERT INTO cfg_auto_role (guild_id,pos,value) VALUES (?,?,?)",
                (gid, pos, json.dumps(v)),
            )


# ── Temp voice config ─────────────────────────────────────────────────────────

_TV_DEF = _DD["temp_voice"]


def load_temp_voice_cfg(gid: int) -> dict:
    rows = db.query("SELECT * FROM cfg_temp_voice WHERE guild_id=?", (gid,))
    if not rows:
        return dict(_TV_DEF)
    r = rows[0]
    pr = _load_list_col("cfg_temp_voice_persist_role", gid)
    tr_rows = db.query(
        "SELECT * FROM cfg_temp_voice_trigger WHERE guild_id=? ORDER BY pos", (gid,)
    )
    triggers = [
        {"create_channel_id": t["create_channel_id"],
         "category_id":       t["category_id"],
         "name_template":     t["name_template"]}
        for t in tr_rows
    ]
    if not triggers:
        triggers = list(_TV_DEF["triggers"])
    return {
        "enabled":      bool(r["enabled"]),
        "persist_roles": pr,
        "triggers":     triggers,
    }


def save_temp_voice_cfg(gid: int, data: dict) -> None:
    db.ensure_guild(gid)
    with db.transaction() as cx:
        cx.execute(
            "INSERT INTO cfg_temp_voice (guild_id,enabled) VALUES (?,?) "
            "ON CONFLICT(guild_id) DO UPDATE SET enabled=excluded.enabled",
            (gid, _int(data.get("enabled", False))),
        )
        cx.execute("DELETE FROM cfg_temp_voice_persist_role WHERE guild_id=?", (gid,))
        for pos, v in enumerate(data.get("persist_roles", [])):
            cx.execute(
                "INSERT INTO cfg_temp_voice_persist_role (guild_id,pos,value) VALUES (?,?,?)",
                (gid, pos, json.dumps(v)),
            )
        cx.execute("DELETE FROM cfg_temp_voice_trigger WHERE guild_id=?", (gid,))
        for pos, t in enumerate(data.get("triggers", [])):
            cx.execute(
                "INSERT INTO cfg_temp_voice_trigger "
                "(guild_id,pos,create_channel_id,category_id,name_template) VALUES (?,?,?,?,?)",
                (gid, pos,
                 str(t.get("create_channel_id", "")),
                 str(t.get("category_id", "")),
                 str(t.get("name_template", "{user}'s Channel"))),
            )


# ── Verify ────────────────────────────────────────────────────────────────────

_VF_DEF = _DD["verify"]


def load_verify(gid: int) -> dict:
    rows = db.query("SELECT * FROM cfg_verify WHERE guild_id=?", (gid,))
    if not rows:
        return dict(_VF_DEF)
    r = rows[0]
    return {
        "enabled":          bool(r["enabled"]),
        "rid":              _int(r["rid"]) if r["rid"] is not None else 0,
        "verify_option":    _int(r["verify_option"]) if r["verify_option"] is not None else 0,
        "password":         str(r["password"]),
        "channel":          str(r["channel"]),
        "panel_message_id": str(r["panel_message_id"]),
        "title":            str(r["title"]),
        "description":      str(r["description"]),
        "color":            str(r["color"]),
    }


def save_verify(gid: int, data: dict) -> None:
    db.ensure_guild(gid)
    db.execute(
        "INSERT INTO cfg_verify "
        "(guild_id,enabled,rid,verify_option,password,channel,panel_message_id,title,description,color) "
        "VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(guild_id) DO UPDATE SET "
        "enabled=excluded.enabled,rid=excluded.rid,verify_option=excluded.verify_option,"
        "password=excluded.password,channel=excluded.channel,"
        "panel_message_id=excluded.panel_message_id,title=excluded.title,"
        "description=excluded.description,color=excluded.color",
        (
            gid,
            _int(data.get("enabled", False)),
            _int(data.get("rid", 0)),
            _int(data.get("verify_option", 0)),
            str(data.get("password", "")),
            str(data.get("channel", "")),
            str(data.get("panel_message_id", "")),
            str(data.get("title", "Verification")),
            str(data.get("description", _VF_DEF["description"])),
            str(data.get("color", "#FF6B4A")),
        ),
    )


# ── Auto slowmode ─────────────────────────────────────────────────────────────

_ASM_DEF = _DD["auto_slowmode"]


def load_auto_slowmode(gid: int) -> dict:
    rows = db.query("SELECT * FROM cfg_auto_slowmode WHERE guild_id=?", (gid,))
    if not rows:
        return dict(_ASM_DEF)
    r = rows[0]
    return {
        "enabled":        bool(r["enabled"]),
        "threshold":      _int(r["threshold"]),
        "interval":       _int(r["interval"]),
        "slowmode_delay": _int(r["slowmode_delay"]),
        "duration":       _int(r["duration"]),
    }


def save_auto_slowmode(gid: int, data: dict) -> None:
    db.ensure_guild(gid)
    db.execute(
        "INSERT INTO cfg_auto_slowmode (guild_id,enabled,threshold,interval,slowmode_delay,duration) "
        "VALUES (?,?,?,?,?,?) ON CONFLICT(guild_id) DO UPDATE SET "
        "enabled=excluded.enabled,threshold=excluded.threshold,interval=excluded.interval,"
        "slowmode_delay=excluded.slowmode_delay,duration=excluded.duration",
        (
            gid,
            _int(data.get("enabled", False)),
            _int(data.get("threshold", 10)),
            _int(data.get("interval", 10)),
            _int(data.get("slowmode_delay", 5)),
            _int(data.get("duration", 120)),
        ),
    )


# ── Mod Gate (on-join PRISM gating) ─────────────────────────────────────────────

_MG_DEF = _DD.get("mod_gate", {
    "enabled": False, "threshold": 30, "action": "quarantine",
    "quarantine_role": 0, "log_channel": 0,
})


def load_mod_gate(gid: int) -> dict:
    rows = db.query("SELECT * FROM cfg_mod_gate WHERE guild_id=?", (gid,))
    if not rows:
        return dict(_MG_DEF)
    r = rows[0]
    return {
        "enabled":         bool(r["enabled"]),
        "threshold":       _int(r["threshold"], 30),
        "action":          str(r["action"] or "quarantine"),
        "quarantine_role": _int(r["quarantine_role"]),
        "log_channel":     _int(r["log_channel"]),
        "use_safety_list": bool(r["use_safety_list"]),
    }


def save_mod_gate(gid: int, data: dict) -> None:
    db.ensure_guild(gid)
    action = str(data.get("action", "quarantine"))
    if action not in ("quarantine", "kick", "approve", "notify"):
        action = "quarantine"
    db.execute(
        "INSERT INTO cfg_mod_gate (guild_id,enabled,threshold,action,quarantine_role,log_channel,use_safety_list) "
        "VALUES (?,?,?,?,?,?,?) ON CONFLICT(guild_id) DO UPDATE SET "
        "enabled=excluded.enabled,threshold=excluded.threshold,action=excluded.action,"
        "quarantine_role=excluded.quarantine_role,log_channel=excluded.log_channel,"
        "use_safety_list=excluded.use_safety_list",
        (
            gid,
            _int(data.get("enabled", False)),
            _int(data.get("threshold", 30)),
            action,
            _int(data.get("quarantine_role", 0)),
            _int(data.get("log_channel", 0)),
            _int(data.get("use_safety_list", True)),
        ),
    )


# ── Counting ──────────────────────────────────────────────────────────────────

_CO_DEF = _DD["counting"]


def load_counting(gid: int) -> dict:
    rows = db.query("SELECT * FROM cfg_counting WHERE guild_id=?", (gid,))
    if not rows:
        return dict(_CO_DEF)
    r = rows[0]
    return {
        "enabled":        bool(r["enabled"]),
        "channel":        str(r["channel"]),
        "current_count":  _int(r["current_count"]),
        "high_score":     _int(r["high_score"]),
        "last_user_id":   _int(r["last_user_id"]),
        "no_double_count": bool(r["no_double_count"]),
        "react_correct":  bool(r["react_correct"]),
        "react_wrong":    bool(r["react_wrong"]),
    }


def save_counting(gid: int, data: dict) -> None:
    db.ensure_guild(gid)
    db.execute(
        "INSERT INTO cfg_counting "
        "(guild_id,enabled,channel,current_count,high_score,last_user_id,"
        "no_double_count,react_correct,react_wrong) "
        "VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(guild_id) DO UPDATE SET "
        "enabled=excluded.enabled,channel=excluded.channel,"
        "current_count=excluded.current_count,high_score=excluded.high_score,"
        "last_user_id=excluded.last_user_id,no_double_count=excluded.no_double_count,"
        "react_correct=excluded.react_correct,react_wrong=excluded.react_wrong",
        (
            gid,
            _int(data.get("enabled", False)),
            str(data.get("channel", "")),
            _int(data.get("current_count", 0)),
            _int(data.get("high_score", 0)),
            _int(data.get("last_user_id", 0)),
            int(bool(data.get("no_double_count", True))),
            int(bool(data.get("react_correct", True))),
            int(bool(data.get("react_wrong", True))),
        ),
    )


# ── Reaction roles ────────────────────────────────────────────────────────────

_RR_DEF = _DD["reaction_roles"]
_RR_PANEL_PROMOTED = {"channel_id", "message_id", "title", "description", "color", "max_roles"}
_RR_ENTRY_PROMOTED = {"emoji", "role_id", "label"}


def load_reaction_roles(gid: int) -> dict:
    panel_rows = db.query(
        "SELECT * FROM cfg_rr_panel WHERE guild_id=? ORDER BY pos", (gid,)
    )
    panels = []
    for pr in panel_rows:
        extra = json.loads(pr["extra_json"] or "{}")
        panel: dict = {
            "channel_id":  str(pr["channel_id"] or ""),
            "message_id":  str(pr["message_id"] or ""),
            "title":       str(pr["title"] or ""),
            "description": str(pr["description"] or ""),
            "color":       str(pr["color"] or "#FF6B4A"),
            "max_roles":   _int(pr["max_roles"] or 0),
        }
        panel.update(extra)
        entry_rows = db.query(
            "SELECT * FROM cfg_rr_entry WHERE guild_id=? AND panel_pos=? ORDER BY pos",
            (gid, pr["pos"]),
        )
        entries = []
        for er in entry_rows:
            ej = json.loads(er["extra_json"] or "{}")
            entry: dict = {
                "emoji":   str(er["emoji"] or ""),
                "role_id": str(er["role_id"] or ""),
                "label":   str(er["label"] or ""),
            }
            entry.update(ej)
            entries.append(entry)
        panel["entries"] = entries
        panels.append(panel)
    return {"panels": panels}


def save_reaction_roles(gid: int, data: dict) -> None:
    db.ensure_guild(gid)
    with db.transaction() as cx:
        cx.execute("DELETE FROM cfg_rr_entry WHERE guild_id=?", (gid,))
        cx.execute("DELETE FROM cfg_rr_panel WHERE guild_id=?", (gid,))
        for pp, panel in enumerate(data.get("panels", [])):
            extra_panel = {k: v for k, v in panel.items()
                           if k not in _RR_PANEL_PROMOTED and k != "entries"}
            cx.execute(
                "INSERT INTO cfg_rr_panel (guild_id,pos,channel_id,message_id,title,"
                "description,color,max_roles,extra_json) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    gid, pp,
                    str(panel.get("channel_id", "")),
                    str(panel.get("message_id", "")),
                    str(panel.get("title", "")),
                    str(panel.get("description", "")),
                    str(panel.get("color", "#FF6B4A")),
                    _int(panel.get("max_roles", 0)),
                    json.dumps(extra_panel),
                ),
            )
            for ep, entry in enumerate(panel.get("entries", [])):
                extra_entry = {k: v for k, v in entry.items() if k not in _RR_ENTRY_PROMOTED}
                cx.execute(
                    "INSERT INTO cfg_rr_entry "
                    "(guild_id,panel_pos,pos,emoji,role_id,label,extra_json) VALUES (?,?,?,?,?,?,?)",
                    (
                        gid, pp, ep,
                        str(entry.get("emoji", "")),
                        str(entry.get("role_id", "")),
                        str(entry.get("label", "")),
                        json.dumps(extra_entry),
                    ),
                )


# ── Suggestions ───────────────────────────────────────────────────────────────

_SG_DEF = _DD["suggestions"]


def load_suggestions(gid: int) -> dict:
    rows = db.query("SELECT * FROM cfg_suggestions WHERE guild_id=?", (gid,))
    if not rows:
        return dict(_SG_DEF)
    r = rows[0]
    channels = _load_list_col("cfg_suggestions_channel", gid)
    return {
        "enabled":                bool(r["enabled"]),
        "channels":               channels,
        "staff_role":             str(r["staff_role"]),
        "log_channel":            str(r["log_channel"]),
        "auto_forward_enabled":   bool(r["auto_forward_enabled"]),
        "auto_forward_channel":   str(r["auto_forward_channel"]),
        "auto_forward_threshold": _int(r["auto_forward_threshold"]),
    }


def save_suggestions(gid: int, data: dict) -> None:
    db.ensure_guild(gid)
    with db.transaction() as cx:
        cx.execute(
            "INSERT INTO cfg_suggestions "
            "(guild_id,enabled,staff_role,log_channel,auto_forward_enabled,"
            "auto_forward_channel,auto_forward_threshold) VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT(guild_id) DO UPDATE SET "
            "enabled=excluded.enabled,staff_role=excluded.staff_role,"
            "log_channel=excluded.log_channel,auto_forward_enabled=excluded.auto_forward_enabled,"
            "auto_forward_channel=excluded.auto_forward_channel,"
            "auto_forward_threshold=excluded.auto_forward_threshold",
            (
                gid,
                _int(data.get("enabled", False)),
                str(data.get("staff_role", "")),
                str(data.get("log_channel", "")),
                int(bool(data.get("auto_forward_enabled", False))),
                str(data.get("auto_forward_channel", "")),
                _int(data.get("auto_forward_threshold", 10)),
            ),
        )
        cx.execute("DELETE FROM cfg_suggestions_channel WHERE guild_id=?", (gid,))
        for pos, v in enumerate(data.get("channels", [])):
            cx.execute(
                "INSERT INTO cfg_suggestions_channel (guild_id,pos,value) VALUES (?,?,?)",
                (gid, pos, json.dumps(v)),
            )


# ── Leveling config ───────────────────────────────────────────────────────────

_LV_DEF = _DD["leveling"]


def load_leveling_cfg(gid: int) -> dict:
    rows = db.query("SELECT * FROM cfg_leveling WHERE guild_id=?", (gid,))
    if not rows:
        return dict(_LV_DEF)
    r = rows[0]
    rr_rows = db.query(
        "SELECT * FROM cfg_leveling_reward WHERE guild_id=? ORDER BY pos", (gid,)
    )
    rewards = [{"level": rr["level"], "role_id": str(rr["role_id"])} for rr in rr_rows]
    return {
        "enabled":              bool(r["enabled"]),
        "announcement":         str(r["announcement"]),
        "announcement_channel": str(r["announcement_channel"]),
        "role_rewards":         rewards,
    }


def save_leveling_cfg(gid: int, data: dict) -> None:
    db.ensure_guild(gid)
    with db.transaction() as cx:
        cx.execute(
            "INSERT INTO cfg_leveling (guild_id,enabled,announcement,announcement_channel) "
            "VALUES (?,?,?,?) ON CONFLICT(guild_id) DO UPDATE SET "
            "enabled=excluded.enabled,announcement=excluded.announcement,"
            "announcement_channel=excluded.announcement_channel",
            (
                gid,
                _int(data.get("enabled", False)),
                str(data.get("announcement", "same_channel")),
                str(data.get("announcement_channel", "")),
            ),
        )
        cx.execute("DELETE FROM cfg_leveling_reward WHERE guild_id=?", (gid,))
        for pos, rr in enumerate(data.get("role_rewards", [])):
            cx.execute(
                "INSERT INTO cfg_leveling_reward (guild_id,pos,level,role_id) VALUES (?,?,?,?)",
                (gid, pos, _int(rr.get("level", 0)), str(rr.get("role_id", ""))),
            )


# ── Auto release ──────────────────────────────────────────────────────────────

_ARL_DEF = _DD["auto_release"]


def load_auto_release(gid: int) -> dict:
    rows = db.query("SELECT * FROM cfg_auto_release WHERE guild_id=?", (gid,))
    if not rows:
        return dict(_ARL_DEF)
    r = rows[0]
    channels = _load_list_col("cfg_auto_release_channel", gid)
    return {
        "enabled":     bool(r["enabled"]),
        "channels":    channels,
        "ignore_bots": bool(r["ignore_bots"]),
    }


def save_auto_release(gid: int, data: dict) -> None:
    db.ensure_guild(gid)
    with db.transaction() as cx:
        cx.execute(
            "INSERT INTO cfg_auto_release (guild_id,enabled,ignore_bots) VALUES (?,?,?) "
            "ON CONFLICT(guild_id) DO UPDATE SET enabled=excluded.enabled,ignore_bots=excluded.ignore_bots",
            (gid, _int(data.get("enabled", False)), int(bool(data.get("ignore_bots", True)))),
        )
        cx.execute("DELETE FROM cfg_auto_release_channel WHERE guild_id=?", (gid,))
        for pos, v in enumerate(data.get("channels", [])):
            cx.execute(
                "INSERT INTO cfg_auto_release_channel (guild_id,pos,value) VALUES (?,?,?)",
                (gid, pos, json.dumps(v)),
            )


# ── MC link config ────────────────────────────────────────────────────────────

_MCL_DEF = _DD["mc_link"]
_MCL_BOOLS = {"enabled", "dm_on_link", "allow_self_unlink", "dm_announcements",
              "chat_enabled"}
_MCL_COLS = list(_MCL_DEF.keys())


def load_mc_link_cfg(gid: int) -> dict:
    rows = db.query("SELECT * FROM cfg_mc_link WHERE guild_id=?", (gid,))
    if not rows:
        return dict(_MCL_DEF)
    r = rows[0]
    return {
        "enabled":              bool(r["enabled"]),
        "api_url":              str(r["api_url"]),
        "api_secret":           str(r["api_secret"]),
        "role_id":              str(r["role_id"]),
        "announce_channel":     str(r["announce_channel"]),
        "dm_on_link":           bool(r["dm_on_link"]),
        "allow_self_unlink":    bool(r["allow_self_unlink"]),
        "announcement_channel": str(r["announcement_channel"]),
        "dm_announcements":     bool(r["dm_announcements"]),
        "chat_enabled":         bool(r["chat_enabled"]),
        "chat_channel":         str(r["chat_channel"]),
        "chat_webhook_url":     str(r["chat_webhook_url"]),
    }


def save_mc_link_cfg(gid: int, data: dict) -> None:
    db.ensure_guild(gid)
    db.execute(
        "INSERT INTO cfg_mc_link "
        "(guild_id,enabled,api_url,api_secret,role_id,announce_channel,dm_on_link,"
        "allow_self_unlink,announcement_channel,dm_announcements,chat_enabled,"
        "chat_channel,chat_webhook_url) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(guild_id) DO UPDATE SET "
        "enabled=excluded.enabled,api_url=excluded.api_url,api_secret=excluded.api_secret,"
        "role_id=excluded.role_id,announce_channel=excluded.announce_channel,"
        "dm_on_link=excluded.dm_on_link,allow_self_unlink=excluded.allow_self_unlink,"
        "announcement_channel=excluded.announcement_channel,"
        "dm_announcements=excluded.dm_announcements,chat_enabled=excluded.chat_enabled,"
        "chat_channel=excluded.chat_channel,chat_webhook_url=excluded.chat_webhook_url",
        (
            gid,
            _int(data.get("enabled", False)),
            str(data.get("api_url", "")),
            str(data.get("api_secret", "")),
            str(data.get("role_id", "")),
            str(data.get("announce_channel", "")),
            int(bool(data.get("dm_on_link", False))),
            int(bool(data.get("allow_self_unlink", True))),
            str(data.get("announcement_channel", "")),
            int(bool(data.get("dm_announcements", False))),
            int(bool(data.get("chat_enabled", False))),
            str(data.get("chat_channel", "")),
            str(data.get("chat_webhook_url", "")),
        ),
    )


# ── Music ─────────────────────────────────────────────────────────────────────

_MU_DEF = _DD["music"]


def load_music(gid: int) -> dict:
    rows = db.query("SELECT * FROM cfg_music WHERE guild_id=?", (gid,))
    if not rows:
        return dict(_MU_DEF)
    r = rows[0]
    sources = _load_list_col("cfg_music_source", gid)
    radio_wl = _load_list_col("cfg_music_radio_wl", gid)
    if not sources:
        sources = list(_MU_DEF["allowed_sources"])
    return {
        "enabled":                bool(r["enabled"]),
        "queue_limit":            _int(r["queue_limit"]),
        "default_volume":         _int(r["default_volume"]),
        "max_song_duration":      _int(r["max_song_duration"]),
        "disconnect_timeout":     _int(r["disconnect_timeout"]),
        "allowed_sources":        sources,
        "radio_whitelist":        radio_wl,
        "allow_all_radios":       bool(r["allow_all_radios"]),
        "radio_247_enabled":      bool(r["radio_247_enabled"]),
        "radio_247_channel_id":   str(r["radio_247_channel_id"]),
        "radio_247_text_channel_id": str(r["radio_247_text_channel_id"]),
        "radio_247_url":          str(r["radio_247_url"]),
    }


def save_music(gid: int, data: dict) -> None:
    db.ensure_guild(gid)
    with db.transaction() as cx:
        cx.execute(
            "INSERT INTO cfg_music "
            "(guild_id,enabled,queue_limit,default_volume,max_song_duration,"
            "disconnect_timeout,allow_all_radios,radio_247_enabled,"
            "radio_247_channel_id,radio_247_text_channel_id,radio_247_url) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(guild_id) DO UPDATE SET "
            "enabled=excluded.enabled,queue_limit=excluded.queue_limit,"
            "default_volume=excluded.default_volume,max_song_duration=excluded.max_song_duration,"
            "disconnect_timeout=excluded.disconnect_timeout,"
            "allow_all_radios=excluded.allow_all_radios,"
            "radio_247_enabled=excluded.radio_247_enabled,"
            "radio_247_channel_id=excluded.radio_247_channel_id,"
            "radio_247_text_channel_id=excluded.radio_247_text_channel_id,"
            "radio_247_url=excluded.radio_247_url",
            (
                gid,
                int(bool(data.get("enabled", True))),
                _int(data.get("queue_limit", 50)),
                _int(data.get("default_volume", 100)),
                _int(data.get("max_song_duration", 600)),
                _int(data.get("disconnect_timeout", 300)),
                int(bool(data.get("allow_all_radios", False))),
                int(bool(data.get("radio_247_enabled", False))),
                str(data.get("radio_247_channel_id", "")),
                str(data.get("radio_247_text_channel_id", "")),
                str(data.get("radio_247_url", "")),
            ),
        )
        cx.execute("DELETE FROM cfg_music_source WHERE guild_id=?", (gid,))
        for pos, v in enumerate(data.get("allowed_sources", _MU_DEF["allowed_sources"])):
            cx.execute(
                "INSERT INTO cfg_music_source (guild_id,pos,value) VALUES (?,?,?)",
                (gid, pos, json.dumps(v)),
            )
        cx.execute("DELETE FROM cfg_music_radio_wl WHERE guild_id=?", (gid,))
        for pos, v in enumerate(data.get("radio_whitelist", [])):
            cx.execute(
                "INSERT INTO cfg_music_radio_wl (guild_id,pos,value) VALUES (?,?,?)",
                (gid, pos, json.dumps(v)),
            )


# ── Donations ─────────────────────────────────────────────────────────────────

_DN_DEF = _DD["donations"]


def load_donations(gid: int) -> dict:
    rows = db.query("SELECT * FROM cfg_donations WHERE guild_id=?", (gid,))
    if not rows:
        return dict(_DN_DEF)
    r = rows[0]
    tier_rows = db.query(
        "SELECT tier_json FROM cfg_donation_tier WHERE guild_id=? ORDER BY pos", (gid,)
    )
    tiers = [json.loads(t["tier_json"]) for t in tier_rows]
    return {
        "enabled":               bool(r["enabled"]),
        "provider":              str(r["provider"]),
        "stripe_secret_key":     str(r["stripe_secret_key"]),
        "stripe_webhook_secret": str(r["stripe_webhook_secret"]),
        "paypal_client_id":      str(r["paypal_client_id"]),
        "paypal_client_secret":  str(r["paypal_client_secret"]),
        "page_text":             str(r["page_text"]),
        "success_text":          str(r["success_text"]),
        "log_enabled":           bool(r["log_enabled"]),
        "log_channel":           str(r["log_channel"]),
        "tiers":                 tiers,
    }


def save_donations(gid: int, data: dict) -> None:
    db.ensure_guild(gid)
    with db.transaction() as cx:
        cx.execute(
            "INSERT INTO cfg_donations "
            "(guild_id,enabled,provider,stripe_secret_key,stripe_webhook_secret,"
            "paypal_client_id,paypal_client_secret,page_text,success_text,log_enabled,log_channel) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(guild_id) DO UPDATE SET "
            "enabled=excluded.enabled,provider=excluded.provider,"
            "stripe_secret_key=excluded.stripe_secret_key,"
            "stripe_webhook_secret=excluded.stripe_webhook_secret,"
            "paypal_client_id=excluded.paypal_client_id,"
            "paypal_client_secret=excluded.paypal_client_secret,"
            "page_text=excluded.page_text,success_text=excluded.success_text,"
            "log_enabled=excluded.log_enabled,log_channel=excluded.log_channel",
            (
                gid,
                _int(data.get("enabled", False)),
                str(data.get("provider", "stripe")),
                str(data.get("stripe_secret_key", "")),
                str(data.get("stripe_webhook_secret", "")),
                str(data.get("paypal_client_id", "")),
                str(data.get("paypal_client_secret", "")),
                str(data.get("page_text", _DN_DEF["page_text"])),
                str(data.get("success_text", _DN_DEF["success_text"])),
                int(bool(data.get("log_enabled", False))),
                str(data.get("log_channel", "")),
            ),
        )
        cx.execute("DELETE FROM cfg_donation_tier WHERE guild_id=?", (gid,))
        for pos, t in enumerate(data.get("tiers", [])):
            cx.execute(
                "INSERT INTO cfg_donation_tier (guild_id,pos,tier_json) VALUES (?,?,?)",
                (gid, pos, json.dumps(t)),
            )


# ── Flag quiz config ──────────────────────────────────────────────────────────

_FQ_DEF = _DD["flag_quiz"]


def load_flag_quiz(gid: int) -> dict:
    rows = db.query("SELECT * FROM cfg_flag_quiz WHERE guild_id=?", (gid,))
    if not rows:
        return dict(_FQ_DEF)
    r = rows[0]
    score_rows = db.query(
        "SELECT user_id, score FROM cfg_flag_quiz_score WHERE guild_id=?", (gid,)
    )
    scores = {sr["user_id"]: sr["score"] for sr in score_rows}
    recent_rows = db.query(
        "SELECT flag FROM cfg_flag_quiz_recent WHERE guild_id=? ORDER BY pos", (gid,)
    )
    recent = [rr["flag"] for rr in recent_rows]
    return {
        "enabled":             bool(r["enabled"]),
        "channel":             str(r["channel"]),
        "hint_after_attempts": _int(r["hint_after_attempts"]),
        "next_delay":          _int(r["next_delay"]),
        "points_enabled":      bool(r["points_enabled"]),
        "scores":              scores,
        "recent_flags":        recent,
    }


def save_flag_quiz(gid: int, data: dict) -> None:
    db.ensure_guild(gid)
    with db.transaction() as cx:
        cx.execute(
            "INSERT INTO cfg_flag_quiz "
            "(guild_id,enabled,channel,hint_after_attempts,next_delay,points_enabled) "
            "VALUES (?,?,?,?,?,?) ON CONFLICT(guild_id) DO UPDATE SET "
            "enabled=excluded.enabled,channel=excluded.channel,"
            "hint_after_attempts=excluded.hint_after_attempts,next_delay=excluded.next_delay,"
            "points_enabled=excluded.points_enabled",
            (
                gid,
                _int(data.get("enabled", False)),
                str(data.get("channel", "")),
                _int(data.get("hint_after_attempts", 3)),
                _int(data.get("next_delay", 3)),
                int(bool(data.get("points_enabled", True))),
            ),
        )
        cx.execute("DELETE FROM cfg_flag_quiz_score WHERE guild_id=?", (gid,))
        for uid, score in data.get("scores", {}).items():
            cx.execute(
                "INSERT INTO cfg_flag_quiz_score (guild_id,user_id,score) VALUES (?,?,?)",
                (gid, str(uid), int(score)),
            )
        cx.execute("DELETE FROM cfg_flag_quiz_recent WHERE guild_id=?", (gid,))
        for pos, flag in enumerate(data.get("recent_flags", [])):
            cx.execute(
                "INSERT INTO cfg_flag_quiz_recent (guild_id,pos,flag) VALUES (?,?,?)",
                (gid, pos, str(flag)),
            )
