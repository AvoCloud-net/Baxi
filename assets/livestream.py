import aiohttp
import asyncio
import os
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
    """YouTube live stream tracking via yt-dlp -  no API key or quota required.

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
        # "Sign in to confirm you're not a bot": these innertube clients avoid the bot check
        # far more often than the default. web first (clean formats + works with cookies),
        # tv as a last-resort fallback for cookieless datacenter IPs.
        "extractor_args": {"youtube": {"player_client": ["web_safari", "web", "tv"]}},
        # Metadata-only: we never download, so don't fail when a client returns no playable
        # format (the tv/innertube clients sometimes do) -  still return id/title/date.
        "ignore_no_formats_error": True,
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            # Bypass YouTube GDPR consent wall (EU/DE servers)
            "Cookie": "SOCS=CAI; CONSENT=YES+cb",
        },
    }

    # Reliable fix for persistent bot checks on a datacenter IP: a Netscape-format cookies
    # file exported from a browser logged into YouTube. Set YT_COOKIES_FILE or drop it at
    # data/youtube_cookies.txt. Used automatically when present.
    _YT_COOKIES_FILE = os.environ.get("YT_COOKIES_FILE", "data/youtube_cookies.txt")
    if os.path.isfile(_YT_COOKIES_FILE):
        _YDL_OPTS["cookiefile"] = _YT_COOKIES_FILE

    def _channel_url(self, handle_or_id: str) -> str:
        import re
        if re.match(r"^UC[\w-]{22}$", handle_or_id):
            return f"https://www.youtube.com/channel/{handle_or_id}"
        return f"https://www.youtube.com/@{handle_or_id.lstrip('@')}"

    async def get_channel(
        self, session: aiohttp.ClientSession, handle_or_id: str
    ) -> Optional[dict]:
        """Validate a YouTube channel and return basic info, or None if not found.

        Uses direct HTTP scraping instead of yt-dlp — more robust against YouTube changes.
        """
        import re

        base_url = self._channel_url(handle_or_id)
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            # Bypass YouTube GDPR consent wall (EU/DE servers)
            "Cookie": "SOCS=CAI; CONSENT=YES+cb",
        }

        import re as _re
        html = None
        channel_id_from_redirect: Optional[str] = None
        for url in (base_url, base_url + "/about", base_url + "/videos"):
            try:
                async with session.get(
                    url, headers=headers, timeout=aiohttp.ClientTimeout(total=15),
                    allow_redirects=True,
                ) as resp:
                    logger.debug.info(f"[YouTubeAPI] GET {url} -> {resp.status} (final: {resp.url})")
                    if resp.status == 200:
                        html = await resp.text()
                        # YouTube sometimes redirects @handle -> /channel/UC...
                        redirect_match = _re.search(r'/channel/(UC[\w-]{22})', str(resp.url))
                        if redirect_match:
                            channel_id_from_redirect = redirect_match.group(1)
                        break
            except Exception as e:
                logger.error(f"[YouTubeAPI] Fetch error for {url}: {e}")
                continue

        if not html:
            return None

        # Resolve channel ID
        if _re.match(r"^UC[\w-]{22}$", handle_or_id):
            channel_id = handle_or_id
        elif channel_id_from_redirect:
            channel_id = channel_id_from_redirect
        else:
            # All known locations YouTube embeds the channel ID
            channel_id_match = (
                _re.search(r'<link rel="canonical"\s+href="https://www\.youtube\.com/channel/(UC[\w-]{22})"', html)
                or _re.search(r'<meta property="og:url"\s+content="https://www\.youtube\.com/channel/(UC[\w-]{22})"', html)
                or _re.search(r'"externalId"\s*:\s*"(UC[\w-]{22})"', html)
                or _re.search(r'"browseId"\s*:\s*"(UC[\w-]{22})"', html)
                or _re.search(r'"channelId"\s*:\s*"(UC[\w-]{22})"', html)
                or _re.search(r'<meta itemprop="channelId"\s+content="(UC[\w-]{22})"', html)
                or _re.search(r'youtube\.com/channel/(UC[\w-]{22})', html)
            )
            if not channel_id_match:
                logger.error(
                    f"[YouTubeAPI] Could not extract UC channel ID for '{handle_or_id}'. "
                    f"Page snippet: {html[:300]!r}"
                )
                return None
            channel_id = channel_id_match.group(1)

        # Display name
        name_match = (
            re.search(r'"channelMetadataRenderer"\s*:\s*\{[^}]*?"title"\s*:\s*"([^"]+)"', html)
            or re.search(r'<meta name="title"\s+content="([^"]+)"', html)
            or re.search(r'"title"\s*:\s*"([^"]+)"\s*,\s*"description"', html)
        )
        display_name = name_match.group(1) if name_match else handle_or_id.lstrip("@")

        # Avatar (yt3.ggpht.com thumbnails embedded in page)
        avatar_match = re.search(r'"(https://yt3\.ggpht\.com/[^"]+)"', html)
        profile_img = avatar_match.group(1) if avatar_match else ""

        return {
            "channel_id": channel_id,
            "display_name": display_name,
            "handle": handle_or_id.lstrip("@"),
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

    async def _latest_via_rss(
        self, session: aiohttp.ClientSession, channel_id: str
    ) -> Optional[dict]:
        """Latest upload via YouTube's official Atom feed. Lightweight + no bot check."""
        import xml.etree.ElementTree as ET

        feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
        ns = {
            "a":     "http://www.w3.org/2005/Atom",
            "yt":    "http://www.youtube.com/xml/schemas/2015",
            "media": "http://search.yahoo.com/mrss/",
        }
        try:
            headers = {"User-Agent": self._YDL_OPTS["http_headers"]["User-Agent"]}
            async with session.get(feed_url, headers=headers, timeout=15) as resp:
                if resp.status != 200:
                    return None
                text = await resp.text()
            root = ET.fromstring(text)
            entry = root.find("a:entry", ns)   # entries are newest-first
            if entry is None:
                return None
            video_id = entry.findtext("yt:videoId", default="", namespaces=ns)
            if not video_id:
                return None
            title = entry.findtext("a:title", default="", namespaces=ns)
            published = entry.findtext("a:published", default="", namespaces=ns)
            thumb = ""
            mt = entry.find("media:group/media:thumbnail", ns)
            if mt is not None:
                thumb = mt.get("url", "")
            if not thumb:
                thumb = f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"
            return {
                "video_id": video_id,
                "title": title,
                "published": published,
                "thumbnail_url": thumb,
                "url": f"https://www.youtube.com/watch?v={video_id}",
            }
        except Exception as e:
            logger.debug.info(f"[YouTubeVideos] RSS fallback for {channel_id}: {e}")
            return None

    async def get_latest_video(
        self, session: aiohttp.ClientSession, channel_id: str
    ) -> Optional[dict]:
        """Fetch the latest uploaded video for a YouTube channel.

        Primary path is the official, low-footprint RSS feed
        (feeds/videos.xml?channel_id=…) -  no bot check, no cookies, a tiny XML GET that
        looks like a normal feed reader. yt-dlp scraping is only used as a fallback, which
        keeps the polling far less conspicuous to YouTube.
        Returns a dict with video metadata or None on failure/empty channel.
        """
        import asyncio
        import yt_dlp
        import re as _re

        # A UC... channel ID is required for both the RSS feed and yt-dlp.
        if not _re.match(r"^UC[\w-]{22}$", channel_id):
            logger.info(f"[YouTubeVideos] '{channel_id}' is not a UC channel ID — resolving via get_channel")
            resolved = await self.get_channel(session, channel_id)
            if not resolved:
                logger.error(f"[YouTubeVideos] Could not resolve channel ID for '{channel_id}'")
                return None
            channel_id = resolved["channel_id"]

        # ── Primary: official RSS feed (unobtrusive) ─────────────────────────────
        rss = await self._latest_via_rss(session, channel_id)
        if rss:
            return rss

        # ── Fallback: yt-dlp scraping ────────────────────────────────────────────
        urls_to_try = [
            f"https://www.youtube.com/channel/{channel_id}/videos",
            f"https://www.youtube.com/channel/{channel_id}/shorts",
        ]

        def _extract():
            ydl_opts_flat = {
                **self._YDL_OPTS,
                "extract_flat": "in_playlist",
                "playlistend": 1,
            }
            info = None
            last_error = None
            for url in urls_to_try:
                try:
                    with yt_dlp.YoutubeDL(ydl_opts_flat) as ydl:
                        info = ydl.extract_info(url, download=False)
                    if info:
                        break
                except yt_dlp.utils.DownloadError as e:
                    last_error = e
                    logger.debug.info(f"[YouTubeVideos] Tab unavailable for {channel_id} ({url}): {e}")
                    continue

            if info is None:
                if last_error:
                    logger.error(f"[YouTubeVideos] yt-dlp error for {channel_id}: {last_error}")
                return None

            try:
                entries = info.get("entries") or []
                if not entries:
                    return None

                first_entry = None
                for entry in entries:
                    if entry and entry.get("id"):
                        first_entry = entry
                        break

                if not first_entry:
                    return None

                video_id = first_entry["id"]
                video_url = first_entry.get("url", f"https://www.youtube.com/watch?v={video_id}")
                title = first_entry.get("title", "")

                thumbnail_url = ""
                thumbnails = first_entry.get("thumbnails") or []
                if thumbnails:
                    thumbnail_url = thumbnails[-1].get("url", "")
                if not thumbnail_url:
                    thumbnail_url = f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"

                # Step 2: full metadata for upload date
                ydl_opts_video = {
                    **self._YDL_OPTS,
                    "extract_flat": False,
                }
                video_full_url = f"https://www.youtube.com/watch?v={video_id}"

                with yt_dlp.YoutubeDL(ydl_opts_video) as ydl:
                    video_info = ydl.extract_info(video_full_url, download=False)
                    if not video_info:
                        return {
                            "video_id": video_id,
                            "title": title,
                            "published": "",
                            "thumbnail_url": thumbnail_url,
                            "url": video_url,
                        }

                    timestamp = video_info.get("timestamp")
                    upload_date = video_info.get("upload_date")
                    published = ""

                    if timestamp:
                        try:
                            from datetime import datetime, timezone
                            dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
                            published = dt.isoformat()
                        except (ValueError, OSError) as e:
                            logger.debug.info(f"[YouTubeVideos] Failed to convert timestamp {timestamp}: {e}")

                    if not published and upload_date:
                        try:
                            upload_str = str(upload_date)
                            if len(upload_str) == 8:
                                year = int(upload_str[:4])
                                month = int(upload_str[4:6])
                                day = int(upload_str[6:8])
                                from datetime import datetime, timezone
                                dt = datetime(year, month, day, tzinfo=timezone.utc)
                                published = dt.isoformat()
                        except (ValueError, TypeError) as e:
                            logger.debug.info(f"[YouTubeVideos] Failed to convert upload_date {upload_date}: {e}")

                    final_thumbnail = thumbnail_url
                    if video_info.get("thumbnail"):
                        final_thumbnail = video_info["thumbnail"]

                    return {
                        "video_id": video_id,
                        "title": video_info.get("title", title),
                        "published": published,
                        "thumbnail_url": final_thumbnail,
                        "url": video_full_url,
                    }

            except yt_dlp.utils.DownloadError as e:
                logger.error(f"[YouTubeVideos] yt-dlp error for {channel_id}: {e}")
                return None
            except Exception as e:
                logger.error(f"[YouTubeVideos] yt-dlp unexpected error for {channel_id}: {e}")
                return None

        result = await asyncio.get_event_loop().run_in_executor(None, _extract)
        return result


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

        # Navigate the nested structure -  layout varies by TikTok version
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

    async def get_latest_video(self, username: str) -> Optional[dict]:
        """Fetch the latest TikTok post for a user via yt-dlp.

        Returns dict with video_id, title, published, thumbnail_url, url, or None on failure.
        """
        import asyncio
        import yt_dlp

        handle = username.lstrip("@")
        url = f"https://www.tiktok.com/@{handle}"

        def _extract():
            ydl_opts = {
                "quiet": True,
                "no_warnings": True,
                "skip_download": True,
                "extract_flat": "in_playlist",
                "playlistend": 5,
                "socket_timeout": 20,
                "logger": _SilentLogger(),
                "http_headers": {
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                },
            }
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                if not info:
                    return None
                entries = info.get("entries") or []
                first = next((e for e in entries if e and e.get("id")), None)
                if not first:
                    return None

                video_id = first["id"]
                title = first.get("title") or first.get("description") or ""
                thumbnail = ""
                thumbnails = first.get("thumbnails") or []
                if thumbnails:
                    thumbnail = thumbnails[-1].get("url", "")
                if not thumbnail:
                    thumbnail = first.get("thumbnail", "")

                published = ""
                timestamp = first.get("timestamp")
                if timestamp:
                    try:
                        from datetime import datetime, timezone
                        dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
                        published = dt.isoformat()
                    except (ValueError, OSError):
                        pass

                return {
                    "video_id": video_id,
                    "title": title,
                    "published": published,
                    "thumbnail_url": thumbnail,
                    "url": f"https://www.tiktok.com/@{handle}/video/{video_id}",
                }
            except yt_dlp.utils.DownloadError as e:
                logger.error(f"[TikTokVideos] yt-dlp error for @{handle}: {e}")
                return None
            except Exception as e:
                logger.error(f"[TikTokVideos] Unexpected error for @{handle}: {e}")
                return None

        return await asyncio.get_event_loop().run_in_executor(None, _extract)


