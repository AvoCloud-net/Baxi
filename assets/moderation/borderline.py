"""Borderline chatfilter cases ("Grenzfälle") in the review queue.

A message whose score lands just below the deletion threshold (see
safetext/pipeline.py, BORDERLINE_BAND) stays up - the author notices nothing - and
becomes a `chatfilter_borderline` item in `mod_review_queue`. Staff get the
summary message in the staff channel (assets/staff.py) and decide in the dashboard:

  ok           the message stays
  delete       Baxi deletes the message
  delete_warn  delete, and the author gets a warning

Every decision applies right away to this server as an exact-match override
(safetext/feedback.py, server-only file, like the deleted_msg review). For the
training loop it is only a *suggestion* (safetext/samples.suggest, if the guild
opted in): the sample stays in the bot-admin labelling queue with the hint
"suggested by server mods" and only becomes a label once a bot admin labels it.

An edited message is re-checked: the open item gets the new text, or closes by
itself (expired, no label) when the message is no longer borderline. Undecided
items expire after 24 h (no action, no label); the message text of closed items
is blanked, and closed items are deleted after 30 days.
"""
from __future__ import annotations

import asyncio
import datetime
import time

import discord
from discord.ext import commands, tasks
from reds_simple_logger import Logger

import assets.data as datasys
from assets import staff
from assets.repo.moderation import (
    add_review_item_for_message, close_pending_for_message, expire_review_items,
    prune_closed_reviews, update_pending_for_message,
)
from assets.share import set_task_status

logger = Logger()

KIND = "chatfilter_borderline"
ACTIONS = ("ok", "delete", "delete_warn")
EXPIRE_AFTER = datetime.timedelta(hours=24)
KEEP_CLOSED = datetime.timedelta(days=30)
_PRUNE_EVERY = 86400           # s: the 30-day cleanup runs at most once a day
_EXCERPT_MAX = 1000            # same cap as the training samples; also the text the override matches


# ── enqueue (called from events.run_chatfilter) ──────────────────────────────
async def enqueue(bot: commands.AutoShardedBot, message: discord.Message, content: str,
                  info: dict, sample_id: str | None = None) -> None:
    """Queue a borderline message once (a re-check of the same message updates the
    open item instead) and refresh the staff notice. Never raises."""
    guild = message.guild
    if guild is None or message.author.bot:
        return
    changes = {"excerpt": content[:_EXCERPT_MAX], "score": info.get("score"),
               "threshold": info.get("threshold")}
    if sample_id:
        changes["sample_id"] = sample_id
    context = {
        "channel_id": str(message.channel.id),
        "channel_name": getattr(message.channel, "name", str(message.channel.id)),
        "author_id": str(message.author.id),
        "jump_url": message.jump_url,
        **changes,
    }
    try:
        pos = await asyncio.to_thread(
            add_review_item_for_message, guild.id, message.author.id, message.author.name,
            KIND, context, message.id)
        if pos is None:   # already known: keep the open item current (edited message)
            await asyncio.to_thread(update_pending_for_message, guild.id, KIND, message.id, changes)
            return
    except Exception as e:
        logger.error(f"[Borderline] enqueue failed @ {guild.id}: {e}")
        return
    staff.schedule_refresh(bot, guild)


async def close_for_message(bot: commands.AutoShardedBot, message: discord.Message) -> None:
    """An edited message is no longer borderline: close its open item. Never raises."""
    if message.guild is None:
        return
    try:
        closed = await asyncio.to_thread(close_pending_for_message, message.guild.id, KIND, message.id)
    except Exception as e:
        logger.error(f"[Borderline] close on edit failed @ {message.guild.id}: {e}")
        return
    if closed:
        staff.schedule_refresh(bot, message.guild)


# ── resolve (called from the dashboard) ──────────────────────────────────────
async def apply(bot: commands.AutoShardedBot, guild_id: int, item: dict, action: str,
                staff_member: discord.Member) -> str:
    """Do the Discord side of *action*. Returns a short note for the dashboard toast.
    discord.Forbidden on the delete propagates (the caller reports missing permissions
    and puts the item back to pending)."""
    if action == "ok":
        return "The message stays."
    ctx = dict(item.get("context") or {})
    guild = bot.get_guild(guild_id)
    if guild is None:
        return "Baxi is no longer on this server - entry closed anyway."
    cid, mid = int(ctx.get("channel_id") or 0), int(ctx.get("message_id") or 0)
    channel = guild.get_channel_or_thread(cid) if cid else None
    if channel is None and cid:
        # not cached (e.g. an archived thread): a partial channel still deletes by id
        channel = bot.get_partial_messageable(cid, guild_id=guild_id)

    notes = []
    if channel is None or not hasattr(channel, "get_partial_message"):
        notes.append("The channel no longer exists.")
    else:
        try:
            await channel.get_partial_message(mid).delete()
            notes.append("Message deleted.")
        except discord.NotFound:
            notes.append("The message was already gone.")

    if action == "delete_warn":
        uid = int(item.get("user_id") or 0)
        try:
            member = guild.get_member(uid) or await guild.fetch_member(uid)
        except discord.NotFound:
            member = None
        if member is None:
            notes.append("The author has left the server, so no warning was given.")
        else:
            from assets.message.warnings import add_warning
            lang = datasys.load_lang_file(guild_id)
            try:
                await add_warning(guild_id=guild_id, user=member, moderator=staff_member,
                                  reason=lang["staff"]["queue"]["warn_reason"], bot=bot,
                                  channel=channel if isinstance(channel, discord.abc.Messageable) else None,
                                  extra={"message_id": str(mid), "sample_id": ctx.get("sample_id")})
                notes.append(f"{member.name} was warned.")
            except Exception as e:
                logger.error(f"[Borderline] warn failed @ {guild_id}: {e}")
                notes.append("The warning could not be posted.")
    if action == "delete":
        # Plain delete: a case of its own (delete + warn is covered by the warning's case).
        case_no = await _open_delete_case(bot, guild, item, ctx, staff_member)
        if case_no:
            notes.append(f"Case #{case_no}, the author was told.")
    return " ".join(notes)


