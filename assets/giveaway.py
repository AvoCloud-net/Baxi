import random
import time

import discord
from discord import app_commands
from discord.ext import tasks, commands

import assets.data as datasys
import config.config as cfg
from reds_simple_logger import Logger

logger = Logger()


# ── Embed builder ─────────────────────────────────────────────────────────────

def _make_embed(
    t: dict,
    reward: str,
    end_ts: int,
    winner_count: int,
    host: discord.Member | discord.User,
    participant_count: int,
    image_url: str | None = None,
    ended: bool = False,
) -> discord.Embed:
    color = cfg.Discord.success_color if ended else cfg.Discord.color
    embed = discord.Embed(
        title=f"{cfg.Icons.celebrate} {t['embed_title']}",
        description=f"**{reward}**",
        color=color,
    )
    time_label = t["field_ended"] if ended else t["field_ends"]
    time_value = f"<t:{end_ts}:f>" if ended else f"<t:{end_ts}:R>"
    embed.add_field(name=time_label, value=time_value, inline=True)
    embed.add_field(name=t["field_winners"], value=str(winner_count), inline=True)
    embed.add_field(name=t["field_host"], value=host.mention, inline=True)
    if image_url:
        embed.set_image(url=image_url)
    embed.set_footer(text=t["footer"])
    return embed


# ── Persistent view ───────────────────────────────────────────────────────────

