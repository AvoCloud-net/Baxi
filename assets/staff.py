"""Staff channel: the one place where Baxi tells a server's team what needs them.

Every staff-facing notice (review queue, later appeals, gate alerts, the Wrapped
preview) goes through `staff_channel()` instead of a log channel per feature.
The setting is `staff.channel`; while it is empty the older per-feature fields
serve as fallback (mod_gate.log_channel, then suggestions.log_channel).

The review queue is announced with ONE summary message ("3 open cases", the count
per kind, the newest case) and a link button to the dashboard queue. Only kinds
that need a timely decision count (NOTICE_KINDS); training-only items such as
deleted_msg never touch the staff channel. Baxi edits the message when the count
changes and sends a new one when
  * the queue was empty in between (the old message then says "all done"),
  * the old message is gone or the staff channel was changed,
  * a NEW case arrives and the message is older than REPOST_AFTER - so it shows
    up at the bottom of the channel again instead of being edited out of sight.
If no staff channel is set any more, the old message is deleted.

API (small on purpose, other features call it):
  NOTICE_KINDS                       queue kinds counted in the notice
  staff_channel(guild)               -> discord.TextChannel | None
  await refresh_queue_notice(bot, guild)   update now (lock + no-op if unchanged)
  schedule_refresh(bot, guild)       same, debounced (~2 s per guild) in the background
  dashboard_url(guild_id, section)   link into a dashboard section of that guild

Call `schedule_refresh` (or `refresh_queue_notice`) after anything that adds,
resolves or expires an item of a NOTICE_KINDS kind.
"""
from __future__ import annotations

import asyncio
import re
import time

import discord
from discord.ext import commands
from reds_simple_logger import Logger

import assets.data as datasys
import config.config as config
from assets.repo.moderation import pending_review_summary

logger = Logger()

NOTICE_KINDS: tuple[str, ...] = ("chatfilter_borderline", "user_report", "join_gate", "appeal")
REPOST_AFTER = 3600          # s: a new case re-posts a notice older than this
_DEBOUNCE = 2.0              # s: bursts of cases become one update
_NOTICE_KEY = "staff_queue_notice"
_EMPTY_STATE = {"channel": "", "message": "", "count": 0, "newest": -1, "posted_at": 0}
_EXCERPT_LEN = 180

_locks: dict[int, asyncio.Lock] = {}
_debounce: dict[int, asyncio.Task] = {}
_perm_warned: set[int] = set()


def _to_id(raw) -> int:
    s = str(raw or "").strip()
    return int(s) if s.isdigit() else 0


def dashboard_url(guild_id: int, section: str = "mod_review") -> str:
    # ?section survives the Discord login, #section opens it directly when logged in
    return f"https://{config.Web.url}/guild/?guild_login={guild_id}&section={section}#{section}"


def staff_channel(guild: discord.Guild) -> discord.TextChannel | None:
    """The guild's staff channel = the notification channel from Settings → General; falls back to
    the Mod-Gate log channel, then the suggestions log channel. None if none of them is set or
    still exists."""
    lookups = (
        lambda: datasys.load_data(guild.id, "notification_channel"),
        lambda: dict(datasys.load_data(guild.id, "staff") or {}).get("channel"),   # older setting
        lambda: dict(datasys.load_data(guild.id, "mod_gate") or {}).get("log_channel"),
        lambda: dict(datasys.load_data(guild.id, "suggestions") or {}).get("log_channel"),
    )
    for lookup in lookups:   # lazy: the fallbacks are only read when needed
        try:
            cid = _to_id(lookup())
        except Exception:
            cid = 0
        ch = guild.get_channel(cid) if cid else None
        if isinstance(ch, discord.TextChannel):
            return ch
    return None


