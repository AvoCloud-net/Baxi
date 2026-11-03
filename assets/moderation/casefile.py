"""Case file: everything the team knows about one user on one server, in one list.

  /case user:@user      ephemeral, staff only (Moderate Members)
  /note add|remove      notes about a user (never visible to the user)
  right-click user -> Apps -> "Add note"
  dashboard             "Case files" section (assets/dash/dash.py -> build_json / stats)

One timeline, newest first: cases (with their state), appeals, notes and chat-filter hits
that have no case. Above it one line: "3 warnings, 1 mute · last action 12 days ago".
Notes: anyone with Moderate Members adds one; the author or anyone with Manage Server
removes it. A numeric trust score no longer exists (cross-server behaviour is not stored);
with Prism on, the human-gated network safety list entry is shown instead.
"""
from __future__ import annotations

import asyncio
import datetime
import statistics

import discord
from discord import app_commands
from discord.ext import commands
from reds_simple_logger import Logger

import assets.data as datasys
import config.config as config
from assets.moderation import cases as cases_mod
from assets.repo import cases as store

logger = Logger()

PAGE_SIZE = 8
NOTE_MAX = 500
_HIT_MERGE_S = 180        # a filter hit within 3 min of a warn/filter case is that case


# ── data ─────────────────────────────────────────────────────────────────────

def _ts(iso: str) -> float:
    try:
        return datetime.datetime.fromisoformat(iso).replace(tzinfo=datetime.timezone.utc).timestamp()
    except (TypeError, ValueError):
        return 0.0


def build(guild_id: int, user_id: int | str) -> dict:
    """Timeline + summary for one user. Plain data (used by Discord and the dashboard)."""
    cases = store.cases_for_user(guild_id, user_id)
    notes = store.notes_for_user(guild_id, user_id)
    hits = store.filter_hits(guild_id, user_id)

    entries: list[dict] = []
    # the summary comes from a query, so it stays right beyond the (capped) list below
    by_type, last_iso = store.counts_for_user(guild_id, user_id)
    counts = {k: by_type.get(k, 0) for k in ("warn", "mute", "kick", "ban")}
    counts["removed"] = by_type.get("filter", 0) + by_type.get("delete", 0)
    for c in cases:
        entries.append({"kind": "case", "ts": c["timestamp"], "no": c["no"], "type": c["type"],
                        "reason": c["reason"], "mod_id": c["mod_id"], "mod_name": c["mod_name"],
                        "lifted": bool(c.get("lifted")), "appeal": c.get("appeal") or "",
                        "duration_s": c.get("duration_s")})
        if c.get("appeal"):
            entries.append({"kind": "appeal", "ts": c.get("appeal_at") or c["timestamp"], "no": c["no"],
                            "state": c["appeal"], "note": c.get("appeal_note") or ""})
    for n in notes:
        entries.append({"kind": "note", "ts": n["created_at"], "id": n["id"], "text": n["text"],
                        "author_id": n["author_id"], "author_name": n["author_name"]})
    case_ts = [_ts(c["timestamp"]) for c in cases if c["type"] in ("warn", "filter")]
    for h in hits:
        t = _ts(h.get("timestamp", ""))
        if any(abs(t - ct) <= _HIT_MERGE_S for ct in case_ts):
            continue   # already a case
        entries.append({"kind": "hit", "ts": h.get("timestamp", ""), "category": h.get("category", "")})
    entries.sort(key=lambda e: e["ts"], reverse=True)

    name = next((c["user_name"] for c in cases if c["user_name"]), "") or \
        next((n["user_name"] for n in notes if n["user_name"]), "")
    last = _ts(last_iso) if last_iso else 0.0
    return {"user_id": str(user_id), "user_name": name, "counts": counts,
            "last_action_ts": int(last) or None, "entries": entries}


def safety_flag(guild_id: int, user_id: int) -> dict | None:
    """The network safety-list entry - only when the server takes part in Prism."""
    try:
        if datasys.load_data(guild_id, "prism_enabled") is False:
            return None
        import assets.trust as trust
        return trust.get_flag(int(user_id))
    except Exception:
        return None


def summary_text(data: dict, lang: dict, now: float | None = None) -> str:
    c = lang["moderation"]["casefile"]
    parts = []
    for key in ("warn", "mute", "kick", "ban", "removed"):
        n = data["counts"].get(key, 0)
        if n:
            parts.append(str(c["counts"][f"{key}_{'one' if n == 1 else 'other'}"]).format(n=n))
    if not parts:
        return c["empty"]
    text = c["list_sep"].join(parts)
    if data.get("last_action_ts"):
        text += " · " + str(c["last"]).format(when=f"<t:{data['last_action_ts']}:R>")
    return text


# ── Discord rendering ────────────────────────────────────────────────────────

