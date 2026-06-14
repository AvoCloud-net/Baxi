"""Temp voice control panel.

When a temporary voice channel is created, a control-panel embed with buttons
is posted to that voice channel's built-in text chat. Only the channel owner may
use the buttons. Buttons let the owner toggle public/private, rename the channel,
set a user limit, and permit/reject specific users.

Owner state is persisted to ``data/temp_voice_owners.json`` so the persistent
view keeps working across bot restarts.

Public API (hard contract — other modules import these names):
    load_state() -> None
    get_owner(channel_id) -> int | None
    set_owner(channel_id, owner_id, guild_id) -> None
    remove_state(channel_id) -> None
    async send_control_panel(bot, channel, owner) -> None
    class TempVoiceControlView(discord.ui.View)
"""
from __future__ import annotations

import discord
from reds_simple_logger import Logger

import assets.data as datasys
import config.config as config
from assets.repo.standalone import (
    load_temp_voice_owners as _load_db_owners,
    save_temp_voice_owners as _save_db_owners,
    load_temp_voice_profiles as _load_db_profiles,
    save_temp_voice_profiles as _save_db_profiles,
    load_temp_voice_permanent as _load_db_permanent,
    save_temp_voice_permanent as _save_db_permanent,
)

logger = Logger()

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

# channel_id -> {"owner_id": int, "guild_id": int}
_owners: dict[int, dict] = {}

# "guild_id:user_id" -> profile dict (see _capture_profile)
_profiles: dict[str, dict] = {}


def load_state() -> None:
    """Load owner state and saved user profiles from the DB into memory.

    Tolerates DB errors (resets to empty in that case).
    """
    global _owners
    _owners = {}
    try:
        raw = _load_db_owners()
        for k, v in raw.items():
            try:
                _owners[int(k)] = {
                    "owner_id": int(v["owner_id"]),
                    "guild_id": int(v["guild_id"]),
                }
            except Exception:
                continue
    except Exception:
        logger.exception("[tempvoice] failed to load owner state, starting empty")
        _owners = {}
    _load_profiles()
    _load_permanent()


def _load_profiles() -> None:
    global _profiles
    _profiles = {}
    try:
        raw = _load_db_profiles()
        if isinstance(raw, dict):
            _profiles = {str(k): v for k, v in raw.items() if isinstance(v, dict)}
    except Exception:
        logger.exception("[tempvoice] failed to load profiles, starting empty")
        _profiles = {}


def _write_profiles() -> None:
    try:
        _save_db_profiles(_profiles)
    except Exception:
        logger.exception("[tempvoice] failed to write profiles")


def _profile_key(guild_id: int, user_id: int) -> str:
    return f"{int(guild_id)}:{int(user_id)}"


def get_profile(guild_id: int, user_id: int) -> dict | None:
    return _profiles.get(_profile_key(guild_id, user_id))


def save_profile(guild_id: int, user_id: int, profile: dict) -> None:
    _profiles[_profile_key(guild_id, user_id)] = profile
    _write_profiles()


# Channel ids marked permanent (not deleted when empty).
_permanent: set[int] = set()


def _load_permanent() -> None:
    global _permanent
    _permanent = set()
    try:
        raw = _load_db_permanent()
        if isinstance(raw, list):
            for cid in raw:
                try:
                    _permanent.add(int(cid))
                except Exception:
                    continue
    except Exception:
        logger.exception("[tempvoice] failed to load permanent set, starting empty")
        _permanent = set()


def _write_permanent() -> None:
    try:
        _save_db_permanent(sorted(_permanent))
    except Exception:
        logger.exception("[tempvoice] failed to write permanent set")


def is_permanent(channel_id: int) -> bool:
    return int(channel_id) in _permanent


def set_permanent(channel_id: int, permanent: bool) -> None:
    cid = int(channel_id)
    if permanent:
        _permanent.add(cid)
    else:
        _permanent.discard(cid)
    _write_permanent()


def _write_state() -> None:
    try:
        serialisable = {
            str(cid): {"owner_id": data["owner_id"], "guild_id": data["guild_id"]}
            for cid, data in _owners.items()
        }
        _save_db_owners(serialisable)
    except Exception:
        logger.exception("[tempvoice] failed to write state")


