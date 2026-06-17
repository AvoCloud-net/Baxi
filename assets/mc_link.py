import aiohttp
import asyncio
import secrets as _secrets
import time
from reds_simple_logger import Logger

from assets.repo.standalone import load_mc_links as _standalone_load, save_mc_links as _standalone_save

logger = Logger()

_links: dict = {}  # guild_id_str → {discord_id: {uuid, name, linked_at}}
_loaded: bool = False  # True once _links was loaded from the DB without error

_lock = asyncio.Lock()

_LINK_SESSION_TTL = 600  # 10 min
# token → {guild_id, discord_id, discord_name, discord_avatar_url,
#          uuid, mc_name, api_url, api_secret, kind, expires_at}
# kind: "new" | "already_linked"  (1:1 default — one MC account per Discord)
_link_sessions: dict[str, dict] = {}


def create_link_session(payload: dict) -> str:
    token = _secrets.token_urlsafe(24)
    payload["expires_at"] = time.time() + _LINK_SESSION_TTL
    _link_sessions[token] = payload
    return token


def get_link_session(token: str) -> dict | None:
    sess = _link_sessions.get(token)
    if not sess:
        return None
    if sess["expires_at"] < time.time():
        _link_sessions.pop(token, None)
        return None
    return sess


def consume_link_session(token: str) -> dict | None:
    return _link_sessions.pop(token, None)


def cleanup_link_sessions():
    now = time.time()
    for tok in [t for t, s in _link_sessions.items() if s["expires_at"] < now]:
        _link_sessions.pop(tok, None)


def _load():
    global _links, _loaded
    try:
        _links = _standalone_load()
        _loaded = True
    except Exception as e:
        # Leave _loaded False: store_link/sync persist via _save(), which does a
        # full-table rewrite. Persisting an empty/partial _links that came from a
        # failed load would WIPE every guild's links. Guard against that.
        logger.error(f"[mc_link] Failed to load links: {e}")
        _links = {}


def _save():
    if not _loaded:
        logger.error("[mc_link] Refusing to save: links were never loaded "
                     "(a full-table rewrite now would wipe all links).")
        return
    try:
        _standalone_save(_links)
    except Exception as e:
        logger.error(f"[mc_link] Failed to save links: {e}")


_load()
# Retry the load lazily on first use if the import-time attempt hit an uninitialized
# DB — without this, one early failure left _links empty for the whole process.
def ensure_loaded() -> None:
    if not _loaded:
        _load()


def is_linked(guild_id: int, discord_id: int) -> bool:
    ensure_loaded()
    return str(discord_id) in _links.get(str(guild_id), {})


def get_link(guild_id: int, discord_id: int) -> dict | None:
    ensure_loaded()
    return _links.get(str(guild_id), {}).get(str(discord_id))


async def resolve_token(api_url: str, secret: str, token: str) -> dict | None:
    """GET /dg/token/{token} → {uuid, name} or None."""
    url = f"{api_url.rstrip('/')}/dg/token/{token.upper()}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers={"Authorization": f"Bearer {secret}"}, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    return await resp.json()
                return None
    except Exception as e:
        logger.error(f"[mc_link] resolve_token failed: {e}")
        return None


async def fetch_online_players(api_url: str, secret: str) -> tuple[dict | None, str | None]:
    """GET /dg/players → (data, None) on success, (None, error) on failure.

    error: "outdated" if plugin lacks the endpoint (404), else "unreachable".
    """
    url = f"{api_url.rstrip('/')}/dg/players"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers={"Authorization": f"Bearer {secret}"}, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    return await resp.json(), None
                if resp.status == 404:
                    return None, "outdated"
                return None, "unreachable"
    except Exception as e:
        logger.error(f"[mc_link] fetch_online_players failed: {e}")
        return None, "unreachable"


async def fetch_all_links(api_url: str, secret: str) -> list[dict] | None:
    """GET /dg/links → list of {uuid, name, discord_id, discord_name, linked_at}.

    Returns None on any failure (unreachable, 404 on old plugins, bad JSON) so the
    caller can treat "couldn't fetch" distinctly from "server has zero links" and
    never reconcile-delete on a transient error.
    """
    url = f"{api_url.rstrip('/')}/dg/links"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers={"Authorization": f"Bearer {secret}"}, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
        links = data.get("links") if isinstance(data, dict) else None
        return links if isinstance(links, list) else None
    except Exception as e:
        logger.error(f"[mc_link] fetch_all_links failed: {e}")
        return None