def _clean(text: str, limit: int) -> str:
    t = discord.utils.escape_mentions(discord.utils.escape_markdown(" ".join(str(text).split())))
    return t if len(t) <= limit else t[:limit].rstrip() + "…"


def _when(iso: str) -> str:
    t = int(_ts(iso))
    return f"<t:{t}:R>" if t else "?"


def render_entry(e: dict, lang: dict, bot_id: int | None) -> str:
    m, c = lang["moderation"], lang["moderation"]["casefile"]
    if e["kind"] == "case":
        mod = cases_mod.mod_label({"mod_id": e["mod_id"], "mod_name": e["mod_name"]}, lang, bot_id)
        head = str(c["case_line"]).format(no=e["no"], type=m["types"].get(e["type"], e["type"]),
                                          when=_when(e["ts"]), mod=_clean(mod, 40))
        if e["lifted"]:
            head += f" · *{c['state_lifted']}*"
        elif e["appeal"] == "open":
            head += f" · *{c['state_open']}*"
        elif e["appeal"] == "kept":
            head += f" · *{c['state_kept']}*"
        reason = cases_mod.display_reason(e["reason"], lang)
        return head + f"\n> {_clean(reason, 150)}"
    if e["kind"] == "appeal":
        state = c["appeal_" + e["state"]]
        line = str(c["appeal_line"]).format(no=e["no"], when=_when(e["ts"])) + f" · {state}"
        return line + (f"\n> {_clean(e['note'], 150)}" if e["note"] else "")
    if e["kind"] == "note":
        return (str(c["note_line"]).format(id=e["id"], author=_clean(e["author_name"], 40), when=_when(e["ts"]))
                + f"\n> {_clean(e['text'], 200)}")
    return str(c["hit_line"]).format(when=_when(e["ts"])) + (f" · {e['category']}" if e["category"] else "")


