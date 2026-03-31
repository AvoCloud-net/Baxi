import asyncio
import random
import discord
from discord.ext import commands
import assets.data as datasys
import config.config as cfg
from reds_simple_logger import Logger

logger = Logger()

# (flag_emoji, canonical_name, accepted_answers_lowercase)
FLAGS: list[tuple[str, str, list[str]]] = [
    # Europe
    ("🇩🇪", "Germany",              ["germany", "deutschland"]),
    ("🇫🇷", "France",               ["france", "frankreich"]),
    ("🇬🇧", "United Kingdom",       ["united kingdom", "uk", "great britain", "britain", "england"]),
    ("🇮🇹", "Italy",                ["italy", "italien"]),
    ("🇪🇸", "Spain",                ["spain", "spanien"]),
    ("🇵🇹", "Portugal",             ["portugal"]),
    ("🇳🇱", "Netherlands",          ["netherlands", "holland", "niederlande"]),
    ("🇧🇪", "Belgium",              ["belgium", "belgien"]),
    ("🇨🇭", "Switzerland",          ["switzerland", "schweiz"]),
    ("🇦🇹", "Austria",              ["austria", "österreich", "oesterreich"]),
    ("🇸🇪", "Sweden",               ["sweden", "schweden"]),
    ("🇳🇴", "Norway",               ["norway", "norwegen"]),
    ("🇩🇰", "Denmark",              ["denmark", "dänemark", "daenemark"]),
    ("🇫🇮", "Finland",              ["finland", "finnland"]),
    ("🇵🇱", "Poland",               ["poland", "polen"]),
    ("🇨🇿", "Czech Republic",       ["czech republic", "czechia", "tschechien"]),
    ("🇸🇰", "Slovakia",             ["slovakia", "slowakei"]),
    ("🇭🇺", "Hungary",              ["hungary", "ungarn"]),
    ("🇷🇴", "Romania",              ["romania", "rumänien", "rumaenien"]),
    ("🇧🇬", "Bulgaria",             ["bulgaria", "bulgarien"]),
    ("🇬🇷", "Greece",               ["greece", "griechenland"]),
    ("🇺🇦", "Ukraine",              ["ukraine"]),
    ("🇷🇸", "Serbia",               ["serbia", "serbien"]),
    ("🇭🇷", "Croatia",              ["croatia", "kroatien"]),
    ("🇸🇮", "Slovenia",             ["slovenia", "slowenien"]),
    ("🇧🇦", "Bosnia",               ["bosnia", "bosnien", "bosnia and herzegovina"]),
    ("🇦🇱", "Albania",              ["albania", "albanien"]),
    ("🇲🇰", "North Macedonia",      ["north macedonia", "nordmazedonien", "mazedonien"]),
    ("🇲🇪", "Montenegro",           ["montenegro"]),
    ("🇱🇹", "Lithuania",            ["lithuania", "litauen"]),
    ("🇱🇻", "Latvia",               ["latvia", "lettland"]),
    ("🇪🇪", "Estonia",              ["estonia", "estland"]),
    ("🇮🇪", "Ireland",              ["ireland", "irland"]),
    ("🇮🇸", "Iceland",              ["iceland", "island"]),
    ("🇲🇹", "Malta",                ["malta"]),
    ("🇨🇾", "Cyprus",               ["cyprus", "zypern"]),
    ("🇱🇺", "Luxembourg",           ["luxembourg", "luxemburg"]),
    ("🇱🇮", "Liechtenstein",        ["liechtenstein"]),
    ("🇲🇨", "Monaco",               ["monaco"]),
    ("🇸🇲", "San Marino",           ["san marino"]),
    ("🇻🇦", "Vatican City",         ["vatican city", "vatikanstadt", "vatikan"]),
    ("🇦🇩", "Andorra",              ["andorra"]),
    # Americas
    ("🇺🇸", "United States",        ["united states", "usa", "us", "america"]),
    ("🇨🇦", "Canada",               ["canada", "kanada"]),
    ("🇲🇽", "Mexico",               ["mexico", "mexiko"]),
    ("🇧🇷", "Brazil",               ["brazil", "brasilien", "brasil"]),
    ("🇦🇷", "Argentina",            ["argentina", "argentinien"]),
    ("🇨🇱", "Chile",                ["chile"]),
    ("🇨🇴", "Colombia",             ["colombia", "kolumbien"]),
    ("🇵🇪", "Peru",                 ["peru"]),
    ("🇻🇪", "Venezuela",            ["venezuela"]),
    ("🇧🇴", "Bolivia",              ["bolivia", "bolivien"]),
    ("🇵🇾", "Paraguay",             ["paraguay"]),
    ("🇺🇾", "Uruguay",              ["uruguay"]),
    ("🇪🇨", "Ecuador",              ["ecuador"]),
    ("🇨🇺", "Cuba",                 ["cuba", "kuba"]),
    ("🇯🇲", "Jamaica",              ["jamaica", "jamaika"]),
    ("🇩🇴", "Dominican Republic",   ["dominican republic", "dominikanische republik"]),
    ("🇵🇦", "Panama",               ["panama"]),
    ("🇨🇷", "Costa Rica",           ["costa rica"]),
    ("🇬🇹", "Guatemala",            ["guatemala"]),
    ("🇭🇳", "Honduras",             ["honduras"]),
    ("🇳🇮", "Nicaragua",            ["nicaragua"]),
    # Asia
    ("🇷🇺", "Russia",               ["russia", "russland"]),
    ("🇨🇳", "China",                ["china"]),
    ("🇯🇵", "Japan",                ["japan"]),
    ("🇰🇷", "South Korea",          ["south korea", "südkorea", "suedkorea", "korea"]),
    ("🇮🇳", "India",                ["india", "indien"]),
    ("🇵🇰", "Pakistan",             ["pakistan"]),
    ("🇧🇩", "Bangladesh",           ["bangladesh"]),
    ("🇮🇩", "Indonesia",            ["indonesia", "indonesien"]),
    ("🇲🇾", "Malaysia",             ["malaysia"]),
    ("🇵🇭", "Philippines",          ["philippines", "philippinen"]),
    ("🇸🇬", "Singapore",            ["singapore", "singapur"]),
    ("🇹🇭", "Thailand",             ["thailand"]),
    ("🇻🇳", "Vietnam",              ["vietnam"]),
    ("🇲🇲", "Myanmar",              ["myanmar", "burma"]),
    ("🇰🇭", "Cambodia",             ["cambodia", "kambodscha"]),
    ("🇲🇳", "Mongolia",             ["mongolia", "mongolei"]),
    ("🇰🇿", "Kazakhstan",           ["kazakhstan", "kasachstan"]),
    ("🇺🇿", "Uzbekistan",           ["uzbekistan", "usbekistan"]),
    ("🇦🇫", "Afghanistan",          ["afghanistan"]),
    ("🇮🇷", "Iran",                 ["iran"]),
    ("🇮🇶", "Iraq",                 ["iraq", "irak"]),
    ("🇸🇾", "Syria",                ["syria", "syrien"]),
    ("🇱🇧", "Lebanon",              ["lebanon", "libanon"]),
    ("🇯🇴", "Jordan",               ["jordan", "jordanien"]),
    ("🇸🇦", "Saudi Arabia",         ["saudi arabia", "saudi-arabien"]),
    ("🇦🇪", "UAE",                  ["uae", "united arab emirates", "emirate", "vae"]),
    ("🇶🇦", "Qatar",                ["qatar", "katar"]),
    ("🇰🇼", "Kuwait",               ["kuwait"]),
    ("🇧🇭", "Bahrain",              ["bahrain"]),
    ("🇴🇲", "Oman",                 ["oman"]),
    ("🇾🇪", "Yemen",                ["yemen", "jemen"]),
    ("🇮🇱", "Israel",               ["israel"]),
    ("🇱🇰", "Sri Lanka",            ["sri lanka"]),
    ("🇳🇵", "Nepal",                ["nepal"]),
    # Africa
    ("🇿🇦", "South Africa",         ["south africa", "südafrika", "suedafrika"]),
    ("🇪🇬", "Egypt",                ["egypt", "ägypten", "aegypten"]),
    ("🇳🇬", "Nigeria",              ["nigeria"]),
    ("🇰🇪", "Kenya",                ["kenya"]),
    ("🇪🇹", "Ethiopia",             ["ethiopia", "äthiopien"]),
    ("🇬🇭", "Ghana",                ["ghana"]),
    ("🇸🇳", "Senegal",              ["senegal"]),
    ("🇹🇿", "Tanzania",             ["tanzania", "tansania"]),
    ("🇺🇬", "Uganda",               ["uganda"]),
    ("🇲🇦", "Morocco",              ["morocco", "marokko"]),
    ("🇩🇿", "Algeria",              ["algeria", "algerien"]),
    ("🇹🇳", "Tunisia",              ["tunisia", "tunesien"]),
    ("🇱🇾", "Libya",                ["libya", "libyen"]),
    ("🇸🇩", "Sudan",                ["sudan"]),
    ("🇦🇴", "Angola",               ["angola"]),
    ("🇨🇲", "Cameroon",             ["cameroon", "kamerun"]),
    ("🇿🇼", "Zimbabwe",             ["zimbabwe", "simbabwe"]),
    ("🇲🇿", "Mozambique",           ["mozambique", "mosambik"]),
    ("🇿🇲", "Zambia",               ["zambia", "sambia"]),
    # Oceania
    ("🇦🇺", "Australia",            ["australia", "australien"]),
    ("🇳🇿", "New Zealand",          ["new zealand", "neuseeland"]),
    ("🇫🇯", "Fiji",                 ["fiji"]),
    ("🇵🇬", "Papua New Guinea",     ["papua new guinea", "papua-neuguinea"]),
]

