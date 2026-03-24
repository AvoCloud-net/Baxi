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


class _SilentLogger:
    """Suppresses all yt-dlp console output."""
    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


class YouTubeAPI:
    """YouTube live stream tracking via yt-dlp — no API key or quota required.

    yt-dlp handles all scraping internally and is actively maintained.
    Blocking yt-dlp calls run in a thread executor to avoid blocking the async loop.
    """

    _YDL_OPTS = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": False,
        "socket_timeout": 15,
        "logger": _SilentLogger(),
    }

    def _channel_url(self, handle_or_id: str) -> str:
        import re
        if re.match(r"^UC[\w-]{22}$", handle_or_id):
            return f"https://www.youtube.com/channel/{handle_or_id}"
        return f"https://www.youtube.com/@{handle_or_id.lstrip('@')}"

    async def get_channel(
        self, session: aiohttp.ClientSession, handle_or_id: str
    ) -> Optional[dict]:
        """Validate a YouTube channel and return basic info, or None if not found."""
        import asyncio, yt_dlp

        url = self._channel_url(handle_or_id) + "/live"

        def _extract():
            # Fetching /live gives channel metadata even when offline
            opts = {**self._YDL_OPTS, "playlistend": 1}
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    return ydl.extract_info(url, download=False)
            except Exception:
                return None

        info = await asyncio.get_event_loop().run_in_executor(None, _extract)
        if not info:
            return None

        channel_id = info.get("channel_id") or info.get("id", handle_or_id)
        display_name = info.get("channel") or info.get("uploader") or info.get("title", handle_or_id)

        # yt-dlp exposes channel thumbnails under "thumbnails" list
        thumbnails = info.get("thumbnails") or []
        profile_img = next(
            (t["url"] for t in reversed(thumbnails) if t.get("url") and "yt3" in t.get("url", "")),
            "",
        )

        return {
            "channel_id": channel_id,
            "display_name": display_name,
            "handle": (info.get("uploader_id") or "").lstrip("@"),
            "profile_image_url": profile_img,
        }

    async def get_live_stream(
        self, session: aiohttp.ClientSession, channel_id: str
    ) -> Optional[dict]:
        """Check if a YouTube channel is currently live via yt-dlp.
        Returns stream data or None if not live."""
        import asyncio, yt_dlp

        url = self._channel_url(channel_id) + "/live"

        def _extract():
            try:
                with yt_dlp.YoutubeDL(self._YDL_OPTS) as ydl:
                    return ydl.extract_info(url, download=False)
            except yt_dlp.utils.DownloadError:
                return None
            except Exception:
                return None

        info = await asyncio.get_event_loop().run_in_executor(None, _extract)
        if not info or not info.get("is_live"):
            return None

        viewers = info.get("concurrent_view_count") or info.get("view_count") or 0
        categories = info.get("categories") or []

        return {
            "video_id": info.get("id", ""),
            "title": info.get("title", ""),
            "game_name": categories[0] if categories else "",
            "viewer_count": viewers,
            "started_at": "",
            "thumbnail_url": info.get("thumbnail", ""),
        }


class TikTokAPI:
    """Unofficial TikTok live stream tracking via page scraping.

    TikTok has no public livestream API. This scrapes the profile and /live pages,
    extracting data from the embedded __UNIVERSAL_DATA_FOR_REHYDRATION__ JSON.
    WARNING: May break if TikTok changes their page structure.
    """

    _HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    async def _fetch_page_data(
        self, session: aiohttp.ClientSession, url: str
    ) -> Optional[dict]:
        """Fetch a TikTok page and extract the embedded JSON data blob."""
        import re, json
        try:
            async with session.get(url, headers=self._HEADERS, allow_redirects=True) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text()
        except Exception as e:
            logger.error(f"[Livestream] TikTok page fetch error ({url}): {e}")
            return None

        # TikTok embeds all page data in a <script> tag with this id
        match = re.search(
            r'<script\s+id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>',
            html, re.DOTALL
        )
        if not match:
            # Fallback: look for SIGI_STATE
            match = re.search(r'<script\s+id="SIGI_STATE"[^>]*>(.*?)</script>', html, re.DOTALL)
        if not match:
            return None

        try:
            return json.loads(match.group(1))
        except (json.JSONDecodeError, ValueError):
            return None

    async def get_user_info(
        self, session: aiohttp.ClientSession, username: str
    ) -> Optional[dict]:
        """Validate a TikTok user by scraping their profile page."""
        import re
        data = await self._fetch_page_data(session, f"https://www.tiktok.com/@{username}")
        if not data:
            return None

        # Navigate the nested structure — layout varies by TikTok version
        # Try __DEFAULT_SCOPE__ → webapp.user-detail → userInfo.user
        scope = data.get("__DEFAULT_SCOPE__") or {}
        user_detail = scope.get("webapp.user-detail") or {}
        user_info = user_detail.get("userInfo") or {}
        user = user_info.get("user") or {}

        if not user.get("uniqueId"):
            # Fallback: search raw JSON for uniqueId matching username
            raw = str(data)
            if username.lower() not in raw.lower():
                return None
            # Best-effort: return minimal info
            return {"display_name": username, "profile_image_url": ""}

        avatar = user.get("avatarLarger") or user.get("avatarMedium") or ""
        return {
            "display_name": user.get("nickname", username),
            "profile_image_url": avatar,
        }

    async def get_live_stream(
        self, session: aiohttp.ClientSession, username: str
    ) -> Optional[dict]:
        """Check if a TikTok user is currently live by scraping their /live page."""
        import re
        data = await self._fetch_page_data(session, f"https://www.tiktok.com/@{username}/live")
        if not data:
            return None

        raw = str(data)

        # If page doesn't contain live room indicators, user is not live
        if "liveRoomInfo" not in raw and "roomInfo" not in raw and "LiveRoom" not in raw:
            return None

        # Try to find live room data in __DEFAULT_SCOPE__
        scope = data.get("__DEFAULT_SCOPE__") or {}
        live_room = (
            scope.get("webapp.live-detail")
            or scope.get("webapp.room-info")
            or {}
        )
        room_info = live_room.get("liveRoomInfo") or live_room.get("roomInfo") or {}

        # Status: 2 = live. If we find the key and it's not 2, they're offline.
        status = room_info.get("status")
        if status is not None and status != 2:
            return None

        # Extract what we can
        title = room_info.get("title", "") or f"{username} is live on TikTok!"
        viewer_count = room_info.get("userCount") or room_info.get("user_count") or 0

        # Fallback regex for viewer count if not found via JSON path
        if not viewer_count:
            m = re.search(r'"userCount"\s*:\s*(\d+)', raw)
            if m:
                viewer_count = int(m.group(1))

        cover_urls = (room_info.get("cover") or {}).get("url_list") or []
        thumbnail = cover_urls[0] if cover_urls else ""

        return {
            "title": title,
            "game_name": "",
            "viewer_count": viewer_count,
            "started_at": "",
            "thumbnail_url": thumbnail,
        }


youtube_api = YouTubeAPI()
tiktok_api = TikTokAPI()