class IGNotFound(Exception):
    """Raised when an Instagram user / resource is not found (404)."""

class IGRateLimited(Exception):
    """Raised when Instagram Graph API returns 429 or rate-limit error code."""

class IGBlocked(Exception):
    """Raised when the access token is invalid, expired, or the app is blocked."""

class IGTransient(Exception):
    """Raised on transient server-side errors (5xx) from Instagram Graph API."""


class InstagramAPI:
    """Instagram profile tracking and media fetching via the Instagram Graph API."""

    _GRAPH = "https://graph.instagram.com"

    _HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
        ),
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "X-IG-App-ID": "936619743392459",
        "Referer": "https://www.instagram.com/",
    }
    _BASE = "https://i.instagram.com/api/v1/users/web_profile_info/"

    async def _fetch_user_data(self, username: str) -> Optional[dict]:
        handle = username.lstrip("@")
        url = f"{self._BASE}?username={handle}"
        async with aiohttp.ClientSession(headers=self._HEADERS) as session:
            async with session.get(url, allow_redirects=True) as resp:
                if resp.status != 200:
                    logger.warning(f"[InstagramAPI] HTTP {resp.status} for @{handle}")
                    return None
                payload = await resp.json(content_type=None)
        return payload.get("data", {}).get("user")

    async def get_profile(self, username: str) -> Optional[dict]:
        handle = username.lstrip("@")
        try:
            user = await self._fetch_user_data(handle)
            if not user:
                return None
            return {
                "username": user.get("username", handle),
                "display_name": user.get("full_name") or user.get("username", handle),
                "profile_image_url": user.get("profile_pic_url", ""),
            }
        except Exception as e:
            logger.error(f"[InstagramAPI] Error fetching profile @{handle}: {e}")
            return None

    async def get_latest_reel_and_post(self, username: str) -> dict:
        """Return {latest_post, latest_reel} from the profile's recent media.

        GraphVideo items are treated as reels (Instagram deprecated standalone
        video posts; all feed videos are Reels in practice).
        GraphImage / GraphSidecar items are treated as regular posts.
        """
        from datetime import timezone, datetime
        handle = username.lstrip("@")
        empty = {"latest_post": None, "latest_reel": None}
        try:
            user = await self._fetch_user_data(handle)
            if not user:
                return empty

            edges = (
                user.get("edge_owner_to_timeline_media", {}).get("edges") or []
            )

            latest_post = None
            latest_reel = None

            for edge in edges:
                node = edge.get("node", {})
                is_video = node.get("is_video", False)
                shortcode = node.get("shortcode", "")
                post_id = str(node.get("id", ""))
                timestamp = node.get("taken_at_timestamp", 0)
                published = datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
                caption_edges = node.get("edge_media_to_caption", {}).get("edges", [])
                caption = caption_edges[0]["node"]["text"] if caption_edges else ""
                if len(caption) > 200:
                    caption = caption[:197] + "..."
                thumbnail_url = node.get("display_url", "")
                url = f"https://www.instagram.com/p/{shortcode}/"

                entry = {
                    "post_id": post_id,
                    "shortcode": shortcode,
                    "caption": caption,
                    "published": published,
                    "thumbnail_url": thumbnail_url,
                    "url": url,
                    "is_reel": is_video,
                }

                if is_video and latest_reel is None:
                    latest_reel = entry
                elif not is_video and latest_post is None:
                    latest_post = entry

                if latest_post is not None and latest_reel is not None:
                    break

            return {"latest_post": latest_post, "latest_reel": latest_reel}
        except Exception as e:
            logger.error(f"[InstagramAPI] Error fetching content for @{handle}: {e}")
            return empty

    async def refresh_token(self, access_token: str) -> tuple[str, int]:
        """Refresh a long-lived Instagram access token. Returns (new_token, expires_unix)."""
        url = (
            f"{self._GRAPH}/refresh_access_token"
            f"?grant_type=ig_refresh_token&access_token={access_token}"
        )
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                data = await resp.json(content_type=None)
        error = data.get("error", {})
        if error:
            code = error.get("code", 0)
            subcode = error.get("error_subcode", 0)
            if code in (190, 102) or subcode in (460, 463, 467):
                raise IGBlocked(error.get("message", "token invalid"))
            raise IGTransient(error.get("message", "unknown error"))
        new_token = data["access_token"]
        expires_in = data.get("expires_in", 5184000)
        return new_token, int(time.time()) + expires_in

    async def get_user_media(self, ig_user_id: str, access_token: str) -> dict:
        """Fetch latest post and reel for a user via Graph API. Returns {latest_post, latest_reel}."""
        from datetime import timezone, datetime
        fields = "id,media_type,timestamp,caption,media_url,thumbnail_url,permalink"
        url = (
            f"{self._GRAPH}/{ig_user_id}/media"
            f"?fields={fields}&limit=20&access_token={access_token}"
        )
        empty = {"latest_post": None, "latest_reel": None}
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 429:
                    raise IGRateLimited(f"HTTP 429 for user {ig_user_id}")
                if resp.status == 404:
                    raise IGNotFound(f"User {ig_user_id} not found")
                if resp.status >= 500:
                    raise IGTransient(f"HTTP {resp.status} for user {ig_user_id}")
                data = await resp.json(content_type=None)
        error = data.get("error", {})
        if error:
            code = error.get("code", 0)
            subcode = error.get("error_subcode", 0)
            msg = error.get("message", "")
            if code in (190, 102) or subcode in (460, 463, 467):
                raise IGBlocked(msg)
            if code == 4 or code == 32 or code == 17:
                raise IGRateLimited(msg)
            raise IGTransient(msg)

        items = data.get("data", [])
        latest_post = None
        latest_reel = None
        for item in items:
            media_type = item.get("media_type", "")
            post_id = str(item.get("id", ""))
            timestamp = item.get("timestamp", "")
            caption = (item.get("caption") or "")[:200]
            thumbnail_url = item.get("thumbnail_url") or item.get("media_url", "")
            permalink = item.get("permalink", "")
            entry = {
                "post_id": post_id,
                "caption": caption,
                "published": timestamp,
                "thumbnail_url": thumbnail_url,
                "url": permalink,
                "is_reel": media_type == "VIDEO",
            }
            if media_type == "VIDEO" and latest_reel is None:
                latest_reel = entry
            elif media_type in ("IMAGE", "CAROUSEL_ALBUM") and latest_post is None:
                latest_post = entry
            if latest_post is not None and latest_reel is not None:
                break
        return {"latest_post": latest_post, "latest_reel": latest_reel}