# Per-guild in-memory active question state
# guild_id -> {
#   "flag": str, "answer": str, "accepted": list[str],
#   "hint_sent": bool, "wrong_attempts": int
# }
_active: dict[int, dict] = {}


async def start_round(
    guild_id: int,
    channel: discord.TextChannel,
    bot: commands.AutoShardedBot,
) -> None:
    """Pick a random flag and post the question to the channel."""
    lang = datasys.load_lang_file(guild_id)
    t: dict = lang["games"]["flag_quiz"]

    flag_emoji, country, accepted = random.choice(FLAGS)

    state = {
        "flag": flag_emoji,
        "answer": country,
        "accepted": accepted,
        "hint_sent": False,
        "wrong_attempts": 0,
    }
    _active[guild_id] = state
    datasys.save_data(guild_id, "flag_quiz_active", state)

    embed = discord.Embed(
        title=t["title"],
        description=str(t["question"]).format(flag=flag_emoji),
        color=cfg.Discord.info_color,
    )
    embed.set_footer(text=t["question_footer"])
    await channel.send(embed=embed)


async def _send_hint(guild_id: int, channel: discord.TextChannel) -> None:
    """Send a hint for the currently active question."""
    if guild_id not in _active:
        return
    q = _active[guild_id]
    if q.get("hint_sent"):
        return
    q["hint_sent"] = True

    lang = datasys.load_lang_file(guild_id)
    t: dict = lang["games"]["flag_quiz"]

    answer = q["answer"]
    hint_chars = answer[0] + " " + "_ " * (len(answer) - 1)
    embed = discord.Embed(
        description=str(t["hint"]).format(
            hint=hint_chars.strip(),
            length=len(answer),
        ),
        color=cfg.Discord.warn_color,
    )
    embed.set_footer(text=t["footer"])
    try:
        await channel.send(embed=embed)
    except (discord.Forbidden, discord.HTTPException):
        pass


