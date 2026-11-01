"""Database backups -> self-hosted backup server.

Takes a consistent snapshot of the live SQLite DB (``sqlite3`` online-backup API, safe while the
bot keeps writing in WAL mode), gzips it and uploads it. Retention (30 days) and mirroring to
further locations are handled by the backup server, so nothing is deleted here except the temp
files. Credentials come from ``config.auth.Backup`` (environment variables, never committed).
"""
from __future__ import annotations

import asyncio
import datetime
import gzip
import hashlib
import os
import shutil
import sqlite3
import tempfile

from discord.ext import tasks

import assets.db as db
import config.auth as auth
import config.config as config
from assets.backup_client import BackupClient, BackupError
from assets.share import set_task_status
from reds_simple_logger import Logger

logger = Logger()

_META_KEY = "backup_last_success"
_FILENAME = "baxi-db.sqlite.gz"   # the server prepends a timestamp and never overwrites


def _peek(v: str) -> str:
    v = str(v)
    return f"'{v[:8]}…' (len {len(v)})" if len(v) > 8 else f"'{v}'"


def config_problem() -> str | None:
    """Why ``config.auth.Backup`` is unusable (None = fine). Shows only a short prefix of each value."""
    b = auth.Backup
    where = f"read from {getattr(auth, '__file__', 'config/auth.py')}"
    for env, attr in (("BACKUP_URL", "url"), ("BACKUP_PROJECT", "project_id"), ("BACKUP_KEY", "key")):
        if env in os.environ and getattr(b, attr, None) == os.environ[env]:
            where += f"; value comes from the environment variable {env}, which overrides the file"
    if not all(hasattr(b, k) for k in ("url", "project_id", "key")):
        return f"class Backup needs url, project_id and key ({where})"
    if "BACKUP-SERVER" in b.url or not b.url.strip():
        return f"url is missing or still the placeholder: {_peek(b.url)} ({where})"
    if not b.project_id.strip().startswith("prj_") or b.project_id == "prj_XXXXXXXXXX":
        return f"project_id is missing or still the placeholder: {_peek(b.project_id)} ({where})"
    if not b.key.strip().startswith("bks_") or b.key == "bks_YOUR-PROJECT-KEY":
        return f"key is missing or still the placeholder: {_peek(b.key)} ({where})"
    return None


def is_configured() -> bool:
    return config_problem() is None


def _client() -> BackupClient:
    url = auth.Backup.url.strip()
    if not url.startswith(("http://", "https://")):
        url = "http://" + url   # tolerate "host:port" without a scheme
    return BackupClient(url, auth.Backup.project_id.strip(), auth.Backup.key.strip(), timeout=600)


def _snapshot_gz(dest_gz: str) -> str:
    """Write a gzipped, consistent copy of the live DB to ``dest_gz``; returns the integrity result."""
    tmp_db = dest_gz[:-3]
    src = sqlite3.connect(db._DB_PATH)
    try:
        dst = sqlite3.connect(tmp_db)
        try:
            src.backup(dst)
            check = dst.execute("PRAGMA quick_check").fetchone()[0]
        finally:
            dst.close()
    finally:
        src.close()
    with open(tmp_db, "rb") as f_in, gzip.open(dest_gz, "wb", compresslevel=6) as f_out:
        shutil.copyfileobj(f_in, f_out)
    os.remove(tmp_db)
    return check


def backup_now(note: str = "") -> dict:
    """Blocking: snapshot + upload, then remember the time so the scheduler skips its next slot.

    Used by the scheduled task and the ``backup`` console command. Raises on failure.
    """
    with tempfile.TemporaryDirectory(prefix="baxi-backup-") as tmp:
        path = os.path.join(tmp, _FILENAME)
        check = _snapshot_gz(path)
        full_note = f"Baxi SQLite snapshot, quick_check={check}" + (f" ({note})" if note else "")
        meta = _client().upload(path, name=_FILENAME, note=full_note)
    db.schema_meta_set(_META_KEY, datetime.datetime.now(datetime.timezone.utc).isoformat())
    return meta


