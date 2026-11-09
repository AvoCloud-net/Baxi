"""Exit feedback: ask someone by DM why they left a server.

Flow: member leaves -> (feature on, not banned/kicked, not asked in the last 30 days) -> one DM
embed with a "Give feedback" button -> modal with the questions the bot admin configured in the
admin dashboard -> answers stored in `exit_feedback`, shown in the admin dashboard.

The bot admin can also send the DM afterwards for any server/user pair (`send_manual`).

Two layers of config:
  * global (bot admin dashboard), `guild_misc` guild 1001 / key `exit_feedback`: enabled (master
    switch), title, description, button, footer (empty = language default), questions (the
    DEFAULT questions, None = language default), disabled_guilds (server ids that are skipped).
  * per server (server dashboard), conf key `exit_feedback`: enabled (opt-in, default off) and
    questions (own ones, None = use the global defaults).
A prompt goes out only when both switches are on; a manual send ignores them.

The DM button is persistent (DynamicItem, custom_id baxi:exitfb:<prompt_id>); everything the
modal needs (user, server, the question snapshot) is read from the stored row, because a DM
interaction has no guild.
"""
from __future__ import annotations

import asyncio
import copy
import datetime
import json
import os
import re

import discord
from discord.ext import commands
from reds_simple_logger import Logger

import assets.data as datasys
import assets.db as db
import config.config as config

logger = Logger()

CFG_GUILD, CFG_KEY = 1001, "exit_feedback"
MAX_QUESTIONS = 5            # Discord: a modal holds at most 5 components
COOLDOWN_DAYS = 30           # automatic prompts: at most one per (server, user) in this time
DM_TIMEOUT = 10
SETTLE_SECONDS = 4           # let a ban/kick show up before deciding it was a voluntary leave
TYPES = ("short", "paragraph", "select", "multiselect")
LIMITS = {"title": 256, "description": 2000, "button": 80, "footer": 200}

_cache: dict | None = None


# ── config ───────────────────────────────────────────────────────────────────

def _default_config() -> dict:
    return {"enabled": False, "title": "", "description": "", "button": "", "footer": "",
            "questions": None, "disabled_guilds": []}


def load_config() -> dict:
    global _cache
    if _cache is None:
        cfg = _default_config()
        try:
            rows = db.query("SELECT data_json FROM guild_misc WHERE guild_id=? AND key=?", (CFG_GUILD, CFG_KEY))
            if rows:
                cfg.update(json.loads(rows[0]["data_json"] or "{}"))
        except Exception as e:
            logger.error(f"[ExitFeedback] config load failed: {type(e).__name__}: {e}")
        _cache = cfg
    return copy.deepcopy(_cache)


def sanitize_question(q, idx: int) -> dict:
    """Validated copy of one question. Raises ValueError with a message for the admin."""
    n = idx + 1
    if not isinstance(q, dict):
        raise ValueError(f"Question {n}: invalid.")
    typ = str(q.get("type", ""))
    if typ not in TYPES:
        raise ValueError(f"Question {n}: unknown type.")
    label = str(q.get("label", "")).strip()
    if not 1 <= len(label) <= 45:
        raise ValueError(f"Question {n}: the label needs 1-45 characters (Discord limit).")
    help_ = str(q.get("help", "")).strip()
    if len(help_) > 100:
        raise ValueError(f"Question {n}: the hint is limited to 100 characters.")
    out = {"id": f"q{n}", "type": typ, "label": label, "help": help_,
           "required": bool(q.get("required")), "options": []}
    if typ in ("select", "multiselect"):
        raw = q.get("options", [])
        if isinstance(raw, str):
            raw = raw.splitlines()
        opts: list[str] = []
        for o in raw if isinstance(raw, list) else []:
            o = str(o).strip()
            if o and o not in opts:
                opts.append(o)
        if not 2 <= len(opts) <= 25 or any(len(o) > 100 for o in opts):
            raise ValueError(f"Question {n}: a dropdown needs 2-25 options of up to 100 characters.")
        out["options"] = opts
    return out