def get_owner(channel_id: int) -> int | None:
    entry = _owners.get(int(channel_id))
    if not entry:
        return None
    return entry.get("owner_id")


def set_owner(channel_id: int, owner_id: int, guild_id: int) -> None:
    _owners[int(channel_id)] = {"owner_id": int(owner_id), "guild_id": int(guild_id)}
    _write_state()


def remove_state(channel_id: int) -> None:
    if int(channel_id) in _owners:
        _owners.pop(int(channel_id), None)
        _write_state()
    if int(channel_id) in _permanent:
        _permanent.discard(int(channel_id))
        _write_permanent()


# ---------------------------------------------------------------------------
# Lang / helpers
# ---------------------------------------------------------------------------

def _t(lang, key, default):
    """Defensively read ``lang["systems"]["temp_voice"][key]`` with a fallback."""
    try:
        return lang.get("systems", {}).get("temp_voice", {}).get(key, default)
    except Exception:
        return default


def _icon(emoji_str: str) -> discord.PartialEmoji | None:
    try:
        return discord.PartialEmoji.from_str(emoji_str.strip())
    except Exception:
        return None


def build_control_embed(channel, owner, is_private, lang) -> discord.Embed:
    """Build the control panel embed for ``channel`` owned by ``owner``."""
    embed = discord.Embed(
        title=_t(lang, "panel_title", "Voice Control Panel"),
        description=_t(lang, "panel_desc",
                       "Manage your temporary voice channel with the buttons below."),
        color=config.Discord.color,
    )

    owner_mention = owner.mention if owner is not None else "?"
    status = (
        _t(lang, "status_private", "🔒 Private") if is_private
        else _t(lang, "status_public", "🔓 Public")
    )
    try:
        if is_permanent(channel.id):
            status += "\n" + _t(lang, "status_permanent", "📌 Permanent")
    except Exception:
        pass

    embed.add_field(
        name=f"{config.Icons.user} {_t(lang, 'owner_field', 'Owner')}",
        value=owner_mention,
        inline=True,
    )
    embed.add_field(
        name=f"{config.Icons.shield} {_t(lang, 'status_field', 'Status')}",
        value=status,
        inline=True,
    )

    # Live permitted / rejected lists derived from channel overwrites.
    permitted, rejected = _overwrite_members(channel, owner.id if owner else 0)
    none_value = _t(lang, "none_value", "—")
    embed.add_field(
        name=f"{config.Icons.check} {_t(lang, 'permitted_field', 'Permitted')}",
        value=_format_members(permitted, none_value),
        inline=False,
    )
    embed.add_field(
        name=f"{config.Icons.people_crossed} {_t(lang, 'rejected_field', 'Rejected')}",
        value=_format_members(rejected, none_value),
        inline=False,
    )

    try:
        embed.set_footer(text=channel.name)
    except Exception:
        pass
    return embed


def _overwrite_members(channel, owner_id: int):
    """Return (permitted_ids, rejected_ids) member lists from channel overwrites."""
    permitted: list[int] = []
    rejected: list[int] = []
    try:
        for target, ow in channel.overwrites.items():
            if not isinstance(target, discord.Member):
                continue
            if target.id == owner_id or target.id == channel.guild.default_role.id:
                continue
            if ow.connect is True:
                permitted.append(target.id)
            elif ow.connect is False:
                rejected.append(target.id)
    except Exception:
        logger.exception("[tempvoice] read overwrites failed")
    return permitted, rejected


def _format_members(ids: list[int], none_value: str) -> str:
    """Format member ids as mentions, truncating long lists."""
    if not ids:
        return none_value
    mentions = [f"<@{uid}>" for uid in ids[:15]]
    extra = len(ids) - 15
    if extra > 0:
        mentions.append(f"+{extra}")
    return " ".join(mentions)


# ---------------------------------------------------------------------------
# Sending the panel
# ---------------------------------------------------------------------------

