import discord
from pathlib import Path
from discord.ext import commands
import assets.data as datasys
import config.config as cfg
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

class SuggestionView(discord.ui.View):
    """Registered at startup so all custom_ids survive bot restarts.

    Row 0: upvote | downvote | join discussion
    Row 1: accept | decline | comment
    """
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

def _make_view(upvotes: int, downvotes: int, t: dict, decided: bool = False) -> SuggestionView:
    """SuggestionView with current vote counts, translated labels, optional disabled state."""
    v = SuggestionView()
    for item in v.children:
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


def _make_staff_only_view(t: dict, decided: bool = False) -> discord.ui.View:
    """View with Join Discussion (row 0) + Accept / Decline / Comment (row 1) when public voting is disabled."""
    v = discord.ui.View(timeout=None)
    v.add_item(discord.ui.Button(
        label=t.get("btn_join_thread", "Join Discussion"),
        emoji=cfg.Icons.message,
        style=discord.ButtonStyle.secondary,
        custom_id="suggestion:join_thread",
        disabled=False,
        row=0,
    ))
    v.add_item(discord.ui.Button(
        label=t.get("btn_accept", "Accept"),
        emoji=cfg.Icons.check,
        style=discord.ButtonStyle.success,
        custom_id="suggestion:accept",
        disabled=decided,
        row=1,
    ))
    v.add_item(discord.ui.Button(
        label=t.get("btn_decline", "Decline"),
        emoji=cfg.Icons.cross,
        style=discord.ButtonStyle.danger,
        custom_id="suggestion:decline",
        disabled=decided,
        row=1,
    ))
    v.add_item(discord.ui.Button(
        label=t.get("btn_comment", "Comment"),
        emoji=cfg.Icons.message,
        style=discord.ButtonStyle.secondary,
        custom_id="suggestion:comment",
        disabled=False,
        row=1,
    ))
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


def _check_permission(interaction: discord.Interaction, data: dict) -> bool:
    staff_role_id = str(data.get("staff_role", "") or "")
    if isinstance(interaction.user, discord.Member):
        if interaction.user.guild_permissions.manage_guild:
            return True
        if staff_role_id:
            return any(str(r.id) == staff_role_id for r in interaction.user.roles)
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
    if interaction.message.embeds:
        thread_name = (interaction.message.embeds[0].description or "").strip()
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

    if interaction.message.embeds and _is_decided(interaction.message.embeds[0], t["status_field"]):
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
    if not msg.embeds:
        return

    msg_id = str(msg.id)
    ts = f"<t:{int(discord.utils.utcnow().timestamp())}:f>"
    embed = msg.embeds[0].copy()
    embed.add_field(
        name=t.get("comment_field", "Staff Update"),
        value=f"{cfg.Icons.message} " + str(t.get("comment_value", "{user}\n> {comment}")).format(
            user=interaction.user.display_name, comment=comment
        ) + f"\n-# {ts}",
        inline=False,
    )

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
                await log_ch.send(embed=log_embed)
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
    if not msg.embeds:
        return

    embed = msg.embeds[0].copy()

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
    up, down = _get_vote_counts(interaction.guild.id, msg_id)
    ch_cfg = _get_channel_config(data, interaction.channel_id or 0)
    if ch_cfg.get("votes_enabled", True):
        disabled_view = _make_view(len(up), len(down), t, decided=True)
    else:
        disabled_view = _make_staff_only_view(t, decided=True)

    await interaction.response.edit_message(embed=embed, view=disabled_view)

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
                await log_ch.send(embed=log_embed)
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

    if not interaction.message.embeds:
        return

    if _is_decided(interaction.message.embeds[0], t["status_field"]):
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
    view = _make_view(len(up), len(down), t, decided=False)
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

    if not interaction.message.embeds:
        return

    fwd_embed = interaction.message.embeds[0].copy()
    fwd_embed.title = t.get("auto_forward_title", f"{cfg.Icons.fire} Popular Suggestion")
    fwd_embed.set_footer(
        text=t.get("auto_forward_footer", "Baxi · Suggestions | {votes} upvotes").format(votes=len(up))
    )
    fwd_embed.add_field(name="", value=f"[{t.get('embed_title', 'Suggestion')}]({interaction.message.jump_url})", inline=False)

    try:
        await fwd_ch.send(embed=fwd_embed)
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
    if first_image_name:
        embed.set_image(url=f"attachment://{first_image_name}")
    embed.set_footer(text=t["footer"])

    view = _make_view(0, 0, t, decided=False) if votes_enabled else _make_staff_only_view(t)

    try:
        if files:
            sent = await message.channel.send(embed=embed, view=view, files=files)
        else:
            sent = await message.channel.send(embed=embed, view=view)
    except Exception as e:
        logger.error(f"[Suggestions] Could not post suggestion embed: {e}")
        return True

    # Store author for lazy thread creation on first Join Discussion click
    votes: dict = dict(datasys.load_data(message.guild.id, "suggestion_votes"))
    msg_id = str(sent.id)
    entry = votes.get(msg_id, {})
    entry["author_id"] = message.author.id
    votes[msg_id] = entry
    datasys.save_data(message.guild.id, "suggestion_votes", votes)

    return True
