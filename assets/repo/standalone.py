"""
assets/repo/standalone.py — mc_links, trust profiles+events,
temp_voice owners/profiles/permanent, ai_feedback.
"""
from __future__ import annotations

import json

import assets.db as db

_MC_PROMOTED = {"uuid", "name", "linked_at", "bedrock_uuid", "bedrock_name"}
_TRUST_PROMOTED = {
    "name", "score", "auto_flagged", "opted_out",
    "account_age_days", "account_created_at",
    "first_seen", "last_seen", "risk_signals",
    "llm_summary", "llm_summary_updated",
}
_TRUST_EV_PROMOTED = {"type", "reason", "guild_id", "timestamp"}


# ── MC links ──────────────────────────────────────────────────────────────────

def load_mc_links() -> dict:
    rows = db.query("SELECT * FROM mc_links")
    out: dict = {}
    for r in rows:
        extra = json.loads(r["extra_json"] or "{}")
        entry: dict = {
            "uuid":         str(r["uuid"] or ""),
            "name":         str(r["name"] or ""),
            "linked_at":    r["linked_at"],
            "bedrock_uuid": r["bedrock_uuid"],
            "bedrock_name": r["bedrock_name"],
        }
        entry.update(extra)
        gid = r["guild_id"]
        did = r["discord_id"]
        out.setdefault(gid, {})[did] = entry
    return out


def save_mc_links(data: dict) -> None:
    with db.transaction() as cx:
        cx.execute("DELETE FROM mc_links")
        for gid, users in data.items():
            for did, entry in users.items():
                extra = {k: v for k, v in entry.items() if k not in _MC_PROMOTED}
                cx.execute(
                    "INSERT INTO mc_links "
                    "(guild_id,discord_id,uuid,name,linked_at,bedrock_uuid,bedrock_name,extra_json) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (
                        str(gid), str(did),
                        str(entry.get("uuid", "")),
                        str(entry.get("name", "")),
                        entry.get("linked_at"),
                        entry.get("bedrock_uuid"),
                        entry.get("bedrock_name"),
                        json.dumps(extra),
                    ),
                )


# ── Trust profiles ────────────────────────────────────────────────────────────

def load_trust() -> dict:
    profiles = db.query("SELECT * FROM trust_profiles")
    out: dict = {}
    for p in profiles:
        events_rows = db.query(
            "SELECT * FROM trust_event WHERE user_id=? ORDER BY pos", (p["user_id"],)
        )
        events = []
        for e in events_rows:
            extra = json.loads(e["extra_json"] or "{}")
            ev: dict = {
                "type":      e["type"],
                "reason":    e["reason"],
                "guild_id":  e["guild_id"],
                "timestamp": e["timestamp"],
            }
            ev.update(extra)
            events.append(ev)

        extra_p = json.loads(p["extra_json"] or "{}")
        profile: dict = {
            "name":                str(p["name"] or ""),
            "score":               int(p["score"] or 100),
            "auto_flagged":        bool(p["auto_flagged"]),
            "opted_out":           bool(p["opted_out"]),
            "account_age_days":    p["account_age_days"],
            "account_created_at":  p["account_created_at"],
            "first_seen":          p["first_seen"],
            "last_seen":           p["last_seen"],
            "risk_signals":        json.loads(p["risk_signals_json"] or "[]"),
            "llm_summary":         p["llm_summary"],
            "llm_summary_updated": p["llm_summary_updated"],
            "events":              events,
        }
        profile.update(extra_p)
        out[p["user_id"]] = profile
    return out