def role_ids(guild_id: int) -> list[int]:
    """The server's staff roles - set once (Settings -> General), used by tickets, suggestions, ...
    Servers that never saved the new setting keep working: the roles of the older per-feature
    fields (ticket.role, suggestions.staff_role) count as the staff team until then."""
    def _split(raw) -> list[int]:
        return [int(x) for x in re.split(r"[,\s]+", str(raw or "")) if x.isdigit()]

    ids = _split(dict(datasys.load_data(guild_id, "staff") or {}).get("roles"))
    if not ids:
        ids = _split(dict(datasys.load_data(guild_id, "ticket") or {}).get("role"))
        ids += _split(dict(datasys.load_data(guild_id, "suggestions") or {}).get("staff_role"))
    return list(dict.fromkeys(ids))


def is_staff(member: discord.Member) -> bool:
    wanted = set(role_ids(member.guild.id))
    return any(r.id in wanted for r in member.roles)


# ── permissions ──────────────────────────────────────────────────────────────
def _no_permission(guild: discord.Guild, channel: discord.TextChannel, why: str) -> None:
    """Log a missing permission once per guild (until a post works again)."""
    if guild.id not in _perm_warned:
        _perm_warned.add(guild.id)
        logger.warn(f"[Staff] cannot post the review-queue notice in #{getattr(channel, 'name', channel.id)} "
                    f"@ {guild.id}: {why}")


def _can_post(guild: discord.Guild, channel: discord.TextChannel) -> bool:
    me = getattr(guild, "me", None)
    if me is None:
        return True   # unknown here: try, a 403 is handled
    perms = channel.permissions_for(me)
    if not (perms.view_channel and perms.send_messages and perms.embed_links):
        _no_permission(guild, channel, "needs View Channel, Send Messages and Embed Links")
        return False
    return True


def _forbidden(guild: discord.Guild, channel: discord.TextChannel) -> None:
    # Normally caught by _can_post first; a 403 anyway (e.g. member cache off) is
    # logged once and retried on the next change.
    _no_permission(guild, channel, "403 Forbidden")


# ── notice content ───────────────────────────────────────────────────────────
def _describe(item: dict | None, lang: dict) -> str:
    """One line about the newest open case."""
    if not item:
        return ""
    t = lang["staff"]["queue"]
    ctx = item.get("context") or {}
    kind = item.get("kind", "")
    label = t["kinds"].get(kind, t["kinds"]["other"])
    if kind == "chatfilter_borderline":
        excerpt = str(ctx.get("excerpt", ""))
        if len(excerpt) > _EXCERPT_LEN:
            excerpt = excerpt[:_EXCERPT_LEN].rstrip() + "…"
        excerpt = discord.utils.escape_mentions(discord.utils.escape_markdown(excerpt))
        cid = _to_id(ctx.get("channel_id"))
        return str(t["newest_borderline"]).format(
            kind=label, channel=f"<#{cid}>" if cid else "?", excerpt=excerpt)
    user = discord.utils.escape_markdown(str(item.get("user_name", "")))
    return str(t["newest_other"]).format(kind=label, user=user)


def _view(guild_id: int, lang: dict) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(style=discord.ButtonStyle.link,
                                    label=lang["staff"]["queue"]["open_button"],
                                    url=dashboard_url(guild_id)))
    return view


def _open_embed(counts: dict[str, int], newest: dict | None, lang: dict) -> discord.Embed:
    t = lang["staff"]["queue"]
    total = sum(counts.values())
    per_kind = " · ".join(
        str(t["per_kind"]).format(kind=t["kinds_plural"].get(k, t["kinds_plural"]["other"]), n=counts[k])
        for k in NOTICE_KINDS if counts.get(k)
    )
    head = str(t["open_one"] if total == 1 else t["open_other"]).format(n=total)
    embed = discord.Embed(title=t["title"], description=f"{head}\n{per_kind}",
                          color=config.Discord.warn_color)
    if line := _describe(newest, lang):
        embed.add_field(name=t["newest"], value=line[:1024], inline=False)
    embed.set_footer(text=t["footer"])
    return embed


def _clear_embed(lang: dict) -> discord.Embed:
    t = lang["staff"]["queue"]
    return discord.Embed(title=t["title"], description=t["clear"],
                         color=config.Discord.success_color).set_footer(text=t["footer"])


