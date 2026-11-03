"""Bayer 4x4 dither art for embeds (avocloud brand v5, BRANDING.md section 7).

Transparent animated GIFs (loop, ~6 fps), graphics only, rust tints only (never coral), square
crisp cells, one shape per command theme, a "!" for errors. They are served by the web app at
``/dither/<shape>.gif`` and ``install`` hooks ``discord.Embed.to_dict`` once, so EVERY embed
Baxi sends that has a title or fields and no thumbnail/image of its own gets its thumbnail
automatically; no call site has to know. The shape follows the running slash command (see
``COMMAND_THEMES``).

Always on: answers to slash commands, red (danger) embeds ("!"), and ``Sticky`` embeds
(moderation, honeypot). Everything else (tickets, suggestions, welcomer, ...) follows the
server setting ``dither`` (General in the dashboard, default on).
"""
import io
import math

import contextvars
import functools
import time
import zlib

import discord
from PIL import Image

import config.config as config

_BAYER = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5]
_B = [(v + 0.5) / 16 for v in _BAYER]
_LIGHT = (0x7A, 0x45, 0x34, 255)   # --avo-dither
_DARK = (0x5C, 0x32, 0x26, 255)    # second tint, for the thin edge of a shape
_CELL = {"thumb": 8, "banner": 4}   # Discord shows a thumbnail at ~80 px: cells must stay >= 2 px there
_SIZES = {"thumb": (256, 256), "banner": (640, 192)}

SHAPES = ("orb", "swirl", "arc", "wave", "dots", "ripple", "alert", "bars", "diamond", "check", "shield")
# calm shapes picked (by title) for embeds that have no command of their own, for variety
_POOL = ("orb", "swirl", "ripple", "dots", "diamond", "wave")

# slash command (root name) -> shape; anything not listed falls back to the pool
COMMAND_THEMES = {
    **dict.fromkeys(("ban", "kick", "mute", "unmute", "unban", "clear"), "shield"),
    **dict.fromkeys(("warn", "unwarn", "warnings", "report"), "arc"),
    **dict.fromkeys(("case", "note", "starboard"), "diamond"),
    **dict.fromkeys(("insights", "leaderboard", "poll", "pollstatus", "music"), "bars"),
    **dict.fromkeys(("rank", "pulse", "quote", "onewordstory"), "wave"),
    **dict.fromkeys(("wrapped", "giveaway", "help"), "swirl"),
    **dict.fromkeys(("birthday", "vote"), "ripple"),
    **dict.fromkeys(("invites", "mc", "dashboard"), "dots"),
    **dict.fromkeys(("owner", "capsule"), "orb"),
}
_theme = contextvars.ContextVar("dither_theme", default=None)   # shape of the running command
_in_command = contextvars.ContextVar("dither_in_command", default=False)
_guild = contextvars.ContextVar("dither_guild", default=None)   # guild the embed is going to
_enabled: dict[int, tuple[bool, float]] = {}
_TTL = 60.0


class Sticky(discord.Embed):
    """An embed that always carries its dither, whatever the server setting says."""


def invalidate(guild_id: int) -> None:
    _enabled.pop(int(guild_id), None)


def _guild_enabled(gid) -> bool:
    if not gid:
        return True
    gid = int(gid)
    hit = _enabled.get(gid)
    if hit is not None and time.monotonic() - hit[1] < _TTL:
        return hit[0]
    try:
        from assets import repo
        on = repo.load_misc(gid, "dither") is not False
    except Exception:
        on = True
    _enabled[gid] = (on, time.monotonic())
    return on


def _seg(px, py, ax, ay, bx, by) -> float:
    """Distance from a point to the segment a-b."""
    dx, dy = bx - ax, by - ay
    k = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - ax - k * dx, py - ay - k * dy)