async def check_answer(
    message: discord.Message, bot: commands.AutoShardedBot
) -> bool:
    """
    Check if the message is a correct answer to the active quiz question.
    Returns True if the message was in the quiz channel (consumed), False otherwise.
    """
    if message.guild is None or message.author.bot:
        return False

    data: dict = dict(datasys.load_data(message.guild.id, "flag_quiz"))

    if not data.get("enabled", False):
        return False

    channel_raw = str(data.get("channel", "") or "")
    if not channel_raw or not channel_raw.isdigit():
        return False
    channel_id = int(channel_raw)
    if message.channel.id != channel_id:
        return False

    if message.guild.id not in _active:
        return True

    q = _active[message.guild.id]
    user_answer = message.content.strip().lower()

    if user_answer in [a.lower() for a in q["accepted"]]:
        # Correct answer
        del _active[message.guild.id]
        datasys.save_data(message.guild.id, "flag_quiz_active", {})

        lang = datasys.load_lang_file(message.guild.id)
        t: dict = lang["games"]["flag_quiz"]

        try:
            await message.add_reaction("🎉")
        except (discord.Forbidden, discord.HTTPException):
            pass

        if data.get("points_enabled", True):
            scores: dict = dict(data.get("scores", {}))
            uid = str(message.author.id)
            scores[uid] = int(scores.get(uid, 0)) + 1
            data["scores"] = scores
            datasys.save_data(message.guild.id, "flag_quiz", data)

        embed = discord.Embed(
            description=str(t["correct"]).format(
                user=message.author.display_name,
                country=q["answer"],
                flag=q["flag"],
            ),
            color=cfg.Discord.success_color,
        )
        embed.set_footer(text=t["footer"])
        await message.channel.send(embed=embed)

        next_delay = int(data.get("next_delay", 3))
        channel = message.channel
        if isinstance(channel, discord.TextChannel):
            asyncio.create_task(
                _next_round(message.guild.id, channel, bot, next_delay)
            )
    else:
        # Wrong answer — react and increment attempt counter, send hint if threshold reached
        try:
            await message.add_reaction("❌")
        except (discord.Forbidden, discord.HTTPException):
            pass

        hint_after = int(data.get("hint_after_attempts", 3))
        if hint_after > 0 and not q.get("hint_sent"):
            q["wrong_attempts"] = q.get("wrong_attempts", 0) + 1
            if q["wrong_attempts"] >= hint_after:
                channel = message.channel
                if isinstance(channel, discord.TextChannel):
                    await _send_hint(message.guild.id, channel)

    return True