def save_trust(data: dict) -> None:
    with db.transaction() as cx:
        cx.execute("DELETE FROM trust_event")
        cx.execute("DELETE FROM trust_profiles")
        for uid, profile in data.items():
            extra_p = {k: v for k, v in profile.items()
                       if k not in _TRUST_PROMOTED and k != "events"}
            cx.execute(
                "INSERT INTO trust_profiles "
                "(user_id,name,score,auto_flagged,opted_out,account_age_days,"
                "account_created_at,first_seen,last_seen,risk_signals_json,"
                "llm_summary,llm_summary_updated,extra_json) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(uid),
                    str(profile.get("name", "")),
                    int(profile.get("score", 100)),
                    int(bool(profile.get("auto_flagged", False))),
                    int(bool(profile.get("opted_out", False))),
                    profile.get("account_age_days"),
                    profile.get("account_created_at"),
                    profile.get("first_seen"),
                    profile.get("last_seen"),
                    json.dumps(profile.get("risk_signals", [])),
                    profile.get("llm_summary"),
                    profile.get("llm_summary_updated"),
                    json.dumps(extra_p),
                ),
            )
            for pos, ev in enumerate(profile.get("events", [])):
                extra_e = {k: v for k, v in ev.items() if k not in _TRUST_EV_PROMOTED}
                cx.execute(
                    "INSERT INTO trust_event "
                    "(user_id,pos,type,reason,guild_id,timestamp,extra_json) VALUES (?,?,?,?,?,?,?)",
                    (
                        str(uid), pos,
                        ev.get("type", ""),
                        ev.get("reason", ""),
                        str(ev.get("guild_id", "")),
                        str(ev.get("timestamp", "")),
                        json.dumps(extra_e),
                    ),
                )


# ── Temp voice owners ─────────────────────────────────────────────────────────

def load_temp_voice_owners() -> dict:
    rows = db.query("SELECT * FROM temp_voice_owners")
    return {
        str(r["channel_id"]): {
            "owner_id": int(r["owner_id"]),
            "guild_id": int(r["guild_id"]),
        }
        for r in rows
    }


def save_temp_voice_owners(data: dict) -> None:
    with db.transaction() as cx:
        cx.execute("DELETE FROM temp_voice_owners")
        for ch_id, v in data.items():
            cx.execute(
                "INSERT INTO temp_voice_owners (channel_id,owner_id,guild_id) VALUES (?,?,?)",
                (int(ch_id), int(v["owner_id"]), int(v["guild_id"])),
            )


# ── Temp voice profiles ───────────────────────────────────────────────────────

def load_temp_voice_profiles() -> dict:
    rows = db.query("SELECT profile_key, data_json FROM temp_voice_profiles")
    return {r["profile_key"]: json.loads(r["data_json"]) for r in rows}


def save_temp_voice_profiles(data: dict) -> None:
    with db.transaction() as cx:
        cx.execute("DELETE FROM temp_voice_profiles")
        for key, v in data.items():
            cx.execute(
                "INSERT INTO temp_voice_profiles (profile_key,data_json) VALUES (?,?)",
                (str(key), json.dumps(v)),
            )


# ── Temp voice permanent ──────────────────────────────────────────────────────

def load_temp_voice_permanent() -> list:
    rows = db.query("SELECT channel_id FROM temp_voice_permanent")
    return [int(r["channel_id"]) for r in rows]


def save_temp_voice_permanent(data: list) -> None:
    with db.transaction() as cx:
        cx.execute("DELETE FROM temp_voice_permanent")
        for ch_id in data:
            cx.execute(
                "INSERT OR IGNORE INTO temp_voice_permanent (channel_id) VALUES (?)", (int(ch_id),)
            )


# ── AI feedback ───────────────────────────────────────────────────────────────

def load_ai_feedback() -> list:
    rows = db.query("SELECT * FROM ai_feedback ORDER BY pos")
    result = []
    for r in rows:
        result.append({
            "message": r["message"],
            "ai_said": r["ai_said"],
            "correct": r["correct"],
            "reason":  r["reason"],
            "admin":   r["admin"],
            "log_id":  r["log_id"],
        })
    return result


def save_ai_feedback(data: list) -> None:
    with db.transaction() as cx:
        cx.execute("DELETE FROM ai_feedback")
        for entry in data:
            cx.execute(
                "INSERT INTO ai_feedback (message,ai_said,correct,reason,admin,log_id) "
                "VALUES (?,?,?,?,?,?)",
                (
                    entry.get("message", ""),
                    entry.get("ai_said", ""),
                    entry.get("correct", ""),
                    entry.get("reason", ""),
                    entry.get("admin", ""),
                    entry.get("log_id", ""),
                ),
            )