async def sync_guild_from_server(guild_id: int, api_url: str, secret: str) -> dict | None:
    """Mirror one guild's link list from its DiscordGate server (server wins).

    Adds links the server has, updates changed ones, removes links the server no
    longer has. Bedrock fields Baxi tracks (which the server doesn't) are preserved.

    Returns stats {added, updated, removed, total} on success, or None when skipped
    — fetch failed, or the server returned zero links while Baxi holds some (guard
    against wiping the whole guild on a glitchy/empty response).
    """
    if not api_url.strip() or not secret.strip():
        return None
    links = await fetch_all_links(api_url.strip(), secret.strip())
    if links is None:
        return None  # fetch failed → no changes

    server_map: dict[str, dict] = {}
    for item in links:
        if not isinstance(item, dict):
            continue
        did = str(item.get("discord_id") or "").strip()
        uuid = str(item.get("uuid") or "").strip()
        if not did or not uuid:
            continue
        server_map[did] = {  # last entry wins on a duplicate discord_id
            "uuid": uuid,
            "name": str(item.get("name") or ""),
            "linked_at": int(item.get("linked_at") or 0),
        }

    async with _lock:
        if not _loaded:
            logger.error(f"[mc_link] sync guild {guild_id}: local links never loaded — skipping (guard).")
            return None
        gid = str(guild_id)
        current = _links.get(gid, {})
        if not server_map and current:
            logger.error(f"[mc_link] sync guild {gid}: server returned 0 links but "
                         f"{len(current)} exist locally — skipping (guard).")
            return None

        added = updated = 0
        new_map: dict[str, dict] = {}
        for did, entry in server_map.items():
            old = current.get(did)
            if old:
                # keep Baxi-only bedrock link the server doesn't know about
                if old.get("bedrock_uuid"):
                    entry["bedrock_uuid"] = old["bedrock_uuid"]
                if old.get("bedrock_name"):
                    entry["bedrock_name"] = old["bedrock_name"]
                if old.get("uuid") != entry["uuid"] or old.get("name") != entry["name"]:
                    updated += 1
            else:
                added += 1
            new_map[did] = entry
        removed = sum(1 for did in current if did not in server_map)

        if not (added or updated or removed):
            return {"added": 0, "updated": 0, "removed": 0, "total": len(new_map)}

        _links[gid] = new_map
        _save()
    return {"added": added, "updated": updated, "removed": removed, "total": len(new_map)}


async def whitelist_player(api_url: str, secret: str, uuid: str, name: str, discord_id: int, discord_name: str = "") -> tuple[bool, str | None]:
    """POST /dg/whitelist → (ok, error).

    error: None on success; "already_linked" when the MC plugin refuses because the
    Discord account already links a different MC account (409, the 1:1 default);
    "unreachable" on any other failure.
    """
    url = f"{api_url.rstrip('/')}/dg/whitelist"
    payload = {"uuid": uuid, "name": name, "discord_id": str(discord_id), "discord_name": discord_name}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers={"Authorization": f"Bearer {secret}"}, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    return True, None
                if resp.status == 409:
                    return False, "already_linked"
                return False, "unreachable"
    except Exception as e:
        logger.error(f"[mc_link] whitelist_player failed: {e}")
        return False, "unreachable"


async def unlink_player(api_url: str, secret: str, uuid: str) -> bool:
    """POST /dg/unlink → bool success. 404 = already unlinked on MC side, treat as OK."""
    url = f"{api_url.rstrip('/')}/dg/unlink"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json={"uuid": uuid}, headers={"Authorization": f"Bearer {secret}"}, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                return resp.status in (200, 404)
    except Exception as e:
        logger.error(f"[mc_link] unlink_player failed: {e}")
        return False


async def admin_link_player(api_url: str, secret: str, mc_name: str, discord_id: int, discord_name: str = "") -> dict | None:
    """POST /dg/admin-link → {success, uuid} or None on failure."""
    url = f"{api_url.rstrip('/')}/dg/admin-link"
    payload = {"mc_name": mc_name, "discord_id": str(discord_id), "discord_name": discord_name}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers={"Authorization": f"Bearer {secret}"}, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    return await resp.json()
                return None
    except Exception as e:
        logger.error(f"[mc_link] admin_link_player failed: {e}")
        return None


