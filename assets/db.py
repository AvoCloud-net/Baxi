"""
assets/db.py — single shared SQLite connection with thread-safe primitives.

One process, one connection, one threading.Lock.  WAL + synchronous=NORMAL +
busy_timeout=5000 handle the two asyncio.to_thread callers without needing a
connection pool.  Every public function acquires _LOCK so multi-statement repo
operations are atomic.
"""
from __future__ import annotations

import contextlib
import json
import os
import sqlite3
import threading
from typing import Generator

_DB_PATH = os.environ.get("BAXI_DB_PATH", "baxi_data.db")
_LOCK = threading.Lock()
_conn: sqlite3.Connection | None = None


# ── Connection ────────────────────────────────────────────────────────────────

def _connect(path: str) -> sqlite3.Connection:
    c = sqlite3.connect(path, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.execute("PRAGMA foreign_keys=ON")
    c.execute("PRAGMA busy_timeout=5000")
    return c


RESTORE_SUFFIX = ".restore-pending"


def apply_pending_restore(path: str) -> str | None:
    """If ``<path>.restore-pending`` exists (staged by the ``restore`` console command), swap it in.

    Must run before the DB is opened. The old DB is kept as ``<path>.pre-restore-<timestamp>``;
    returns that path, or None if nothing was pending / there was no old DB.
    """
    pending = path + RESTORE_SUFFIX
    if not os.path.exists(pending):
        return None
    import datetime
    import shutil
    kept = None
    if os.path.exists(path):
        kept = f"{path}.pre-restore-{datetime.datetime.now():%Y%m%d-%H%M%S}"
        n = 1
        while os.path.exists(kept):   # two restores in the same second must not overwrite each other
            n += 1
            kept = f"{path}.pre-restore-{datetime.datetime.now():%Y%m%d-%H%M%S}-{n}"
        shutil.move(path, kept)
    for suffix in ("-wal", "-shm"):   # stale WAL files would be replayed onto the restored DB
        if os.path.exists(path + suffix):
            os.remove(path + suffix)
    os.replace(pending, path)
    print(f"[restore] restored database applied; previous DB kept as {kept}", flush=True)
    return kept


def init(db_path: str | None = None) -> None:
    """Connect and create all tables (IF NOT EXISTS).  Call once at startup."""
    global _conn, _DB_PATH
    if db_path is not None:
        _DB_PATH = db_path
    with _LOCK:
        apply_pending_restore(_DB_PATH)
        _conn = _connect(_DB_PATH)
        _create_schema(_conn)
        _migrate_columns(_conn)
        _conn.commit()


# Columns added to existing tables after their initial release. CREATE TABLE IF NOT EXISTS
# never alters an existing table, so we add any missing columns here (idempotent).
_COLUMN_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "cfg_mod_gate": [("use_safety_list", "INTEGER DEFAULT 1")],
    "cfg_ticket": [
        ("title", "TEXT DEFAULT ''"),
        ("panel_style", "TEXT DEFAULT 'buttons'"),
    ],
    "cfg_ticket_button": [("description", "TEXT DEFAULT ''")],
    "cfg_chatfilter": [
        ("sensitivity", "TEXT DEFAULT 'medium'"),
        ("exempt_staff", "INTEGER DEFAULT 1"),
        ("training_opt_in", "INTEGER DEFAULT 0"),
        ("c_goodwords", "TEXT DEFAULT '[]'"),
        ("c_badwords", "TEXT DEFAULT '[]'"),
        ("bypass", "TEXT DEFAULT '[]'"),
    ],
    "cfg_mc_link": [
        ("status_channel", "TEXT DEFAULT ''"),
        ("status_message_id", "TEXT DEFAULT ''"),
    ],
    "global_reports": [
        ("category", "TEXT DEFAULT ''"),
        ("message_text", "TEXT DEFAULT ''"),
    ],
    "cfg_livestream": [("ping_role", "TEXT DEFAULT ''")],
    "quotes": [
        ("post_channel_id", "TEXT DEFAULT ''"),
        ("post_message_id", "TEXT DEFAULT ''"),
        ("reaction_order", "TEXT DEFAULT ''"),
    ],
    "cfg_welcomer": [
        ("embed_title", "TEXT DEFAULT ''"),
        ("card_title", "TEXT DEFAULT 'Welcome, {displayname}!'"),
        ("card_subtitle", "TEXT DEFAULT '{server}'"),
        ("card_footer", "TEXT DEFAULT 'Member #{membercount}'"),
    ],
    "leveling_users": [
        ("text_xp", "INTEGER DEFAULT 0"),
        ("voice_xp", "INTEGER DEFAULT 0"),
    ],
}

# Data fixes that run after the column migrations at every start. Each must be idempotent.
_DATA_MIGRATIONS: list[str] = [
    # Leveling: XP from before the text/voice split counts as text XP. Afterwards every write
    # keeps xp = text_xp + voice_xp, so this matches nothing and the total (and level) never moves.
    "UPDATE leveling_users SET text_xp = COALESCE(xp, 0) - COALESCE(voice_xp, 0), "
    "voice_xp = COALESCE(voice_xp, 0) "
    "WHERE COALESCE(text_xp, 0) + COALESCE(voice_xp, 0) < COALESCE(xp, 0)",
    # Covered by the primary key (guild_id, user_id) and ix_leveling_users_total.
    "DROP INDEX IF EXISTS ix_leveling_users_guild",
    # Case numbers start at 1 (they were mod_events.pos from 0). Two steps because SQLite
    # checks the primary key row by row: flip to negative, then back. Matches nothing once done.
    "UPDATE mod_events SET pos = -(pos + 1) WHERE guild_id IN (SELECT guild_id FROM mod_events WHERE pos = 0)",
    "UPDATE mod_events SET pos = -pos WHERE pos < 0",
    # Legacy guilds get their case counter from the highest number they ever used, so pruning
    # old cases can never hand a number out twice. INSERT OR IGNORE: an existing counter wins.
    "INSERT OR IGNORE INTO mod_case_counter (guild_id, next_no) "
    "SELECT guild_id, MAX(pos) + 1 FROM mod_events GROUP BY guild_id",
]