async def send_control_panel(bot, channel: "discord.VoiceChannel", owner: "discord.Member") -> None:
    """Post the control panel into the voice channel's text chat.

    Never raises — failures are logged and swallowed.
    """
    try:
        set_owner(channel.id, owner.id, channel.guild.id)

        # Ensure the owner can always connect / see the channel.
        try:
            await channel.set_permissions(
                owner, connect=True, view_channel=True, reason="Temp voice owner"
            )
        except Exception:
            logger.exception("[tempvoice] failed to grant owner permissions")

        # Load and apply the owner's saved profile, if any.
        is_private = False
        profile = get_profile(channel.guild.id, owner.id)
        if profile:
            is_private = await _apply_profile(channel, owner, profile)

        lang = datasys.load_lang_file(channel.guild.id)
        embed = build_control_embed(channel, owner, is_private=is_private, lang=lang)

        # Voice channels are Messageable in discord.py 2.x — .send posts to text chat.
        # Ping the owner so the panel surfaces for them.
        await channel.send(
            content=owner.mention,
            embed=embed,
            view=TempVoiceControlView(bot),
            allowed_mentions=discord.AllowedMentions(users=[owner]),
        )
    except Exception:
        logger.exception("[tempvoice] send_control_panel failed")


# ---------------------------------------------------------------------------
# Modals
# ---------------------------------------------------------------------------

class _RenameModal(discord.ui.Modal):
    def __init__(self, lang):
        super().__init__(title=_t(lang, "rename_modal_title", "Rename Channel"))
        self._lang = lang
        self.name_input = discord.ui.TextInput(
            label=_t(lang, "rename_label", "New channel name"),
            max_length=64,
            required=True,
        )
        self.add_item(self.name_input)

    async def on_submit(self, interaction: discord.Interaction):
        lang = self._lang
        try:
            channel = interaction.channel
            if channel is None:
                await interaction.response.send_message(
                    _t(lang, "channel_gone", "This channel no longer exists."),
                    ephemeral=True,
                )
                return
            await channel.edit(name=str(self.name_input.value))
            await interaction.response.send_message(
                _t(lang, "renamed", "Channel renamed."), ephemeral=True
            )
        except Exception:
            logger.exception("[tempvoice] rename failed")
            await _safe_fail(interaction)


class _LimitModal(discord.ui.Modal):
    def __init__(self, lang):
        super().__init__(title=_t(lang, "limit_modal_title", "Set User Limit"))
        self._lang = lang
        self.limit_input = discord.ui.TextInput(
            label=_t(lang, "limit_label", "Max users (0 = unlimited)"),
            max_length=2,
            required=True,
        )
        self.add_item(self.limit_input)

    async def on_submit(self, interaction: discord.Interaction):
        lang = self._lang
        try:
            raw = str(self.limit_input.value).strip()
            if not raw.isdigit():
                await interaction.response.send_message(
                    _t(lang, "limit_invalid",
                       "Enter a whole number between 0 and 99."),
                    ephemeral=True,
                )
                return
            n = int(raw)
            if n < 0 or n > 99:
                await interaction.response.send_message(
                    _t(lang, "limit_invalid",
                       "Enter a whole number between 0 and 99."),
                    ephemeral=True,
                )
                return
            channel = interaction.channel
            if channel is None:
                await interaction.response.send_message(
                    _t(lang, "channel_gone", "This channel no longer exists."),
                    ephemeral=True,
                )
                return
            await channel.edit(user_limit=n)
            await interaction.response.send_message(
                _t(lang, "limit_set", "User limit updated."), ephemeral=True
            )
        except Exception:
            logger.exception("[tempvoice] limit set failed")
            await _safe_fail(interaction)


# ---------------------------------------------------------------------------
# Nested (transient) user-select views
# ---------------------------------------------------------------------------

async def _refresh_panel(panel_message, channel, lang) -> None:
    """Re-render a panel message to reflect current channel state."""
    if panel_message is None:
        return
    try:
        owner_id = get_owner(channel.id)
        owner = channel.guild.get_member(owner_id) if owner_id else None
        embed = build_control_embed(channel, owner, _is_private(channel), lang)
        await panel_message.edit(embed=embed)
    except Exception:
        logger.exception("[tempvoice] refresh panel failed")


