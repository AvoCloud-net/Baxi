import copy
import discord
from pathlib import Path
from discord.ext import commands
import assets.data as datasys
import config.config as cfg
import assets.v2 as v2
from reds_simple_logger import Logger

logger = Logger()



# ── Modals ────────────────────────────────────────────────────────────────────

class SuggestionCommentModal(discord.ui.Modal):
    def __init__(self, t: dict):
        super().__init__(title=t.get("modal_comment_title", "Add Staff Comment"))
        self.t = t
        self.comment_input = discord.ui.TextInput(
            label=t.get("modal_comment_label", "Comment"),
            placeholder=t.get("modal_comment_placeholder", "Enter your comment or update..."),
            required=True,
            max_length=500,
            style=discord.TextStyle.paragraph,
        )
        self.add_item(self.comment_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        comment = self.comment_input.value.strip()
        await _process_comment(interaction, comment, self.t)


class SuggestionDecisionModal(discord.ui.Modal):
    def __init__(self, accepted: bool, t: dict):
        title_key = "modal_accept_title" if accepted else "modal_decline_title"
        super().__init__(title=t.get(title_key, "Accept" if accepted else "Decline"))
        self.accepted = accepted
        self.t = t
        self.reason_input = discord.ui.TextInput(
            label=t.get("modal_reason_label", "Reason (optional)"),
            placeholder=t.get("modal_reason_placeholder", "Enter a reason..."),
            required=False,
            max_length=500,
            style=discord.TextStyle.paragraph,
        )
        self.add_item(self.reason_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        reason = self.reason_input.value.strip() if self.reason_input.value else None
        await _process_decision(interaction, self.accepted, reason, self.t)


# ── Persistent view ───────────────────────────────────────────────────────────

class _SplitCard(v2.CardView):
    """Suggestion card: the text (with the decision on top once there is one), a vote line, the member
    buttons, a divider and a "Staff" label, then the staff buttons, all inside one container so the
    two groups read as two groups."""
    staff_label = "Staff"
    status_field: str | None = None   # name of the embed field that holds the decision
    votes_text = ""                   # "▰▰▰▱▱ 60 % · 5 votes", empty while nobody voted

    def _render(self, embed: discord.Embed) -> discord.Embed:
        """The decision field moves from the bottom of the card to the top of the text."""
        if not self.status_field:
            return embed
        status = [f for f in embed.fields if f.name == self.status_field]
        if not status:
            return embed
        e = discord.Embed.from_dict(copy.deepcopy(embed.to_dict()))   # copy() shares the fields list
        e.clear_fields()
        for f in embed.fields:
            if f.name != self.status_field:
                e.add_field(name=f.name, value=f.value, inline=f.inline)
        e.description = f"{status[0].value}\n\n{embed.description}" if embed.description else status[0].value
        return e

    def set_card(self, embed: discord.Embed, *, header: str = "") -> None:
        rows = [c for c in self.children if isinstance(c, discord.ui.ActionRow)]
        self.clear_items()
        extra: list[discord.ui.Item] = []
        if len(rows) >= 2:
            extra = [discord.ui.Separator(visible=True)]
            if self.votes_text:
                extra.append(discord.ui.TextDisplay(self.votes_text))
            extra += [rows[0], discord.ui.Separator(visible=True),
                      discord.ui.TextDisplay(f"-# {self.staff_label}"), *rows[1:]]
        else:
            extra = list(rows)
        self.add_item(v2.card_container(self._render(embed), extra=extra))


def _votes_line(up: int, down: int, t: dict) -> str:
    total = up + down
    if not total:
        return ""
    filled = round(up / total * 10)
    return f"{'▰' * filled}{'▱' * (10 - filled)}  **{round(up / total * 100)} %**  ·  {total} {t.get('votes_label', 'votes')}"


class SuggestionView(_SplitCard):
    """Registered at startup so all custom_ids survive bot restarts. A suggestion message is
    ``SuggestionView(card_embed)`` (Components V2); ``SuggestionView()`` only registers the buttons.

    Members: upvote | downvote | join discussion      Staff: accept | decline | comment
    """
    row0 = discord.ui.ActionRow()
    row1 = discord.ui.ActionRow()

    def __init__(self, embed: discord.Embed | None = None, staff_label: str = "Staff",
                 status_field: str | None = None, votes_text: str = ""):
        self.staff_label = staff_label
        self.status_field = status_field
        self.votes_text = votes_text
        super().__init__(embed, timeout=None)

    @row0.button(label="0", emoji=cfg.Icons.thumbsup, style=discord.ButtonStyle.secondary, custom_id="suggestion:upvote")
    async def upvote(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _handle_public_vote(interaction, upvoted=True)

    @row0.button(label="0", emoji=cfg.Icons.thumbsdown, style=discord.ButtonStyle.secondary, custom_id="suggestion:downvote")
    async def downvote(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _handle_public_vote(interaction, upvoted=False)

    @row0.button(label="Join Discussion", emoji=cfg.Icons.message, style=discord.ButtonStyle.secondary, custom_id="suggestion:join_thread")
    async def join_thread(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _handle_join_thread(interaction)

    @row1.button(label="Accept", emoji=cfg.Icons.check, style=discord.ButtonStyle.success, custom_id="suggestion:accept")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _open_decision_modal(interaction, accepted=True)

    @row1.button(label="Decline", emoji=cfg.Icons.cross, style=discord.ButtonStyle.danger, custom_id="suggestion:decline")
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _open_decision_modal(interaction, accepted=False)

    @row1.button(label="Comment", emoji=cfg.Icons.message, style=discord.ButtonStyle.secondary, custom_id="suggestion:comment")
    async def comment(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _open_comment_modal(interaction)


class _ClassicView(discord.ui.View):
    """The old (embed + buttons) layout, kept only to update suggestions that were posted before the
    Components V2 switch (their message is still a classic embed message). Same custom_ids as above."""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="0", emoji=cfg.Icons.thumbsup, style=discord.ButtonStyle.secondary, custom_id="suggestion:upvote", row=0)
    async def upvote(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _handle_public_vote(interaction, upvoted=True)

    @discord.ui.button(label="0", emoji=cfg.Icons.thumbsdown, style=discord.ButtonStyle.secondary, custom_id="suggestion:downvote", row=0)
    async def downvote(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _handle_public_vote(interaction, upvoted=False)

    @discord.ui.button(label="Join Discussion", emoji=cfg.Icons.message, style=discord.ButtonStyle.secondary, custom_id="suggestion:join_thread", row=0)
    async def join_thread(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _handle_join_thread(interaction)

    @discord.ui.button(label="Accept", emoji=cfg.Icons.check, style=discord.ButtonStyle.success, custom_id="suggestion:accept", row=1)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _open_decision_modal(interaction, accepted=True)

    @discord.ui.button(label="Decline", emoji=cfg.Icons.cross, style=discord.ButtonStyle.danger, custom_id="suggestion:decline", row=1)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _open_decision_modal(interaction, accepted=False)

    @discord.ui.button(label="Comment", emoji=cfg.Icons.message, style=discord.ButtonStyle.secondary, custom_id="suggestion:comment", row=1)
    async def comment(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _open_comment_modal(interaction)


# ── View helpers ──────────────────────────────────────────────────────────────

def _make_view(upvotes: int, downvotes: int, t: dict, decided: bool = False,
               embed: discord.Embed | None = None):
    """The vote view with current counts, translated labels, optional disabled state.
    With ``embed`` it is the V2 card view, without it the classic one (old messages)."""
    v = (SuggestionView(embed, t.get("staff_label", "Staff"), t.get("status_field"), _votes_line(upvotes, downvotes, t))
         if embed is not None else _ClassicView())
    if embed is not None and decided:   # decided: accept / decline are gone, comments stay possible
        for row in [c for c in v.walk_children() if isinstance(c, discord.ui.ActionRow)]:
            for item in [i for i in row.children if isinstance(i, discord.ui.Button)
                         and i.custom_id in ("suggestion:accept", "suggestion:decline")]:
                row.remove_item(item)
    for item in v.walk_children():
        if not isinstance(item, discord.ui.Button):
            continue
        if item.custom_id == "suggestion:upvote":
            item.label = str(upvotes)
            item.emoji = cfg.Icons.thumbsup
            item.disabled = decided
        elif item.custom_id == "suggestion:downvote":
            item.label = str(downvotes)
            item.emoji = cfg.Icons.thumbsdown
            item.disabled = decided
        elif item.custom_id == "suggestion:join_thread":
            item.label = t.get("btn_join_thread", "Join Discussion")
            item.disabled = False  # always enabled
        elif item.custom_id == "suggestion:accept":
            item.label = t.get("btn_accept", "Accept")
            item.emoji = cfg.Icons.check
            item.disabled = decided
        elif item.custom_id == "suggestion:decline":
            item.label = t.get("btn_decline", "Decline")
            item.emoji = cfg.Icons.cross
            item.disabled = decided
        elif item.custom_id == "suggestion:comment":
            item.label = t.get("btn_comment", "Comment")
            item.disabled = False  # always enabled
    return v


def _make_staff_only_view(t: dict, decided: bool = False, embed: discord.Embed | None = None):
    """View with Join Discussion (row 0) + Accept / Decline / Comment (row 1) when public voting is
    disabled; V2 card with ``embed``, classic (old messages) without."""
    def btn(key: str, default: str, emoji, style, cid: str, disabled: bool) -> discord.ui.Button:
        return discord.ui.Button(label=t.get(key, default), emoji=emoji, style=style, custom_id=cid, disabled=disabled)

    join = btn("btn_join_thread", "Join Discussion", cfg.Icons.message, discord.ButtonStyle.secondary, "suggestion:join_thread", False)
    accept = btn("btn_accept", "Accept", cfg.Icons.check, discord.ButtonStyle.success, "suggestion:accept", decided)
    decline = btn("btn_decline", "Decline", cfg.Icons.cross, discord.ButtonStyle.danger, "suggestion:decline", decided)
    comment = btn("btn_comment", "Comment", cfg.Icons.message, discord.ButtonStyle.secondary, "suggestion:comment", False)
    if embed is None:   # classic message
        v = discord.ui.View(timeout=None)
        for b, row in ((join, 0), (accept, 1), (decline, 1), (comment, 1)):
            b.row = row
            v.add_item(b)
        return v
    v = _SplitCard(timeout=None)
    v.staff_label = t.get("staff_label", "Staff")
    v.status_field = t.get("status_field")
    v.add_item(discord.ui.ActionRow(join))
    v.add_item(discord.ui.ActionRow(comment) if decided else discord.ui.ActionRow(accept, decline, comment))
    v.set_card(embed)
    return v


# ── Shared helpers ────────────────────────────────────────────────────────────

def _get_vote_counts(guild_id: int, msg_id: str) -> tuple[list, list]:
    votes: dict = dict(datasys.load_data(guild_id, "suggestion_votes"))
    entry = votes.get(msg_id, {"up": [], "down": []})
    return list(entry.get("up", [])), list(entry.get("down", []))


def _save_vote_counts(guild_id: int, msg_id: str, up: list, down: list) -> None:
    votes: dict = dict(datasys.load_data(guild_id, "suggestion_votes"))
    entry = votes.get(msg_id, {})
    entry["up"] = up
    entry["down"] = down
    votes[msg_id] = entry
    datasys.save_data(guild_id, "suggestion_votes", votes)


def _get_suggestion_thread(guild: discord.Guild, msg_id: str) -> discord.Thread | None:
    votes: dict = dict(datasys.load_data(guild.id, "suggestion_votes"))
    thread_id = votes.get(msg_id, {}).get("thread_id")
    if not thread_id:
        return None
    thread = guild.get_channel_or_thread(int(thread_id))
    return thread if isinstance(thread, discord.Thread) else None


def _is_decided(embed: discord.Embed, status_field_name: str) -> bool:
    return any(f.name == status_field_name for f in embed.fields)


def _is_v2(msg: discord.Message) -> bool:
    """True for suggestions posted as Components V2; older ones are still classic embed messages."""
    return bool(msg.flags.components_v2)


def _card_embed(msg: discord.Message, guild_id: int) -> discord.Embed | None:
    """The suggestion's content as an embed: read from the classic message, or from the copy kept in
    ``suggestion_votes[msg_id]["card"]`` (a V2 message has no embeds to read back)."""
    if not _is_v2(msg) and msg.embeds:
        return msg.embeds[0].copy()
    d = dict(datasys.load_data(guild_id, "suggestion_votes")).get(str(msg.id), {}).get("card")
    return discord.Embed.from_dict(d) if d else None


def _store_card(guild_id: int, msg_id: str, embed: discord.Embed) -> None:
    votes: dict = dict(datasys.load_data(guild_id, "suggestion_votes"))
    entry = votes.get(msg_id, {})
    entry["card"] = embed.to_dict()
    votes[msg_id] = entry
    datasys.save_data(guild_id, "suggestion_votes", votes)


def _build_view(guild_id: int, channel_id: int | None, data: dict, t: dict, msg_id: str,
                embed: discord.Embed | None, decided: bool):
    """Vote view or staff-only view for the channel's setting; V2 when ``embed`` is given."""
    if _get_channel_config(data, channel_id or 0).get("votes_enabled", True):
        up, down = _get_vote_counts(guild_id, msg_id)
        return _make_view(len(up), len(down), t, decided, embed)
    return _make_staff_only_view(t, decided, embed)


def _check_permission(interaction: discord.Interaction, data: dict) -> bool:
    # the server's one shared staff team (assets/staff.py)
    from assets import staff
    if isinstance(interaction.user, discord.Member):
        if interaction.user.guild_permissions.manage_guild:
            return True
        return staff.is_staff(interaction.user)
    return False


def _get_channel_config(data: dict, channel_id: int) -> dict:
    """Return the channel config dict for the given channel_id, or a fallback."""
    for ch in data.get("channels", []):
        ch_id = ch if isinstance(ch, str) else str(ch.get("id", ""))
        if ch_id == str(channel_id):
            return ch if isinstance(ch, dict) else {"id": ch_id, "votes_enabled": True}
    return {"id": str(channel_id), "votes_enabled": True}


# ── Join thread handler ───────────────────────────────────────────────────────

async def _handle_join_thread(interaction: discord.Interaction) -> None:
    if interaction.guild is None or interaction.message is None:
        return

    lang = datasys.load_lang_file(interaction.guild.id)
    t: dict = lang["systems"]["suggestions"]

    msg_id = str(interaction.message.id)
    votes: dict = dict(datasys.load_data(interaction.guild.id, "suggestion_votes"))
    entry = votes.get(msg_id, {})

    thread = _get_suggestion_thread(interaction.guild, msg_id)
    thread_id = entry.get("thread_id")
    if thread is None and thread_id:
        try:
            fetched = await interaction.guild.fetch_channel(int(thread_id))
            if isinstance(fetched, discord.Thread):
                thread = fetched
        except (discord.NotFound, discord.HTTPException):
            thread = None

    # Thread exists -  check membership, then add or tell user they're already in
    if thread is not None:
        already = False
        try:
            await thread.fetch_member(interaction.user.id)
            already = True
        except discord.NotFound:
            already = False
        except discord.HTTPException:
            already = False

        if already:
            await interaction.response.send_message(
                str(t.get("already_in_thread", "You are already in the conversation: {thread}")).format(thread=thread.mention),
                ephemeral=True,
            )
            return

        try:
            await thread.add_user(interaction.user)
        except (discord.Forbidden, discord.HTTPException):
            pass

        await interaction.response.send_message(
            str(t.get("thread_joined", "You joined the discussion: {thread}")).format(thread=thread.mention),
            ephemeral=True,
        )
        return

    # No thread yet -  create now, add author + clicker
    parent = interaction.channel
    if not isinstance(parent, discord.TextChannel):
        await interaction.response.send_message(
            t.get("thread_not_found", "Discussion thread not found."), ephemeral=True
        )
        return

    thread_name = ""
    card = _card_embed(interaction.message, interaction.guild.id)
    if card is not None:
        thread_name = (card.description or "").strip()
    if len(thread_name) > 80:
        thread_name = thread_name[:77] + "..."
    if not thread_name:
        thread_name = t.get("embed_title", "Suggestion")

    try:
        thread = await parent.create_thread(
            name=thread_name[:100],
            type=discord.ChannelType.private_thread,
            invitable=True,
        )
    except (discord.Forbidden, discord.HTTPException) as e:
        logger.error(f"[Suggestions] Could not create discussion thread: {e}")
        await interaction.response.send_message(
            t.get("thread_not_found", "Discussion thread not found."), ephemeral=True
        )
        return

    author_id = entry.get("author_id")
    if author_id:
        try:
            author_id_int = int(author_id)
        except (TypeError, ValueError):
            author_id_int = 0
        if author_id_int and author_id_int != interaction.user.id:
            author = interaction.guild.get_member(author_id_int)
            if author is None:
                try:
                    author = await interaction.guild.fetch_member(author_id_int)
                except (discord.NotFound, discord.HTTPException):
                    author = None
            if author is not None:
                try:
                    await thread.add_user(author)
                except (discord.Forbidden, discord.HTTPException):
                    pass

    try:
        await thread.add_user(interaction.user)
    except (discord.Forbidden, discord.HTTPException):
        pass

    entry["thread_id"] = thread.id
    votes[msg_id] = entry
    datasys.save_data(interaction.guild.id, "suggestion_votes", votes)

    await interaction.response.send_message(
        str(t.get("thread_joined", "You joined the discussion: {thread}")).format(thread=thread.mention),
        ephemeral=True,
    )


# ── Modal triggers ────────────────────────────────────────────────────────────

async def _open_decision_modal(interaction: discord.Interaction, accepted: bool) -> None:
    """Check permissions and either show ephemeral error or open the reason modal."""
    if interaction.guild is None or interaction.message is None:
        return

    data: dict = dict(datasys.load_data(interaction.guild.id, "suggestions"))
    lang = datasys.load_lang_file(interaction.guild.id)
    t: dict = lang["systems"]["suggestions"]

    if not _check_permission(interaction, data):
        await interaction.response.send_message(t["no_permission"], ephemeral=True)
        return

    card = _card_embed(interaction.message, interaction.guild.id)
    if card is not None and _is_decided(card, t["status_field"]):
        await interaction.response.send_message(t["already_decided"], ephemeral=True)
        return

    await interaction.response.send_modal(SuggestionDecisionModal(accepted=accepted, t=t))


async def _open_comment_modal(interaction: discord.Interaction) -> None:
    """Check permissions and open the staff comment modal. Works on pending and decided suggestions."""
    if interaction.guild is None or interaction.message is None:
        return

    data: dict = dict(datasys.load_data(interaction.guild.id, "suggestions"))
    lang = datasys.load_lang_file(interaction.guild.id)
    t: dict = lang["systems"]["suggestions"]

    if not _check_permission(interaction, data):
        await interaction.response.send_message(t["no_permission"], ephemeral=True)
        return

    await interaction.response.send_modal(SuggestionCommentModal(t=t))


# ── Comment processing ────────────────────────────────────────────────────────

async def _process_comment(
    interaction: discord.Interaction,
    comment: str,
    t: dict,
) -> None:
    if interaction.guild is None or interaction.message is None:
        return

    data: dict = dict(datasys.load_data(interaction.guild.id, "suggestions"))
    msg = interaction.message
    embed = _card_embed(msg, interaction.guild.id)
    if embed is None:
        return

    msg_id = str(msg.id)
    ts = f"<t:{int(discord.utils.utcnow().timestamp())}:f>"
    embed.add_field(
        name=t.get("comment_field", "Staff Update"),
        value=f"{cfg.Icons.message} " + str(t.get("comment_value", "{user}\n> {comment}")).format(
            user=interaction.user.display_name, comment=comment
        ) + f"\n-# {ts}",
        inline=False,
    )

    if _is_v2(msg):
        _store_card(interaction.guild.id, msg_id, embed)
        view = _build_view(interaction.guild.id, interaction.channel_id, data, t, msg_id, embed,
                           _is_decided(embed, t["status_field"]))
        await interaction.response.edit_message(view=view)
    else:
        await interaction.response.edit_message(embed=embed)

    # Thread update
    thread = _get_suggestion_thread(interaction.guild, msg_id)
    if thread:
        try:
            await thread.send(
                f"{cfg.Icons.message} " + str(t.get("thread_update_comment", "**Staff update** by {user}\n> {comment}")).format(
                    user=interaction.user.display_name, comment=comment
                ) + f"\n-# {ts}"
            )
        except (discord.Forbidden, discord.HTTPException):
            pass

    # Log channel
    log_ch_id = str(data.get("log_channel", "") or "")
    if log_ch_id and log_ch_id.isdigit():
        log_ch = interaction.guild.get_channel(int(log_ch_id))
        if isinstance(log_ch, discord.TextChannel):
            log_embed = discord.Embed(
                description=f"{cfg.Icons.message} " + str(t["log_comment"]).format(
                    reviewer=interaction.user.mention,
                    link=msg.jump_url,
                    comment=comment,
                ),
                color=cfg.Discord.info_color,
            )
            log_embed.set_footer(text=t["footer"])
            try:
                await log_ch.send(view=v2.from_embed(log_embed))
            except (discord.Forbidden, discord.HTTPException):
                pass


# ── Decision processing ───────────────────────────────────────────────────────

async def _process_decision(
    interaction: discord.Interaction,
    accepted: bool,
    reason: str | None,
    t: dict,
) -> None:
    if interaction.guild is None or interaction.message is None:
        return

    data: dict = dict(datasys.load_data(interaction.guild.id, "suggestions"))
    msg = interaction.message
    embed = _card_embed(msg, interaction.guild.id)
    if embed is None:
        return

    # Build status value (with or without reason)
    if accepted:
        embed.color = cfg.Discord.success_color
        if reason:
            status_value = str(t["status_accepted_reason"]).format(
                user=interaction.user.mention, reason=reason
            )
        else:
            status_value = str(t["status_accepted"]).format(user=interaction.user.mention)
    else:
        embed.color = cfg.Discord.danger_color
        if reason:
            status_value = str(t["status_declined_reason"]).format(
                user=interaction.user.mention, reason=reason
            )
        else:
            status_value = str(t["status_declined"]).format(user=interaction.user.mention)

    embed.add_field(name=t["status_field"], value=status_value, inline=False)

    # Disabled view preserving current vote counts
    msg_id = str(msg.id)
    if _is_v2(msg):
        _store_card(interaction.guild.id, msg_id, embed)
        await interaction.response.edit_message(view=_build_view(
            interaction.guild.id, interaction.channel_id, data, t, msg_id, embed, decided=True))
    else:
        await interaction.response.edit_message(embed=embed, view=_build_view(
            interaction.guild.id, interaction.channel_id, data, t, msg_id, None, decided=True))

    # Thread update
    thread = _get_suggestion_thread(interaction.guild, msg_id)
    if thread:
        if accepted:
            icon = cfg.Icons.check
            if reason:
                thread_msg = f"{icon} " + str(t.get("thread_update_accepted_reason", "Suggestion **accepted** by {user}\n**Reason:** {reason}")).format(
                    user=interaction.user.mention, reason=reason
                )
            else:
                thread_msg = f"{icon} " + str(t.get("thread_update_accepted", "Suggestion **accepted** by {user}")).format(
                    user=interaction.user.mention
                )
        else:
            icon = cfg.Icons.cross
            if reason:
                thread_msg = f"{icon} " + str(t.get("thread_update_declined_reason", "Suggestion **declined** by {user}\n**Reason:** {reason}")).format(
                    user=interaction.user.mention, reason=reason
                )
            else:
                thread_msg = f"{icon} " + str(t.get("thread_update_declined", "Suggestion **declined** by {user}")).format(
                    user=interaction.user.mention
                )
        try:
            await thread.send(thread_msg)
        except (discord.Forbidden, discord.HTTPException):
            pass

    # Log channel
    log_ch_id = str(data.get("log_channel", "") or "")
    if log_ch_id and log_ch_id.isdigit():
        log_ch = interaction.guild.get_channel(int(log_ch_id))
        if isinstance(log_ch, discord.TextChannel):
            if accepted:
                log_key = "log_accepted_reason" if reason else "log_accepted"
            else:
                log_key = "log_declined_reason" if reason else "log_declined"
            log_embed = discord.Embed(
                description=str(t[log_key]).format(
                    reviewer=interaction.user.mention,
                    link=msg.jump_url,
                    reason=reason or "",
                ),
                color=cfg.Discord.success_color if accepted else cfg.Discord.danger_color,
            )
            log_embed.set_footer(text=t["footer"])
            try:
                await log_ch.send(view=v2.from_embed(log_embed))
            except (discord.Forbidden, discord.HTTPException):
                pass


# ── Public voting ─────────────────────────────────────────────────────────────

async def _handle_public_vote(interaction: discord.Interaction, upvoted: bool) -> None:
    if interaction.guild is None or interaction.message is None:
        return

    data: dict = dict(datasys.load_data(interaction.guild.id, "suggestions"))
    lang = datasys.load_lang_file(interaction.guild.id)
    t: dict = lang["systems"]["suggestions"]

    ch_cfg = _get_channel_config(data, interaction.channel_id or 0)
    if not ch_cfg.get("votes_enabled", True):
        await interaction.response.send_message(t["voting_disabled"], ephemeral=True)
        return

    card = _card_embed(interaction.message, interaction.guild.id)
    if card is None:
        return

    if _is_decided(card, t["status_field"]):
        await interaction.response.send_message(t["already_decided"], ephemeral=True)
        return

    msg_id = str(interaction.message.id)
    up, down = _get_vote_counts(interaction.guild.id, msg_id)
    uid = interaction.user.id

    if upvoted:
        if uid in up:
            up.remove(uid)
        else:
            up.append(uid)
            if uid in down:
                down.remove(uid)
    else:
        if uid in down:
            down.remove(uid)
        else:
            down.append(uid)
            if uid in up:
                up.remove(uid)

    _save_vote_counts(interaction.guild.id, msg_id, up, down)
    view = _make_view(len(up), len(down), t, decided=False, embed=card if _is_v2(interaction.message) else None)
    await interaction.response.edit_message(view=view)

    # Auto-forward when upvote threshold is crossed (optional feature)
    if upvoted:
        await _maybe_auto_forward(interaction, msg_id, up, t)


# ── Auto-forward helper ───────────────────────────────────────────────────────

async def _maybe_auto_forward(
    interaction: discord.Interaction,
    msg_id: str,
    up: list,
    t: dict,
) -> None:
    """Forward a popular suggestion to the configured channel once the threshold is crossed."""
    if interaction.guild is None or interaction.message is None:
        return

    data: dict = dict(datasys.load_data(interaction.guild.id, "suggestions"))
    if not data.get("auto_forward_enabled"):
        return

    fwd_ch_id = str(data.get("auto_forward_channel", "") or "")
    if not fwd_ch_id or not fwd_ch_id.isdigit():
        return

    threshold = max(1, int(data.get("auto_forward_threshold", 10)))
    if len(up) < threshold:
        return

    # Check if already forwarded (flag stored in suggestion_votes entry)
    votes: dict = dict(datasys.load_data(interaction.guild.id, "suggestion_votes"))
    entry = votes.get(msg_id, {})
    if entry.get("forwarded"):
        return

    entry["forwarded"] = True
    votes[msg_id] = entry
    datasys.save_data(interaction.guild.id, "suggestion_votes", votes)

    fwd_ch = interaction.guild.get_channel(int(fwd_ch_id))
    if not isinstance(fwd_ch, discord.TextChannel):
        return

    fwd_embed = _card_embed(interaction.message, interaction.guild.id)
    if fwd_embed is None:
        return
    fwd_embed.title = t.get("auto_forward_title", f"{cfg.Icons.fire} Popular Suggestion")
    fwd_embed.set_footer(
        text=t.get("auto_forward_footer", "Baxi · Suggestions | {votes} upvotes").format(votes=len(up))
    )
    fwd_embed.add_field(name="", value=f"[{t.get('embed_title', 'Suggestion')}]({interaction.message.jump_url})", inline=False)

    try:
        await fwd_ch.send(view=v2.from_embed(fwd_embed))
        logger.debug.info(f"[Suggestions] Auto-forwarded msg={msg_id} to channel={fwd_ch_id} ({len(up)} upvotes)")
    except (discord.Forbidden, discord.HTTPException) as e:
        logger.error(f"[Suggestions] Auto-forward failed: {e}")


# ── Incoming message handler ──────────────────────────────────────────────────

async def check_suggestion(message: discord.Message, bot: commands.AutoShardedBot) -> bool:
    if message.guild is None or message.author.bot:
        return False

    data: dict = dict(datasys.load_data(message.guild.id, "suggestions"))
    if not data.get("enabled", False):
        return False

    # Support both old format (list of strings) and new format (list of dicts)
    channels_raw: list = list(data.get("channels", []))
    channel_config: dict | None = None
    for ch in channels_raw:
        ch_id = ch if isinstance(ch, str) else str(ch.get("id", ""))
        if ch_id == str(message.channel.id):
            channel_config = (
                ch if isinstance(ch, dict)
                else {"id": ch_id, "votes_enabled": True}
            )
            break

    if channel_config is None:
        return False

    lang = datasys.load_lang_file(message.guild.id)
    t: dict = lang["systems"]["suggestions"]

    votes_enabled: bool = bool(channel_config.get("votes_enabled", True))

    raw_content = message.content or ""

    # Save image attachments
    files: list[discord.File] = []
    first_image_name: str | None = None
    for i, attachment in enumerate(message.attachments):
        ct = attachment.content_type or ""
        if ct.startswith("image/"):
            try:
                ext = attachment.filename.rsplit(".", 1)[-1] if "." in attachment.filename else "png"
                filename = f"suggest-{message.id}-{i}.{ext}"
                file_path = Path(cfg.Globalchat.attachments_dir) / filename
                img_data = await attachment.read()
                with open(file_path, "wb") as f:
                    f.write(img_data)
                files.append(discord.File(str(file_path), filename=filename))
                if first_image_name is None:
                    first_image_name = filename
            except Exception as e:
                logger.error(f"[Suggestions] Attachment save failed: {e}")

    try:
        await message.delete()
    except (discord.Forbidden, discord.HTTPException):
        pass

    embed = discord.Embed(
        title=f"{cfg.Icons.bulb} {t['embed_title']}",
        description=raw_content or t["no_text"],
        color=cfg.Discord.info_color,
    )
    embed.set_author(
        name=message.author.display_name,
        icon_url=str(message.author.display_avatar.url),
    )
    embed.set_thumbnail(url=str(message.author.display_avatar.url))   # V2 card: the avatar sits beside the text
    if first_image_name:
        embed.set_image(url=f"attachment://{first_image_name}")
    embed.set_footer(text=t["footer"])

    view = _make_view(0, 0, t, decided=False, embed=embed) if votes_enabled else _make_staff_only_view(t, embed=embed)

    try:
        if files:
            sent = await message.channel.send(view=view, files=files)
        else:
            sent = await message.channel.send(view=view)
    except Exception as e:
        logger.error(f"[Suggestions] Could not post suggestion embed: {e}")
        return True

    # Store author for lazy thread creation on first Join Discussion click
    votes: dict = dict(datasys.load_data(message.guild.id, "suggestion_votes"))
    msg_id = str(sent.id)
    entry = votes.get(msg_id, {})
    entry["author_id"] = message.author.id
    entry["card"] = embed.to_dict()   # V2 messages carry no embed to read back
    votes[msg_id] = entry
    datasys.save_data(message.guild.id, "suggestion_votes", votes)

    return True