# ── refresh ──────────────────────────────────────────────────────────────────
async def refresh_queue_notice(bot: commands.AutoShardedBot, guild: discord.Guild | None) -> None:
    """Bring the summary message in the staff channel up to date. Never raises."""
    if guild is None:
        return
    lock = _locks.setdefault(guild.id, asyncio.Lock())
    async with lock:   # two cases at once must not send two messages
        try:
            await _refresh(guild)
        except Exception as e:
            logger.error(f"[Staff] queue notice @ {guild.id}: {type(e).__name__}: {e}")


def _save(guild_id: int, state: dict) -> None:
    datasys.save_data(guild_id, _NOTICE_KEY, {**_EMPTY_STATE, **state})


async def _refresh(guild: discord.Guild) -> None:
    counts, newest = pending_review_summary(guild.id, NOTICE_KINDS)
    total = sum(counts.values())
    state = {**_EMPTY_STATE, **dict(datasys.load_data(guild.id, _NOTICE_KEY) or {})}
    old_cid, old_mid = _to_id(state.get("channel")), _to_id(state.get("message"))
    if not old_mid and not total:
        return   # nothing to show, nothing to clear
    newest_pos = int(newest["pos"]) if newest else -1
    channel = staff_channel(guild)
    if (old_mid and state.get("count") == total and state.get("newest") == newest_pos
            and channel is not None and channel.id == old_cid):
        return   # nothing changed: no API call

    lang = datasys.load_lang_file(guild.id)
    old_ch = guild.get_channel(old_cid) if old_cid else None
    old_msg = (old_ch.get_partial_message(old_mid)
               if isinstance(old_ch, discord.TextChannel) and old_mid else None)

    async def drop_old() -> None:
        if old_msg is not None:
            try:
                await old_msg.delete()
            except (discord.NotFound, discord.Forbidden):
                pass

    if total == 0:
        # Queue is clear: say so in the old message and forget it, so the next
        # case gets a fresh message (and a fresh notification) again.
        if old_msg is not None:
            try:
                await old_msg.edit(embed=_clear_embed(lang), view=None)
            except (discord.NotFound, discord.Forbidden):
                pass
        _save(guild.id, {})
        return

    if channel is None:          # staff channel removed: take the old notice down
        await drop_old()
        if old_mid:
            _save(guild.id, {})
        return
    if not _can_post(guild, channel):
        return

    embed, view = _open_embed(counts, newest, lang), _view(guild.id, lang)
    new_case = newest_pos > int(state.get("newest", -1))
    stale = time.time() - float(state.get("posted_at") or 0) > REPOST_AFTER
    if old_msg is not None and old_cid == channel.id and not (new_case and stale):
        try:
            await old_msg.edit(embed=embed, view=view)
            _save(guild.id, {**state, "count": total, "newest": newest_pos})
            _perm_warned.discard(guild.id)
            return
        except discord.NotFound:
            pass   # someone deleted it: send a new one below
        except discord.Forbidden:
            _forbidden(guild, channel)
            return
    else:
        await drop_old()   # moved channel, or re-post at the bottom
    try:
        msg = await channel.send(embed=embed, view=view)
    except discord.Forbidden:
        _forbidden(guild, channel)
        if old_mid:
            _save(guild.id, {})   # the old one is gone already
        return
    _perm_warned.discard(guild.id)
    _save(guild.id, {"channel": str(channel.id), "message": str(msg.id), "count": total,
                     "newest": newest_pos, "posted_at": int(time.time())})


def schedule_refresh(bot: commands.AutoShardedBot, guild: discord.Guild | None) -> None:
    """refresh_queue_notice in the background, debounced: calls within _DEBOUNCE
    seconds for the same guild become one update. Does not delay the caller."""
    if guild is None:
        return
    if (t := _debounce.get(guild.id)) is not None and not t.done():
        return

    async def later() -> None:
        await asyncio.sleep(_DEBOUNCE)
        _debounce.pop(guild.id, None)   # changes from now on schedule a new update
        await refresh_queue_notice(bot, guild)

    try:
        _debounce[guild.id] = asyncio.get_running_loop().create_task(later())
    except RuntimeError:
        return