def sanitize_questions(raw) -> list[dict]:
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_QUESTIONS:
        raise ValueError(f"Add 1-{MAX_QUESTIONS} questions.")
    return [sanitize_question(q, i) for i, q in enumerate(raw)]


def sanitize_config(raw: dict) -> dict:
    """Validated config from the dashboard. Raises ValueError."""
    cfg = _default_config()
    cfg["enabled"] = bool(raw.get("enabled"))
    for k, mx in LIMITS.items():
        v = str(raw.get(k, "") or "").strip()
        if len(v) > mx:
            raise ValueError(f"'{k}' is limited to {mx} characters.")
        cfg[k] = v
    cfg["questions"] = None if raw.get("questions") is None else sanitize_questions(raw["questions"])
    ids = raw.get("disabled_guilds", [])
    if isinstance(ids, str):
        ids = re.split(r"[\s,;]+", ids)
    cfg["disabled_guilds"] = sorted({str(i).strip() for i in ids if str(i).strip().isdigit()})
    return cfg


def save_config(raw: dict) -> dict:
    global _cache
    cfg = sanitize_config(raw)
    db.execute(
        "INSERT INTO guild_misc (guild_id, key, data_json) VALUES (?,?,?) "
        "ON CONFLICT(guild_id, key) DO UPDATE SET data_json=excluded.data_json",
        (CFG_GUILD, CFG_KEY, json.dumps(cfg)))
    _cache = cfg
    return copy.deepcopy(cfg)


def guild_config(guild_id: int) -> dict:
    """Per-server settings from the server dashboard: enabled (opt-in) and own questions."""
    cfg = {"enabled": False, "questions": None}
    try:
        stored = datasys.load_data(int(guild_id), "exit_feedback")
        if isinstance(stored, dict):
            cfg.update({k: stored[k] for k in cfg if k in stored})
    except Exception as e:
        logger.error(f"[ExitFeedback] guild config load failed @ {guild_id}: {type(e).__name__}: {e}")
    return cfg


def sanitize_guild_config(raw: dict) -> dict:
    """Validated per-server settings. questions=None means 'use the global defaults'."""
    return {"enabled": bool(raw.get("enabled")),
            "questions": None if raw.get("questions") is None else sanitize_questions(raw["questions"])}


def global_questions(guild_id: int) -> list[dict]:
    """The default questions: set by the bot admin, else the language default of the server."""
    return load_config()["questions"] or default_questions(str(datasys.load_lang(int(guild_id))))


def effective_questions(guild_id: int) -> list[dict]:
    return guild_config(guild_id)["questions"] or global_questions(guild_id)


def default_questions(lang_code: str = "de") -> list[dict]:
    data = datasys.load_json(os.path.join("lang", "lang.json"))
    texts = (data.get(lang_code) or data["de"])["exit_feedback"]
    return sanitize_questions(texts["default_questions"])


def _texts(guild_id: int) -> dict:
    return datasys.load_lang_file(int(guild_id))["exit_feedback"]


def _fill(text: str, **kw) -> str:
    for k, v in kw.items():
        text = text.replace("{" + k + "}", str(v))
    return text


# ── storage ──────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.datetime.utcnow().isoformat(timespec="seconds")


def _recent(guild_id: int, user_id: int) -> bool:
    since = (datetime.datetime.utcnow() - datetime.timedelta(days=COOLDOWN_DAYS)).isoformat()
    rows = db.query(
        "SELECT 1 FROM exit_feedback WHERE guild_id=? AND user_id=? AND source='auto' "
        "AND status IN ('sent','answered') AND sent_at>=? LIMIT 1", (str(guild_id), str(user_id), since))
    return bool(rows)


def _create(guild_id, guild_name, user_id, user_name, source, questions) -> int:
    cur = db.execute(
        "INSERT INTO exit_feedback (guild_id,guild_name,user_id,user_name,source,status,questions_json) "
        "VALUES (?,?,?,?,?,'pending',?)",
        (str(guild_id), guild_name, str(user_id), user_name, source, json.dumps(questions)))
    return int(cur.lastrowid)


