#!/usr/bin/env python3
"""Smoke check for mc_link.render_status_embed — run from the repo root:

    python3 tools/check_mc_status_board.py

Covers the payload shapes the board must survive: offline, outdated plugin, a
Paper server (tps/mspt/via), a Velocity proxy (backends, no tps), and a minimal
response where every optional field is missing. No bot, no network, no Discord.
"""
import os
import sys

# Running a script puts tools/ on sys.path, not the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from assets.mc_link import format_uptime, render_status_embed

checks = 0


def check(cond, what):
    global checks
    checks += 1
    if not cond:
        raise AssertionError(f"FAILED: {what}")


def fields(embed):
    return {f.name: f.value for f in embed.fields}


# ── uptime formatting ────────────────────────────────────────────────────────
up = format_uptime
check(up(0) == "0m", "zero uptime")
check(up(59) == "0m", "sub-minute rounds down")
check(up(3600) == "1h 0m", "exact hour keeps the minutes place")
check(up(90061) == "1d 1h 1m", "days suppress nothing below them")
check(up(86399) == "23h 59m", "just under a day stays in hours")

# ── offline ──────────────────────────────────────────────────────────────────
e = render_status_embed(None, None)
check("offline" in e.title.lower(), "None renders as offline")
check("Last check" in fields(e), "offline board still shows a timestamp")

# ── outdated plugin ──────────────────────────────────────────────────────────
e = render_status_embed({"outdated": True}, None)
check("outdated" in e.title.lower(), "404 renders as outdated plugin")

# ── full Paper payload ───────────────────────────────────────────────────────
paper = {
    "online": True,
    "platform": "Paper",
    "version": "1.21.11",
    "uptime_seconds": 93784,
    "players": {"count": 7, "max": 50},
    "tps": [19.98, 19.95, 20.0],
    "mspt": 2.31,
    "via": {"min": 47, "max": 774, "min_name": "1.8", "max_name": "1.21.11"},
}
e = render_status_embed(paper, None)
f = fields(e)
check("online" in e.title.lower(), "healthy payload renders as online")
check(f["Players"] == "**7** / 50", "player counts render")
check(f["Uptime"] == "1d 2h 3m", "uptime renders")
check(f["Version"] == "Paper 1.21.11", "platform and version combine")
check("19.98" in f["Performance"] and "2.31" in f["Performance"], "tps and mspt render")
check(f["Clients"] == "`1.8` – `1.21.11`", "via range renders")
check("Backends" not in f, "no backends field for a single server")

# ── Velocity payload: backends, no tps ───────────────────────────────────────
velocity = {
    "online": True,
    "platform": "Velocity",
    "version": "3.3.0",
    "uptime_seconds": 300,
    "players": {"count": 3, "max": 100},
    "servers": [{"name": "lobby", "players": 2}, {"name": "smp", "players": 1}, {"name": "creative", "players": 0}],
}
e = render_status_embed(velocity, None)
f = fields(e)
check("Performance" not in f, "no performance field without tps")
check("lobby" in f["Backends"] and "smp" in f["Backends"], "populated backends listed")
check("creative" not in f["Backends"], "empty backends omitted")

# ── minimal payload: every optional field missing ────────────────────────────
e = render_status_embed({"online": True}, None)
f = fields(e)
check(f["Players"] == "**0** / 0", "missing players block defaults to 0/0")
check("Version" not in f, "missing version omits the field")
check("Clients" not in f, "missing via omits the field")

# ── single-version via collapses ─────────────────────────────────────────────
e = render_status_embed({"online": True, "via": {"min_name": "1.21.11", "max_name": "1.21.11"}}, None)
check(fields(e)["Clients"] == "`1.21.11`", "identical via bounds render once")

# ── German locale swaps the labels ───────────────────────────────────────────
import json
de = json.load(open("lang/lang.json"))["de"]["systems"]["mc_link"]
f = fields(render_status_embed(paper, de))
check("Spieler" in f and "Laufzeit" in f, "de locale renders localized field names")
check("Players" not in f, "de locale does not fall back to English")

print(f"mc status board OK — {checks} checks passed")
sys.exit(0)