async def send_chat_in(api_url: str, secret: str, discord_id: int, discord_name: str, mc_name: str, content: str) -> bool:
    """POST /dg/chat-in → bool success. Relays a Discord message to MC players."""
    url = f"{api_url.rstrip('/')}/dg/chat-in"
    payload = {
        "discord_id": str(discord_id),
        "discord_name": discord_name,
        "mc_name": mc_name,
        "message": content,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers={"Authorization": f"Bearer {secret}"}, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                return resp.status == 200
    except Exception as e:
        logger.error(f"[mc_link] send_chat_in failed: {e}")
        return False


async def remove_link(guild_id: int, discord_id: int):
    async with _lock:
        gid = str(guild_id)
        if gid in _links:
            _links[gid].pop(str(discord_id), None)
        _save()


def is_bedrock_uuid(uuid: str) -> bool:
    return uuid.startswith("00000000-0000-0000")


async def store_link(guild_id: int, discord_id: int, uuid: str, name: str):
    import time
    async with _lock:
        gid = str(guild_id)
        if gid not in _links:
            _links[gid] = {}
        entry = {
            "uuid": uuid,
            "name": name,
            "linked_at": int(time.time()),
        }
        # Preserve a supported Bedrock secondary across a (re)link of the Java primary.
        prev = _links[gid].get(str(discord_id), {})
        if prev.get("bedrock_uuid"):
            entry["bedrock_uuid"] = prev["bedrock_uuid"]
        if prev.get("bedrock_name"):
            entry["bedrock_name"] = prev["bedrock_name"]
        _links[gid][str(discord_id)] = entry
        _save()


async def add_bedrock_link(guild_id: int, discord_id: int, bedrock_uuid: str, bedrock_name: str):
    async with _lock:
        gid = str(guild_id)
        entry = _links.get(gid, {}).get(str(discord_id))
        if entry is None:
            return
        entry["bedrock_uuid"] = bedrock_uuid
        entry["bedrock_name"] = bedrock_name
        _save()


async def _render_link_attachment(bot, guild_id: int, discord_id: int, mc_name: str, mc_uuid: str | None):
    """Render the avatar pair card. Returns (discord.File, embed_image_url) or (None, None)."""
    import discord as _discord
    from assets import mc_link_card
    try:
        user = bot.get_user(discord_id) or await bot.fetch_user(discord_id)
        if user is None or not mc_uuid:
            return None, None
        buf = await mc_link_card.render_confirm(
            discord_name=user.name,
            discord_avatar_url=str(user.display_avatar.url),
            mc_name=mc_name,
            mc_uuid=mc_uuid,
        )
        filename = "mc_link_card.png"
        return _discord.File(buf, filename=filename), f"attachment://{filename}"
    except Exception as e:
        logger.error(f"[mc_link] card render failed: {e}")
        return None, None


async def announce_link(bot, guild_id: int, discord_id: int, mc_name: str, guild_conf: dict, lang: dict):
    import discord as _discord
    import config.config as _cfg
    channel_id_str: str = guild_conf.get("announce_channel", "")
    if not channel_id_str:
        return
    try:
        guild = bot.get_guild(guild_id)
        if guild is None:
            return
        channel = guild.get_channel(int(channel_id_str))
        if channel is None:
            return
        t = lang["systems"]["mc_link"]
        link = get_link(guild_id, discord_id) or {}
        file, img_url = await _render_link_attachment(bot, guild_id, discord_id, mc_name, link.get("uuid"))
        embed = _discord.Embed(
            description=t["announce"].format(mention=f"<@{discord_id}>", mc_name=mc_name),
            color=_cfg.Discord.success_color,
        )
        embed.set_footer(text=t["footer"])
        if img_url:
            embed.set_image(url=img_url)
            await channel.send(embed=embed, file=file)
        else:
            await channel.send(embed=embed)
    except Exception as e:
        logger.error(f"[mc_link] announce_link failed: {e}")


async def dm_user(bot, guild_id: int, discord_id: int, mc_name: str, guild_conf: dict, lang: dict):
    import discord as _discord
    import config.config as _cfg
    if not guild_conf.get("dm_on_link", False):
        return
    try:
        guild = bot.get_guild(guild_id)
        guild_name = guild.name if guild else "Unknown server"
        user = bot.get_user(discord_id) or await bot.fetch_user(discord_id)
        if user is None:
            return
        t = lang["systems"]["mc_link"]
        link = get_link(guild_id, discord_id) or {}
        file, img_url = await _render_link_attachment(bot, guild_id, discord_id, mc_name, link.get("uuid"))
        embed = _discord.Embed(
            title=f"{_cfg.Icons.check} {t['success_title']}",
            description=t["dm_desc"].format(mc_name=mc_name, guild=guild_name),
            color=_cfg.Discord.success_color,
        )
        embed.set_footer(text=t["footer"])
        if img_url:
            embed.set_image(url=img_url)
            await user.send(embed=embed, file=file)
        else:
            await user.send(embed=embed)
    except Exception as e:
        logger.error(f"[mc_link] dm_user failed: {e}")