class _PermitSelect(discord.ui.UserSelect):
    def __init__(self, channel, lang, panel_message=None):
        super().__init__(
            placeholder=_t(lang, "permit_prompt",
                           "Select users to permit (they can join):"),
            min_values=1,
            max_values=10,
        )
        self._channel = channel
        self._lang = lang
        self._panel = panel_message

    async def callback(self, interaction: discord.Interaction):
        lang = self._lang
        try:
            await interaction.response.defer(ephemeral=True)
            channel = self._channel
            if channel is None:
                await interaction.followup.send(
                    _t(lang, "channel_gone", "This channel no longer exists."),
                    ephemeral=True,
                )
                return

            # Create one reusable invite for the permitted users (best effort).
            invite = None
            try:
                invite = await channel.create_invite(
                    max_age=86400, max_uses=0, unique=False,
                    reason="Temp voice permit invite",
                )
            except Exception:
                logger.exception("[tempvoice] create_invite failed")

            count = 0
            sent = 0
            for user in self.values:
                try:
                    await channel.set_permissions(
                        user, connect=True, view_channel=True,
                        reason="Temp voice permit",
                    )
                    count += 1
                except Exception:
                    logger.exception("[tempvoice] permit set_permissions failed")
                    continue

                # DM the permitted user an invite so they can jump straight in.
                if invite is not None:
                    try:
                        await _dm_invite(user, channel, invite, lang)
                        sent += 1
                    except (discord.Forbidden, discord.HTTPException):
                        # DMs closed / blocked — permission still granted.
                        pass
                    except Exception:
                        logger.exception("[tempvoice] permit DM failed")

            await _refresh_panel(self._panel, channel, lang)

            if sent:
                msg = _t(lang, "permitted_invited",
                         "Permitted {count} user(s) and sent {sent} invite(s).").format(
                    count=count, sent=sent)
            else:
                msg = _t(lang, "permitted",
                         "Permitted {count} user(s).").format(count=count)
            await interaction.followup.send(msg, ephemeral=True)
        except Exception:
            logger.exception("[tempvoice] permit select failed")
            await _safe_fail(interaction)


class _RejectSelect(discord.ui.UserSelect):
    def __init__(self, channel, lang, panel_message=None):
        super().__init__(
            placeholder=_t(lang, "reject_prompt",
                           "Select users to reject (they cannot join):"),
            min_values=1,
            max_values=10,
        )
        self._channel = channel
        self._lang = lang
        self._panel = panel_message

    async def callback(self, interaction: discord.Interaction):
        lang = self._lang
        try:
            await interaction.response.defer(ephemeral=True)
            channel = self._channel
            if channel is None:
                await interaction.followup.send(
                    _t(lang, "channel_gone", "This channel no longer exists."),
                    ephemeral=True,
                )
                return
            count = 0
            current_members = {m.id for m in getattr(channel, "members", [])}
            for user in self.values:
                try:
                    await channel.set_permissions(
                        user, connect=False, reason="Temp voice reject"
                    )
                    count += 1
                    # Disconnect if currently inside.
                    if user.id in current_members:
                        member = channel.guild.get_member(user.id)
                        if member is not None:
                            try:
                                await member.move_to(None)
                            except Exception:
                                logger.exception("[tempvoice] disconnect failed")
                except Exception:
                    logger.exception("[tempvoice] reject set_permissions failed")
            await _refresh_panel(self._panel, channel, lang)
            await interaction.followup.send(
                _t(lang, "rejected", "Rejected {count} user(s).").format(count=count),
                ephemeral=True,
            )
        except Exception:
            logger.exception("[tempvoice] reject select failed")
            await _safe_fail(interaction)


class _SelectView(discord.ui.View):
    """Transient (non-persistent) view holding a single UserSelect."""

    def __init__(self, select: discord.ui.UserSelect):
        super().__init__(timeout=120)
        self.add_item(select)


def _is_private(channel) -> bool:
    """True if @everyone is denied connect on the channel."""
    try:
        ow = channel.overwrites_for(channel.guild.default_role)
        return ow.connect is False
    except Exception:
        return False


def _capture_profile(channel, owner_id: int) -> dict:
    """Snapshot the current channel state into a saveable profile dict."""
    permitted: list[int] = []
    rejected: list[int] = []
    try:
        for target, ow in channel.overwrites.items():
            if not isinstance(target, discord.Member):
                continue
            if target.id == owner_id or target.id == channel.guild.default_role.id:
                continue
            if ow.connect is True:
                permitted.append(target.id)
            elif ow.connect is False:
                rejected.append(target.id)
    except Exception:
        logger.exception("[tempvoice] capture overwrites failed")
    return {
        "is_private": _is_private(channel),
        "user_limit": int(getattr(channel, "user_limit", 0) or 0),
        "name": channel.name,
        "permitted": permitted,
        "rejected": rejected,
    }