async def _next_round(
    guild_id: int,
    channel: discord.TextChannel,
    bot: commands.AutoShardedBot,
    delay: int,
) -> None:
    await asyncio.sleep(delay)
    data: dict = dict(datasys.load_data(guild_id, "flag_quiz"))
    if data.get("enabled", False) and guild_id not in _active:
        await start_round(guild_id, channel, bot)


async def resume_all(bot: commands.AutoShardedBot) -> None:
    """Called once on bot ready — restores the saved active question or starts a new one."""
    for guild in bot.guilds:
        try:
            data: dict = dict(datasys.load_data(guild.id, "flag_quiz"))
            if not data.get("enabled", False):
                continue
            channel_raw = str(data.get("channel", "") or "")
            if not channel_raw or not channel_raw.isdigit():
                continue
            if guild.id in _active:
                continue

            # Try to restore the question that was active before the restart
            saved: dict = dict(datasys.load_data(guild.id, "flag_quiz_active"))
            if saved.get("flag") and saved.get("answer") and saved.get("accepted"):
                _active[guild.id] = {
                    "flag": saved["flag"],
                    "answer": saved["answer"],
                    "accepted": saved["accepted"],
                    "hint_sent": bool(saved.get("hint_sent", False)),
                    "wrong_attempts": int(saved.get("wrong_attempts", 0)),
                }
                logger.debug.info(f"[FlagQuiz] Restored active question for guild {guild.id}: {saved['answer']}")
            else:
                # No saved state — start a fresh round
                ch = guild.get_channel(int(channel_raw))
                if isinstance(ch, discord.TextChannel):
                    await start_round(guild.id, ch, bot)
        except Exception as e:
            logger.error(f"[FlagQuiz] resume_all failed for guild {guild.id}: {e}")


def get_leaderboard(
    guild_id: int, bot: commands.AutoShardedBot
) -> list[tuple[str, int]]:
    """Return sorted (display_name, points) list for the guild."""
    data: dict = dict(datasys.load_data(guild_id, "flag_quiz"))
    scores: dict = dict(data.get("scores", {}))
    guild = bot.get_guild(guild_id)
    result: list[tuple[str, int]] = []
    for uid_str, pts in scores.items():
        name = f"<@{uid_str}>"
        if guild:
            member = guild.get_member(int(uid_str))
            if member:
                name = member.display_name
        result.append((name, int(pts)))
    result.sort(key=lambda x: x[1], reverse=True)
    return result
