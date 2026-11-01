"""Moderation cases: one running number (#123) per action, one DM to the user.

Every action against a person (warn, mute, kick, ban, unban, unmute, a removed message)
is a *case*. A case is a `mod_events` row, its `pos` is the number (assets/repo/cases.py).
This module is the one place that

  * writes a case            record() / discard()
  * tells the user           notify()   - THE message a user gets after an action: what
                                          happened, why, how long, the case number and
                                          an "Appeal" button (assets/moderation/appeals.py)

Order for callers: record() first (the DM and the audit-log reason need the number), then
notify(), then the Discord action; discard() the case when that action fails.

Callers pass discord objects; nothing here needs a running event loop except notify().
"""
from __future__ import annotations

import asyncio
import datetime
import time

import discord
from reds_simple_logger import Logger

import assets.data as datasys
import config.config as config
from assets.repo import cases as store

logger = Logger()

TYPES = ("warn", "mute", "kick", "ban", "unban", "unmute", "filter", "delete")
_REASON_MAX = 500
_FILTER_DM_EVERY = 600      # s: at most one automatic DM per user and server
DM_TIMEOUT = 5              # s: a DM may never hold up an action longer than this
_filter_dm_last: dict[tuple[int, int], float] = {}


def appeal_url(guild_id: int) -> str:
    return f"https://{config.Web.url}/appeal/{guild_id}"


def display_reason(reason: str | None, lang: dict) -> str:
    r = (reason or "").strip()
    return lang["moderation"]["no_reason"] if r in ("", "N/A", "n/a") else r


def mod_label(case: dict, lang: dict, bot_id: int | None) -> str:
    """Who did it, for staff views."""
    if str(case.get("mod_id")) in ("0", "") or (bot_id and str(case.get("mod_id")) == str(bot_id)):
        return lang["moderation"]["by_baxi"]
    return str(case.get("mod_name") or "?")


def human_duration(seconds: int, lang: dict | None = None) -> str:
    """'1 week 1 hour' / '1 Woche 1 Stunde' in the server's language."""
    u = (lang or datasys.load_lang_file(1001))["moderation"]["units"]
    left, parts = max(0, int(seconds)), []
    for key, size in (("week", 604800), ("day", 86400), ("hour", 3600), ("minute", 60), ("second", 1)):
        n, left = divmod(left, size)
        if n:
            parts.append(f"{n} {u[key + ('_one' if n == 1 else '_other')]}")
    return u["sep"].join(parts) or f"0 {u['second_other']}"


def filter_reason(lang: dict, code: str) -> str:
    """Human wording for a chat-filter reason code (\"2\" -> \"Insults\"); no raw codes in DMs."""
    return lang["moderation"]["auto"]["filter_reasons"].get(str(code), "")


def filter_why(lang: dict, code: str) -> str:
    a = lang["moderation"]["auto"]
    r = filter_reason(lang, code)
    return str(a["chatfilter_why"]).format(reason=r) if r else a["chatfilter"]


def can_act(guild: discord.Guild, target, action: str, lang: dict) -> str | None:
    """None if Baxi can ban/kick/mute *target* here, else a plain sentence for the moderator.
    Checked BEFORE a case is opened or the user is messaged: no DM about something that
    then cannot happen."""
    c = lang["moderation"]["cannot"]
    me = getattr(guild, "me", None)
    if me is None:
        return None
    perm = {"ban": "ban_members", "kick": "kick_members", "mute": "moderate_members"}[action]
    if not getattr(me.guild_permissions, perm, False) and not me.guild_permissions.administrator:
        return c[action]
    if getattr(guild, "owner_id", None) == getattr(target, "id", None) and getattr(target, "id", None) is not None:
        return c["owner"]
    top = getattr(target, "top_role", None)
    if top is not None and me.top_role <= top:
        return c["hierarchy"]
    return None


# ── write ────────────────────────────────────────────────────────────────────

def _who(obj) -> tuple[str, str]:
    if obj is None:
        return "0", "Baxi"
    return str(getattr(obj, "id", 0)), str(getattr(obj, "name", "") or getattr(obj, "id", ""))


def record(guild_id: int, type: str, user, mod, reason: str, **extra) -> int | None:
    """Write a case, return its number (None if the database refused - callers carry on
    without a number, a moderation action must never fail because of bookkeeping)."""
    if type not in TYPES:
        raise ValueError(f"unknown case type {type!r}")
    uid, uname = _who(user)
    mid, mname = _who(mod)
    event = {
        "type": type, "user_id": uid, "user_name": uname, "mod_id": mid, "mod_name": mname,
        "reason": (reason or "")[:_REASON_MAX],
        "timestamp": datetime.datetime.utcnow().isoformat(),
        **{k: v for k, v in extra.items() if v is not None},
    }
    return datasys.append_mod_event(int(guild_id), event)


def discard(guild_id: int, no: int | None) -> None:
    """Take a case back because the action behind it failed."""
    if no:
        try:
            store.delete_case(int(guild_id), int(no))
        except Exception as e:
            logger.error(f"[Cases] discard #{no} @ {guild_id}: {e}")


# ── tell the user ────────────────────────────────────────────────────────────

