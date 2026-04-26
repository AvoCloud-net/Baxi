import aiohttp
import asyncio
import json
import os
from reds_simple_logger import Logger

logger = Logger()

_DATA_DIR = "data"
_LINKS_FILE = os.path.join(_DATA_DIR, "mc_links.json")

_links: dict = {}  # guild_id_str → {discord_id: {uuid, name, linked_at}}

_lock = asyncio.Lock()


def _load():
    global _links
    if not os.path.exists(_LINKS_FILE):
        _links = {}
        return
    try:
        with open(_LINKS_FILE, "r") as f:
            _links = json.load(f)
    except Exception as e:
        logger.error(f"[mc_link] Failed to load links: {e}")
        _links = {}


def _save():
    try:
        os.makedirs(_DATA_DIR, exist_ok=True)
        with open(_LINKS_FILE, "w") as f:
            json.dump(_links, f, indent=2)
    except Exception as e:
        logger.error(f"[mc_link] Failed to save links: {e}")


_load()


def is_linked(guild_id: int, discord_id: int) -> bool:
    return str(discord_id) in _links.get(str(guild_id), {})


def get_link(guild_id: int, discord_id: int) -> dict | None:
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


async def whitelist_player(api_url: str, secret: str, uuid: str, name: str, discord_id: int, discord_name: str = "") -> bool:
    """POST /dg/whitelist → bool success."""
    url = f"{api_url.rstrip('/')}/dg/whitelist"
    payload = {"uuid": uuid, "name": name, "discord_id": str(discord_id), "discord_name": discord_name}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers={"Authorization": f"Bearer {secret}"}, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                return resp.status == 200
    except Exception as e:
        logger.error(f"[mc_link] whitelist_player failed: {e}")
        return False


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


async def remove_link(guild_id: int, discord_id: int):
    async with _lock:
        gid = str(guild_id)
        if gid in _links:
            _links[gid].pop(str(discord_id), None)
        _save()


async def store_link(guild_id: int, discord_id: int, uuid: str, name: str):
    import time
    async with _lock:
        gid = str(guild_id)
        if gid not in _links:
            _links[gid] = {}
        _links[gid][str(discord_id)] = {
            "uuid": uuid,
            "name": name,
            "linked_at": int(time.time()),
        }
        _save()
