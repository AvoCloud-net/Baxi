import io
import os

import discord
from discord.ext import commands
from reds_simple_logger import Logger

import assets.data as datasys
import config.config as config

logger = Logger()

# Default font path (bundled with Pillow)
_DEFAULT_FONT_SIZE = 36
_CARD_WIDTH = 1024
_CARD_HEIGHT = 500


def _hex_to_color(hex_str: str, fallback: discord.Color = config.Discord.color) -> discord.Color:
    if hex_str and isinstance(hex_str, str) and len(hex_str) == 7:
        try:
            r, g, b = int(hex_str[1:3], 16), int(hex_str[3:5], 16), int(hex_str[5:7], 16)
            return discord.Color.from_rgb(r, g, b)
        except ValueError:
            pass
    return fallback


def _hex_to_rgb(hex_str: str, fallback: tuple = (26, 26, 46)) -> tuple:
    if hex_str and isinstance(hex_str, str) and len(hex_str) == 7:
        try:
            return int(hex_str[1:3], 16), int(hex_str[3:5], 16), int(hex_str[5:7], 16)
        except ValueError:
            pass
    return fallback


async def _generate_welcome_card(member: discord.Member, welcomer_config: dict) -> discord.File:
    from PIL import Image, ImageDraw, ImageFont

    guild_id = member.guild.id
    card_color = _hex_to_rgb(welcomer_config.get("card_color", "#1a1a2e"))

    # Load background
    bg_path = f"data/{guild_id}/welcomer_bg.png"
    if welcomer_config.get("has_custom_bg", False) and os.path.exists(bg_path):
        bg = Image.open(bg_path).convert("RGB")
        bg = bg.resize((_CARD_WIDTH, _CARD_HEIGHT), Image.LANCZOS)
    else:
        # Default gradient background
        bg = Image.new("RGB", (_CARD_WIDTH, _CARD_HEIGHT), card_color)
        draw_bg = ImageDraw.Draw(bg)
        for y in range(_CARD_HEIGHT):
            ratio = y / _CARD_HEIGHT
            r = int(card_color[0] * (1 - ratio * 0.3))
            g = int(card_color[1] * (1 - ratio * 0.3))
            b = int(card_color[2] * (1 - ratio * 0.2))
            draw_bg.line([(0, y), (_CARD_WIDTH, y)], fill=(r, g, b))

    draw = ImageDraw.Draw(bg)

    # Semi-transparent overlay for text readability (on custom backgrounds)
    if welcomer_config.get("has_custom_bg", False):
        overlay = Image.new("RGBA", (_CARD_WIDTH, _CARD_HEIGHT), (*card_color, 140))
        bg = bg.convert("RGBA")
        bg = Image.alpha_composite(bg, overlay)
        draw = ImageDraw.Draw(bg)

    # Load avatar
    avatar_size = 128
    avatar_x = (_CARD_WIDTH - avatar_size) // 2
    avatar_y = 60

    if member.avatar:
        try:
            avatar_bytes = await member.avatar.read()
            avatar_img = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
            avatar_img = avatar_img.resize((avatar_size, avatar_size), Image.LANCZOS)

            # Circular mask
            mask = Image.new("L", (avatar_size, avatar_size), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.ellipse((0, 0, avatar_size, avatar_size), fill=255)

            bg.paste(avatar_img, (avatar_x, avatar_y), mask)
        except Exception as e:
            logger.error(f"Welcome card avatar error: {e}")

    # Draw circle border around avatar area
    draw.ellipse(
        (avatar_x - 3, avatar_y - 3, avatar_x + avatar_size + 3, avatar_y + avatar_size + 3),
        outline=(255, 255, 255, 200) if bg.mode == "RGBA" else (255, 255, 255),
        width=3,
    )

    # Text
    try:
        font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 42)
        font_medium = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18)
    except OSError:
        font_large = ImageFont.load_default()
        font_medium = ImageFont.load_default()
        font_small = ImageFont.load_default()

    text_color = (255, 255, 255)

    # Welcome text
    welcome_text = f"Welcome, {member.display_name}!"
    bbox = draw.textbbox((0, 0), welcome_text, font=font_large)
    text_w = bbox[2] - bbox[0]
    draw.text(((_CARD_WIDTH - text_w) // 2, avatar_y + avatar_size + 30), welcome_text, fill=text_color, font=font_large)

    # Server name
    server_text = member.guild.name
    bbox = draw.textbbox((0, 0), server_text, font=font_medium)
    text_w = bbox[2] - bbox[0]
    draw.text(((_CARD_WIDTH - text_w) // 2, avatar_y + avatar_size + 90), server_text, fill=(*text_color[:2], 200) if bg.mode == "RGBA" else text_color, font=font_medium)

    # Member count
    count_text = f"Member #{member.guild.member_count}"
    bbox = draw.textbbox((0, 0), count_text, font=font_small)
    text_w = bbox[2] - bbox[0]
    draw.text(((_CARD_WIDTH - text_w) // 2, _CARD_HEIGHT - 50), count_text, fill=(*text_color[:2], 180) if bg.mode == "RGBA" else (200, 200, 200), font=font_small)

    # Save to buffer
    buf = io.BytesIO()
    bg.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return discord.File(buf, filename="welcome.png")


async def on_member_join(member: discord.Member, bot: commands.AutoShardedBot):
    try:
        logger.info(f"Welcomer: on_member_join triggered for {member.name} in {member.guild.name}")
        welcomer_config: dict = dict(datasys.load_data(member.guild.id, "welcomer"))
        logger.info(f"Welcomer config: {welcomer_config}")
        if not welcomer_config.get("enabled", False):
            logger.info("Welcomer: disabled, returning")
            return

        channel_id = int(welcomer_config.get("channel", 0))
        if channel_id == 0:
            logger.info("Welcomer: channel_id is 0, returning")
            return

        channel = member.guild.get_channel(channel_id)
        if channel is None or not isinstance(channel, discord.TextChannel):
            logger.info(f"Welcomer: channel {channel_id} not found or not TextChannel, returning")
            return

        lang = datasys.load_lang_file(member.guild.id)
        message_template = str(welcomer_config.get(
            "message",
            lang["systems"]["welcomer"]["default_welcome"]
        ))

        text = _format_message(message_template, member)

        embed_color = _hex_to_color(welcomer_config.get("color", ""), config.Discord.color)

        embed = discord.Embed(
            title=lang["systems"]["welcomer"]["title"],
            description=text,
            color=embed_color,
        )

        if member.avatar:
            embed.set_thumbnail(url=member.avatar.url)

        embed.set_footer(text=f"Member #{member.guild.member_count}")

        # Generate welcome card if enabled
        image_mode = welcomer_config.get("image_mode", "none")
        file = None
        if image_mode == "generate":
            try:
                file = await _generate_welcome_card(member, welcomer_config)
                embed.set_image(url="attachment://welcome.png")
            except Exception as e:
                logger.error(f"Welcome card generation error: {e}")

        await channel.send(embed=embed, file=file)

    except Exception as e:
        logger.error(f"Welcomer join error: {e}")


async def on_member_remove(member: discord.Member, bot: commands.AutoShardedBot):
    try:
        welcomer_config: dict = dict(datasys.load_data(member.guild.id, "welcomer"))
        if not welcomer_config.get("leave_enabled", False):
            return

        channel_id = int(welcomer_config.get("leave_channel", 0))
        if channel_id == 0:
            return

        channel = member.guild.get_channel(channel_id)
        if channel is None or not isinstance(channel, discord.TextChannel):
            return

        lang = datasys.load_lang_file(member.guild.id)
        message_template = str(welcomer_config.get(
            "leave_message",
            lang["systems"]["welcomer"]["default_leave"]
        ))

        text = _format_message(message_template, member)

        leave_color = _hex_to_color(welcomer_config.get("leave_color", ""), config.Discord.warn_color)

        embed = discord.Embed(
            description=text,
            color=leave_color,
        )

        if member.avatar:
            embed.set_thumbnail(url=member.avatar.url)

        await channel.send(embed=embed)

    except Exception as e:
        logger.error(f"Welcomer leave error: {e}")


def _format_message(template: str, member: discord.Member) -> str:
    return template.format(
        user=member.mention,
        username=member.name,
        displayname=member.display_name,
        server=member.guild.name,
        membercount=member.guild.member_count,
    )