def _get(prompt_id: int) -> dict | None:
    rows = db.query("SELECT * FROM exit_feedback WHERE prompt_id=?", (int(prompt_id),))
    if not rows:
        return None
    r = dict(rows[0])
    r["questions"] = json.loads(r.pop("questions_json") or "[]")
    r["answers"] = json.loads(r.pop("answers_json") or "[]")
    return r


def _record_answers(prompt_id: int, user_id: int, answers: list[dict]) -> str:
    """'ok' | 'answered' | 'unavailable'. One answer per prompt, only by the person asked."""
    with db.transaction() as cx:
        row = cx.execute("SELECT user_id,status FROM exit_feedback WHERE prompt_id=?", (int(prompt_id),)).fetchone()
        if row is None or row["user_id"] != str(user_id) or row["status"] not in ("sent", "answered"):
            return "unavailable"
        if row["status"] == "answered":
            return "answered"
        cx.execute("UPDATE exit_feedback SET status='answered', answered_at=?, answers_json=? WHERE prompt_id=?",
                   (_now(), json.dumps(answers), int(prompt_id)))
    return "ok"


def list_for_guild(guild_id: int, limit: int = 100) -> list[dict]:
    """Answered feedback of ONE server (server dashboard), newest first, with the staff reply."""
    rows = db.query("SELECT * FROM exit_feedback WHERE guild_id=? AND status='answered' "
                    "ORDER BY prompt_id DESC LIMIT ?", (str(guild_id), int(limit)))
    return [{"id": r["prompt_id"], "user_id": r["user_id"], "user_name": r["user_name"],
             "answered_at": r["answered_at"], "answers": json.loads(r["answers_json"] or "[]"),
             "reply": r["reply_text"] or "", "replied_at": r["replied_at"]} for r in rows]


REPLY_MIN, REPLY_MAX = 2, 1000


async def reply(bot: commands.Bot, guild: discord.Guild, prompt_id: int, staff_name: str,
                text: str) -> tuple[bool, str]:
    """Server staff answer a piece of feedback; the text goes to the member by DM.
    One reply per feedback. Returns (ok, message for the staff member)."""
    text = (text or "").strip()
    if not REPLY_MIN <= len(text) <= REPLY_MAX:
        return False, f"The reply needs {REPLY_MIN}-{REPLY_MAX} characters."
    row = await asyncio.to_thread(_get, prompt_id)
    if row is None or row["guild_id"] != str(guild.id) or row["status"] != "answered":
        return False, "This feedback does not exist on this server."
    if row.get("reply_text"):
        return False, "This feedback has already been answered."
    import assets.message.chatfilter as chatfilter
    if not await chatfilter.text_is_clean(guild.id, 0, int(row["user_id"]), text):
        return False, "The reply was blocked by this server's chat filter."
    # claim first, so two staff members cannot both answer
    claimed = await asyncio.to_thread(
        lambda: db.execute("UPDATE exit_feedback SET reply_text=?, replied_at=?, replied_by=? "
                           "WHERE prompt_id=? AND COALESCE(reply_text,'')=''",
                           (text, _now(), staff_name[:80], int(prompt_id))).rowcount)
    if not claimed:
        return False, "This feedback has already been answered."
    try:
        t = _texts(guild.id)
        kw = {"server": guild.name}
        embed = discord.Embed(title=_fill(t["reply_title"], **kw), description=text, color=config.Discord.color)
        embed.set_author(name=guild.name, icon_url=guild.icon.url if guild.icon else None)
        embed.set_footer(text=_fill(t["reply_footer"], **kw))
        user = await bot.fetch_user(int(row["user_id"]))
        await asyncio.wait_for(user.send(embed=embed), DM_TIMEOUT)
    except Exception as e:
        await asyncio.to_thread(
            db.execute, "UPDATE exit_feedback SET reply_text='', replied_at=NULL, replied_by='' WHERE prompt_id=?",
            (int(prompt_id),))
        if isinstance(e, (discord.Forbidden, discord.NotFound, asyncio.TimeoutError)):
            return False, "The member cannot be reached by DM (closed DMs, or no server in common)."
        logger.error(f"[ExitFeedback] reply DM failed @ {guild.id}: {type(e).__name__}: {e}")
        return False, "Sending failed, please try again later."
    await _update_staff_notice(guild, row, text, staff_name)
    return True, "Reply sent."