def build_dm(guild: discord.Guild, case_no: int | None, type: str, reason: str,
             lang: dict, *, seconds: int | None = None, permanent: bool = False,
             appeal_days: int = store.APPEAL_WINDOW_DAYS) -> discord.Embed:
    """The one message a user gets: what happened, why, how long, which case, how to appeal."""
    m = lang["moderation"]
    colour = {
        "warn": config.Discord.warn_color, "mute": config.Discord.warn_color,
        "kick": config.Discord.danger_color, "ban": config.Discord.danger_color,
        "filter": config.Discord.warn_color, "delete": config.Discord.warn_color,
        "unban": config.Discord.success_color, "unmute": config.Discord.success_color,
    }.get(type, config.Discord.color)
    embed = discord.Embed(title=str(m["dm"]["title"][type]).format(guild=guild.name),
                          description=m["dm"]["line"][type], color=colour)
    if type in ("warn", "mute", "kick", "ban", "filter", "delete"):
        embed.add_field(name=m["dm"]["f_reason"], value=display_reason(reason, lang)[:1000], inline=False)
    if seconds:
        until = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=seconds)
        embed.add_field(
            name=m["dm"]["f_duration"],
            value=str(m["dm"]["until"]).format(duration=human_duration(seconds, lang),
                                               until=f"<t:{int(until.timestamp())}:f>"),
            inline=True)
    elif permanent:
        embed.add_field(name=m["dm"]["f_duration"], value=m["forever"], inline=True)
    if case_no:
        embed.add_field(name=m["dm"]["f_case"], value=f"#{case_no}", inline=True)
        if type in store.APPEALABLE_TYPES:
            embed.set_footer(text=str(m["dm"]["appeal_hint"]).format(days=appeal_days))
    return embed


async def notify(guild: discord.Guild, user, case_no: int | None, type: str, reason: str, *,
                 seconds: int | None = None, permanent: bool = False, throttle: bool = False) -> bool:
    """DM *user* about a case. True if it arrived. Never raises and never takes longer than
    DM_TIMEOUT seconds (closed DMs are normal, a slow DM must not delay a punishment).
    Automatic messages (removed message, warning given by Baxi itself) are throttled to one
    DM per 10 minutes per user so a spammer does not get a flood - the case still exists."""
    if user is None or getattr(user, "bot", False):
        return False
    if type == "filter" or throttle:
        key = (guild.id, int(user.id))
        now = time.monotonic()
        if now - _filter_dm_last.get(key, -1e9) < _FILTER_DM_EVERY:
            return False
        _filter_dm_last[key] = now
        if len(_filter_dm_last) > 5000:
            for k in [k for k, t in _filter_dm_last.items() if now - t > _FILTER_DM_EVERY]:
                _filter_dm_last.pop(k, None)
    try:
        lang = datasys.load_lang_file(guild.id)
        embed = build_dm(guild, case_no, type, reason, lang, seconds=seconds, permanent=permanent)
        view = None
        if case_no and type in store.APPEALABLE_TYPES:
            from assets.moderation.appeals import AppealButton
            view = discord.ui.View(timeout=None)
            view.add_item(AppealButton(guild.id, int(case_no), lang["moderation"]["dm"]["appeal_button"]))
        embed.set_author(name=guild.name, icon_url=guild.icon.url if guild.icon else None)
        if view is not None:
            await asyncio.wait_for(user.send(embed=embed, view=view), DM_TIMEOUT)
        else:
            await asyncio.wait_for(user.send(embed=embed), DM_TIMEOUT)
        return True
    except (discord.Forbidden, discord.HTTPException, asyncio.TimeoutError):
        return False
    except Exception as e:
        logger.error(f"[Cases] DM for #{case_no} @ {guild.id} failed: {type(e).__name__}: {e}")
        return False


def begin(guild: discord.Guild, target, action: str, mod, reason: str, lang: dict, **extra) -> tuple[int | None, str | None]:
    """can_act + record in one step, for the automations. Returns (case number, None) or
    (None, why not). Callers send the DM (before a ban/kick, after a mute) and call discard()
    if the action then fails."""
    blocked = can_act(guild, target, action, lang)
    if blocked:
        return None, blocked
    return record(guild.id, action, target, mod, reason, **extra), None


async def run_automatic(guild: discord.Guild, member, action: str, reason: str, perform, *,
                        seconds: int | None = None, dm: str = "auto") -> bool:
    """One call for an automation's kick/ban/mute: case (attributed to Baxi) + DM + the action.
    *perform* is an async callable taking a suffix for the audit-log reason (" (case #12)").
    Returns True if the action ran, False if Baxi could not do it (no case, no DM then).
    dm: "auto" (before a kick/ban, after a mute), "before", "after", "background" (never
    waits), or "none". Exceptions of *perform* propagate after the case is taken back, so the
    caller's own handling stays as it was. A mute right after another one (a raider's next
    message) does not open a second case."""
    lang = datasys.load_lang_file(guild.id)
    me = getattr(guild, "me", None)
    if action == "mute" and store.recent_case(guild.id, member.id, ("mute",), 300):
        await perform("")
        return True
    no, blocked = begin(guild, member, action, me, reason, lang, duration_s=seconds)
    if blocked:
        return False
    mode = dm if dm != "auto" else ("before" if action in ("kick", "ban") else "after")
    send = lambda: notify(guild, member, no, action, reason, seconds=seconds, permanent=action == "ban")
    if mode == "before":
        await send()
    try:
        await perform(f" (case #{no})" if no else "")
    except BaseException:
        discard(guild.id, no)
        raise
    if mode == "after":
        await send()
    elif mode == "background":
        asyncio.get_running_loop().create_task(send())
    return True


def dm_failed_note(lang: dict, user, guild_id: int) -> str:
    """A line for the moderator's reply when the DM did not arrive."""
    return str(lang["moderation"]["dm"]["closed_dm"]).format(
        user=getattr(user, "mention", str(user)), url=appeal_url(guild_id))
