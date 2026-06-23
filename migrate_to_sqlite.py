"""One-shot, idempotent migration: per-guild JSON files -> baxi_data.db.

Reuses the validated repo facade (assets.data.save_data / save_temp_actions) for
everything routable, plus the standalone repo functions for the flat globals.
After a successful import it MOVES the old JSON into data_backup_pre_sqlite/
(preserving the tree). data/safetext/ and lang/lang.json are left in place.

Safe to re-run: guarded by schema_meta.migration_complete. Call `run()`.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import datetime

import assets.db as db
import assets.data as datasys
import assets.repo as repo
from assets.repo import standalone as _standalone

_DATA = "data"
_BACKUP = "data_backup_pre_sqlite"

# standalone per-guild file -> load_data/save_data sys key
_GUILD_FILES = {
    "tickets.json":                  "open_tickets",
    "transcripts.json":              "transcripts",
    "users.json":                    "users",
    "stats.json":                    "stats",
    "chatfilter_log.json":           "chatfilter_log",
    "globalchat_message_data.json":  "globalchat_message_data",
    "activity.json":                 "activity",
    "mod_events.json":               "mod_events",
    "filter_events.json":            "filter_events",
    "leveling_users.json":           "leveling_users",
}

_counts: dict[str, int] = {}


def _bump(label: str, n: int = 1) -> None:
    _counts[label] = _counts.get(label, 0) + n


def _read(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        print(f"[migrate] read failed {path}: {exc}", file=sys.stderr)
        return None


def _migrate_guild_dir(gid: int, gdir: str) -> None:
    # conf.json: dispatch every key through save_data (handles conf systems,
    # runtime keys, scalars, and the 1001 bag keys via is_1001_key routing).
    conf_path = os.path.join(gdir, "conf.json")
    if os.path.exists(conf_path):
        conf = _read(conf_path)
        if isinstance(conf, dict):
            for key, val in conf.items():
                try:
                    datasys.save_data(gid, key, val)
                    _bump(f"conf:{key}")
                except Exception as exc:
                    print(f"[migrate] guild {gid} conf key {key}: {exc}", file=sys.stderr)

    # standalone per-guild files
    for fname, syskey in _GUILD_FILES.items():
        path = os.path.join(gdir, fname)
        if not os.path.exists(path):
            continue
        data = _read(path)
        if data is None:
            continue
        try:
            datasys.save_data(gid, syskey, data)
            _bump(syskey, len(data) if hasattr(data, "__len__") else 1)
        except Exception as exc:
            print(f"[migrate] guild {gid} {fname}: {exc}", file=sys.stderr)

    # temp_actions via the dedicated API
    ta_path = os.path.join(gdir, "temp_actions.json")
    if os.path.exists(ta_path):
        ta = _read(ta_path)
        if isinstance(ta, dict):
            try:
                datasys.save_temp_actions(gid, ta)
                _bump("temp_actions", len(ta.get("bans", [])) + len(ta.get("timeouts", [])))
            except Exception as exc:
                print(f"[migrate] guild {gid} temp_actions: {exc}", file=sys.stderr)


def _migrate_flat_globals() -> None:
    mc = os.path.join(_DATA, "mc_links.json")
    if os.path.exists(mc):
        d = _read(mc)
        if isinstance(d, dict):
            _standalone.save_mc_links(d); _bump("mc_links", len(d))

    # Trust profiles are intentionally NOT migrated: the cross-server behavioral profile
    # (score + event dossier + LLM summaries) was removed for Discord Developer Policy
    # compliance. Any legacy data/1001/trust.json is ignored on purpose.

    owners = os.path.join(_DATA, "temp_voice_owners.json")
    if os.path.exists(owners):
        d = _read(owners)
        if isinstance(d, dict):
            _standalone.save_temp_voice_owners(d); _bump("temp_voice_owners", len(d))

    profiles = os.path.join(_DATA, "temp_voice_profiles.json")
    if os.path.exists(profiles):
        d = _read(profiles)
        if isinstance(d, dict):
            _standalone.save_temp_voice_profiles(d); _bump("temp_voice_profiles", len(d))

    perm = os.path.join(_DATA, "temp_voice_permanent.json")
    if os.path.exists(perm):
        d = _read(perm)
        if isinstance(d, list):
            _standalone.save_temp_voice_permanent(d); _bump("temp_voice_permanent", len(d))

    fb = os.path.join(_DATA, "ai_feedback.json")
    if os.path.exists(fb):
        d = _read(fb)
        if isinstance(d, list):
            _standalone.save_ai_feedback(d); _bump("ai_feedback", len(d))


def _backup_json_files() -> None:
    """Move every data/**/*.json (except data/safetext/) into the backup tree."""
    safetext = os.path.join(_DATA, "safetext") + os.sep
    for root, _dirs, files in os.walk(_DATA):
        if (root + os.sep).startswith(safetext):
            continue
        for fname in files:
            if not fname.endswith(".json"):
                continue
            src = os.path.join(root, fname)
            rel = os.path.relpath(src, _DATA)
            dst = os.path.join(_BACKUP, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            try:
                if os.path.exists(dst):
                    os.remove(dst)  # overwrite-safe so re-migration doesn't fail
                shutil.move(src, dst)
            except Exception as exc:
                print(f"[migrate] backup move failed {src}: {exc}", file=sys.stderr)


def _has_source_json() -> bool:
    """True if un-migrated source JSON still exist in data/ (guild dirs or flat globals)."""
    if not os.path.isdir(_DATA):
        return False
    for entry in os.listdir(_DATA):
        gdir = os.path.join(_DATA, entry)
        if entry.isdigit() and os.path.isdir(gdir):
            try:
                if any(f.endswith(".json") for f in os.listdir(gdir)):
                    return True
            except OSError:
                pass
    for flat in ("mc_links.json", "ai_feedback.json", "temp_voice_owners.json",
                 "temp_voice_profiles.json", "temp_voice_permanent.json"):
        if os.path.exists(os.path.join(_DATA, flat)):
            return True
    return False


def _db_has_guild_data() -> bool:
    """True if the DB already holds real per-guild data (not just an empty schema).

    Used to detect a stale/foreign baxi_data.db (migration flag set, but no real
    data) that was copied onto a machine whose own data/ was never imported.
    """
    try:
        if db.query("SELECT 1 FROM guild_config LIMIT 1"):
            return True
        if db.query("SELECT 1 FROM guilds WHERE guild_id != 1001 LIMIT 1"):
            return True
    except Exception:
        return False
    return False


def run() -> None:
    db.init()
    if db.is_migrated():
        # Auto-heal: the migrated flag lives inside baxi_data.db, so a stale/foreign
        # DB copied onto a server (e.g. a dev DB uploaded by mistake) would skip the
        # server's real data. If the flag is set but the DB has no guild data while
        # source JSON still exist locally, re-run the import from those files.
        if _has_source_json() and not _db_has_guild_data():
            print("[migrate] WARNING: migrated flag set but DB has no guild data and "
                  "source JSON exist in data/ — likely a stale/foreign baxi_data.db. "
                  "Re-importing from the local data/ files.", file=sys.stderr)
        else:
            print("[migrate] already migrated — skipping")
            return
    if not os.path.isdir(_DATA):
        print("[migrate] no data/ directory — fresh install, marking migrated")
        db.schema_meta_set("schema_version", "1")
        db.schema_meta_set("migrated_at", datetime.datetime.utcnow().isoformat())
        db.schema_meta_set("migration_complete", "1")
        return

    print("[migrate] starting JSON -> SQLite migration")
    for entry in sorted(os.listdir(_DATA)):
        gdir = os.path.join(_DATA, entry)
        if not os.path.isdir(gdir) or not entry.isdigit():
            continue
        try:
            _migrate_guild_dir(int(entry), gdir)
        except Exception as exc:
            print(f"[migrate] guild dir {entry} failed: {exc}", file=sys.stderr)

    _migrate_flat_globals()

    db.schema_meta_set("schema_version", "1")
    db.schema_meta_set("migrated_at", datetime.datetime.utcnow().isoformat())
    db.schema_meta_set("migration_complete", "1")

    _backup_json_files()

    print("[migrate] complete. Imported row counts:")
    for label in sorted(_counts):
        print(f"    {label:32} {_counts[label]}")
    print(f"[migrate] old JSON moved to {_BACKUP}/")


if __name__ == "__main__":
    run()
