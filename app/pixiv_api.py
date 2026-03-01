"""Pixiv App API client implementation."""

import hashlib
import json
import os
from datetime import datetime
from typing import Optional, Dict, Any, List
import logging

try:
    import cloudscraper  # type: ignore
except ImportError:
    import httpx
    cloudscraper = None

from app.models import (
    ArtworkResponse, AuthorInfo, ImageInfo,
    ArtworkStats
)
from app.config import settings

logger = logging.getLogger(__name__)


class PixivAppAPI:
    """Official Pixiv App API client (v6.x - app-api.pixiv.net)."""

    CLIENT_ID = "MOBrBDS8blbauoSck0ZfDbtuzpyT"
    CLIENT_SECRET = "lsACyCD94FhDUtGTXi3QzcFE2uU1hqtDaKeqrdwj"
    HASH_SECRET = "28c1fdd170a5204386cb1313c7077b34f83e4aaf4aa829ce78c231e05b0bae2c"
    BASE_URL = "https://app-api.pixiv.net"
    AUTH_URL = "https://oauth.secure.pixiv.net"

    def __init__(self, refresh_token: Optional[str] = None):
        """Initialize Pixiv API client.
        
        Args:
            refresh_token: OAuth refresh token for authentication
        """
        self.refresh_token = refresh_token or settings.pixiv_refresh_token
        self.access_token: Optional[str] = None
        self.user_id: Optional[int] = None

        # Use cloudscraper if available to bypass Cloudflare
        if cloudscraper:
            self.session = cloudscraper.create_scraper()
            logger.info("Using cloudscraper for requests")
        else:
            logger.warning("cloudscraper not available, using httpx")
            self.session = None

        self.headers = {
            "app-os": "ios",
            "app-os-version": "14.6",
            "user-agent": "PixivIOSApp/7.13.3 (iOS 14.6; iPhone13,2)",
            "Accept-Language": "ja-JP",
        }

    def _get_auth_headers(self) -> Dict[str, str]:
        """Get authentication headers with current timestamp."""
        local_time = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S+00:00")
        headers = self.headers.copy()
        headers["x-client-time"] = local_time
        headers["x-client-hash"] = hashlib.md5(
            (local_time + self.HASH_SECRET).encode("utf-8")
        ).hexdigest()
        return headers

    def auth(self, refresh_token: Optional[str] = None) -> Dict[str, Any]:
        """Authenticate using refresh token.
        
        Args:
            refresh_token: OAuth refresh token (uses instance token if not provided)
            
        Returns:
            Authentication response with access_token
            
        Raises:
            Exception: If authentication fails
        """
        token = refresh_token or self.refresh_token
        if not token:
            raise ValueError("refresh_token is required for authentication")

        url = f"{self.AUTH_URL}/auth/token"
        headers = self._get_auth_headers()
        data = {
            "client_id": self.CLIENT_ID,
            "client_secret": self.CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": token,
            "get_secure_url": 1,
        }

        try:
            if cloudscraper:
                response = self.session.post(url, headers=headers, data=data)
            else:
                import httpx
                response = httpx.post(url, headers=headers, data=data, timeout=30.0)
            
            response.raise_for_status()
            result = response.json()
            
            # Store tokens
            self.access_token = result["response"]["access_token"]
            self.refresh_token = result["response"]["refresh_token"]
            self.user_id = result["response"]["user"]["id"]
            
            logger.info(f"Authenticated as user {self.user_id}")
            return result
        except Exception as e:
            logger.error(f"Authentication failed: {str(e)}")
            raise

    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        require_auth: bool = True,
    ) -> Dict[str, Any]:
        """Make API request.
        
        Args:
            method: HTTP method (GET, POST)
            endpoint: API endpoint path
            params: Query parameters
            data: Request body data
            require_auth: Whether to require authentication
            
        Returns:
            JSON response
        """
        url = f"{self.BASE_URL}{endpoint}"
        headers = self.headers.copy()

        if require_auth:
            if not self.access_token:
                logger.info("No access token, attempting authentication")
                self.auth()
            headers["Authorization"] = f"Bearer {self.access_token}"

        try:
            if cloudscraper:
                if method == "GET":
                    response = self.session.get(url, headers=headers, params=params)
                else:
                    response = self.session.post(url, headers=headers, data=data)
            else:
                import httpx
                client = httpx.Client(timeout=30.0)
                if method == "GET":
                    response = client.get(url, headers=headers, params=params)
                else:
                    response = client.post(url, headers=headers, data=data)
                client.close()

            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"API request failed: {method} {url} - {str(e)}")
            raise

    def illust_detail(self, illust_id: int) -> Dict[str, Any]:
        """Get illustration detail.
        
        Args:
            illust_id: Pixiv artwork ID
            
        Returns:
            Illust detail data
        """
        return self._request("GET", "/v1/illust/detail", params={"illust_id": illust_id})

    def user_detail(self, user_id: int) -> Dict[str, Any]:
        """Get user detail.
        
        Args:
            user_id: Pixiv user ID
            
        Returns:
            User detail data
        """
        return self._request("GET", "/v1/user/detail", params={"user_id": user_id})

    def user_illusts(
        self,
        user_id: int,
        type: str = "illust",
        offset: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Get user illustrations.
        
        Args:
            user_id: Pixiv user ID
            type: Content type (illust, manga)
            offset: Pagination offset
            
        Returns:
            User illustrations list
        """
        params = {"user_id": user_id, "type": type, "filter": "for_ios"}
        if offset:
            params["offset"] = offset
        return self._request("GET", "/v1/user/illusts", params=params)

    def illust_ranking(
        self,
        mode: str = "day",
        date: Optional[str] = None,
        offset: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Get illustration ranking.
        
        Args:
            mode: Ranking mode (day, week, month, day_male, day_female, etc.)
            date: Date in YYYY-MM-DD format
            offset: Pagination offset
            
        Returns:
            Ranking list
        """
        params = {"mode": mode, "filter": "for_ios"}
        if date:
            params["date"] = date
        if offset:
            params["offset"] = offset
        return self._request("GET", "/v1/illust/ranking", params=params)

    def search_illust(
        self,
        word: str,
        search_target: str = "partial_match_for_tags",
        sort: str = "date_desc",
        duration: Optional[str] = None,
        offset: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Search illustrations.
        
        Args:
            word: Search keyword
            search_target: Search target (partial_match_for_tags, exact_match_for_tags, title_and_caption)
            sort: Sort order (date_desc, date_asc, popular_desc)
            duration: Duration filter (within_last_day, within_last_week, within_last_month)
            offset: Pagination offset
            
        Returns:
            Search results
        """
        params = {
            "word": word,
            "search_target": search_target,
            "sort": sort,
            "filter": "for_ios",
        }
        if duration:
            params["duration"] = duration
        if offset:
            params["offset"] = offset
        return self._request("GET", "/v1/search/illust", params=params)

    def illust_related(
        self,
        illust_id: int,
        offset: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Get related illustrations.
        
        Args:
            illust_id: Pixiv artwork ID
            offset: Pagination offset
            
        Returns:
            Related illustrations
        """
        params = {"illust_id": illust_id, "filter": "for_ios"}
        if offset:
            params["offset"] = offset
        return self._request("GET", "/v2/illust/related", params=params)

    def illust_recommended(
        self,
        content_type: str = "illust",
        include_ranking_label: bool = True,
        offset: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Get recommended illustrations.
        
        Args:
            content_type: Content type (illust, manga)
            include_ranking_label: Include ranking label
            offset: Pagination offset
            
        Returns:
            Recommended illustrations
        """
        params = {
            "content_type": content_type,
            "include_ranking_label": "true" if include_ranking_label else "false",
            "filter": "for_ios",
        }
        if offset:
            params["offset"] = offset
        return self._request("GET", "/v1/illust/recommended", params=params)

    def ugoira_metadata(self, illust_id: int) -> Dict[str, Any]:
        """Get ugoira (animation) metadata.
        
        Args:
            illust_id: Pixiv artwork ID
            
        Returns:
            Ugoira metadata including frame delays and ZIP URL
        """
        return self._request("GET", "/v1/ugoira/metadata", params={"illust_id": illust_id})

    def parse_artwork_from_api(self, api_data: Dict[str, Any], artwork_id: int) -> Optional[ArtworkResponse]:
        """Parse API response to ArtworkResponse model.
        
        Args:
            api_data: API response data
            artwork_id: Artwork ID
            
        Returns:
            Parsed ArtworkResponse or None if parsing fails
        """
        try:
            illust = api_data.get("illust") or api_data
            if not illust:
                return None

            # Author info
            user = illust.get("user", {})
            author = AuthorInfo(
                id=user.get("id", 0),
                name=user.get("name", "Unknown"),
                avatar_url=user.get("profile_image_urls", {}).get("medium"),
            )

            # Images
            images = []
            page_count = illust.get("page_count", 1)
            
            if page_count == 1:
                # Single image
                urls = illust.get("image_urls", {}) or illust.get("meta_single_page", {})
                original_url = (
                    urls.get("original") or 
                    illust.get("meta_single_page", {}).get("original_image_url")
                )
                if original_url:
                    images.append(ImageInfo(
                        url=original_url,
                        thumbnail=urls.get("large") or urls.get("medium"),
                        width=illust.get("width"),
                        height=illust.get("height"),
                    ))
            else:
                # Multiple images
                meta_pages = illust.get("meta_pages", [])
                for page in meta_pages:
                    urls = page.get("image_urls", {})
                    original_url = urls.get("original")
                    if original_url:
                        images.append(ImageInfo(
                            url=original_url,
                            thumbnail=urls.get("large") or urls.get("medium"),
                        ))

            # Tags
            tags = [tag.get("name", "") for tag in illust.get("tags", []) if tag.get("name")]

            # Stats
            stats = ArtworkStats(
                likes=illust.get("total_view", 0),  # API doesn't expose like count directly
                bookmarks=illust.get("total_bookmarks", 0),
                views=illust.get("total_view", 0),
            )

            # Created date
            created_at = None
            create_date = illust.get("create_date")
            if create_date:
                try:
                    created_at = datetime.fromisoformat(create_date.replace("Z", "+00:00"))
                except Exception:
                    pass

            # R-18 detection
            is_r18 = illust.get("x_restrict", 0) > 0 or illust.get("sanity_level", 0) >= 6

            return ArtworkResponse(
                id=artwork_id,
                title=illust.get("title", "Untitled"),
                author=author,
                images=images,
                tags=tags,
                stats=stats,
                created_at=created_at,
                is_r18=is_r18,
                page_count=page_count,
                description=illust.get("caption", ""),
                related_artworks=[],
            )
        except Exception as e:
            logger.error(f"Error parsing artwork from API: {str(e)}", exc_info=True)
            return None

    async def get_artwork(self, artwork_id: int) -> Optional[ArtworkResponse]:
        """Get artwork detail using official API.
        
        Args:
            artwork_id: Pixiv artwork ID
            
        Returns:
            Parsed ArtworkResponse or None if failed
        """
        try:
            logger.info(f"Fetching artwork {artwork_id} from official API")
            api_data = self.illust_detail(artwork_id)
            return self.parse_artwork_from_api(api_data, artwork_id)
        except Exception as e:
            logger.error(f"Failed to get artwork from API: {str(e)}")
            return None