def _migrate_columns(conn: sqlite3.Connection) -> None:
    for table, cols in _COLUMN_MIGRATIONS.items():
        try:
            existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        except sqlite3.OperationalError:
            continue  # table doesn't exist yet (fresh DB already has the column via schema)
        for name, ddl in cols:
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
    for sql in _DATA_MIGRATIONS:
        conn.execute(sql)


def close() -> None:
    """Checkpoint and close the shared connection (used before the DB file is replaced)."""
    global _conn
    with _LOCK:
        if _conn is not None:
            try:
                _conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            finally:
                _conn.close()
                _conn = None


def _get_conn() -> sqlite3.Connection:
    if _conn is None:
        raise RuntimeError("db.init() has not been called")
    return _conn


# ── Public helpers ────────────────────────────────────────────────────────────

def execute(sql: str, params: tuple = ()) -> sqlite3.Cursor:
    """Execute a single write statement and commit."""
    with _LOCK:
        cur = _get_conn().execute(sql, params)
        _get_conn().commit()
        return cur


def query(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    """Execute a read query and return all rows."""
    with _LOCK:
        return _get_conn().execute(sql, params).fetchall()


@contextlib.contextmanager
def transaction() -> Generator[sqlite3.Connection, None, None]:
    """Context manager: acquire lock, yield connection, commit on success / rollback on error."""
    with _LOCK:
        conn = _get_conn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def guild_ids() -> list[int]:
    """Return all guild_ids except the global-bag sentinel 1001."""
    with _LOCK:
        rows = _get_conn().execute(
            "SELECT guild_id FROM guilds WHERE guild_id != 1001"
        ).fetchall()
    return [r["guild_id"] for r in rows]


def ensure_guild(gid: int) -> None:
    """INSERT OR IGNORE a guild row (creates the root row with defaults)."""
    with _LOCK:
        _get_conn().execute(
            "INSERT OR IGNORE INTO guilds (guild_id) VALUES (?)", (int(gid),)
        )
        _get_conn().commit()


def is_migrated() -> bool:
    """True if the migration has already completed."""
    try:
        rows = query(
            "SELECT value FROM schema_meta WHERE key='migration_complete'"
        )
        return bool(rows) and rows[0]["value"] == "1"
    except Exception:
        return False


def schema_meta_set(key: str, value: str) -> None:
    execute(
        "INSERT INTO schema_meta (key,value) VALUES (?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def schema_meta_get(key: str) -> str | None:
    rows = query("SELECT value FROM schema_meta WHERE key=?", (key,))
    return rows[0]["value"] if rows else None


# ── Schema ────────────────────────────────────────────────────────────────────

def _create_schema(conn: sqlite3.Connection) -> None:  # noqa: C901 (long but cohesive)
    stmts = _DDL.strip().split(";\n")
    for stmt in stmts:
        s = stmt.strip()
        if s:
            conn.execute(s)


_DDL = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS guilds (
    guild_id             INTEGER PRIMARY KEY,
    lang                 TEXT    NOT NULL DEFAULT 'en',
    guild_name           TEXT    NOT NULL DEFAULT '',
    discord_guild_id     INTEGER NOT NULL DEFAULT 0,
    owner_id             INTEGER NOT NULL DEFAULT 0,
    owner_name           TEXT    NOT NULL DEFAULT '',
    terms                INTEGER NOT NULL DEFAULT 0,
    prism_enabled        INTEGER NOT NULL DEFAULT 1,
    notification_channel TEXT    NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS cfg_chatfilter (
    guild_id INTEGER PRIMARY KEY REFERENCES guilds(guild_id) ON DELETE CASCADE,
    enabled INTEGER DEFAULT 0, system TEXT DEFAULT 'AI',
    phishing_filter INTEGER DEFAULT 0, warn_on_violation INTEGER DEFAULT 0,
    sensitivity TEXT DEFAULT 'medium', exempt_staff INTEGER DEFAULT 1,
    training_opt_in INTEGER DEFAULT 0,
    c_goodwords TEXT DEFAULT '[]', c_badwords TEXT DEFAULT '[]', bypass TEXT DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS cfg_chatfilter_ai_category (
    guild_id INTEGER REFERENCES guilds(guild_id) ON DELETE CASCADE,
    cat_key  TEXT,
    enabled  INTEGER DEFAULT 1,
    PRIMARY KEY (guild_id, cat_key)
);

CREATE TABLE IF NOT EXISTS cfg_ticket (
    guild_id INTEGER PRIMARY KEY REFERENCES guilds(guild_id) ON DELETE CASCADE,
    enabled INTEGER DEFAULT 0, channel TEXT DEFAULT '', transcript TEXT DEFAULT '',
    catid TEXT DEFAULT '', role TEXT DEFAULT '', color TEXT DEFAULT '#FF6B4A',
    message TEXT DEFAULT 'Click a button below to open a ticket.',
    channel_name_template TEXT DEFAULT '{button}-{user}',
    panel_message_id TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS cfg_ticket_button (
    guild_id INTEGER REFERENCES guilds(guild_id) ON DELETE CASCADE,
    pos INTEGER,
    btn_id TEXT, label TEXT, emoji TEXT, style TEXT,
    PRIMARY KEY (guild_id, pos)
);

CREATE TABLE IF NOT EXISTS cfg_serverlog (
    guild_id INTEGER PRIMARY KEY REFERENCES guilds(guild_id) ON DELETE CASCADE,
    enabled INTEGER DEFAULT 0, channel TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS cfg_serverlog_event (
    guild_id  INTEGER REFERENCES guilds(guild_id) ON DELETE CASCADE,
    event_key TEXT,
    enabled   INTEGER DEFAULT 1,
    PRIMARY KEY (guild_id, event_key)
);

CREATE TABLE IF NOT EXISTS cfg_warn (
    guild_id    INTEGER PRIMARY KEY REFERENCES guilds(guild_id) ON DELETE CASCADE,
    enabled     INTEGER DEFAULT 1,
    expiry_days INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS cfg_warn_step (
    guild_id INTEGER REFERENCES guilds(guild_id) ON DELETE CASCADE,
    pos INTEGER, warns INTEGER, action TEXT, duration INTEGER DEFAULT 0, dm INTEGER DEFAULT 1,
    PRIMARY KEY (guild_id, pos)
);

CREATE TABLE IF NOT EXISTS cfg_antispam (
    guild_id         INTEGER PRIMARY KEY REFERENCES guilds(guild_id) ON DELETE CASCADE,
    enabled          INTEGER DEFAULT 0,
    max_messages     INTEGER DEFAULT 5,
    interval         INTEGER DEFAULT 5,
    max_duplicates   INTEGER DEFAULT 3,
    duplicate_window INTEGER DEFAULT 60,
    action           TEXT    DEFAULT 'mute'
);

CREATE TABLE IF NOT EXISTS cfg_antispam_wl_channel (
    guild_id INTEGER REFERENCES guilds(guild_id) ON DELETE CASCADE,
    pos INTEGER, value TEXT, PRIMARY KEY (guild_id, pos)
);

CREATE TABLE IF NOT EXISTS cfg_antispam_wl_role (
    guild_id INTEGER REFERENCES guilds(guild_id) ON DELETE CASCADE,
    pos INTEGER, value TEXT, PRIMARY KEY (guild_id, pos)
);

CREATE TABLE IF NOT EXISTS cfg_welcomer (
    guild_id        INTEGER PRIMARY KEY REFERENCES guilds(guild_id) ON DELETE CASCADE,
    enabled         INTEGER DEFAULT 0,
    channel         TEXT    DEFAULT '0',
    message         TEXT    DEFAULT 'Welcome {user} to {server}!',
    leave_enabled   INTEGER DEFAULT 0,
    leave_channel   TEXT    DEFAULT '0',
    leave_message   TEXT    DEFAULT '{user} has left {server}.',
    color           TEXT    DEFAULT '#FF6B4A',
    image_mode      TEXT    DEFAULT 'none',
    card_color      TEXT    DEFAULT '#1a1a2e',
    has_custom_bg   INTEGER DEFAULT 0,
    leave_color     TEXT    DEFAULT '#f59e0b',
    embed_title     TEXT    DEFAULT '',
    card_title      TEXT    DEFAULT 'Welcome, {displayname}!',
    card_subtitle   TEXT    DEFAULT '{server}',
    card_footer     TEXT    DEFAULT 'Member #{membercount}'
);

CREATE TABLE IF NOT EXISTS cfg_livestream (
    guild_id    INTEGER PRIMARY KEY REFERENCES guilds(guild_id) ON DELETE CASCADE,
    enabled     INTEGER DEFAULT 0,
    category_id TEXT    DEFAULT '',
    ping_role   TEXT    DEFAULT ''
);

CREATE TABLE IF NOT EXISTS cfg_livestream_streamer (
    guild_id          INTEGER REFERENCES guilds(guild_id) ON DELETE CASCADE,
    pos               INTEGER,
    platform          TEXT,
    login             TEXT,
    display_name      TEXT,
    channel_id        TEXT,
    message_id        TEXT,
    profile_image_url TEXT,
    extra_json        TEXT DEFAULT '{}',
    PRIMARY KEY (guild_id, pos)
);

CREATE TABLE IF NOT EXISTS cfg_social (
    guild_id      INTEGER,
    platform      TEXT,
    enabled       INTEGER DEFAULT 0,
    alert_channel TEXT    DEFAULT '',
    ping_role     TEXT    DEFAULT '',
    PRIMARY KEY (guild_id, platform),
    FOREIGN KEY (guild_id) REFERENCES guilds(guild_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS cfg_social_channel (
    guild_id          INTEGER,
    platform          TEXT,
    pos               INTEGER,
    channel_id        TEXT,
    username          TEXT,
    display_name      TEXT,
    profile_image_url TEXT,
    alert_channel     TEXT,
    extra_json        TEXT DEFAULT '{}',
    PRIMARY KEY (guild_id, platform, pos),
    FOREIGN KEY (guild_id) REFERENCES guilds(guild_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS cfg_stats_channels (
    guild_id    INTEGER PRIMARY KEY REFERENCES guilds(guild_id) ON DELETE CASCADE,
    enabled     INTEGER DEFAULT 0,
    category_id TEXT    DEFAULT ''
);

CREATE TABLE IF NOT EXISTS cfg_stats_channel_item (
    guild_id   INTEGER REFERENCES guilds(guild_id) ON DELETE CASCADE,
    stat_key   TEXT,
    enabled    INTEGER DEFAULT 0,
    channel_id TEXT    DEFAULT '',
    template   TEXT    DEFAULT '',
    PRIMARY KEY (guild_id, stat_key)
);

CREATE TABLE IF NOT EXISTS cfg_auto_roles (
    guild_id INTEGER PRIMARY KEY REFERENCES guilds(guild_id) ON DELETE CASCADE,
    enabled  INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS cfg_auto_role (
    guild_id INTEGER REFERENCES guilds(guild_id) ON DELETE CASCADE,
    pos INTEGER, value TEXT, PRIMARY KEY (guild_id, pos)
);

CREATE TABLE IF NOT EXISTS cfg_temp_voice (
    guild_id INTEGER PRIMARY KEY REFERENCES guilds(guild_id) ON DELETE CASCADE,
    enabled  INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS cfg_temp_voice_persist_role (
    guild_id INTEGER REFERENCES guilds(guild_id) ON DELETE CASCADE,
    pos INTEGER, value TEXT, PRIMARY KEY (guild_id, pos)
);

CREATE TABLE IF NOT EXISTS cfg_temp_voice_trigger (
    guild_id          INTEGER REFERENCES guilds(guild_id) ON DELETE CASCADE,
    pos               INTEGER,
    create_channel_id TEXT,
    category_id       TEXT,
    name_template     TEXT DEFAULT '{user}''s Channel',
    PRIMARY KEY (guild_id, pos)
);

CREATE TABLE IF NOT EXISTS cfg_verify (
    guild_id         INTEGER PRIMARY KEY REFERENCES guilds(guild_id) ON DELETE CASCADE,
    enabled          INTEGER DEFAULT 0,
    rid              INTEGER DEFAULT 0,
    verify_option    INTEGER DEFAULT 0,
    password         TEXT    DEFAULT '',
    channel          TEXT    DEFAULT '',
    panel_message_id TEXT    DEFAULT '',
    title            TEXT    DEFAULT 'Verification',
    description      TEXT    DEFAULT '',
    color            TEXT    DEFAULT '#FF6B4A'
);

CREATE TABLE IF NOT EXISTS cfg_rr_panel (
    guild_id    INTEGER REFERENCES guilds(guild_id) ON DELETE CASCADE,
    pos         INTEGER,
    channel_id  TEXT,
    message_id  TEXT,
    title       TEXT,
    description TEXT,
    color       TEXT    DEFAULT '#FF6B4A',
    max_roles   INTEGER DEFAULT 0,
    extra_json  TEXT    DEFAULT '{}',
    PRIMARY KEY (guild_id, pos)
);

CREATE TABLE IF NOT EXISTS cfg_rr_entry (
    guild_id  INTEGER,
    panel_pos INTEGER,
    pos       INTEGER,
    emoji     TEXT,
    role_id   TEXT,
    label     TEXT,
    extra_json TEXT DEFAULT '{}',
    PRIMARY KEY (guild_id, panel_pos, pos),
    FOREIGN KEY (guild_id) REFERENCES guilds(guild_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS cfg_mod_gate (
    guild_id        INTEGER PRIMARY KEY REFERENCES guilds(guild_id) ON DELETE CASCADE,
    enabled         INTEGER DEFAULT 0,
    threshold       INTEGER DEFAULT 30,
    action          TEXT    DEFAULT 'quarantine',
    quarantine_role INTEGER DEFAULT 0,
    log_channel     INTEGER DEFAULT 0,
    use_safety_list INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS cfg_antiraid (
    guild_id INTEGER PRIMARY KEY REFERENCES guilds(guild_id) ON DELETE CASCADE,
    data     TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS cfg_assistant (
    guild_id INTEGER PRIMARY KEY REFERENCES guilds(guild_id) ON DELETE CASCADE,
    data     TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS cfg_counting (
    guild_id        INTEGER PRIMARY KEY REFERENCES guilds(guild_id) ON DELETE CASCADE,
    enabled         INTEGER DEFAULT 0,
    channel         TEXT    DEFAULT '',
    current_count   INTEGER DEFAULT 0,
    high_score      INTEGER DEFAULT 0,
    last_user_id    INTEGER DEFAULT 0,
    no_double_count INTEGER DEFAULT 1,
    react_correct   INTEGER DEFAULT 1,
    react_wrong     INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS cfg_flag_quiz (
    guild_id           INTEGER PRIMARY KEY REFERENCES guilds(guild_id) ON DELETE CASCADE,
    enabled            INTEGER DEFAULT 0,
    channel            TEXT    DEFAULT '',
    hint_after_attempts INTEGER DEFAULT 3,
    next_delay         INTEGER DEFAULT 3,
    points_enabled     INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS cfg_flag_quiz_score (
    guild_id INTEGER REFERENCES guilds(guild_id) ON DELETE CASCADE,
    user_id  TEXT,
    score    INTEGER DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS cfg_flag_quiz_recent (
    guild_id INTEGER REFERENCES guilds(guild_id) ON DELETE CASCADE,
    pos      INTEGER,
    flag     TEXT,
    PRIMARY KEY (guild_id, pos)
);

CREATE TABLE IF NOT EXISTS cfg_suggestions (
    guild_id               INTEGER PRIMARY KEY REFERENCES guilds(guild_id) ON DELETE CASCADE,
    enabled                INTEGER DEFAULT 0,
    staff_role             TEXT    DEFAULT '',
    log_channel            TEXT    DEFAULT '',
    auto_forward_enabled   INTEGER DEFAULT 0,
    auto_forward_channel   TEXT    DEFAULT '',
    auto_forward_threshold INTEGER DEFAULT 10
);

CREATE TABLE IF NOT EXISTS cfg_suggestions_channel (
    guild_id INTEGER REFERENCES guilds(guild_id) ON DELETE CASCADE,
    pos INTEGER, value TEXT, PRIMARY KEY (guild_id, pos)
);

CREATE TABLE IF NOT EXISTS cfg_leveling (
    guild_id             INTEGER PRIMARY KEY REFERENCES guilds(guild_id) ON DELETE CASCADE,
    enabled              INTEGER DEFAULT 0,
    announcement         TEXT    DEFAULT 'same_channel',
    announcement_channel TEXT    DEFAULT ''
);

CREATE TABLE IF NOT EXISTS cfg_leveling_reward (
    guild_id INTEGER REFERENCES guilds(guild_id) ON DELETE CASCADE,
    pos      INTEGER,
    level    INTEGER,
    role_id  TEXT,
    PRIMARY KEY (guild_id, pos)
);

CREATE TABLE IF NOT EXISTS cfg_auto_release (
    guild_id    INTEGER PRIMARY KEY REFERENCES guilds(guild_id) ON DELETE CASCADE,
    enabled     INTEGER DEFAULT 0,
    ignore_bots INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS cfg_auto_release_channel (
    guild_id INTEGER REFERENCES guilds(guild_id) ON DELETE CASCADE,
    pos INTEGER, value TEXT, PRIMARY KEY (guild_id, pos)
);

CREATE TABLE IF NOT EXISTS cfg_mc_link (
    guild_id              INTEGER PRIMARY KEY REFERENCES guilds(guild_id) ON DELETE CASCADE,
    enabled               INTEGER DEFAULT 0,
    api_url               TEXT    DEFAULT '',
    api_secret            TEXT    DEFAULT '',
    role_id               TEXT    DEFAULT '',
    announce_channel      TEXT    DEFAULT '',
    dm_on_link            INTEGER DEFAULT 0,
    allow_self_unlink     INTEGER DEFAULT 1,
    announcement_channel  TEXT    DEFAULT '',
    dm_announcements      INTEGER DEFAULT 0,
    chat_enabled          INTEGER DEFAULT 0,
    chat_channel          TEXT    DEFAULT '',
    chat_webhook_url      TEXT    DEFAULT '',
    status_channel        TEXT    DEFAULT '',
    status_message_id     TEXT    DEFAULT ''
);

CREATE TABLE IF NOT EXISTS cfg_music (
    guild_id                  INTEGER PRIMARY KEY REFERENCES guilds(guild_id) ON DELETE CASCADE,
    enabled                   INTEGER DEFAULT 1,
    queue_limit               INTEGER DEFAULT 50,
    default_volume            INTEGER DEFAULT 100,
    max_song_duration         INTEGER DEFAULT 600,
    disconnect_timeout        INTEGER DEFAULT 300,
    allow_all_radios          INTEGER DEFAULT 0,
    radio_247_enabled         INTEGER DEFAULT 0,
    radio_247_channel_id      TEXT    DEFAULT '',
    radio_247_text_channel_id TEXT    DEFAULT '',
    radio_247_url             TEXT    DEFAULT ''
);

CREATE TABLE IF NOT EXISTS cfg_music_source (
    guild_id INTEGER REFERENCES guilds(guild_id) ON DELETE CASCADE,
    pos INTEGER, value TEXT, PRIMARY KEY (guild_id, pos)
);

CREATE TABLE IF NOT EXISTS cfg_music_radio_wl (
    guild_id INTEGER REFERENCES guilds(guild_id) ON DELETE CASCADE,
    pos INTEGER, value TEXT, PRIMARY KEY (guild_id, pos)
);

CREATE TABLE IF NOT EXISTS warnings (
    id       TEXT,
    guild_id INTEGER,
    user_id  TEXT,
    reason   TEXT,
    mod      TEXT,
    mod_id   INTEGER DEFAULT 0,
    date     TEXT,
    pos      INTEGER,
    PRIMARY KEY (guild_id, user_id, id)
);

CREATE INDEX IF NOT EXISTS ix_warnings_guild ON warnings(guild_id);

CREATE TABLE IF NOT EXISTS custom_commands (
    guild_id  INTEGER,
    name      TEXT,
    data_json TEXT,
    PRIMARY KEY (guild_id, name)
);

CREATE TABLE IF NOT EXISTS giveaways (
    guild_id      INTEGER,
    message_id    TEXT,
    channel_id    TEXT,
    reward        TEXT,
    winner_count  INTEGER,
    end_time      INTEGER,
    host_id       INTEGER,
    ended         INTEGER DEFAULT 0,
    image_url     TEXT,
    winner_message TEXT,
    extra_json    TEXT DEFAULT '{}',
    PRIMARY KEY (guild_id, message_id)
);

CREATE TABLE IF NOT EXISTS giveaway_participant (
    guild_id   INTEGER,
    message_id TEXT,
    pos        INTEGER,
    user_id    TEXT,
    PRIMARY KEY (guild_id, message_id, pos)
);

CREATE TABLE IF NOT EXISTS polls (
    guild_id     INTEGER,
    message_id   TEXT,
    question     TEXT,
    answers_json TEXT,
    show_votes   INTEGER DEFAULT 1,
    image_url    TEXT,
    channel_id   TEXT,
    end_time     REAL,
    closed       INTEGER DEFAULT 0,
    extra_json   TEXT DEFAULT '{}',
    PRIMARY KEY (guild_id, message_id)
);

CREATE TABLE IF NOT EXISTS poll_vote (
    guild_id   INTEGER,
    message_id TEXT,
    user_id    TEXT,
    choice     TEXT,
    PRIMARY KEY (guild_id, message_id, user_id)
);

CREATE TABLE IF NOT EXISTS suggestion_votes (
    guild_id       INTEGER,
    suggestion_id  TEXT,
    data_json      TEXT,
    PRIMARY KEY (guild_id, suggestion_id)
);

CREATE TABLE IF NOT EXISTS flag_quiz_active (
    guild_id  INTEGER PRIMARY KEY,
    data_json TEXT
);

CREATE TABLE IF NOT EXISTS sticky_messages (
    guild_id        INTEGER,
    channel_id      TEXT,
    message         TEXT,
    last_message_id TEXT,
    extra_json      TEXT DEFAULT '{}',
    PRIMARY KEY (guild_id, channel_id)
);

CREATE TABLE IF NOT EXISTS audit_log (
    guild_id   INTEGER,
    pos        INTEGER,
    entry_json TEXT,
    PRIMARY KEY (guild_id, pos)
);

CREATE TABLE IF NOT EXISTS tickets (
    guild_id        INTEGER,
    channel_id      TEXT,
    user_id         INTEGER,
    supporter_id    INTEGER,
    created_at      INTEGER,
    status          TEXT,
    title           TEXT,
    message         TEXT,
    button_id       TEXT,
    transcript_json TEXT DEFAULT '[]',
    extra_json      TEXT DEFAULT '{}',
    PRIMARY KEY (guild_id, channel_id)
);

CREATE TABLE IF NOT EXISTS transcripts (
    guild_id      INTEGER,
    transcript_id TEXT,
    data_json     TEXT,
    PRIMARY KEY (guild_id, transcript_id)
);

CREATE TABLE IF NOT EXISTS users (
    guild_id     INTEGER,
    user_id      TEXT,
    name         TEXT,
    flagged      INTEGER DEFAULT 0,
    reason       TEXT,
    entry_date   TEXT,
    auto_flagged INTEGER DEFAULT 0,
    extra_json   TEXT DEFAULT '{}',
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS stats (
    guild_id  INTEGER PRIMARY KEY,
    data_json TEXT
);

CREATE TABLE IF NOT EXISTS chatfilter_log (
    guild_id  INTEGER,
    log_id    TEXT,
    data_json TEXT,
    PRIMARY KEY (guild_id, log_id)
);

CREATE TABLE IF NOT EXISTS globalchat_message_data (
    guild_id  INTEGER,
    gcmid     TEXT,
    data_json TEXT,
    PRIMARY KEY (guild_id, gcmid)
);

CREATE TABLE IF NOT EXISTS temp_bans (
    guild_id  INTEGER,
    pos       INTEGER,
    data_json TEXT,
    PRIMARY KEY (guild_id, pos)
);

CREATE TABLE IF NOT EXISTS temp_timeouts (
    guild_id  INTEGER,
    pos       INTEGER,
    data_json TEXT,
    PRIMARY KEY (guild_id, pos)
);

CREATE TABLE IF NOT EXISTS mod_events (
    guild_id   INTEGER,
    pos        INTEGER,
    type       TEXT,
    user_id    TEXT,
    user_name  TEXT,
    mod_id     TEXT,
    mod_name   TEXT,
    reason     TEXT,
    timestamp  TEXT,
    extra_json TEXT DEFAULT '{}',
    PRIMARY KEY (guild_id, pos)
);

CREATE INDEX IF NOT EXISTS ix_mod_events_ts ON mod_events(guild_id, timestamp);
-- "my servers" (appeal page): looks a user up across guilds
CREATE INDEX IF NOT EXISTS ix_mod_events_user ON mod_events(user_id, guild_id);
-- case file: one user's cases in one guild, newest first
CREATE INDEX IF NOT EXISTS ix_mod_events_guild_user ON mod_events(guild_id, user_id, pos);

-- Case numbers (= mod_events.pos) only ever go up, even when old cases are pruned.
CREATE TABLE IF NOT EXISTS mod_case_counter (
    guild_id INTEGER PRIMARY KEY,
    next_no  INTEGER NOT NULL
);

-- Moderator notes about a user. Never shown to the user.
CREATE TABLE IF NOT EXISTS mod_notes (
    guild_id   INTEGER,
    id         INTEGER,
    user_id    TEXT,
    user_name  TEXT DEFAULT '',
    author_id  TEXT,
    author_name TEXT DEFAULT '',
    text       TEXT,
    created_at TEXT,
    PRIMARY KEY (guild_id, id)
);

CREATE INDEX IF NOT EXISTS ix_mod_notes_user ON mod_notes(guild_id, user_id);

CREATE TABLE IF NOT EXISTS filter_events (
    guild_id  INTEGER,
    pos       INTEGER,
    timestamp TEXT,
    data_json TEXT,
    PRIMARY KEY (guild_id, pos)
);

CREATE INDEX IF NOT EXISTS ix_filter_events_ts ON filter_events(guild_id, timestamp);

CREATE TABLE IF NOT EXISTS mod_review_queue (
    guild_id     INTEGER,
    pos          INTEGER,
    user_id      TEXT,
    user_name    TEXT,
    kind         TEXT,                       -- join_gate | deleted_msg | prism_flag | user_report | chatfilter_borderline | appeal
    status       TEXT DEFAULT 'pending',     -- pending | approved | rejected | expired
    context_json TEXT DEFAULT '{}',
    created_at   TEXT,
    resolved_by  TEXT DEFAULT '',
    resolved_at  TEXT DEFAULT '',
    PRIMARY KEY (guild_id, pos)
);

CREATE INDEX IF NOT EXISTS ix_mod_review_status ON mod_review_queue(guild_id, status);
CREATE INDEX IF NOT EXISTS ix_mod_review_due ON mod_review_queue(status, kind, created_at);

CREATE TABLE IF NOT EXISTS activity (
    guild_id  INTEGER PRIMARY KEY,
    data_json TEXT
);

-- xp is the total (text_xp + voice_xp), kept as its own column for the leaderboard index.
CREATE TABLE IF NOT EXISTS leveling_users (
    guild_id INTEGER,
    user_id  TEXT,
    xp       INTEGER DEFAULT 0,
    level    INTEGER DEFAULT 0,
    messages INTEGER DEFAULT 0,
    name     TEXT,
    text_xp  INTEGER DEFAULT 0,
    voice_xp INTEGER DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);

CREATE INDEX IF NOT EXISTS ix_leveling_users_total ON leveling_users(guild_id, xp DESC);

CREATE TABLE IF NOT EXISTS quotes (
    guild_id          INTEGER REFERENCES guilds(guild_id) ON DELETE CASCADE,
    quote_id          INTEGER,
    author_id         TEXT DEFAULT '',
    author_name       TEXT DEFAULT '',
    content           TEXT DEFAULT '',
    source_channel_id TEXT DEFAULT '',
    source_message_id TEXT DEFAULT '',
    saved_by          TEXT DEFAULT '',
    created_at        TEXT DEFAULT '',
    post_channel_id   TEXT DEFAULT '',
    post_message_id   TEXT DEFAULT '',
    reaction_order    TEXT DEFAULT '',
    PRIMARY KEY (guild_id, quote_id)
);

CREATE INDEX IF NOT EXISTS ix_quotes_author ON quotes(guild_id, author_id);
CREATE INDEX IF NOT EXISTS ix_quotes_source ON quotes(guild_id, source_message_id);

-- One row per user and emoji on a quote. emoji is a key: "u<hex>-<hex>" (unicode) or "c<id>" (custom).
CREATE TABLE IF NOT EXISTS quote_reactions (
    guild_id   INTEGER REFERENCES guilds(guild_id) ON DELETE CASCADE,
    quote_id   INTEGER,
    emoji      TEXT,
    user_id    TEXT,
    created_at TEXT DEFAULT '',
    PRIMARY KEY (guild_id, quote_id, emoji, user_id)
);

CREATE TABLE IF NOT EXISTS time_capsules (
    capsule_id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id   INTEGER REFERENCES guilds(guild_id) ON DELETE CASCADE,
    user_id    TEXT,
    content    TEXT,
    target     TEXT DEFAULT 'dm',
    reveal     INTEGER DEFAULT 1,
    created_at INTEGER,
    deliver_at INTEGER,
    attempts   INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS ix_capsules_due ON time_capsules(deliver_at);
CREATE INDEX IF NOT EXISTS ix_capsules_user ON time_capsules(guild_id, user_id);

-- Starboard stores IDs only; the message text lives in the board post on Discord.
CREATE TABLE IF NOT EXISTS starboard_entries (
    guild_id           INTEGER REFERENCES guilds(guild_id) ON DELETE CASCADE,
    message_id         TEXT,
    channel_id         TEXT DEFAULT '',
    author_id          TEXT DEFAULT '',
    stars              INTEGER DEFAULT 0,
    board_message_id   TEXT DEFAULT '',
    message_created_at TEXT DEFAULT '',
    PRIMARY KEY (guild_id, message_id)
);

CREATE INDEX IF NOT EXISTS ix_starboard_board ON starboard_entries(guild_id, board_message_id);

-- Invite leaderboard (assets/invites.py): which invite brought a member in. Pairs only.
CREATE TABLE IF NOT EXISTS invite_joins (
    guild_id   INTEGER REFERENCES guilds(guild_id) ON DELETE CASCADE,
    user_id    TEXT,
    inviter_id TEXT,
    code       TEXT DEFAULT '',
    joined_at  INTEGER,
    PRIMARY KEY (guild_id, user_id)
);

CREATE INDEX IF NOT EXISTS ix_invite_joins_inviter ON invite_joins(guild_id, inviter_id);

-- Birthdays: the date belongs to the user (day + month, no year), one row for all servers.
CREATE TABLE IF NOT EXISTS user_birthdays (
    user_id TEXT PRIMARY KEY,
    day     INTEGER,
    month   INTEGER
);

CREATE INDEX IF NOT EXISTS ix_birthdays_date ON user_birthdays(month, day);

-- Servers on which a user hid their birthday (no announcement, not in /birthday upcoming).
CREATE TABLE IF NOT EXISTS birthday_hidden (
    guild_id INTEGER REFERENCES guilds(guild_id) ON DELETE CASCADE,
    user_id  TEXT,
    PRIMARY KEY (guild_id, user_id)
);

-- Last congratulation per server and user (at most once in 300 days) and the 24 h birthday role.
-- Rows without a pending role are pruned after about a year.
CREATE TABLE IF NOT EXISTS birthday_celebrations (
    guild_id      INTEGER REFERENCES guilds(guild_id) ON DELETE CASCADE,
    user_id       TEXT,
    celebrated_on TEXT,              -- local date (YYYY-MM-DD) in the server's timezone
    celebrated_at INTEGER,
    role_id       TEXT DEFAULT '',
    role_until    INTEGER DEFAULT 0, -- unix time; 0 = no role to take back
    PRIMARY KEY (guild_id, user_id)
);

CREATE INDEX IF NOT EXISTS ix_birthday_role_due ON birthday_celebrations(role_until);

-- Server Wrapped (assets/wrapped.py). Completed days of the activity blob, kept past its
-- 90-day window so the yearly recap covers more than three months. Counts only.
CREATE TABLE IF NOT EXISTS wrapped_days (
    guild_id    INTEGER REFERENCES guilds(guild_id) ON DELETE CASCADE,
    day         TEXT,                -- UTC date, same key as activity.msg_by_day
    msg_json    TEXT DEFAULT '{}',
    voice_json  TEXT DEFAULT '{}',
    member_json TEXT DEFAULT '{}',
    PRIMARY KEY (guild_id, day)
);

-- Messages per user and channel ("your favourite channel"), counts only.
CREATE TABLE IF NOT EXISTS wrapped_user_channels (
    guild_id   INTEGER REFERENCES guilds(guild_id) ON DELETE CASCADE,
    year       INTEGER,
    user_id    TEXT,
    channel_id TEXT,
    count      INTEGER DEFAULT 0,
    PRIMARY KEY (guild_id, year, user_id, channel_id)
);

-- The computed recap (once per guild and year) and the per-user part of it.
CREATE TABLE IF NOT EXISTS wrapped_results (
    guild_id    INTEGER REFERENCES guilds(guild_id) ON DELETE CASCADE,
    year        INTEGER,
    data_json   TEXT,
    computed_at INTEGER,
    PRIMARY KEY (guild_id, year)
);

CREATE TABLE IF NOT EXISTS wrapped_users (
    guild_id  INTEGER REFERENCES guilds(guild_id) ON DELETE CASCADE,
    year      INTEGER,
    user_id   TEXT,
    data_json TEXT,
    PRIMARY KEY (guild_id, year, user_id)
);

-- What was already sent (vote, staff preview, shares) - makes every step restart-safe.
CREATE TABLE IF NOT EXISTS wrapped_state (
    guild_id  INTEGER REFERENCES guilds(guild_id) ON DELETE CASCADE,
    year      INTEGER,
    data_json TEXT DEFAULT '{}',
    PRIMARY KEY (guild_id, year)
);

-- Members who do not want to be named in the server recap.
CREATE TABLE IF NOT EXISTS wrapped_optout (
    guild_id INTEGER REFERENCES guilds(guild_id) ON DELETE CASCADE,
    user_id  TEXT,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS bot_admins (
    pos      INTEGER PRIMARY KEY,
    admin_id TEXT
);

CREATE TABLE IF NOT EXISTS global_bans (
    user_id   TEXT PRIMARY KEY,
    data_json TEXT
);

-- Network-wide user reports (operator oversight). Human-submitted reports, not inferred data.
CREATE TABLE IF NOT EXISTS global_reports (
    pos            INTEGER PRIMARY KEY AUTOINCREMENT,
    reported_id    TEXT,
    reported_name  TEXT,
    reporter_id    TEXT,
    reporter_name  TEXT,
    guild_id       TEXT,
    guild_name     TEXT,
    reason         TEXT,
    message_link   TEXT DEFAULT '',
    timestamp      TEXT,
    category       TEXT DEFAULT '',
    message_text   TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS ix_global_reports_reported ON global_reports(reported_id);

CREATE TABLE IF NOT EXISTS globalchat_bans (
    user_id   TEXT PRIMARY KEY,
    data_json TEXT
);

CREATE TABLE IF NOT EXISTS globalchat_guilds (
    guild_id    TEXT PRIMARY KEY,
    config_json TEXT
);

CREATE TABLE IF NOT EXISTS updates_channels (
    guild_id    TEXT PRIMARY KEY,
    config_json TEXT
);

CREATE TABLE IF NOT EXISTS mc_links (
    guild_id     TEXT,
    discord_id   TEXT,
    uuid         TEXT,
    name         TEXT,
    linked_at    INTEGER,
    bedrock_uuid TEXT,
    bedrock_name TEXT,
    extra_json   TEXT DEFAULT '{}',
    PRIMARY KEY (guild_id, discord_id)
);

-- Compliance (Discord Developer Policy): the old cross-server behavioral profile
-- (trust score + per-user event dossier + LLM summaries) constituted profiling of
-- individuals and is removed. Drop the tables wherever they still exist.
DROP TABLE IF EXISTS trust_profiles;
DROP TABLE IF EXISTS trust_event;

-- Human-gated safety denylist: written ONLY by a moderator action (ban / report to
-- network), never by automated behavioral inference. Stores a coarse mod-chosen
-- category fact, no score, no event history, no message content.
CREATE TABLE IF NOT EXISTS safety_flags (
    user_id          TEXT PRIMARY KEY,
    category         TEXT,                  -- raid | spam | hate | other
    reason           TEXT DEFAULT '',
    flagged_by_guild INTEGER,
    flagged_by       TEXT DEFAULT '',       -- moderator name (audit)
    timestamp        TEXT
);

-- Users who opted out of the network safety list.
CREATE TABLE IF NOT EXISTS safety_optout (
    user_id TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS temp_voice_owners (
    channel_id INTEGER PRIMARY KEY,
    owner_id   INTEGER,
    guild_id   INTEGER
);

CREATE TABLE IF NOT EXISTS temp_voice_profiles (
    profile_key TEXT PRIMARY KEY,
    data_json   TEXT
);

CREATE TABLE IF NOT EXISTS temp_voice_permanent (
    channel_id INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS ai_feedback (
    pos     INTEGER PRIMARY KEY AUTOINCREMENT,
    message TEXT,
    ai_said TEXT,
    correct TEXT,
    reason  TEXT,
    admin   TEXT,
    log_id  TEXT
);

CREATE TABLE IF NOT EXISTS guild_misc (
    guild_id  INTEGER,
    key       TEXT,
    data_json TEXT,
    PRIMARY KEY (guild_id, key)
)
"""
