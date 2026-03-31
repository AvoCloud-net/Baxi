import discord
from pathlib import Path
from discord.ext import commands
import assets.data as datasys
import config.config as cfg
from reds_simple_logger import Logger

logger = Logger()


# ── Modal ─────────────────────────────────────────────────────────────────────

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
    """Registered at startup so all custom_ids survive bot restarts."""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="👍  0", style=discord.ButtonStyle.secondary, custom_id="suggestion:upvote")
    async def upvote(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _handle_public_vote(interaction, upvoted=True)

    @discord.ui.button(label="👎  0", style=discord.ButtonStyle.secondary, custom_id="suggestion:downvote")
    async def downvote(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _handle_public_vote(interaction, upvoted=False)

    @discord.ui.button(label="✅  Accept", style=discord.ButtonStyle.success, custom_id="suggestion:accept")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _open_decision_modal(interaction, accepted=True)

    @discord.ui.button(label="❌  Decline", style=discord.ButtonStyle.danger, custom_id="suggestion:decline")
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _open_decision_modal(interaction, accepted=False)


# ── View helpers ──────────────────────────────────────────────────────────────

def _make_view(upvotes: int, downvotes: int, t: dict, decided: bool = False) -> SuggestionView:
    """SuggestionView with current vote counts, translated labels, optional disabled state."""
    v = SuggestionView()
    for item in v.children:
        if not isinstance(item, discord.ui.Button):
            continue
        if item.custom_id == "suggestion:upvote":
            item.label = f"👍  {upvotes}"
            item.disabled = decided
        elif item.custom_id == "suggestion:downvote":
            item.label = f"👎  {downvotes}"
            item.disabled = decided
        elif item.custom_id == "suggestion:accept":
            item.label = t.get("btn_accept", "✅  Accept")
            item.disabled = decided
        elif item.custom_id == "suggestion:decline":
            item.label = t.get("btn_decline", "❌  Decline")
            item.disabled = decided
    return v


def _make_staff_only_view(t: dict, decided: bool = False) -> discord.ui.View:
    """View with only Accept / Decline when public voting is disabled."""
    v = discord.ui.View(timeout=None)
    v.add_item(discord.ui.Button(
        label=t.get("btn_accept", "✅  Accept"),
        style=discord.ButtonStyle.success,
        custom_id="suggestion:accept",
        disabled=decided,
    ))
    v.add_item(discord.ui.Button(
        label=t.get("btn_decline", "❌  Decline"),
        style=discord.ButtonStyle.danger,
        custom_id="suggestion:decline",
        disabled=decided,
    ))
    return v


# ── Shared helpers ────────────────────────────────────────────────────────────

def _get_vote_counts(guild_id: int, msg_id: str) -> tuple[list, list]:
    votes: dict = dict(datasys.load_data(guild_id, "suggestion_votes"))
    entry = votes.get(msg_id, {"up": [], "down": []})
    return list(entry.get("up", [])), list(entry.get("down", []))


def _save_vote_counts(guild_id: int, msg_id: str, up: list, down: list) -> None:
    votes: dict = dict(datasys.load_data(guild_id, "suggestion_votes"))
    votes[msg_id] = {"up": up, "down": down}
    datasys.save_data(guild_id, "suggestion_votes", votes)


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


# ── Modal trigger ─────────────────────────────────────────────────────────────

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


# ── Decision processing (called from modal on_submit) ─────────────────────────

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
                user=interaction.user.display_name, reason=reason
            )
        else:
            status_value = str(t["status_accepted"]).format(user=interaction.user.display_name)
    else:
        embed.color = cfg.Discord.danger_color
        if reason:
            status_value = str(t["status_declined_reason"]).format(
                user=interaction.user.display_name, reason=reason
            )
        else:
            status_value = str(t["status_declined"]).format(user=interaction.user.display_name)

    embed.add_field(name=t["status_field"], value=status_value, inline=False)

    # Disabled view preserving current vote counts
    msg_id = str(msg.id)
    up, down = _get_vote_counts(interaction.guild.id, msg_id)
    votes_enabled = data.get("votes_enabled", True)
    if votes_enabled:
        disabled_view = _make_view(len(up), len(down), t, decided=True)
    else:
        disabled_view = _make_staff_only_view(t, decided=True)

    await interaction.response.edit_message(embed=embed, view=disabled_view)

    # Optional log channel
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

    if not data.get("votes_enabled", True):
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


# ── Incoming message handler ──────────────────────────────────────────────────

async def check_suggestion(message: discord.Message, bot: commands.AutoShardedBot) -> bool:
    if message.guild is None or message.author.bot:
        return False

    data: dict = dict(datasys.load_data(message.guild.id, "suggestions"))
    if not data.get("enabled", False):
        return False

    channels: list = list(data.get("channels", []))
    if str(message.channel.id) not in [str(c) for c in channels]:
        return False

    lang = datasys.load_lang_file(message.guild.id)
    t: dict = lang["systems"]["suggestions"]

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
        title=t["embed_title"],
        description=message.content or t["no_text"],
        color=cfg.Discord.info_color,
    )
    embed.set_author(
        name=message.author.display_name,
        icon_url=str(message.author.display_avatar.url),
    )
    if first_image_name:
        embed.set_image(url=f"attachment://{first_image_name}")
    embed.set_footer(text=t["footer"])

    votes_enabled = data.get("votes_enabled", True)
    view = _make_view(0, 0, t, decided=False) if votes_enabled else _make_staff_only_view(t)

    try:
        if files:
            await message.channel.send(embed=embed, view=view, files=files)
        else:
            await message.channel.send(embed=embed, view=view)
    except Exception as e:
        logger.error(f"[Suggestions] Could not post suggestion embed: {e}")

    return True