def list_backups() -> list[dict]:
    """Backups of this project on the server, newest first."""
    return sorted(_client().list(), key=lambda b: b["created_at"], reverse=True)


def download_snapshot(meta: dict, workdir: str) -> str:
    """Download backup ``meta`` into ``workdir``, verify SHA-256, gunzip and integrity-check it.

    Returns the path of the plain SQLite file. Raises ``BackupError`` if anything is off.
    """
    gz_path = os.path.join(workdir, "download.gz")
    _client().download(meta["id"], gz_path)
    sha = hashlib.sha256()
    with open(gz_path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            sha.update(chunk)
    if meta.get("sha256") and sha.hexdigest() != meta["sha256"]:
        raise BackupError("checksum mismatch - download is corrupt")
    db_path = os.path.join(workdir, "restored.sqlite")
    try:
        with gzip.open(gz_path, "rb") as f_in, open(db_path, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
        conn = sqlite3.connect(db_path)
        try:
            check = conn.execute("PRAGMA integrity_check").fetchone()[0]
            tables = conn.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
        finally:
            conn.close()
    except (OSError, sqlite3.Error) as e:
        raise BackupError(f"backup is not a valid SQLite database: {e}") from e
    if check != "ok" or tables == 0:
        raise BackupError(f"backup failed the integrity check ({check}, {tables} tables)")
    return db_path


def stage_snapshot(snapshot_path: str) -> str:
    """Put a verified snapshot next to the live DB as ``<db>.restore-pending``.

    The swap itself happens in ``db.init()`` at the next start (``db.apply_pending_restore``), so it
    is safe while the bot is running: nothing touches the open DB file until the bot restarts.
    """
    pending = db._DB_PATH + db.RESTORE_SUFFIX
    tmp = pending + ".tmp"
    shutil.copyfile(snapshot_path, tmp)
    os.replace(tmp, pending)   # atomic: a half-written file is never picked up
    return pending


def cancel_staged() -> bool:
    pending = db._DB_PATH + db.RESTORE_SUFFIX
    if os.path.exists(pending):
        os.remove(pending)
        return True
    return False


def _seconds_until_due() -> float:
    """Time left until the next backup is due, based on the last successful one (survives restarts)."""
    try:
        last = db.schema_meta_get(_META_KEY)
        if last:
            due = datetime.datetime.fromisoformat(last) + datetime.timedelta(hours=config.Backup.interval_hours)
            return max(0.0, (due - datetime.datetime.now(datetime.timezone.utc)).total_seconds())
    except Exception as e:
        logger.error(f"[Backup] could not read last backup time: {e}")
    return 0.0


class BackupTask:
    """Uploads a DB snapshot every ``config.Backup.interval_hours`` (first run waits until one is due)."""

    @tasks.loop(hours=config.Backup.interval_hours)
    async def backup(self):
        if not is_configured():
            set_task_status("Backup", "idle", f"Not configured: {config_problem()}")
            return
        set_task_status("Backup", "running", "Uploading database snapshot...")
        waits = (0, *config.Backup.retry_minutes)
        last_err: Exception | None = None
        for attempt, wait_min in enumerate(waits, start=1):
            if wait_min:
                await asyncio.sleep(wait_min * 60)
            try:
                meta = await asyncio.to_thread(backup_now)
            except (BackupError, OSError, sqlite3.Error) as e:
                last_err = e
                logger.error(f"[Backup] attempt {attempt}/{len(waits)} failed: {e}")
                continue
            size_kb = meta.get("size", 0) / 1024
            logger.debug.success(f"[Backup] uploaded {meta.get('filename')} ({size_kb:.0f} KiB)")
            set_task_status("Backup", "ok", f"Uploaded {meta.get('filename')} ({size_kb:.0f} KiB)")
            return
        set_task_status("Backup", "error", f"Backup failed after {len(waits)} attempts: {last_err}")

    @backup.before_loop
    async def _wait_until_due(self):
        delay = await asyncio.to_thread(_seconds_until_due)
        if delay > 0 and is_configured():
            set_task_status("Backup", "idle", f"Next backup in {delay / 3600:.1f}h")
            await asyncio.sleep(delay)