def list_responses(limit: int = 100) -> list[dict]:
    rows = db.query("SELECT * FROM exit_feedback WHERE status IN ('sent','answered') "
                    "ORDER BY prompt_id DESC LIMIT ?", (int(limit),))
    out = []
    for r in rows:
        out.append({"id": r["prompt_id"], "guild_id": r["guild_id"], "guild_name": r["guild_name"],
                    "user_id": r["user_id"], "user_name": r["user_name"], "source": r["source"],
                    "status": r["status"], "sent_at": r["sent_at"], "answered_at": r["answered_at"],
                    "answers": json.loads(r["answers_json"] or "[]"),
                    "reply": r["reply_text"] or ""})
    return out


def stats() -> dict:
    rows = db.query("SELECT status, COUNT(*) AS n FROM exit_feedback GROUP BY status")
    c = {r["status"]: r["n"] for r in rows}
    sent, answered = c.get("sent", 0), c.get("answered", 0)
    return {"sent": sent + answered, "answered": answered}


def delete_user(user_id: int | str) -> int:
    """Remove everything stored about this person (data deletion in the admin dashboard)."""
    return db.execute("DELETE FROM exit_feedback WHERE user_id=?", (str(user_id),)).rowcount


# ── DM, button, modal ────────────────────────────────────────────────────────

def build_embed(bot: commands.Bot, guild: discord.Guild, cfg: dict) -> discord.Embed:
    t = _texts(guild.id)
    kw = {"server": guild.name, "bot": bot.user.name if bot.user else "Baxi"}
    embed = discord.Embed(title=_fill(cfg["title"] or t["title"], **kw),
                          description=_fill(cfg["description"] or t["description"], **kw),
                          color=config.Discord.color)
    embed.set_author(name=guild.name, icon_url=guild.icon.url if guild.icon else None)
    embed.set_footer(text=_fill(cfg["footer"] or t["footer"], **kw))
    return embed


async def send_prompt(bot: commands.Bot, guild: discord.Guild, user: discord.abc.User, *,
                      manual: bool = False) -> str:
    """Send the DM. Returns 'sent' | 'off' | 'guild_off' | 'recent' | 'bot' | 'dm_closed' | 'failed'.
    Automatic prompts respect the switch, the per-server opt-out and the 30-day limit; a manual
    send (admin dashboard) ignores all three."""
    if getattr(user, "bot", False):
        return "bot"
    cfg = load_config()
    if not manual:
        if not cfg["enabled"] or not guild_config(guild.id)["enabled"]:
            return "off"
        if str(guild.id) in cfg["disabled_guilds"]:
            return "guild_off"
        if await asyncio.to_thread(_recent, guild.id, user.id):
            return "recent"
    try:
        t = _texts(guild.id)
        questions = effective_questions(guild.id)
        embed = build_embed(bot, guild, cfg)
        prompt_id = await asyncio.to_thread(
            _create, guild.id, guild.name, user.id, getattr(user, "name", str(user.id)),
            "manual" if manual else "auto", questions)
    except Exception as e:
        logger.error(f"[ExitFeedback] prepare failed @ {guild.id}: {type(e).__name__}: {e}")
        return "failed"
    view = discord.ui.View(timeout=None)
    view.add_item(FeedbackButton(prompt_id, _fill(cfg["button"] or t["button"], server=guild.name)))
    try:
        await asyncio.wait_for(user.send(embed=embed, view=view), DM_TIMEOUT)
    except (discord.Forbidden, discord.HTTPException, asyncio.TimeoutError):
        await asyncio.to_thread(db.execute, "DELETE FROM exit_feedback WHERE prompt_id=?", (prompt_id,))
        return "dm_closed"
    except Exception as e:
        logger.error(f"[ExitFeedback] DM failed @ {guild.id}: {type(e).__name__}: {e}")
        await asyncio.to_thread(db.execute, "DELETE FROM exit_feedback WHERE prompt_id=?", (prompt_id,))
        return "failed"
    await asyncio.to_thread(db.execute, "UPDATE exit_feedback SET status='sent', sent_at=? WHERE prompt_id=?",
                            (_now(), prompt_id))
    return "sent"