async def _apply_profile(channel, owner, profile: dict) -> bool:
    """Apply a saved profile to a freshly created channel. Best effort.

    Returns the resulting is_private flag.
    """
    is_private = bool(profile.get("is_private", False))
    guild = channel.guild
    try:
        # Name + user limit.
        edits = {}
        name = profile.get("name")
        if isinstance(name, str) and name.strip():
            edits["name"] = name[:100]
        limit = profile.get("user_limit")
        if isinstance(limit, int) and 0 <= limit <= 99:
            edits["user_limit"] = limit
        if edits:
            try:
                await channel.edit(reason="Temp voice load profile", **edits)
            except Exception:
                logger.exception("[tempvoice] profile edit failed")

        # Public / private base state for @everyone.
        try:
            if is_private:
                await channel.set_permissions(
                    guild.default_role, connect=False,
                    reason="Temp voice profile private",
                )
            else:
                await channel.set_permissions(
                    guild.default_role, connect=True, view_channel=True,
                    reason="Temp voice profile public",
                )
        except Exception:
            logger.exception("[tempvoice] profile default_role perms failed")

        # Re-grant the owner (always able to connect).
        try:
            await channel.set_permissions(
                owner, connect=True, view_channel=True, reason="Temp voice owner",
            )
        except Exception:
            pass

        # Restore permitted / rejected members.
        for uid in profile.get("permitted", []):
            member = guild.get_member(int(uid)) if str(uid).isdigit() or isinstance(uid, int) else None
            if member is not None:
                try:
                    await channel.set_permissions(
                        member, connect=True, view_channel=True,
                        reason="Temp voice profile permit",
                    )
                except Exception:
                    pass
        for uid in profile.get("rejected", []):
            member = guild.get_member(int(uid)) if str(uid).isdigit() or isinstance(uid, int) else None
            if member is not None:
                try:
                    await channel.set_permissions(
                        member, connect=False, reason="Temp voice profile reject",
                    )
                except Exception:
                    pass
    except Exception:
        logger.exception("[tempvoice] apply profile failed")
    return is_private


async def _dm_invite(user, channel, invite, lang) -> None:
    """DM ``user`` an embed + join button for ``invite``.

    Raises on failure (closed DMs) so the caller can count successes.
    """
    guild_name = getattr(channel.guild, "name", "the server")
    embed = discord.Embed(
        title=_t(lang, "invite_dm_title", "You've been invited!"),
        description=_t(lang, "invite_dm_desc",
                       "You can now join **{channel}** in **{guild}**.").format(
            channel=channel.name, guild=guild_name),
        color=config.Discord.color,
    )
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(
        label=_t(lang, "invite_button", "Join Voice"),
        style=discord.ButtonStyle.link,
        url=invite.url,
    ))
    await user.send(embed=embed, view=view)


def _can_persist(member, guild_id: int) -> bool:
    """True if ``member`` has a role allowed to make channels permanent."""
    try:
        cfg = datasys.load_data(guild_id, "temp_voice") or {}
        allowed = {str(r) for r in (cfg.get("persist_roles") or [])}
        if not allowed:
            return False
        return any(str(r.id) in allowed for r in getattr(member, "roles", []))
    except Exception:
        logger.exception("[tempvoice] persist role check failed")
        return False


async def _safe_fail(interaction: discord.Interaction):
    """Best-effort generic failure reply so the interaction never hangs."""
    msg = "Something went wrong. Please try again."
    try:
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except Exception:
        logger.exception("[tempvoice] failed to send failure message")


# ---------------------------------------------------------------------------
# Persistent control view
# ---------------------------------------------------------------------------

