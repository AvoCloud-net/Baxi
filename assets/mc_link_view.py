"""Discord View with Confirm/Cancel buttons for the /mc link flow.

Mirrors the web confirm/cancel/accept logic from assets/dash/dash.py without
the web roundtrip — the user clicks buttons directly in the ephemeral message.
"""
from __future__ import annotations

import discord
from typing import cast
from reds_simple_logger import Logger

import config.config as config

logger = Logger()


def _icon(emoji_str: str) -> discord.PartialEmoji | None:
    try:
        return discord.PartialEmoji.from_str(emoji_str.strip())
    except Exception:
        return None


class MCLinkConfirmView(discord.ui.View):
    def __init__(
        self,
        bot,
        token: str,
        *,
        guild_id: int,
        author_id: int,
        kind: str,
        timeout: float = 600.0,
    ):
        super().__init__(timeout=timeout)
        self.bot = bot
        self.token = token
        self.guild_id = guild_id
        self.author_id = author_id
        self.kind = kind

        self.confirm.emoji = _icon(config.Icons.check)
        self.cancel.emoji = _icon(config.Icons.cross)

        if kind == "already_linked":
            self.confirm.label = "OK"
            self.cancel.label = "Back"

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "This confirmation isn't for you.", ephemeral=True
            )
            return False
        return True

    async def _disable(self):
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True

    async def on_timeout(self):
        # Drop session, disable buttons. Message edit not possible without stored message ref.
        from assets.mc_link import consume_link_session
        consume_link_session(self.token)
        await self._disable()

    @discord.ui.button(label="Accept Link", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        from assets import mc_link as mcl
        from assets import mc_link_card as card
        from assets import data as datasys
        import config.config as config

        await interaction.response.defer()

        sess = mcl.get_link_session(self.token)
        if not sess:
            await self._render_cancel(
                interaction,
                title="Link expired",
                subtitle="This link has expired. Run /mc link again in Discord to get a new one.",
            )
            return

        kind = sess["kind"]
        guild_id = sess["guild_id"]
        discord_id = sess["discord_id"]
        mc_name = sess["mc_name"]
        lang = datasys.load_lang_file(guild_id)
        t = lang["systems"]["mc_link"]
        guild_conf = datasys.load_data(guild_id, "mc_link")

        if kind == "already_linked":
            mcl.consume_link_session(self.token)
            await self._render_success(
                interaction,
                title=t.get("success_title", "All done!"),
                subtitle=t.get("already_linked_desc", "Your account is already linked. No changes were made."),
                mc_name=mc_name,
            )
            return

        ok, err = await mcl.whitelist_player(
            sess["api_url"], sess["api_secret"],
            sess["uuid"], mc_name,
            sess["discord_id"], sess["discord_name"],
        )
        if not ok:
            if err == "already_linked":
                # MC plugin enforces the 1:1 default — the Discord already links a
                # different MC account. Show that instead of a generic failure.
                fail_title = t.get("already_linked_title", "Already linked")
                fail_subtitle = t.get("already_linked_desc", "Your Discord account is already linked to a Minecraft account. Unlink it first, or ask an admin.")
            else:
                fail_title = "Couldn't complete"
                fail_subtitle = t.get("link_failed", "Minecraft server unreachable. Try again later.")
            await self._render_cancel(interaction, title=fail_title, subtitle=fail_subtitle)
            mcl.consume_link_session(self.token)
            return

        await mcl.store_link(guild_id, discord_id, sess["uuid"], mc_name)
        guild = self.bot.get_guild(guild_id)
        role_id_str = guild_conf.get("role_id", "")
        if guild and role_id_str:
            try:
                role = guild.get_role(int(role_id_str))
                member = guild.get_member(discord_id)
                if role and member:
                    await member.add_roles(role, reason="MC account linked")
            except Exception:
                logger.exception("[mc_link_view] role add failed")
        await mcl.announce_link(self.bot, guild_id, discord_id, mc_name, guild_conf, lang)
        await mcl.dm_user(self.bot, guild_id, discord_id, mc_name, guild_conf, lang)

        mcl.consume_link_session(self.token)

        await self._render_success(
            interaction,
            title=t.get("success_title", "All done!"),
            subtitle=t.get("dm_desc", "Your Minecraft account **{mc_name}** is now linked.").format(
                mc_name=mc_name, guild=(interaction.guild.name if interaction.guild else "this server"),
            ),
            mc_name=mc_name,
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        from assets import mc_link as mcl
        await interaction.response.defer()
        mcl.consume_link_session(self.token)
        await self._render_cancel(
            interaction,
            title="Cancelled",
            subtitle="The link request was cancelled. Run /mc link again in Discord to start over.",
        )

    async def _render_success(self, interaction: discord.Interaction, *, title: str, subtitle: str, mc_name: str):
        from assets import mc_link_card as card
        try:
            buf = await card.render_success()
            await self._disable()
            file = discord.File(buf, filename="mc_link_success.png")
            embed = discord.Embed(title=title, description=subtitle, color=0x22C55E)
            embed.set_image(url="attachment://mc_link_success.png")
            await interaction.edit_original_response(attachments=[file], embed=embed, view=self)
        except Exception:
            logger.exception("[mc_link_view] render_success failed")
            await self._fallback_text(interaction, f"✅ {title}\n{subtitle}")

    async def _render_cancel(self, interaction: discord.Interaction, *, title: str, subtitle: str):
        from assets import mc_link_card as card
        try:
            buf = await card.render_cancel()
            await self._disable()
            file = discord.File(buf, filename="mc_link_cancel.png")
            embed = discord.Embed(title=title, description=subtitle, color=0xA5A5AA)
            embed.set_image(url="attachment://mc_link_cancel.png")
            await interaction.edit_original_response(attachments=[file], embed=embed, view=self)
        except Exception:
            logger.exception("[mc_link_view] render_cancel failed")
            await self._fallback_text(interaction, f"❌ {title}\n{subtitle}")

    async def _fallback_text(self, interaction: discord.Interaction, content: str):
        try:
            await self._disable()
            await interaction.edit_original_response(content=content, embed=None, attachments=[], view=self)
        except Exception:
            logger.exception("[mc_link_view] fallback edit failed")
