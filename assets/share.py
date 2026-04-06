
from collections import deque
import time as _time

# ── Bot instance (set in on_ready, used by Prism notifications) ───────────────
bot = None

globalchat_message_data: dict = {}

phishing_url_list: set = set()

temp_voice_channels: set = set()

livestream_task = None

# ── Task instances (populated in on_ready) ────────────────────────────────────
task_instances: dict = {}   # task_key -> task object

# ── Admin: live log buffer (newest at right, max 500 entries) ─────────────────
admin_log_buffer: deque = deque(maxlen=500)
admin_log_total: int = 0  # total entries ever added (unbounded counter for offset tracking)

# ── Admin: task status tracker ────────────────────────────────────────────────
task_status: dict = {
    "GCDH": {
        "name": "Global Chat Data Handler",
        "status": "idle",
        "last_run": None,
        "detail": "Syncs global chat message data every 15s",
    },
    "UpdateStats": {
        "name": "Stats Updater",
        "status": "idle",
        "last_run": None,
        "detail": "Updates guild/user counts every 10 min",
    },
    "Livestream": {
        "name": "Livestream Checker",
        "status": "idle",
        "last_run": None,
        "detail": "Polls Twitch for streamer status",
        "extra": "",  # e.g. "Checking 12 streamers across 5 guilds"
    },
    "StatsChannels": {
        "name": "Stats Channels",
        "status": "idle",
        "last_run": None,
        "detail": "Updates voice channel stats every 10 min",
    },
    "TempActions": {
        "name": "Temp Actions",
        "status": "idle",
        "last_run": None,
        "detail": "Checks expired bans/mutes every 60s",
    },
    "TrustScore": {
        "name": "Prism Trust Scores",
        "status": "idle",
        "last_run": None,
        "detail": "Recalculates Prism scores every hour",
    },
    "PhishingList": {
        "name": "Phishing List",
        "status": "idle",
        "last_run": None,
        "detail": "Refreshes phishing domain list every 12h",
    },
    "GarbageCollector": {
        "name": "Garbage Collector",
        "status": "idle",
        "last_run": None,
        "detail": "Removes log entries older than 30 days (daily)",
    },
    "YouTubeVideos": {
        "name": "YouTube Video Tracker",
        "status": "idle",
        "last_run": None,
        "detail": "Checks YouTube channels for new video uploads every 10 min",
    },
}


def admin_log(level: str, message: str, source: str = "system"):
    """Append a log entry to the admin live log buffer."""
    global admin_log_total
    entry = {
        "time": _time.strftime("%H:%M:%S"),
        "level": level,   # "info" | "success" | "warning" | "error"
        "source": source,
        "message": message,
    }
    admin_log_buffer.append(entry)
    admin_log_total += 1


def set_task_status(task_key: str, status: str, detail: str = "", extra: str = ""):
    """Update task status and last_run timestamp."""
    if task_key not in task_status:
        return
    task_status[task_key]["status"] = status
    task_status[task_key]["last_run"] = _time.strftime("%H:%M:%S")
    if detail:
        task_status[task_key]["detail"] = detail
    if extra is not None:
        task_status[task_key]["extra"] = extra
    # Mirror to log buffer
    lvl = "success" if status == "ok" else ("error" if status == "error" else "info")
    admin_log(lvl, detail or status, source=task_key)