class CaseFileView(discord.ui.View):
    """Pages of the case file; only the staffer who opened it can turn them."""

    def __init__(self, data: dict, lang: dict, owner_id: int, header: str, bot_id: int | None):
        super().__init__(timeout=600)
        self.data, self.lang, self.owner_id, self.header, self.bot_id = data, lang, owner_id, header, bot_id
        self.page = 0
        self.pages = max(1, -(-len(data["entries"]) // PAGE_SIZE))
        c = lang["moderation"]["casefile"]
        self.prev_btn.label, self.next_btn.label = c["prev"], c["next"]
        self._sync()

    def embed(self) -> discord.Embed:
        c = self.lang["moderation"]["casefile"]
        e = self.data["entries"][self.page * PAGE_SIZE:(self.page + 1) * PAGE_SIZE]
        body = "\n\n".join(render_entry(x, self.lang, self.bot_id) for x in e) or c["nothing"]
        embed = discord.Embed(
            title=str(c["title"]).format(user=self.data["user_name"] or self.data["user_id"]),
            description=f"{self.header}\n\n{body}"[:4000], color=config.Discord.color)
        if self.pages > 1:
            embed.set_footer(text=str(c["page"]).format(page=self.page + 1, pages=self.pages))
        return embed

    def _sync(self) -> None:
        self.prev_btn.disabled = self.page <= 0
        self.next_btn.disabled = self.page >= self.pages - 1
        if self.pages <= 1:
            self.clear_items()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.owner_id

    @discord.ui.button(style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = max(0, self.page - 1)
        self._sync()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = min(self.pages - 1, self.page + 1)
        self._sync()
        await interaction.response.edit_message(embed=self.embed(), view=self)


def _is_staff(interaction: discord.Interaction) -> bool:
    p = interaction.permissions
    return interaction.guild is not None and (p.moderate_members or p.manage_guild or p.administrator)


async def show_case_file(interaction: discord.Interaction, user: discord.abc.User) -> None:
    lang = datasys.load_lang_file(interaction.guild.id)
    if not _is_staff(interaction):
        return await interaction.response.send_message(lang["moderation"]["no_staff"], ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    data = await asyncio.to_thread(build, interaction.guild.id, user.id)
    if not data["user_name"]:
        data["user_name"] = user.name
    header = summary_text(data, lang)
    flag = await asyncio.to_thread(safety_flag, interaction.guild.id, user.id)
    if flag:
        header += "\n" + str(lang["moderation"]["casefile"]["safety_list"]).format(
            category=flag.get("category", "?"))
    view = CaseFileView(data, lang, interaction.user.id, header, interaction.client.user.id)
    await interaction.followup.send(embed=view.embed(), view=view if view.children else discord.utils.MISSING,
                                    ephemeral=True)


# ── notes ────────────────────────────────────────────────────────────────────

class NoteModal(discord.ui.Modal):
    def __init__(self, target: discord.abc.User, lang: dict):
        m = lang["moderation"]["note"]
        super().__init__(title=str(m["modal_title"]).format(user=target.name)[:45], timeout=600)
        self.target, self.lang = target, lang
        self.text = discord.ui.TextInput(label=m["field_label"][:45], style=discord.TextStyle.paragraph,
                                         max_length=NOTE_MAX, required=True)
        self.add_item(self.text)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not _is_staff(interaction):
            return await interaction.response.send_message(self.lang["moderation"]["no_staff"], ephemeral=True)
        text = self.text.value.strip()
        if not text:
            return await interaction.response.send_message(self.lang["moderation"]["note"]["empty"], ephemeral=True)
        nid = await asyncio.to_thread(store.add_note, interaction.guild.id, self.target.id, self.target.name,
                                      interaction.user.id, interaction.user.name, text)
        await interaction.response.send_message(
            str(self.lang["moderation"]["note"]["added"]).format(id=nid), ephemeral=True)


def can_remove_note(note: dict, user_id: int, manage_guild: bool) -> bool:
    return manage_guild or str(note["author_id"]) == str(user_id)


# ── stats ────────────────────────────────────────────────────────────────────

def stats(guild_id: int, bot_id: int | None, days: int = 30) -> dict:
    """Overview for the dashboard. Deliberately no totals, ranks or sorting by volume."""
    since = (datetime.datetime.utcnow() - datetime.timedelta(days=days)).isoformat()
    mods = store.actions_by_mod(guild_id, since)
    for m in mods:
        m["automatic"] = m["mod_id"] in ("0", "") or (bot_id is not None and m["mod_id"] == str(bot_id))
    mods.sort(key=lambda m: (m["automatic"], m["mod_name"].lower()))
    secs = store.review_handle_seconds(guild_id, since)
    open_ = store.open_counts(guild_id)
    return {
        "days": days, "mods": mods,
        "median_minutes": round(statistics.median(secs) / 60, 1) if secs else None,
        "handled": len(secs),
        "open_appeals": open_.get("appeal", 0),
        "open_total": sum(open_.values()),
    }


# ── registration ─────────────────────────────────────────────────────────────

def register(bot: commands.AutoShardedBot) -> None:
    @bot.tree.command(name="case", description="Full case file of a member (staff)")
    @app_commands.guild_only()
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.describe(user="The user whose case file you want to see.")
    async def case_cmd(interaction: discord.Interaction, user: discord.User):
        await show_case_file(interaction, user)

    note_group = app_commands.Group(name="note", description="Private staff notes about members",
                                    guild_only=True, default_permissions=discord.Permissions(moderate_members=True))

    @note_group.command(name="add", description="Add a note")
    @app_commands.describe(user="The user the note is about.", text="The note (only moderators can see it).")
    async def note_add(interaction: discord.Interaction, user: discord.User, text: app_commands.Range[str, 1, NOTE_MAX]):
        lang = datasys.load_lang_file(interaction.guild.id)
        if not _is_staff(interaction):
            return await interaction.response.send_message(lang["moderation"]["no_staff"], ephemeral=True)
        if not text.strip():
            return await interaction.response.send_message(lang["moderation"]["note"]["empty"], ephemeral=True)
        nid = await asyncio.to_thread(store.add_note, interaction.guild.id, user.id, user.name,
                                      interaction.user.id, interaction.user.name, text.strip())
        await interaction.response.send_message(str(lang["moderation"]["note"]["added"]).format(id=nid), ephemeral=True)

    @note_group.command(name="remove", description="Remove a note")
    @app_commands.describe(number="The note number, e.g. 3 for N3.")
    async def note_remove(interaction: discord.Interaction, number: int):
        lang = datasys.load_lang_file(interaction.guild.id)
        m = lang["moderation"]["note"]
        if not _is_staff(interaction):
            return await interaction.response.send_message(lang["moderation"]["no_staff"], ephemeral=True)
        note = await asyncio.to_thread(store.get_note, interaction.guild.id, number)
        if note is None:
            return await interaction.response.send_message(str(m["not_found"]).format(id=number), ephemeral=True)
        if not can_remove_note(note, interaction.user.id, interaction.permissions.manage_guild):
            return await interaction.response.send_message(m["not_yours"], ephemeral=True)
        await asyncio.to_thread(store.delete_note, interaction.guild.id, number)
        await interaction.response.send_message(str(m["removed"]).format(id=number), ephemeral=True)

    bot.tree.add_command(note_group)

    @bot.tree.context_menu(name="Add note")
    @app_commands.guild_only()
    @app_commands.default_permissions(moderate_members=True)
    async def add_note_ctx(interaction: discord.Interaction, user: discord.User):
        lang = datasys.load_lang_file(interaction.guild.id)
        if not _is_staff(interaction):
            return await interaction.response.send_message(lang["moderation"]["no_staff"], ephemeral=True)
        await interaction.response.send_modal(NoteModal(user, lang))
