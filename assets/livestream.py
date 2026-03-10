import aiohttp
import asyncio
import time
from typing import Optional
from reds_simple_logger import Logger

import config.config as config
import config.auth as auth

logger = Logger()


class TwitchAPI:
    """Handles Twitch Helix API authentication and requests."""

    def __init__(self):
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0

    async def _ensure_token(self, session: aiohttp.ClientSession):
        if self._access_token and time.time() < self._token_expires_at:
            return

        params = {
            "client_id": auth.Twitch.client_id,
            "client_secret": auth.Twitch.client_secret,
            "grant_type": "client_credentials",
        }
        async with session.post(config.Twitch.token_url, params=params) as resp:
            data = await resp.json()
            self._access_token = data["access_token"]
            self._token_expires_at = time.time() + data.get("expires_in", 3600) - 60

    def _headers(self) -> dict:
        return {
            "Client-ID": auth.Twitch.client_id,
            "Authorization": f"Bearer {self._access_token}",
        }

    async def get_streams(
        self, session: aiohttp.ClientSession, user_logins: list[str]
    ) -> dict[str, dict]:
        """Fetch live stream data for a list of Twitch usernames.
        Returns dict mapping lowercase login -> stream data for those currently live."""
        if not user_logins:
            return {}

        await self._ensure_token(session)

        params = [("user_login", login) for login in user_logins]
        async with session.get(
            f"{config.Twitch.api_url}/streams",
            headers=self._headers(),
            params=params,
        ) as resp:
            if resp.status != 200:
                logger.error(f"[Livestream] Twitch API error: {resp.status}")
                return {}
            data = await resp.json()

        result = {}
        for stream in data.get("data", []):
            login = stream["user_login"].lower()
            result[login] = {
                "user_name": stream["user_name"],
                "title": stream["title"],
                "game_name": stream["game_name"],
                "viewer_count": stream["viewer_count"],
                "started_at": stream["started_at"],
                "thumbnail_url": stream["thumbnail_url"].replace(
                    "{width}", "440"
                ).replace("{height}", "248"),
                "profile_image_url": "",
            }
        return result

    async def get_users(
        self, session: aiohttp.ClientSession, logins: list[str]
    ) -> dict[str, dict]:
        """Fetch user profile data (mainly for profile images)."""
        if not logins:
            return {}

        await self._ensure_token(session)

        params = [("login", login) for login in logins]
        async with session.get(
            f"{config.Twitch.api_url}/users",
            headers=self._headers(),
            params=params,
        ) as resp:
            if resp.status != 200:
                return {}
            data = await resp.json()

        result = {}
        for user in data.get("data", []):
            result[user["login"].lower()] = {
                "display_name": user["display_name"],
                "profile_image_url": user["profile_image_url"],
                "offline_image_url": user.get("offline_image_url", ""),
            }
        return result


twitch_api = TwitchAPI()
