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

    async def get_latest_video(
        self, session: aiohttp.ClientSession, channel_id: str
    ) -> Optional[dict]:
        """Fetch the latest uploaded video for a YouTube channel via yt-dlp.

        YouTube deprecated their RSS feeds (now returning 404).
        yt-dlp handles all the scraping internally and is actively maintained.
        Returns a dict with video metadata or None on failure/empty channel.
        """
        import asyncio
        import yt_dlp
        import re as _re

        # yt-dlp requires a real UC... channel ID — resolve handle first if needed
        if not _re.match(r"^UC[\w-]{22}$", channel_id):
            logger.info(f"[YouTubeVideos] '{channel_id}' is not a UC channel ID — resolving via get_channel")
            resolved = await self.get_channel(session, channel_id)
            if not resolved:
                logger.error(f"[YouTubeVideos] Could not resolve channel ID for '{channel_id}'")
                return None
            channel_id = resolved["channel_id"]

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


class InstagramAPI:
    """Instagram public profile tracking via Instagram's private mobile API."""

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


youtube_api = YouTubeAPI()
tiktok_api = TikTokAPI()
instagram_api = InstagramAPI()