class GiveawayView(discord.ui.View):
    """Persistent view — survives bot restarts."""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="0",
        emoji=cfg.Icons.celebrate,
        style=discord.ButtonStyle.primary,
        custom_id="giveaway:enter",
    )
    async def enter(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _handle_enter(interaction)


def _make_enter_view(count: int, ended: bool = False) -> GiveawayView:
    v = GiveawayView()
    for item in v.children:
        if isinstance(item, discord.ui.Button) and item.custom_id == "giveaway:enter":
            item.label = str(count)
            item.disabled = ended
    return v


# ── Button handler ────────────────────────────────────────────────────────────

async def _handle_enter(interaction: discord.Interaction) -> None:
    if interaction.guild is None or interaction.message is None:
        return

    lang = datasys.load_lang_file(interaction.guild.id)
    t: dict = lang["systems"]["giveaway"]
    msg_id = str(interaction.message.id)

    giveaways: dict = dict(datasys.load_data(interaction.guild.id, "giveaways"))
    entry = giveaways.get(msg_id)
    if not entry:
        await interaction.response.send_message(t["not_found"], ephemeral=True)
        return

    if entry.get("ended") or time.time() > entry.get("end_time", 0):
        await interaction.response.send_message(t["already_ended"], ephemeral=True)
        return

    participants: list = list(entry.get("participants", []))
    uid = interaction.user.id

    if uid in participants:
        participants.remove(uid)
        msg = t["left"]
    else:
        participants.append(uid)
        msg = t["entered"]

    entry["participants"] = participants
    giveaways[msg_id] = entry
    datasys.save_data(interaction.guild.id, "giveaways", giveaways)

    view = _make_enter_view(len(participants))
    await interaction.response.edit_message(view=view)
    await interaction.followup.send(msg, ephemeral=True)


# ── End giveaway ──────────────────────────────────────────────────────────────

async def _end_giveaway(
    bot: commands.AutoShardedBot,
    guild_id: int,
    msg_id: str,
    entry: dict,
) -> None:
    lang = datasys.load_lang_file(guild_id)
    t: dict = lang["systems"]["giveaway"]

    # Mark ended first to prevent double-firing
    entry["ended"] = True
    giveaways: dict = dict(datasys.load_data(guild_id, "giveaways"))
    giveaways[msg_id] = entry
    datasys.save_data(guild_id, "giveaways", giveaways)

    guild = bot.get_guild(guild_id)
    if not guild:
        return

    channel_id = entry.get("channel_id")
    if not channel_id:
        return
    channel = guild.get_channel(int(channel_id))
    if not isinstance(channel, discord.TextChannel):
        return

    try:
        msg = await channel.fetch_message(int(msg_id))
    except (discord.NotFound, discord.HTTPException):
        return

    participants: list = list(entry.get("participants", []))
    winner_count: int = int(entry.get("winner_count", 1))
    reward: str = str(entry.get("reward", ""))
    end_ts: int = int(entry.get("end_time", 0))
    host_id: int = int(entry.get("host_id", 0))
    winner_message: str = str(entry.get("winner_message", ""))
    image_url: str | None = entry.get("image_url")

    host = guild.get_member(host_id) or bot.get_user(host_id)

    # Update embed to ended state
    if msg.embeds and host:
        embed = _make_embed(t, reward, end_ts, winner_count, host,
                            len(participants), image_url, ended=True)
        disabled_view = _make_enter_view(len(participants), ended=True)
        try:
            await msg.edit(embed=embed, view=disabled_view)
        except (discord.Forbidden, discord.HTTPException):
            pass

    # Pick winners
    actual_count = min(winner_count, len(participants))
    if actual_count == 0:
        no_winner_embed = discord.Embed(
            title=f"{cfg.Icons.cross} {t['no_winners_title']}",
            description=str(t["no_winners"]).format(reward=reward, msg_link=msg.jump_url),
            color=cfg.Discord.danger_color,
        )
        no_winner_embed.set_footer(text=t["footer"])
        try:
            await channel.send(embed=no_winner_embed)
        except (discord.Forbidden, discord.HTTPException):
            pass
        return

    winners = random.sample(participants, actual_count)
    winner_mentions = " ".join(f"<@{w}>" for w in winners)

    # Channel announcement embed
    announce_embed = discord.Embed(
        title=f"{cfg.Icons.celebrate} {t['winner_announce_title']}",
        description=str(t["winner_announce"]).format(
            winners=winner_mentions,
            reward=reward,
            msg_link=msg.jump_url,
        ),
        color=cfg.Discord.success_color,
    )
    if winner_message:
        announce_embed.add_field(
            name=t["winner_message_field"],
            value=winner_message,
            inline=False,
        )
    announce_embed.set_footer(text=t["footer"])
    try:
        await channel.send(embed=announce_embed)
    except (discord.Forbidden, discord.HTTPException):
        pass

    # DM each winner
    for uid in winners:
        member = guild.get_member(uid)
        if member:
            dm_embed = discord.Embed(
                title=f"{cfg.Icons.celebrate} {t['winner_dm_title']}",
                description=str(t["winner_dm"]).format(
                    reward=reward,
                    guild=guild.name,
                    msg_link=msg.jump_url,
                ),
                color=cfg.Discord.success_color,
            )
            if winner_message:
                dm_embed.add_field(
                    name=t["winner_message_field"],
                    value=winner_message,
                    inline=False,
                )
            dm_embed.set_footer(text=t["footer"])
            try:
                await member.send(embed=dm_embed)
            except (discord.Forbidden, discord.HTTPException):
                pass


# ── Background task ───────────────────────────────────────────────────────────

class GiveawayTask:
    def __init__(self, bot: commands.AutoShardedBot):
        self.bot = bot

    @tasks.loop(seconds=30)
    async def check_giveaways(self):
        import os
        now = time.time()
        data_dir = "data"
        if not os.path.exists(data_dir):
            return
        for guild_folder in os.listdir(data_dir):
            try:
                guild_id = int(guild_folder)
            except ValueError:
                continue
            try:
                giveaways: dict = dict(datasys.load_data(guild_id, "giveaways"))
            except Exception:
                continue
            if not giveaways:
                continue
            for msg_id, entry in list(giveaways.items()):
                if entry.get("ended"):
                    continue
                if now >= entry.get("end_time", 0):
                    logger.debug.info(f"[Giveaway] Ending giveaway {msg_id} in guild {guild_id}")
                    try:
                        await _end_giveaway(self.bot, guild_id, msg_id, entry)
                    except Exception as e:
                        logger.error(f"[Giveaway] Error ending {msg_id}: {e}")


# ── Command ───────────────────────────────────────────────────────────────────

def giveaway_commands(bot: commands.AutoShardedBot) -> None:

    @bot.tree.command(name="giveaway", description="Start a giveaway in this channel")
    @app_commands.describe(
        reward="What are you giving away?",
        duration="Duration (e.g. 1h, 30m, 2d, 1h30m)",
        winners="Number of winners (1–20)",
        winner_message="Custom message sent to winners (optional)",
        image="Optional image to show in the giveaway embed",
    )
    @app_commands.guild_only()
    async def giveaway_cmd(
        interaction: discord.Interaction,
        reward: str,
        duration: str,
        winners: app_commands.Range[int, 1, 20],
        winner_message: str | None = None,
        image: discord.Attachment | None = None,
    ):
        await interaction.response.defer(ephemeral=True)
        if interaction.guild is None:
            return

        lang = datasys.load_lang_file(interaction.guild.id)
        t: dict = lang["systems"]["giveaway"]

        if not isinstance(interaction.user, discord.Member):
            return
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.edit_original_response(content=t["no_permission"])
            return

        # Parse duration using shared helper
        td = datasys.parse_duration(duration)
        if td is None or td.total_seconds() < 60:
            await interaction.edit_original_response(content=t["invalid_duration"])
            return

        end_time = time.time() + td.total_seconds()
        end_ts = int(end_time)

        image_url: str | None = None
        if image and image.content_type and image.content_type.startswith("image/"):
            image_url = image.url

        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.edit_original_response(content=t["channel_only"])
            return

        embed = _make_embed(t, reward, end_ts, winners, interaction.user, 0, image_url)
        view = _make_enter_view(0)

        try:
            msg = await channel.send(embed=embed, view=view)
        except (discord.Forbidden, discord.HTTPException):
            await interaction.edit_original_response(content=t["send_error"])
            return

        giveaways: dict = dict(datasys.load_data(interaction.guild.id, "giveaways"))
        giveaways[str(msg.id)] = {
            "channel_id": str(channel.id),
            "reward": reward,
            "winner_count": winners,
            "end_time": end_time,
            "host_id": interaction.user.id,
            "participants": [],
            "ended": False,
            "image_url": image_url,
            "winner_message": winner_message or "",
        }
        datasys.save_data(interaction.guild.id, "giveaways", giveaways)

        await interaction.edit_original_response(
            content=str(t["started"]).format(channel=channel.mention)
        )

    logger.debug.info("Giveaway commands loaded.")