def _field(shape: str, x: float, y: float, w: float, h: float, t: float) -> float:
    """0..1 value at cell (x, y) for phase t (0..tau, loops). Off the shape it is exactly 0."""
    if shape == "wave":
        u = x / w * math.tau
        base = 0.5 + math.sin(u * 1.5 + t) * 0.17 + math.sin(u * 3 + 1.2 - t) * 0.05
        return max(0.0, 1 - abs(y / h - base) * 4.5)
    cx, cy, r = w * 0.5, h * 0.5, min(w, h) * 0.46
    u = r / 29.4   # shape constants below were tuned on a 64-cell canvas; u rescales them
    d = math.hypot(x - cx, y - cy)
    if shape == "alert":    # "!": solid inside, a halo that breathes outside
        top, bot, dot = cy - r * 0.62, cy + r * 0.12, cy + r * 0.62
        k = min(1.0, max(0.0, (y - top) / (bot - top)))
        sd_bar = math.hypot(x - cx, y - min(max(y, top), bot)) - (r * 0.2 - k * r * 0.05)
        sd = min(sd_bar, math.hypot(x - cx, y - dot) - r * 0.18)
        return max(0.0, min(0.9, 0.55 - sd / (r * 0.4 + math.sin(t) * r * 0.04)))
    if shape == "check":    # a check mark, halo breathes like the "!"
        sd = min(_seg(x, y, cx - r * 0.5, cy + r * 0.02, cx - r * 0.12, cy + r * 0.4),
                 _seg(x, y, cx - r * 0.12, cy + r * 0.4, cx + r * 0.55, cy - r * 0.38)) - r * 0.13
        return max(0.0, min(0.9, 0.55 - sd / (r * 0.4 + math.sin(t) * r * 0.04)))
    if shape == "bars":     # five equaliser bars
        bw, gap = r * 0.27, r * 0.1
        left = cx - (5 * bw + 4 * gap) / 2
        i = int((x - left) // (bw + gap))
        if not 0 <= i < 5 or (x - left) - i * (bw + gap) >= bw:
            return 0.0
        base = cy + r * 0.8
        top = base - r * 1.55 * (0.62 + 0.3 * math.sin(t + i * 1.3)) * (0.85 + 0.15 * math.sin(i * 2.1 + 1))
        return 0.3 + 0.65 * (1 - (y - top) / (base - top)) if top <= y <= base else 0.0
    if shape == "diamond":  # rhombus, rings pulse inside it
        m = (abs(x - cx) + abs(y - cy)) / (r * 0.95)
        return 0.0 if m >= 1 else min(1.0, (1 - m) ** 0.6 * 1.25) * (0.7 + 0.3 * math.cos(m * 7 - t))
    if shape == "shield":   # flat top, pointed bottom, a light band sweeps over it
        top, mid, bot = cy - r * 0.75, cy + r * 0.05, cy + r * 0.85
        hw = r * 0.62 if y <= mid else r * 0.62 * (1 - (y - mid) / (bot - mid))
        if not top <= y <= bot or abs(x - cx) >= hw:
            return 0.0
        edge = min(1.0, (hw - abs(x - cx)) / (r * 0.3))
        return edge * (0.4 + 0.5 * max(0.0, math.cos((x + y) / u * 0.1 - t)))
    if shape == "arc":      # ring, the fade sweeps around it
        v = 1 - abs(d - r * 0.78) / (r * 0.34)
        a = math.atan2(y - cy, x - cx)
        return max(0.0, v) * (0.55 + 0.45 * math.cos(a - t))
    if d >= r:
        return 0.0
    if shape == "ripple":   # rings travel outwards
        return (1 - d / r) * (0.45 + 0.55 * (0.5 + 0.5 * math.cos(d / u * 0.9 - t)))
    if shape == "dots":     # the lattice drifts one period (8 cells) per loop
        gx, gy = ((x / u + t / math.tau * 8) % 8) - 4, ((y / u) % 8) - 4
        return (1 - (d / r) ** 2) * max(0.0, 1 - math.hypot(gx, gy) / 3.8) * 1.5
    if shape == "swirl":    # arms rotate
        a = math.atan2(y - cy, x - cx)
        arm = 0.5 + 0.5 * math.cos(3 * a + d / u * 0.35 - t)
        return (1 - d / r) * (0.25 + 0.75 * arm) * 1.3
    # orb: the light drifts a little around the upper left, the sphere itself stays put
    lx, ly = x - (cx - r * 0.25 + math.cos(t) * r * 0.08), y - (cy - r * 0.25 + math.sin(t) * r * 0.08)
    return max(0.0, 1 - math.hypot(lx, ly) / (r * 1.5))


_FRAMES = 24
_FRAME_MS = 170   # ~6 fps, 4 s loop: slow drift (BRANDING.md section 7)


def _render(shape: str, form: str) -> bytes:
    px_w, px_h = _SIZES[form]
    cell = _CELL[form]
    w, h = px_w // cell, px_h // cell
    palette = [0, 0, 0, *_LIGHT[:3], *_DARK[:3]] + [0] * (256 - 3) * 3   # 0 = transparent
    frames = []
    for i in range(_FRAMES):
        t = i / _FRAMES * math.tau
        img = Image.new("P", (w, h), 0)
        pix = img.load()
        for y in range(h):
            for x in range(w):
                v = _field(shape, x, y, w, h, t)
                if v > _B[(y & 3) * 4 + (x & 3)]:
                    pix[x, y] = 1 if v > 0.38 else 2
        img.putpalette(palette)
        frames.append(img.resize((px_w, px_h), Image.NEAREST))   # never blurred
    buf = io.BytesIO()
    frames[0].save(buf, "GIF", save_all=True, append_images=frames[1:], loop=0,
                   duration=_FRAME_MS, transparency=0, disposal=2, optimize=False)
    return buf.getvalue()


_cache: dict[tuple[str, str], bytes] = {}


def png(shape: str = "orb", form: str = "thumb") -> bytes:
    key = (shape, form)
    if key not in _cache:
        _cache[key] = _render(shape, form)
    return _cache[key]


def url(shape: str = "orb", form: str = "thumb") -> str:
    return f"https://{config.Web.url}/dither/{shape}{'' if form == 'thumb' else '_' + form}.gif"


def _shape_for(embed) -> str:
    """alert for danger, check for success, else the command's shape, else one picked by title."""
    c = embed.color.value if embed.color is not None else None
    if c == config.Discord.danger_color.value:
        return "alert"
    if c == config.Discord.success_color.value:
        return "check"
    cmd = _theme.get()
    if cmd:
        return cmd
    return _POOL[zlib.crc32(str(embed.title or "").encode()) % len(_POOL)]


def _scoped(cls, name: str, guild_of) -> None:
    """Wrap an async send/edit so embeds serialised inside it know their guild."""
    orig = getattr(cls, name)

    @functools.wraps(orig)
    async def wrapper(self, *args, **kwargs):
        token = _guild.set(guild_of(self))
        try:
            return await orig(self, *args, **kwargs)
        finally:
            _guild.reset(token)

    setattr(cls, name, wrapper)


def install(bot, web) -> None:
    """Serve the GIFs, follow the running command, and decorate every embed."""
    from quart import Response, abort

    @web.route("/dither/<name>.gif")
    async def _dither_gif(name: str):
        shape, _, form = name.partition("_")
        form = form or "thumb"
        if shape not in SHAPES or form not in _SIZES:
            abort(404)
        return Response(png(shape, form), mimetype="image/gif",
                        headers={"Cache-Control": "public, max-age=604800"})

    prev_check = bot.tree.interaction_check

    async def _check(interaction: discord.Interaction) -> bool:
        cmd = interaction.command
        root = getattr(cmd, "root_parent", None) or cmd
        _theme.set(COMMAND_THEMES.get(getattr(root, "name", "")))
        _in_command.set(True)
        return await prev_check(interaction)

    bot.tree.interaction_check = _check

    # Which guild is an embed going to? Channel/member sends know it; interaction replies
    # get it from the interaction, which is created in the gateway task that spawns the
    # view/command tasks (they copy the context). A stale value can only flip a cosmetic.
    _scoped(discord.abc.Messageable, "send", lambda self: getattr(getattr(self, "guild", None), "id", None))
    _scoped(discord.Message, "edit", lambda self: getattr(self.guild, "id", None))
    _scoped(discord.InteractionResponse, "send_message", lambda self: self._parent.guild_id)
    _scoped(discord.InteractionResponse, "edit_message", lambda self: self._parent.guild_id)
    _scoped(discord.Interaction, "edit_original_response", lambda self: self.guild_id)
    orig_init = discord.Interaction.__init__

    @functools.wraps(orig_init)
    def init(self, *args, **kwargs):
        orig_init(self, *args, **kwargs)
        _guild.set(self.guild_id)

    discord.Interaction.__init__ = init

    orig = discord.Embed.to_dict

    def to_dict(self):
        d = orig(self)
        if "thumbnail" in d or "image" in d or not (d.get("title") or d.get("fields")):
            return d
        shape = _shape_for(self)
        if shape == "alert" or isinstance(self, Sticky) or _in_command.get() or _guild_enabled(_guild.get()):
            d["thumbnail"] = {"url": url(shape)}
        return d

    discord.Embed.to_dict = to_dict
