"""Quart routes for the SafeText admin panel.

All endpoints are gated by `_require_bot_admin`, so only Baxi bot admins can
view the log, mark feedback, or trigger a fine-tune.

Mount with `register(app, discord_auth, _require_bot_admin)`; see the call at
the end of `dash.dash_web`.
"""
from __future__ import annotations

import quart
from quart_discord import requires_authorization

from assets.message.safetext import feedback, finetune
from assets.message.safetext.logstore import read_recent


def register(app, discord_auth, _require_bot_admin, bot=None) -> None:

    def _deny():
        return quart.jsonify({"error": "forbidden"}), 403

    def _enrich(entries: list[dict]) -> list[dict]:
        if bot is None:
            return entries
        g_cache: dict[int, str] = {}
        u_cache: dict[int, str] = {}
        for e in entries:
            gid = e.get("gid")
            uid = e.get("user_id")
            if isinstance(gid, int):
                if gid not in g_cache:
                    g = bot.get_guild(gid)
                    g_cache[gid] = g.name if g else ""
                e["guild_name"] = g_cache[gid]
            if isinstance(uid, int):
                if uid not in u_cache:
                    u = bot.get_user(uid)
                    u_cache[uid] = u.name if u else ""
                e["user_name"] = u_cache[uid]
        return entries

    @app.route("/api/safetext/log")
    @requires_authorization
    async def safetext_log():
        _user, is_admin = await _require_bot_admin(discord_auth)
        if not is_admin:
            return _deny()
        limit = min(int(quart.request.args.get("limit", 200)), 1000)
        gid_arg = quart.request.args.get("gid")
        gid = int(gid_arg) if gid_arg and gid_arg.isdigit() else None
        entries = read_recent(limit=limit, guild_id=gid)
        return quart.jsonify({"entries": _enrich(entries)})

    @app.route("/api/safetext/feedback", methods=["POST"])
    @requires_authorization
    async def safetext_feedback():
        user, is_admin = await _require_bot_admin(discord_auth)
        if not is_admin:
            return _deny()
        data = await quart.request.get_json(silent=True) or {}
        required = ("log_id", "message", "model_said", "correct_label")
        if any(k not in data for k in required):
            return quart.jsonify({"error": "missing fields", "required": required}), 400
        result = await feedback.submit(
            log_id=str(data["log_id"]),
            message=str(data["message"]),
            model_said=str(data["model_said"]),
            correct_label=str(data["correct_label"]),
            reason=str(data.get("reason") or ""),
            admin=str(getattr(user, "name", "unknown")),
        )
        return quart.jsonify(result)

    @app.route("/api/safetext/feedback/list")
    @requires_authorization
    async def safetext_feedback_list():
        _user, is_admin = await _require_bot_admin(discord_auth)
        if not is_admin:
            return _deny()
        only_untrained = quart.request.args.get("only_untrained") == "1"
        return quart.jsonify({"entries": feedback.list_entries(only_untrained=only_untrained)})

    @app.route("/api/safetext/status")
    @requires_authorization
    async def safetext_status():
        _user, is_admin = await _require_bot_admin(discord_auth)
        if not is_admin:
            return _deny()
        from assets.message.safetext.models import LORA_DIR, TOXIC_MODEL
        return quart.jsonify({
            "models": {"toxic": TOXIC_MODEL},
            "lora_present": LORA_DIR.exists() and any(LORA_DIR.iterdir()),
            "feedback": feedback.stats(),
            "finetune": finetune.read_status(),
        })

    @app.route("/api/safetext/finetune", methods=["POST"])
    @requires_authorization
    async def safetext_finetune():
        _user, is_admin = await _require_bot_admin(discord_auth)
        if not is_admin:
            return _deny()
        return quart.jsonify(await finetune.start_job())

    @app.route("/api/safetext/reload", methods=["POST"])
    @requires_authorization
    async def safetext_reload():
        _user, is_admin = await _require_bot_admin(discord_auth)
        if not is_admin:
            return _deny()
        from assets.message.safetext.models import reload_models
        reload_models()
        return quart.jsonify({"ok": True})
