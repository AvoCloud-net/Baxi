"""Appeals: a user asks the team to reverse a case.

One flow for every kind of action: "Appeal" button (DM) or the appeal page (dashboard)
-> one text field -> an item of kind `appeal` in the review queue -> staff press Lift or
Keep (with an optional short reason) -> the user gets the answer by DM and on the page.

Rules, all enforced in one transaction (repo/cases.submit_appeal):
  * only the person the case is about,
  * one appeal per case,
  * until APPEAL_WINDOW_DAYS (14) after the action,
  * not for unban/unmute, not for a case that is already lifted.

The DM button is persistent (DynamicItem, custom_id baxi:appeal:<guild>:<case>) and works
from DMs, where the interaction has no guild - everything is read from the custom_id.
"""
from __future__ import annotations

import asyncio
import datetime
import re

import discord
from assets import dither_art
from discord.ext import commands
from reds_simple_logger import Logger

import assets.data as datasys
import assets.repo as repo
import config.config as config
from assets import staff
from assets.repo import cases as store

logger = Logger()

TEXT_MIN, TEXT_MAX = 10, 1000
REASON_MAX = 300


# ── submit ───────────────────────────────────────────────────────────────────

def check_text(text: str) -> str | None:
    t = (text or "").strip()
    return t if TEXT_MIN <= len(t) <= TEXT_MAX else None


async def submit(bot: commands.AutoShardedBot, guild_id: int, case_no: int,
                 user: discord.abc.User, text: str) -> str:
    """Create the appeal. Returns a status key (see module docstring) - 'ok' on success,
    plus 'no_guild' / 'failed' / 'too_short'."""
    guild = bot.get_guild(int(guild_id))
    if guild is None:
        return "no_guild"
    clean = check_text(text)
    if clean is None:
        return "too_short"
    try:
        status, _pos = await asyncio.to_thread(
            store.submit_appeal, int(guild_id), int(case_no), user.id, user.name, clean)
    except Exception as e:
        logger.error(f"[Appeals] submit failed @ {guild_id}: {type(e).__name__}: {e}")
        return "failed"
    if status == "ok":
        staff.schedule_refresh(bot, guild)
    return status


def appeal_state(case: dict, now: datetime.datetime | None = None) -> str:
    """What a user may do with this case: open (can appeal) | sent | lifted | kept | expired | no."""
    if case.get("type") not in store.APPEALABLE_TYPES:
        return "no"
    if case.get("lifted") and case.get("appeal") != "lifted":
        return "lifted_plain"
    a = case.get("appeal")
    if a == "open":
        return "sent"
    if a in ("lifted", "kept"):
        return a
    now = now or datetime.datetime.utcnow()
    try:
        age = now - datetime.datetime.fromisoformat(case.get("timestamp", ""))
    except ValueError:
        return "expired"
    return "expired" if age > datetime.timedelta(days=store.APPEAL_WINDOW_DAYS) else "open"


PAGE_DAYS = 30   # the page also shows the answer to an appeal for a while after the 14 days


def page_since() -> str:
    return (datetime.datetime.utcnow() - datetime.timedelta(days=PAGE_DAYS)).isoformat()


def cases_for_page(guild_id: int, user_id: int) -> list[dict]:
    """The caller's OWN cases that can still be appealed (14 days) or that have an appeal
    (up to 30 days) - the only thing the appeal page shows. The user id always comes from
    the login session, never from the request."""
    out = []
    for c in store.cases_for_user(int(guild_id), user_id, limit=100):
        if c["type"] in store.APPEALABLE_TYPES and c["timestamp"] >= page_since():
            if appeal_state(c) != "expired" or c.get("appeal"):
                out.append(c)
    return out


# ── the DM button + modal ────────────────────────────────────────────────────