class FeedbackModal(discord.ui.Modal):
    def __init__(self, row: dict, texts: dict):
        super().__init__(title=_fill(texts["modal_title"], server=row["guild_name"])[:45], timeout=900)
        self.prompt_id, self.texts, self.questions = row["prompt_id"], texts, row["questions"][:MAX_QUESTIONS]
        self.guild_id = int(row["guild_id"])
        self._inputs: list[tuple[dict, discord.ui.Item]] = []
        for q in self.questions:
            if q["type"] in ("short", "paragraph"):
                comp = discord.ui.TextInput(
                    style=discord.TextStyle.short if q["type"] == "short" else discord.TextStyle.paragraph,
                    placeholder=q["help"] or None, required=q["required"],
                    max_length=200 if q["type"] == "short" else 1000)
                self.add_item(discord.ui.Label(text=q["label"], component=comp))
            else:
                multi = q["type"] == "multiselect"
                comp = discord.ui.Select(
                    options=[discord.SelectOption(label=o, value=o) for o in q["options"]],
                    min_values=1 if q["required"] else 0,
                    max_values=len(q["options"]) if multi else 1,
                    required=q["required"])
                self.add_item(discord.ui.Label(text=q["label"], description=q["help"] or None, component=comp))
            self._inputs.append((q, comp))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        answers = []
        for q, comp in self._inputs:
            if isinstance(comp, discord.ui.TextInput):
                value = comp.value.strip()
            else:
                vals = list(comp.values)
                value = vals if q["type"] == "multiselect" else (vals[0] if vals else "")
            if value:
                answers.append({"id": q["id"], "label": q["label"], "type": q["type"], "answer": value})
        status = await asyncio.to_thread(_record_answers, self.prompt_id, interaction.user.id, answers)
        key = {"ok": "thanks", "answered": "already"}.get(status, "unavailable")
        await interaction.response.send_message(self.texts[key], ephemeral=True)
        if status == "ok":
            asyncio.get_running_loop().create_task(
                post_staff_notice(interaction.client, self.guild_id, self.prompt_id, interaction.user, answers))
            try:   # the button has done its job
                if interaction.message is not None:
                    await interaction.message.edit(view=None)
            except discord.HTTPException:
                pass

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        logger.error(f"[ExitFeedback] modal error: {type(error).__name__}: {error}")
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(self.texts["failed"], ephemeral=True)
        except discord.HTTPException:
            pass