class TempVoiceControlView(discord.ui.View):
    def __init__(self, bot=None):
        super().__init__(timeout=None)
        self.bot = bot

        self.public_btn.emoji = _icon(config.Icons.check)
        self.private_btn.emoji = _icon(config.Icons.shield)
        self.rename_btn.emoji = _icon(config.Icons.pin)
        self.limit_btn.emoji = _icon(config.Icons.user)
        self.permit_btn.emoji = _icon(config.Icons.hand)
        self.reject_btn.emoji = _icon(config.Icons.people_crossed)
        self.save_btn.emoji = _icon(config.Icons.bulb)
        self.permanent_btn.emoji = _icon(config.Icons.pin)

    # -- access control -----------------------------------------------------
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        lang = datasys.load_lang_file(interaction.guild_id)
        channel = interaction.channel
        if channel is None:
            try:
                await interaction.response.send_message(
                    _t(lang, "channel_gone", "This channel no longer exists."),
                    ephemeral=True,
                )
            except Exception:
                pass
            return False

        owner_id = get_owner(channel.id)
        if owner_id is None or interaction.user.id != owner_id:
            try:
                await interaction.response.send_message(
                    _t(lang, "not_owner",
                       "Only the channel owner can use this control panel."),
                    ephemeral=True,
                )
            except Exception:
                pass
            return False
        return True

    async def _rerender(self, interaction: discord.Interaction, is_private: bool, lang):
        """Edit the panel message to reflect a new public/private status."""
        try:
            owner_id = get_owner(interaction.channel.id)
            owner = None
            if owner_id is not None:
                owner = interaction.guild.get_member(owner_id)
            embed = build_control_embed(
                interaction.channel, owner, is_private=is_private, lang=lang
            )
            await interaction.message.edit(embed=embed)
        except Exception:
            logger.exception("[tempvoice] panel re-render failed")

    # -- row 0: public / private -------------------------------------------
    @discord.ui.button(
        label="Public", style=discord.ButtonStyle.success,
        custom_id="tempvoice:public", row=0,
    )
    async def public_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        lang = datasys.load_lang_file(interaction.guild_id)
        try:
            await interaction.response.defer(ephemeral=True)
            channel = interaction.channel
            if channel is None:
                await interaction.followup.send(
                    _t(lang, "channel_gone", "This channel no longer exists."),
                    ephemeral=True,
                )
                return
            await channel.set_permissions(
                interaction.guild.default_role,
                connect=True, view_channel=True,
                reason="Temp voice set public",
            )
            await self._rerender(interaction, is_private=False, lang=lang)
            await interaction.followup.send(
                _t(lang, "now_public",
                   "Channel is now public — anyone can join."),
                ephemeral=True,
            )
        except Exception:
            logger.exception("[tempvoice] public callback failed")
            await _safe_fail(interaction)

    @discord.ui.button(
        label="Private", style=discord.ButtonStyle.secondary,
        custom_id="tempvoice:private", row=0,
    )
    async def private_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        lang = datasys.load_lang_file(interaction.guild_id)
        try:
            await interaction.response.defer(ephemeral=True)
            channel = interaction.channel
            if channel is None:
                await interaction.followup.send(
                    _t(lang, "channel_gone", "This channel no longer exists."),
                    ephemeral=True,
                )
                return
            # Lock connect for everyone but leave view_channel untouched.
            await channel.set_permissions(
                interaction.guild.default_role,
                connect=False,
                reason="Temp voice set private",
            )
            # Ensure the owner can still connect.
            owner_id = get_owner(channel.id)
            if owner_id is not None:
                owner = interaction.guild.get_member(owner_id)
                if owner is not None:
                    try:
                        await channel.set_permissions(
                            owner, connect=True, view_channel=True,
                            reason="Temp voice owner",
                        )
                    except Exception:
                        logger.exception("[tempvoice] re-grant owner failed")
            await self._rerender(interaction, is_private=True, lang=lang)
            await interaction.followup.send(
                _t(lang, "now_private",
                   "Channel is now private — only permitted users can join."),
                ephemeral=True,
            )
        except Exception:
            logger.exception("[tempvoice] private callback failed")
            await _safe_fail(interaction)

    # -- row 1: rename / limit / permit / reject ---------------------------
    @discord.ui.button(
        label="Rename", style=discord.ButtonStyle.primary,
        custom_id="tempvoice:rename", row=1,
    )
    async def rename_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        lang = datasys.load_lang_file(interaction.guild_id)
        try:
            await interaction.response.send_modal(_RenameModal(lang))
        except Exception:
            logger.exception("[tempvoice] rename modal failed")
            await _safe_fail(interaction)

    @discord.ui.button(
        label="User Limit", style=discord.ButtonStyle.primary,
        custom_id="tempvoice:limit", row=1,
    )
    async def limit_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        lang = datasys.load_lang_file(interaction.guild_id)
        try:
            await interaction.response.send_modal(_LimitModal(lang))
        except Exception:
            logger.exception("[tempvoice] limit modal failed")
            await _safe_fail(interaction)

    @discord.ui.button(
        label="Permit", style=discord.ButtonStyle.secondary,
        custom_id="tempvoice:permit", row=1,
    )
    async def permit_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        lang = datasys.load_lang_file(interaction.guild_id)
        try:
            channel = interaction.channel
            if channel is None:
                await interaction.response.send_message(
                    _t(lang, "channel_gone", "This channel no longer exists."),
                    ephemeral=True,
                )
                return
            view = _SelectView(_PermitSelect(channel, lang, interaction.message))
            await interaction.response.send_message(
                content=_t(lang, "permit_prompt",
                           "Select users to permit (they can join):"),
                view=view,
                ephemeral=True,
            )
        except Exception:
            logger.exception("[tempvoice] permit callback failed")
            await _safe_fail(interaction)

    @discord.ui.button(
        label="Reject", style=discord.ButtonStyle.danger,
        custom_id="tempvoice:reject", row=1,
    )
    async def reject_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        lang = datasys.load_lang_file(interaction.guild_id)
        try:
            channel = interaction.channel
            if channel is None:
                await interaction.response.send_message(
                    _t(lang, "channel_gone", "This channel no longer exists."),
                    ephemeral=True,
                )
                return
            view = _SelectView(_RejectSelect(channel, lang, interaction.message))
            await interaction.response.send_message(
                content=_t(lang, "reject_prompt",
                           "Select users to reject (they cannot join):"),
                view=view,
                ephemeral=True,
            )
        except Exception:
            logger.exception("[tempvoice] reject callback failed")
            await _safe_fail(interaction)

    @discord.ui.button(
        label="Save Settings", style=discord.ButtonStyle.secondary,
        custom_id="tempvoice:save", row=2,
    )
    async def save_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        lang = datasys.load_lang_file(interaction.guild_id)
        try:
            channel = interaction.channel
            if channel is None:
                await interaction.response.send_message(
                    _t(lang, "channel_gone", "This channel no longer exists."),
                    ephemeral=True,
                )
                return
            profile = _capture_profile(channel, interaction.user.id)
            save_profile(interaction.guild_id, interaction.user.id, profile)
            await interaction.response.send_message(
                _t(lang, "settings_saved",
                   "Settings saved. Your next temp channel will use them."),
                ephemeral=True,
            )
        except Exception:
            logger.exception("[tempvoice] save callback failed")
            await _safe_fail(interaction)

    @discord.ui.button(
        label="Permanent", style=discord.ButtonStyle.secondary,
        custom_id="tempvoice:permanent", row=2,
    )
    async def permanent_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        lang = datasys.load_lang_file(interaction.guild_id)
        try:
            channel = interaction.channel
            if channel is None:
                await interaction.response.send_message(
                    _t(lang, "channel_gone", "This channel no longer exists."),
                    ephemeral=True,
                )
                return
            # Only members with an allowed role may toggle permanence.
            if not _can_persist(interaction.user, interaction.guild_id):
                await interaction.response.send_message(
                    _t(lang, "permanent_no_perm",
                       "You don't have a role allowed to make channels permanent."),
                    ephemeral=True,
                )
                return
            new_state = not is_permanent(channel.id)
            set_permanent(channel.id, new_state)
            await interaction.response.defer(ephemeral=True)
            await self._rerender(interaction, is_private=_is_private(channel), lang=lang)
            await interaction.followup.send(
                _t(lang, "permanent_on", "Channel is now permanent — it won't be deleted.")
                if new_state else
                _t(lang, "permanent_off", "Channel is temporary again — deleted when empty."),
                ephemeral=True,
            )
        except Exception:
            logger.exception("[tempvoice] permanent callback failed")
            await _safe_fail(interaction)