class AppealModal(discord.ui.Modal):
    def __init__(self, guild_id: int, case_no: int, lang: dict):
        m = lang["moderation"]["appeal"]
        super().__init__(title=str(m["modal_title"]).format(no=case_no)[:45], timeout=900)
        self.guild_id, self.case_no, self.lang = guild_id, case_no, lang
        self.text = discord.ui.TextInput(
            label=m["field_label"][:45], placeholder=m["field_placeholder"][:100],
            style=discord.TextStyle.paragraph, min_length=TEXT_MIN, max_length=TEXT_MAX, required=True)
        self.add_item(self.text)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        m = self.lang["moderation"]["appeal"]
        status = await submit(interaction.client, self.guild_id, self.case_no, interaction.user, self.text.value)
        if status == "ok":
            await interaction.response.send_message(str(m["sent"]).format(no=self.case_no), ephemeral=True)
            # the button has done its job: take it off the DM (best effort)
            try:
                if interaction.message is not None:
                    await interaction.message.edit(view=None)
            except discord.HTTPException:
                pass
            return
        await interaction.response.send_message(_error_text(self.lang, status), ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        logger.error(f"[Appeals] modal error: {type(error).__name__}: {error}")
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(_error_text(self.lang, "failed"), ephemeral=True)
        except discord.HTTPException:
            pass


def _error_text(lang: dict, status: str) -> str:
    errors = lang["moderation"]["appeal"]["errors"]
    # "no such case", "not yours" and "no such server" all read the same: the answer must not
    # tell anybody which case numbers exist or whose they are.
    key = {"not_found": "unavailable", "not_yours": "unavailable", "no_guild": "unavailable"}.get(status, status)
    return str(errors.get(key, errors["failed"])).format(days=store.APPEAL_WINDOW_DAYS, min=TEXT_MIN)


class AppealButton(discord.ui.DynamicItem[discord.ui.Button],
                   template=r"baxi:appeal:(?P<gid>[0-9]+):(?P<no>[0-9]+)"):
    def __init__(self, guild_id: int, case_no: int, label: str = "Appeal") -> None:
        super().__init__(discord.ui.Button(
            label=label, style=discord.ButtonStyle.secondary,
            custom_id=f"baxi:appeal:{guild_id}:{case_no}"))
        self.guild_id, self.case_no = int(guild_id), int(case_no)

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button,
                             match: re.Match[str]) -> "AppealButton":
        return cls(int(match["gid"]), int(match["no"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        # The guild comes from the custom_id: in a DM interaction.guild is None.
        lang = datasys.load_lang_file(self.guild_id)
        case = await asyncio.to_thread(store.get_case, self.guild_id, self.case_no)
        if case is None or case["user_id"] != str(interaction.user.id):
            # the button only exists in the user's own DM; this guards against a forwarded copy
            return await interaction.response.send_message(
                _error_text(lang, "not_found" if case is None else "not_yours"), ephemeral=True)
        state = appeal_state(case)
        if state != "open":
            key = {"sent": "already", "lifted": "lifted", "lifted_plain": "lifted", "kept": "already",
                   "expired": "expired"}.get(state, "not_appealable")
            return await interaction.response.send_message(_error_text(lang, key), ephemeral=True)
        await interaction.response.send_modal(AppealModal(self.guild_id, self.case_no, lang))


# ── staff decision ───────────────────────────────────────────────────────────

def lift_permission(case_type: str) -> str | None:
    """Discord permission a staffer needs to lift a case of this type (besides Manage Server)."""
    return {"ban": "ban_members", "mute": "moderate_members"}.get(case_type)


async def apply_decision(bot: commands.AutoShardedBot, guild_id: int, item: dict, action: str,
                         reason: str, staff_name: str) -> str:
    """Do what staff decided: 'lift' undoes the case where that is possible, 'keep' leaves it.
    Updates the case, tells the user. discord.Forbidden from the undo propagates (the
    caller puts the queue item back to pending). Returns a short note for the dashboard."""
    ctx = dict(item.get("context") or {})
    case_no = int(ctx.get("case_no") or 0)
    reason = (reason or "").strip()[:REASON_MAX]
    guild = bot.get_guild(guild_id)
    case = await asyncio.to_thread(store.get_case, guild_id, case_no)
    now = datetime.datetime.utcnow().isoformat()
    notes: list[str] = []
    what_key = "record"

    if action == "lift":
        if case is not None and guild is not None:
            note_text, what_key = await _undo(bot, guild, case, staff_name)
            notes.append(note_text)
        elif case is None:
            notes.append("The case no longer exists.")
        await asyncio.to_thread(store.update_case, guild_id, case_no, {
            "lifted": "1", "appeal": "lifted", "appeal_decided": now,
            "appeal_note": reason or None})
        if case is not None and (case["type"] == "filter" or case.get("log_id") or case.get("sample_id")):
            await _learn_false_positive(guild_id, case, staff_name)
            notes.append("Sent to the chat filter as a suggested false positive.")
    else:
        await asyncio.to_thread(store.update_case, guild_id, case_no, {
            "appeal": "kept", "appeal_decided": now, "appeal_note": reason or None})
        notes.append("The case stays.")

    await asyncio.to_thread(store.set_review_context, guild_id, int(item["pos"]), {
        "decision": action, "decision_reason": reason})
    if guild is not None:
        sent = await _tell_user(bot, guild, int(item["user_id"]), case_no, case, action, reason, what_key)
        notes.append("The user was told by DM." if sent else "The user could not be reached by DM; the appeal page shows the answer.")
    return " ".join(n for n in notes if n)


def _naive_utc(dt: datetime.datetime) -> datetime.datetime:
    return dt.astimezone(datetime.timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


async def _member_of(guild: discord.Guild, uid: int):
    """The member from the cache, else from Discord; None if they left."""
    member = guild.get_member(uid)
    if member is not None:
        return member
    try:
        return await guild.fetch_member(uid)
    except (discord.NotFound, discord.HTTPException):
        return None


async def _undo(bot: commands.AutoShardedBot, guild: discord.Guild, case: dict, staff_name: str) -> tuple[str, str]:
    """Undo what can be undone. Returns (note for staff, key of the sentence for the user in
    lang.moderation.appeal.result.what). Says what really happened - never claims a mute was
    removed that had already ended."""
    gid, uid, typ = guild.id, int(case["user_id"]), case["type"]
    lang = datasys.load_lang_file(gid)
    audit = str(lang["moderation"]["appeal"]["lift_reason"]).format(no=case["no"]) + f" - {staff_name}"
    if typ == "warn":
        wid = case.get("warn_id")
        if wid:
            await asyncio.to_thread(repo.remove_warning, gid, str(uid), str(wid))
            return "The warning was removed.", "warn"
        return "Case cleared (this old warning has no link to a stored warning, remove it with /unwarn if needed).", "record"
    if typ == "mute":
        member = await _member_of(guild, uid)
        now = datetime.datetime.utcnow()
        until = _naive_utc(member.timed_out_until) if member is not None and member.timed_out_until else None
        active = until is not None and until > now
        end = None
        if case.get("duration_s"):
            try:
                end = datetime.datetime.fromisoformat(case["timestamp"]) + datetime.timedelta(seconds=int(case["duration_s"]))
            except ValueError:
                end = None
        if not active:
            return "The mute had already ended; the case is cleared.", "mute_ended"
        if end is not None and (end <= now or abs((until - end).total_seconds()) > 120):
            return "The member has a different, newer mute; it was left alone and this case is cleared.", "mute_other"
        await member.timeout(None, reason=audit)
        ta = datasys.load_temp_actions(gid)
        ta["timeouts"] = [t for t in ta.get("timeouts", []) if int(t.get("user_id", 0)) != uid]
        datasys.save_temp_actions(gid, ta)
        return "The mute was removed.", "mute"
    if typ == "ban":
        try:
            await guild.unban(discord.Object(id=uid), reason=audit)
            msg, key = "The user was unbanned.", "ban"
        except discord.NotFound:
            msg, key = "The user was already unbanned.", "ban_done"
        ta = datasys.load_temp_actions(gid)
        ta["bans"] = [t for t in ta.get("bans", []) if int(t.get("user_id", 0)) != uid]
        datasys.save_temp_actions(gid, ta)
        return msg, key
    if typ == "kick":
        return "A kick can't be undone; the case is cleared.", "record"
    return "The case is cleared.", "record"


async def _learn_false_positive(guild_id: int, case: dict, staff_name: str) -> None:
    """Same path as 'OK' on a borderline item (moderation/borderline.learn): an exact-match
    override for THIS server, and - if the server opted in - a *suggestion* for the bot
    admins' labelling queue. Never a final training label. Never raises."""
    text = ""
    log_id = str(case.get("log_id") or "")
    if log_id:
        try:
            text = await asyncio.to_thread(store.chatfilter_message, log_id)
        except Exception:
            text = ""
    if text:
        try:
            from assets.message.safetext import feedback
            await feedback.submit(
                log_id=f"appeal:{guild_id}:{case['no']}", message=text, model_said="unsafe",
                correct_label="SAFE", admin=staff_name, reason="appeal lifted (chatfilter)",
                guild_id=guild_id)
        except Exception as e:
            logger.error(f"[Appeals] override failed @ {guild_id}: {e}")
    sample_id = str(case.get("sample_id") or "")
    if sample_id:
        try:
            from assets.message.safetext import samples
            if samples.enabled_for(dict(datasys.load_data(guild_id, "chatfilter"))):
                await asyncio.to_thread(samples.suggest, sample_id, "SAFE")
        except Exception as e:
            logger.error(f"[Appeals] training suggestion failed @ {guild_id}: {e}")


async def _tell_user(bot: commands.AutoShardedBot, guild: discord.Guild, user_id: int, case_no: int,
                     case: dict | None, action: str, reason: str, what_key: str = "record") -> bool:
    lang = datasys.load_lang_file(guild.id)
    r = lang["moderation"]["appeal"]["result"]
    if action == "lift":
        embed = dither_art.Sticky(title=str(r["lift_title"]).format(guild=guild.name),
                              description=str(r["lift_body"]).format(no=case_no, what=r["what"].get(what_key, "")).strip(),
                              color=config.Discord.success_color)
    else:
        embed = dither_art.Sticky(title=str(r["keep_title"]).format(guild=guild.name),
                              description=str(r["keep_body"]).format(no=case_no),
                              color=config.Discord.warn_color)
    if reason:
        embed.add_field(name=r["f_note"], value=reason, inline=False)
    try:
        user = bot.get_user(user_id) or await bot.fetch_user(user_id)
        await asyncio.wait_for(user.send(embed=embed), 5)
        return True
    except (discord.Forbidden, discord.HTTPException, asyncio.TimeoutError):
        return False
