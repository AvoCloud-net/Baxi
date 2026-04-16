import re
import time
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

import assets.data as datasys
import config.config as cfg


# ── Embed builder ──────────────────────────────────────────────────────────────

def _make_poll_embed(
    question: str,
    answers: list[str],
    vote_counts: list[int],
    show_votes: bool,
    image_url: Optional[str] = None,
    end_time: Optional[float] = None,
    closed: bool = False,
) -> discord.Embed:
    total = sum(vote_counts)
    lines = []
    for i, (ans, cnt) in enumerate(zip(answers, vote_counts)):
        letter = "ABCDEFGHIJ"[i]
        if show_votes:
            pct = int(cnt / total * 100) if total > 0 else 0
            lines.append(f"**{letter}.** {ans} — {cnt} ({pct}%)")
        else:
            lines.append(f"**{letter}.** {ans}")

    color = cfg.Discord.warn_color if closed else cfg.Discord.color
    title = f"{cfg.Icons.stats} {question}" if not closed else f"{cfg.Icons.stats} {question} *(closed)*"

    embed = discord.Embed(
        title=title,
        description="\n".join(lines),
        color=color,
    )

    if end_time and not closed:
        embed.add_field(name="Ends", value=f"<t:{int(end_time)}:R>", inline=True)
    elif end_time and closed:
        embed.add_field(name="Ended", value=f"<t:{int(end_time)}:f>", inline=True)

    if closed:
        if total == 0:
            result_value = "No votes."
        else:
            max_votes = max(vote_counts)
            winners = [answers[i] for i, c in enumerate(vote_counts) if c == max_votes]
            result_value = ", ".join(f"**{w}**" for w in winners)
        embed.add_field(name=f"{cfg.Icons.trophy} Result", value=result_value, inline=False)

    if show_votes or closed:
        embed.set_footer(text=f"Baxi · {total} votes total")
    else:
        embed.set_footer(text="Baxi · vote counts hidden")
    if image_url:
        embed.set_image(url=image_url)
    return embed


# ── View builder ───────────────────────────────────────────────────────────────

