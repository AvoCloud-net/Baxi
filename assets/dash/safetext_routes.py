"""Quart routes for the SafeText admin panel.

All endpoints are gated by `_require_bot_admin`, so only Baxi bot admins can
view the log, submit corrections (feedback overrides), label training samples,
reload the model or switch / roll back model versions.

Mount with `register(app, discord_auth, _require_bot_admin)`; see the call at
the end of `dash.dash_web`.
"""
from __future__ import annotations

import asyncio

import quart
from quart_discord import requires_authorization

from assets.message.safetext import feedback
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
        from assets.message.safetext import models as _models
        return quart.jsonify({
            "models": {"toxic": _models.current_source() or _models.TOXIC_MODEL},
            "feedback": feedback.stats(),
            "overrides": feedback.override_count(),
        })

    @app.route("/api/safetext/reload", methods=["POST"])
    @requires_authorization
    async def safetext_reload():
        _user, is_admin = await _require_bot_admin(discord_auth)
        if not is_admin:
            return _deny()
        from assets.message.safetext import lexicon
        from assets.message.safetext.models import reload_models
        reload_models()
        lexicon.reload()
        return quart.jsonify({"ok": True})

    # ── training samples ─────────────────────────────────────────────────────
    @app.route("/api/safetext/samples/next")
    @requires_authorization
    async def safetext_samples_next():
        _user, is_admin = await _require_bot_admin(discord_auth)
        if not is_admin:
            return _deny()
        from assets.message.safetext import samples
        skip = {s for s in quart.request.args.get("skip", "").split(",") if s}
        sample = await asyncio.to_thread(samples.next_unlabelled, skip)
        return quart.jsonify({"sample": sample, "stats": await asyncio.to_thread(samples.stats)})

    @app.route("/api/safetext/samples/label", methods=["POST"])
    @requires_authorization
    async def safetext_samples_label():
        user, is_admin = await _require_bot_admin(discord_auth)
        if not is_admin:
            return _deny()
        from assets.message.safetext import samples
        data = await quart.request.get_json(silent=True) or {}
        admin = str(getattr(user, "name", "unknown"))
        res = await asyncio.to_thread(samples.label, str(data.get("id", "")),
                                      str(data.get("label", "")), admin)
        if not res.get("ok"):
            return quart.jsonify(res), 400
        # A bot-admin label also corrects this exact message right away (global override).
        if res["label"] != "DISCARD":
            sample = res["sample"]
            model_said = "unsafe" if sample.get("verdict") == "unsafe" else "safe"
            await feedback.submit(
                log_id=f"sample:{sample['id']}", message=sample["text"],
                model_said=model_said, correct_label=res["label"], admin=admin,
                reason="training sample label",
            )
        return quart.jsonify({"ok": True, "stats": await asyncio.to_thread(samples.stats)})

    # ── model versions ───────────────────────────────────────────────────────
    @app.route("/api/safetext/models")
    @requires_authorization
    async def safetext_models():
        _user, is_admin = await _require_bot_admin(discord_auth)
        if not is_admin:
            return _deny()
        from assets.message.safetext import models as _models
        return quart.jsonify({
            "active": _models.read_active(),
            "loaded_from": _models.current_source(),
            "base_model": _models.BASE_MODEL,
            "versions": await asyncio.to_thread(_models.list_versions),
        })

    @app.route("/api/safetext/models/activate", methods=["POST"])
    @requires_authorization
    async def safetext_models_activate():
        user, is_admin = await _require_bot_admin(discord_auth)
        if not is_admin:
            return _deny()
        from assets.message.safetext import models as _models
        data = await quart.request.get_json(silent=True) or {}
        version = data.get("version") or None
        res = await asyncio.to_thread(_models.activate, version, str(getattr(user, "name", "")))
        return quart.jsonify(res), (200 if res.get("ok") else 400)