async def _open_delete_case(bot, guild: discord.Guild, item: dict, ctx: dict,
                            staff_member: discord.Member) -> int | None:
    """Case #n for a message a moderator removed from the queue, and the DM with the
    Appeal button. Never raises."""
    try:
        from types import SimpleNamespace
        from assets.moderation import cases
        uid = int(item.get("user_id") or 0)
        lang = datasys.load_lang_file(guild.id)
        reason = lang["staff"]["queue"]["warn_reason"]
        author = SimpleNamespace(id=uid, name=str(item.get("user_name") or uid))
        no = cases.record(guild.id, "delete", author, staff_member, reason,
                          message_id=str(ctx.get("message_id") or ""), sample_id=ctx.get("sample_id"),
                          channel_id=str(ctx.get("channel_id") or ""))
        user = guild.get_member(uid) or bot.get_user(uid)
        if user is None:
            try:
                user = await bot.fetch_user(uid)
            except discord.HTTPException:
                user = None
        if user is not None:
            await cases.notify(guild, user, no, "delete", reason)
        return no
    except Exception as e:
        logger.error(f"[Borderline] delete case failed @ {guild.id}: {e}")
        return None


async def learn(guild_id: int, item: dict, action: str, staff_name: str) -> None:
    """Server override now, training suggestion for the bot admins (see module
    docstring). Never raises."""
    ctx = dict(item.get("context") or {})
    text = str(ctx.get("excerpt", "")).strip()
    if not text:
        return
    label = "SAFE" if action == "ok" else "2"   # borderline only comes from the insult/toxicity path
    try:
        from assets.message.safetext import feedback
        await feedback.submit(
            log_id=f"review:{guild_id}:{item.get('pos')}", message=text,
            model_said="safe", correct_label=label, admin=staff_name,
            reason=f"mod review {action} ({KIND})", guild_id=guild_id,
        )
    except Exception as e:
        logger.error(f"[Borderline] override failed @ {guild_id}: {e}")
    sample_id = str(ctx.get("sample_id") or "")
    if not sample_id:
        return
    try:
        from assets.message.safetext import samples
        if samples.enabled_for(dict(datasys.load_data(guild_id, "chatfilter"))):
            await asyncio.to_thread(samples.suggest, sample_id, label)
    except Exception as e:
        logger.error(f"[Borderline] training suggestion failed @ {guild_id}: {e}")


# ── expiry + cleanup ─────────────────────────────────────────────────────────
class BorderlineExpiryTask:
    """Closes borderline items nobody decided within 24 h (no action, no label) and,
    once a day, deletes queue items closed more than 30 days ago. One indexed query
    per tick; nothing else happens while none is due."""

    def __init__(self, bot: commands.AutoShardedBot):
        self.bot = bot
        self._last_prune = 0.0

    @tasks.loop(minutes=10)
    async def tick(self):
        try:
            now = datetime.datetime.utcnow()
            pruned = 0
            if time.monotonic() - self._last_prune >= _PRUNE_EVERY or not self._last_prune:
                self._last_prune = time.monotonic()
                pruned = await asyncio.to_thread(prune_closed_reviews, (now - KEEP_CLOSED).isoformat())
                # same daily pass: cases and notes past their one-year retention
                from assets.repo import cases as _cases
                await asyncio.to_thread(_cases.prune_old)
            expired = await asyncio.to_thread(expire_review_items, KIND, (now - EXPIRE_AFTER).isoformat())
            if not expired and not pruned:
                return
            for guild_id in expired:
                await staff.refresh_queue_notice(self.bot, self.bot.get_guild(guild_id))
            set_task_status("ModQueueExpiry", "ok",
                            f"{sum(expired.values())} case(s) expired, {pruned} old item(s) removed")
        except Exception as e:
            logger.error(f"[Borderline] expiry tick: {e}")
            set_task_status("ModQueueExpiry", "error", f"Error: {e}")

    @tick.before_loop
    async def _before(self):
        await self.bot.wait_until_ready()