class FeedbackButton(discord.ui.DynamicItem[discord.ui.Button], template=r"baxi:exitfb:(?P<id>[0-9]+)"):
    def __init__(self, prompt_id: int, label: str = "Feedback") -> None:
        super().__init__(discord.ui.Button(label=label[:80], style=discord.ButtonStyle.primary,
                                           custom_id=f"baxi:exitfb:{prompt_id}"))
        self.prompt_id = int(prompt_id)

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button,
                             match: re.Match[str]) -> "FeedbackButton":
        return cls(int(match["id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        row = await asyncio.to_thread(_get, self.prompt_id)
        if row is None or row["user_id"] != str(interaction.user.id) or row["status"] not in ("sent", "answered"):
            t = _texts(1001)
            return await interaction.response.send_message(t["unavailable"], ephemeral=True)
        t = _texts(int(row["guild_id"]))
        if row["status"] == "answered":
            return await interaction.response.send_message(t["already"], ephemeral=True)
        await interaction.response.send_modal(FeedbackModal(row, t))


# ── staff channel notice + reply button ──────────────────────────────────────

def _staff_embed(guild: discord.Guild, user_name: str, user_id, answers: list[dict]) -> discord.Embed:
    t = _texts(guild.id)
    embed = discord.Embed(title=_fill(t["staff_title"], user=user_name),
                          description=_fill(t["staff_desc"], user=user_name),
                          color=config.Discord.color)
    for a in answers[:MAX_QUESTIONS]:
        val = ", ".join(a["answer"]) if isinstance(a["answer"], list) else str(a["answer"])
        embed.add_field(name=str(a["label"])[:256], value=val[:1024] or "-", inline=False)
    if not answers:
        embed.add_field(name="-", value="-", inline=False)
    embed.set_footer(text=_fill(t["staff_footer"], id=user_id))
    return embed


async def post_staff_notice(bot: commands.Bot, guild_id: int, prompt_id: int, user: discord.abc.User,
                            answers: list[dict]) -> None:
    """Tell the server's staff channel that feedback arrived, with a Reply button. Best effort."""
    try:
        guild = bot.get_guild(int(guild_id))
        if guild is None:
            return
        from assets import staff
        channel = staff.staff_channel(guild)
        if channel is None:
            return
        t = _texts(guild.id)
        view = discord.ui.View(timeout=None)
        view.add_item(StaffReplyButton(prompt_id, t["staff_button"]))
        msg = await channel.send(embed=_staff_embed(guild, getattr(user, "display_name", user.name), user.id, answers),
                                 view=view, allowed_mentions=discord.AllowedMentions.none())
        await asyncio.to_thread(db.execute,
                                "UPDATE exit_feedback SET staff_channel_id=?, staff_message_id=? WHERE prompt_id=?",
                                (str(channel.id), str(msg.id), int(prompt_id)))
    except Exception as e:
        logger.error(f"[ExitFeedback] staff notice failed @ {guild_id}: {type(e).__name__}: {e}")


async def _update_staff_notice(guild: discord.Guild, row: dict, text: str, staff_name: str) -> None:
    """After a reply (from the button or the dashboard): show it on the staff message, drop the button."""
    try:
        if not row.get("staff_channel_id") or not row.get("staff_message_id"):
            return
        channel = guild.get_channel(int(row["staff_channel_id"]))
        if channel is None:
            return
        msg = await channel.fetch_message(int(row["staff_message_id"]))
        embed = msg.embeds[0] if msg.embeds else discord.Embed(color=config.Discord.color)
        embed.add_field(name=_fill(_texts(guild.id)["staff_reply_field"], staff=staff_name)[:256],
                        value=text[:1024], inline=False)
        await msg.edit(embed=embed, view=None)
    except Exception as e:
        logger.warning(f"[ExitFeedback] staff notice update failed @ {guild.id}: {type(e).__name__}: {e}")


class StaffReplyModal(discord.ui.Modal):
    def __init__(self, prompt_id: int, user_name: str, texts: dict):
        super().__init__(title=_fill(texts["staff_modal_title"], user=user_name)[:45], timeout=900)
        self.prompt_id, self.texts = prompt_id, texts
        self.text = discord.ui.TextInput(style=discord.TextStyle.paragraph, min_length=REPLY_MIN, max_length=REPLY_MAX,
                                         placeholder=texts["staff_modal_placeholder"][:100], required=True)
        self.add_item(discord.ui.Label(text=texts["staff_modal_label"][:45], component=self.text))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        ok, msg = await reply(interaction.client, interaction.guild, self.prompt_id,
                              interaction.user.display_name, self.text.value)
        await interaction.followup.send(self.texts["staff_sent"] if ok else msg, ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        logger.error(f"[ExitFeedback] staff modal error: {type(error).__name__}: {error}")
        try:
            msg = self.texts["failed"]
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except discord.HTTPException:
            pass


class StaffReplyButton(discord.ui.DynamicItem[discord.ui.Button], template=r"baxi:exitfbreply:(?P<id>[0-9]+)"):
    def __init__(self, prompt_id: int, label: str = "Reply") -> None:
        super().__init__(discord.ui.Button(label=label[:80], style=discord.ButtonStyle.primary,
                                           custom_id=f"baxi:exitfbreply:{prompt_id}"))
        self.prompt_id = int(prompt_id)

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button,
                             match: re.Match[str]) -> "StaffReplyButton":
        return cls(int(match["id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        guild, member = interaction.guild, interaction.user
        if guild is None:
            return await interaction.response.send_message(_texts(1001)["unavailable"], ephemeral=True)
        t = _texts(guild.id)
        row = await asyncio.to_thread(_get, self.prompt_id)
        if row is None or row["guild_id"] != str(guild.id) or row["status"] != "answered":
            return await interaction.response.send_message(t["unavailable"], ephemeral=True)
        from assets import staff
        if not (isinstance(member, discord.Member) and (staff.is_staff(member) or member.guild_permissions.manage_guild)):
            return await interaction.response.send_message(t["staff_no_permission"], ephemeral=True)
        if row.get("reply_text"):
            return await interaction.response.send_message(t["staff_already"], ephemeral=True)
        await interaction.response.send_modal(StaffReplyModal(self.prompt_id, row["user_name"] or str(row["user_id"]), t))


# ── triggers ─────────────────────────────────────────────────────────────────

async def _was_removed(guild: discord.Guild, member: discord.abc.User) -> bool:
    """True if the member was banned or kicked (they are not asked why they 'left')."""
    try:
        await guild.fetch_ban(discord.Object(id=member.id))
        return True
    except discord.NotFound:
        pass
    except discord.HTTPException:
        pass
    try:   # read-only look, does not claim the entry the server log uses
        cutoff = discord.utils.utcnow() - datetime.timedelta(seconds=30)
        async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.kick):
            if entry.created_at >= cutoff and getattr(entry.target, "id", None) == member.id:
                return True
    except (discord.Forbidden, discord.HTTPException):
        pass
    return False


async def _on_leave(bot: commands.Bot, member: discord.Member) -> None:
    try:
        await asyncio.sleep(SETTLE_SECONDS)
        if await _was_removed(member.guild, member):
            return
        status = await send_prompt(bot, member.guild, member)
        if status not in ("sent", "off", "guild_off", "recent", "bot", "dm_closed"):
            logger.warning(f"[ExitFeedback] {member.id} @ {member.guild.id}: {status}")
    except Exception as e:
        logger.error(f"[ExitFeedback] leave handler failed: {type(e).__name__}: {e}")


def on_member_remove(bot: commands.Bot, member: discord.Member) -> None:
    """Called from events.on_member_remove. Cheap when the feature is off."""
    if member.bot:
        return
    cfg = load_config()
    if not cfg["enabled"] or str(member.guild.id) in cfg["disabled_guilds"]:
        return
    if not guild_config(member.guild.id)["enabled"]:
        return
    asyncio.get_running_loop().create_task(_on_leave(bot, member))


async def send_manual(bot: commands.Bot, guild_id: int, user_id: int) -> tuple[bool, str]:
    """Admin dashboard: send the DM for any server/user pair. Returns (ok, message)."""
    guild = bot.get_guild(int(guild_id))
    if guild is None:
        return False, "Baxi is not on that server (unknown server ID)."
    try:
        user = await bot.fetch_user(int(user_id))
    except discord.NotFound:
        return False, "User not found."
    except discord.HTTPException as e:
        return False, f"Discord error: {e}"
    status = await send_prompt(bot, guild, user, manual=True)
    msg = {"sent": f"Sent to {user.name} for {guild.name}.",
           "bot": "That user is a bot.",
           "dm_closed": f"{user.name} cannot be reached by DM (closed DMs, or no server in common).",
           }.get(status, "Sending failed, see the logs.")
    return status == "sent", msg