def build_poll_view(
    answers: list[str],
    vote_counts: list[int],
    show_votes: bool,
    closed: bool = False,
) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    for i, ans in enumerate(answers):
        letter = "ABCDEFGHIJ"[i]
        vote_row = i // 5
        _MAX_ANS = 20
        ans_short = ans[:_MAX_ANS] + ("…" if len(ans) > _MAX_ANS else "")
        if show_votes:
            btn_label = f"{letter}. {ans_short} ({vote_counts[i]})"
        else:
            btn_label = f"{letter}. {ans_short}"
        view.add_item(discord.ui.Button(
            label=btn_label,
            style=discord.ButtonStyle.secondary,
            custom_id=f"poll:vote:{i}",
            row=vote_row,
            disabled=closed,
        ))

    if not closed:
        close_row = min((len(answers) - 1) // 5 + 1, 4)
        view.add_item(discord.ui.Button(
            label="Close Poll",
            style=discord.ButtonStyle.danger,
            custom_id="poll:close",
            row=close_row,
        ))

    return view


# ── Close poll (shared) ────────────────────────────────────────────────────────

async def _close_poll(
    bot: commands.AutoShardedBot,
    guild_id: int,
    msg_id: str,
    entry: dict,
) -> None:
    entry["closed"] = True
    polls: dict = dict(datasys.load_data(guild_id, "polls"))
    polls[msg_id] = entry
    datasys.save_data(guild_id, "polls", polls)

    guild = bot.get_guild(guild_id)
    if not guild:
        return
    channel = guild.get_channel(int(entry.get("channel_id", 0)))
    if not isinstance(channel, discord.TextChannel):
        return
    try:
        msg = await channel.fetch_message(int(msg_id))
    except (discord.NotFound, discord.HTTPException):
        return

    answers: list[str] = entry["answers"]
    user_votes: dict = entry.get("user_votes", {})
    vote_counts = [0] * len(answers)
    for v in user_votes.values():
        if 0 <= v < len(answers):
            vote_counts[v] += 1

    embed = _make_poll_embed(
        entry["question"], answers, vote_counts, entry.get("show_votes", True),
        entry.get("image_url"), entry.get("end_time"), closed=True,
    )
    view = build_poll_view(answers, vote_counts, show_votes=True, closed=True)
    try:
        await msg.edit(embed=embed, view=view)
    except (discord.Forbidden, discord.HTTPException):
        pass


# ── Vote handler ───────────────────────────────────────────────────────────────

async def _handle_vote(interaction: discord.Interaction, answer_idx: int) -> None:
    if interaction.guild is None or interaction.message is None:
        return

    msg_id = str(interaction.message.id)
    polls: dict = dict(datasys.load_data(interaction.guild.id, "polls"))
    entry = polls.get(msg_id)
    if not entry:
        await interaction.response.send_message("Poll not found.", ephemeral=True)
        return

    if entry.get("closed") or (entry.get("end_time") and time.time() > entry["end_time"]):
        await interaction.response.send_message("This poll is closed.", ephemeral=True)
        return

    answers: list[str] = entry["answers"]
    if answer_idx >= len(answers):
        await interaction.response.send_message("Invalid answer.", ephemeral=True)
        return

    show_votes: bool = entry.get("show_votes", True)
    user_votes: dict = entry.get("user_votes", {})
    uid = str(interaction.user.id)
    prev = user_votes.get(uid)

    if prev == answer_idx:
        del user_votes[uid]
        msg = "Vote removed."
    else:
        user_votes[uid] = answer_idx
        msg = f"Switched to **{answers[answer_idx]}**!" if prev is not None else f"Voted for **{answers[answer_idx]}**!"

    entry["user_votes"] = user_votes
    polls[msg_id] = entry
    datasys.save_data(interaction.guild.id, "polls", polls)

    vote_counts = [0] * len(answers)
    for v in user_votes.values():
        if 0 <= v < len(answers):
            vote_counts[v] += 1

    new_embed = _make_poll_embed(
        entry["question"], answers, vote_counts, show_votes,
        entry.get("image_url"), entry.get("end_time"),
    )
    new_view = build_poll_view(answers, vote_counts, show_votes)
    await interaction.response.edit_message(embed=new_embed, view=new_view)
    await interaction.followup.send(msg, ephemeral=True)


# ── Close handler ──────────────────────────────────────────────────────────────

async def _handle_close(interaction: discord.Interaction) -> None:
    if interaction.guild is None or interaction.message is None:
        return

    if not isinstance(interaction.user, discord.Member):
        return
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message("No permission.", ephemeral=True)
        return

    msg_id = str(interaction.message.id)
    polls: dict = dict(datasys.load_data(interaction.guild.id, "polls"))
    entry = polls.get(msg_id)
    if not entry:
        await interaction.response.send_message("Poll not found.", ephemeral=True)
        return
    if entry.get("closed"):
        await interaction.response.send_message("Already closed.", ephemeral=True)
        return

    answers: list[str] = entry["answers"]
    user_votes: dict = entry.get("user_votes", {})
    vote_counts = [0] * len(answers)
    for v in user_votes.values():
        if 0 <= v < len(answers):
            vote_counts[v] += 1

    entry["closed"] = True
    polls[msg_id] = entry
    datasys.save_data(interaction.guild.id, "polls", polls)

    embed = _make_poll_embed(
        entry["question"], answers, vote_counts, show_votes=True,
        image_url=entry.get("image_url"), end_time=entry.get("end_time"), closed=True,
    )
    view = build_poll_view(answers, vote_counts, show_votes=True, closed=True)
    await interaction.response.edit_message(embed=embed, view=view)


# ── Persistent dynamic buttons ─────────────────────────────────────────────────

class PollButton(discord.ui.DynamicItem[discord.ui.Button], template=r"poll:vote:(?P<answer_idx>\d+)"):
    def __init__(self, answer_idx: int) -> None:
        super().__init__(
            discord.ui.Button(
                custom_id=f"poll:vote:{answer_idx}",
                style=discord.ButtonStyle.secondary,
            )
        )
        self.answer_idx = answer_idx

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ) -> "PollButton":
        return cls(int(match["answer_idx"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        await _handle_vote(interaction, self.answer_idx)


class PollCloseButton(discord.ui.DynamicItem[discord.ui.Button], template=r"poll:close"):
    def __init__(self) -> None:
        super().__init__(
            discord.ui.Button(
                label="Close Poll",
                style=discord.ButtonStyle.danger,
                custom_id="poll:close",
            )
        )

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ) -> "PollCloseButton":
        return cls()

    async def callback(self, interaction: discord.Interaction) -> None:
        await _handle_close(interaction)


# ── Background task ────────────────────────────────────────────────────────────

class PollTask:
    def __init__(self, bot: commands.AutoShardedBot):
        self.bot = bot

    @tasks.loop(seconds=30)
    async def check_polls(self):
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
                polls: dict = dict(datasys.load_data(guild_id, "polls"))
            except Exception:
                continue
            if not polls:
                continue
            for msg_id, entry in list(polls.items()):
                if entry.get("closed"):
                    continue
                end_time = entry.get("end_time")
                if end_time and now >= end_time:
                    try:
                        await _close_poll(self.bot, guild_id, msg_id, entry)
                    except Exception as e:
                        print(f"[Poll] Error closing {msg_id}: {e}")


# ── Command ────────────────────────────────────────────────────────────────────

def poll_commands(bot: commands.AutoShardedBot) -> None:

    @bot.tree.command(name="poll", description="Create a poll with up to 10 answer options")
    @app_commands.describe(
        question="The poll question",
        answer1="First answer (required)",
        answer2="Second answer (required)",
        show_votes="Show vote counts on buttons and in embed",
        duration="Optional duration (e.g. 1h, 30m, 2d) — auto-closes after",
        answer3="Third answer",
        answer4="Fourth answer",
        answer5="Fifth answer",
        answer6="Sixth answer",
        answer7="Seventh answer",
        answer8="Eighth answer",
        answer9="Ninth answer",
        answer10="Tenth answer",
        image="Optional image to display in the poll",
    )
    @app_commands.guild_only()
    async def poll_cmd(
        interaction: discord.Interaction,
        question: str,
        answer1: str,
        answer2: str,
        show_votes: bool,
        duration: Optional[str] = None,
        answer3: Optional[str] = None,
        answer4: Optional[str] = None,
        answer5: Optional[str] = None,
        answer6: Optional[str] = None,
        answer7: Optional[str] = None,
        answer8: Optional[str] = None,
        answer9: Optional[str] = None,
        answer10: Optional[str] = None,
        image: Optional[discord.Attachment] = None,
    ):
        await interaction.response.defer(ephemeral=True)
        if interaction.guild is None:
            return

        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.manage_guild:
            await interaction.edit_original_response(content="No permission.")
            return

        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.edit_original_response(content="This command can only be used in text channels.")
            return

        answers = [
            a for a in [answer1, answer2, answer3, answer4, answer5,
                        answer6, answer7, answer8, answer9, answer10]
            if a is not None
        ]

        end_time: Optional[float] = None
        if duration:
            td = datasys.parse_duration(duration)
            if td is None or td.total_seconds() < 60:
                await interaction.edit_original_response(content="Invalid duration. Use e.g. `1h`, `30m`, `2d`.")
                return
            end_time = time.time() + td.total_seconds()

        image_url: Optional[str] = None
        if image and image.content_type and image.content_type.startswith("image/"):
            image_url = image.url

        vote_counts = [0] * len(answers)
        embed = _make_poll_embed(question, answers, vote_counts, show_votes, image_url, end_time)
        view = build_poll_view(answers, vote_counts, show_votes)

        try:
            msg = await channel.send(embed=embed, view=view)
        except (discord.Forbidden, discord.HTTPException):
            await interaction.edit_original_response(content="Failed to send poll.")
            return

        polls: dict = dict(datasys.load_data(interaction.guild.id, "polls"))
        polls[str(msg.id)] = {
            "question": question,
            "answers": answers,
            "show_votes": show_votes,
            "image_url": image_url,
            "channel_id": str(channel.id),
            "end_time": end_time,
            "user_votes": {},
            "closed": False,
        }
        datasys.save_data(interaction.guild.id, "polls", polls)

        await interaction.edit_original_response(content=f"Poll created in {channel.mention}!")