class TwitterAPI:
    """Unofficial X (Twitter) post tracking via the public guest GraphQL API.

    X has no free official API. This calls the same GraphQL endpoints the website uses
    (UserByScreenName → UserTweets) with the web app's public bearer token.

    Two auth modes:
      - Guest token (default, no config): X serves only large/popular accounts; small or
        new accounts return an empty timeline.
      - Cookie auth (config.auth.Twitter.auth_token + ct0): unlocks every public account.

    WARNING: May break if X rotates the public bearer or changes GraphQL query IDs.
    Alerts on original posts and reposts (retweets). Replies are ignored.
    """

    # Public bearer baked into the X web app (not a secret; same one snscrape/twikit use).
    _BEARER = (
        "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D"
        "1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
    )
    _GQL = "https://api.twitter.com/graphql"
    _Q_USER_BY_NAME = "G3KGOASz96M-Qu0nwmGXNg"   # UserByScreenName
    _Q_USER_TWEETS = "V7H0Ap3_Hh2FyS75OCDO3Q"    # UserTweets
    _UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

    _USER_FEATURES = {
        "hidden_profile_likes_enabled": True, "hidden_profile_subscriptions_enabled": True,
        "responsive_web_graphql_exclude_directive_enabled": True, "verified_phone_label_enabled": False,
        "subscriptions_verification_info_is_identity_verified_enabled": True,
        "subscriptions_verification_info_verified_since_enabled": True,
        "highlights_tweets_tab_ui_enabled": True, "responsive_web_twitter_article_notes_tab_enabled": True,
        "creator_subscriptions_tweet_preview_api_enabled": True,
        "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
        "responsive_web_graphql_timeline_navigation_enabled": True,
    }
    _TWEET_FEATURES = {
        "responsive_web_graphql_exclude_directive_enabled": True, "verified_phone_label_enabled": False,
        "creator_subscriptions_tweet_preview_api_enabled": True,
        "responsive_web_graphql_timeline_navigation_enabled": True,
        "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
        "c9s_tweet_anatomy_moderator_badge_enabled": True, "tweetypie_unmention_optimization_enabled": True,
        "responsive_web_edit_tweet_api_enabled": True,
        "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
        "view_counts_everywhere_api_enabled": True, "longform_notetweets_consumption_enabled": True,
        "responsive_web_twitter_article_tweet_consumption_enabled": True, "tweet_awards_web_tipping_enabled": False,
        "freedom_of_speech_not_reach_fetch_enabled": True, "standardized_nudges_misinfo": True,
        "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
        "rweb_video_timestamps_enabled": True, "longform_notetweets_rich_text_read_enabled": True,
        "longform_notetweets_inline_media_enabled": True, "responsive_web_enhance_cards_enabled": False,
    }

    def __init__(self):
        self._guest_token: Optional[str] = None
        self._guest_token_ts: float = 0.0
        self._rest_id_cache: dict = {}   # screen_name(lower) -> rest_id

    @staticmethod
    def _cookies() -> Optional[tuple]:
        """Return (auth_token, ct0) if both cookies are configured, else None."""
        at = getattr(getattr(auth, "Twitter", None), "auth_token", "") or ""
        ct0 = getattr(getattr(auth, "Twitter", None), "ct0", "") or ""
        return (at, ct0) if at and ct0 else None

    @staticmethod
    def has_cookies() -> bool:
        """True if X login cookies are configured (unlocks every public timeline).

        In guest mode (no cookies) X hides the timelines of small/new accounts.
        """
        return TwitterAPI._cookies() is not None

    async def _get_guest_token(self, session: aiohttp.ClientSession, force: bool = False) -> Optional[str]:
        # Guest tokens are valid for a few hours; reuse across checks.
        if self._guest_token and not force and (time.time() - self._guest_token_ts) < 3 * 3600:
            return self._guest_token
        try:
            async with session.post(
                "https://api.twitter.com/1.1/guest/activate.json",
                headers={"Authorization": f"Bearer {self._BEARER}", "User-Agent": self._UA},
            ) as resp:
                if resp.status != 200:
                    logger.error(f"[TwitterPosts] guest token activate failed: {resp.status}")
                    return None
                data = await resp.json()
        except Exception as e:
            logger.error(f"[TwitterPosts] guest token error: {e}")
            return None
        self._guest_token = data.get("guest_token")
        self._guest_token_ts = time.time()
        return self._guest_token

    async def _graphql(self, session: aiohttp.ClientSession, qid: str, op: str,
                       variables: dict, features: dict) -> Optional[dict]:
        import json
        from urllib.parse import quote
        cookies = self._cookies()
        for attempt in range(2):
            headers = {"Authorization": f"Bearer {self._BEARER}", "User-Agent": self._UA}
            if cookies:
                # Authenticated mode: cookies unlock every public account's timeline.
                at, ct0 = cookies
                headers["Cookie"] = f"auth_token={at}; ct0={ct0}"
                headers["x-csrf-token"] = ct0
            else:
                # Guest mode: works for large accounts only.
                gt = await self._get_guest_token(session, force=(attempt == 1))
                if not gt:
                    return None
                headers["x-guest-token"] = gt
            url = (f"{self._GQL}/{qid}/{op}?variables={quote(json.dumps(variables))}"
                   f"&features={quote(json.dumps(features))}")
            try:
                async with session.get(url, headers=headers) as resp:
                    if resp.status in (401, 403):
                        if cookies:
                            logger.error(f"[TwitterPosts] {op} auth rejected ({resp.status}) — X cookies expired/invalid")
                            return None
                        # guest token likely expired -> refresh and retry once
                        self._guest_token = None
                        continue
                    if resp.status == 429:
                        logger.warning(f"[TwitterPosts] rate limited on {op}")
                        return None
                    if resp.status != 200:
                        logger.error(f"[TwitterPosts] {op} HTTP {resp.status}")
                        return None
                    return await resp.json()
            except Exception as e:
                logger.error(f"[TwitterPosts] {op} request error: {e}")
                return None
        return None

    @staticmethod
    def _avatar(legacy: dict) -> str:
        url = legacy.get("profile_image_url_https") or ""
        return url.replace("_normal.", "_400x400.")

    @staticmethod
    def _media_url(legacy: dict) -> str:
        media = (legacy.get("extended_entities") or legacy.get("entities") or {}).get("media")
        if isinstance(media, list) and media:
            return (media[0] or {}).get("media_url_https", "") or ""
        return ""

    @staticmethod
    def _clean_text(text: str) -> str:
        import re as _re
        # drop the trailing t.co media/quote link X appends (incl. a truncated bare "https://")
        return _re.sub(r"\s*https://(t\.co/\w*)?\s*$", "", text or "").strip()

    @staticmethod
    def _parse_created(created_at: str) -> str:
        if not created_at:
            return ""
        try:
            from email.utils import parsedate_to_datetime
            return parsedate_to_datetime(created_at).isoformat()
        except (ValueError, TypeError):
            return ""

    async def _resolve_user(self, session: aiohttp.ClientSession, username: str) -> Optional[dict]:
        """Resolve a screen name to {rest_id, name, profile_image_url}."""
        handle = username.lstrip("@")
        data = await self._graphql(
            session, self._Q_USER_BY_NAME, "UserByScreenName",
            {"screen_name": handle, "withSafetyModeUserFields": True}, self._USER_FEATURES,
        )
        if not data:
            return None
        result = (((data.get("data") or {}).get("user") or {}).get("result")) or {}
        if result.get("__typename") != "User":
            return None
        rest_id = result.get("rest_id")
        legacy = result.get("legacy") or {}
        if not rest_id:
            return None
        self._rest_id_cache[handle.lower()] = rest_id
        return {
            "rest_id": rest_id,
            "name": legacy.get("name", handle),
            "profile_image_url": self._avatar(legacy),
        }

    async def get_user_info(
        self, session: aiohttp.ClientSession, username: str
    ) -> Optional[dict]:
        """Validate an X user. Returns {display_name, profile_image_url} or None."""
        info = await self._resolve_user(session, username)
        if not info:
            return None
        return {
            "display_name": info["name"],
            "profile_image_url": info["profile_image_url"],
        }

    @staticmethod
    def _unwrap_tweet(result: dict) -> Optional[dict]:
        """Return the tweet 'result' object, unwrapping TweetWithVisibilityResults."""
        if not isinstance(result, dict):
            return None
        if result.get("__typename") == "TweetWithVisibilityResults":
            result = result.get("tweet") or {}
        return result if result.get("legacy") else None

    def _format_entry(self, result: dict, handle: str) -> Optional[dict]:
        tweet = self._unwrap_tweet(result)
        if not tweet:
            return None
        legacy = tweet.get("legacy") or {}

        # Drop replies (keep originals + reposts)
        if legacy.get("in_reply_to_screen_name"):
            return None

        post_id = legacy.get("id_str") or tweet.get("rest_id")
        if not post_id:
            return None
        post_id = str(post_id)
        created = legacy.get("created_at", "")

        rt = (legacy.get("retweeted_status_result") or {}).get("result")
        inner = self._unwrap_tweet(rt) if rt else None
        if inner:
            inner_legacy = inner.get("legacy") or {}
            orig = ((inner.get("core") or {}).get("user_results") or {}).get("result", {})
            orig_handle = (orig.get("legacy") or {}).get("screen_name", "")
            body = self._clean_text(inner_legacy.get("full_text") or "")
            title = f"🔁 @{orig_handle}: {body}" if orig_handle else f"🔁 {body}"
            inner_id = str(inner_legacy.get("id_str") or inner.get("rest_id") or post_id)
            url = f"https://x.com/{orig_handle or handle}/status/{inner_id}"
            thumbnail = self._media_url(inner_legacy)
        else:
            title = self._clean_text(legacy.get("full_text") or "")
            url = f"https://x.com/{handle}/status/{post_id}"
            thumbnail = self._media_url(legacy)

        if not title:
            title = f"New post by @{handle}"

        return {
            "post_id": post_id,
            "title": title[:256],
            "published": self._parse_created(created),
            "thumbnail_url": thumbnail,
            "url": url,
            "_ts": created,
        }

    async def get_latest_post(self, username: str) -> Optional[dict]:
        """Fetch the newest original post or repost for a user.

        Returns dict with post_id, title, published, thumbnail_url, url, or None.
        """
        handle = username.lstrip("@")
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
            rest_id = self._rest_id_cache.get(handle.lower())
            if not rest_id:
                info = await self._resolve_user(session, handle)
                if not info:
                    return None
                rest_id = info["rest_id"]

            variables = {
                "userId": rest_id, "count": 20, "includePromotedContent": False,
                "withQuickPromoteEligibilityTweetFields": False, "withVoice": False,
                "withV2Timeline": True,
            }
            data = await self._graphql(
                session, self._Q_USER_TWEETS, "UserTweets", variables, self._TWEET_FEATURES,
            )
            if not data:
                return None

        try:
            timeline = ((((data.get("data") or {}).get("user") or {}).get("result") or {})
                        .get("timeline_v2") or {}).get("timeline") or {}
            instructions = timeline.get("instructions") or []
        except AttributeError:
            return None

        candidates: list = []
        for instr in instructions:
            # Skip TimelinePinEntry so a pinned tweet never re-alerts as "new".
            if instr.get("type") != "TimelineAddEntries":
                continue
            for entry in instr.get("entries") or []:
                if not str(entry.get("entryId", "")).startswith("tweet-"):
                    continue
                result = (((entry.get("content") or {}).get("itemContent") or {})
                          .get("tweet_results") or {}).get("result")
                post = self._format_entry(result, handle) if result else None
                if post:
                    candidates.append(post)

        if not candidates:
            return None

        # Newest by created_at timestamp (fall back to list order).
        def _key(p):
            return self._parse_created(p.get("_ts", "")) or ""
        candidates.sort(key=_key, reverse=True)
        latest = candidates[0]
        latest.pop("_ts", None)
        return latest


youtube_api = YouTubeAPI()
tiktok_api = TikTokAPI()
instagram_api = InstagramAPI()
twitter_api = TwitterAPI()
