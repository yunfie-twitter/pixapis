"""Enhanced Pixiv HTML scraper with Ajax endpoint support."""

import re
import json
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime
import os
import httpx
from requests import Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup

from app.models import (
    ArtworkResponse, AuthorInfo, ImageInfo,
    ArtworkStats
)
from app.config import settings

logger = logging.getLogger(__name__)


class PixivScraper:
    """Enhanced Pixiv scraper with Ajax API and HTML fallback."""

    BASE_URL = "https://www.pixiv.net"
    AJAX_BASE = "https://www.pixiv.net/ajax"
    CHUNK_SIZE = 1048576  # 1MB chunks for downloads

    def __init__(self, session_id: Optional[str] = None):
        """Initialize scraper.
        
        Args:
            session_id: PHPSESSID cookie value for authenticated requests
        """
        self.session_id = session_id or settings.pixiv_session
        
        # Setup requests session with retry logic
        self.session = Session()
        retries = Retry(
            total=5,
            backoff_factor=0.1,
            status_forcelist=[500, 502, 503, 504]
        )
        self.session.mount("http://", HTTPAdapter(max_retries=retries))
        self.session.mount("https://", HTTPAdapter(max_retries=retries))
        
        # Setup httpx client for async operations
        self.client = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            limits=httpx.Limits(max_keepalive_connections=20)
        )
        
        # Setup headers
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.pixiv.net/",
            "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        }
        
        if self.session_id:
            self.headers["Cookie"] = f"PHPSESSID={self.session_id}"
            logger.info("Scraper initialized with authentication")
        else:
            logger.warning("Scraper initialized without authentication (R-18 content unavailable)")

    async def close(self):
        """Close HTTP clients."""
        await self.client.aclose()
        self.session.close()

    def _make_request(self, url: str, method: str = "GET", **kwargs) -> Any:
        """Make HTTP request with retry logic.
        
        Args:
            url: Target URL
            method: HTTP method
            **kwargs: Additional request parameters
            
        Returns:
            Response object
        """
        headers = kwargs.pop("headers", {})
        merged_headers = {**self.headers, **headers}
        
        try:
            if method == "GET":
                response = self.session.get(url, headers=merged_headers, **kwargs)
            elif method == "POST":
                response = self.session.post(url, headers=merged_headers, **kwargs)
            else:
                raise ValueError(f"Unsupported method: {method}")
            
            response.raise_for_status()
            return response
        except Exception as e:
            logger.error(f"Request failed: {method} {url} - {str(e)}")
            raise

    def get_artwork_ajax(self, artwork_id: int) -> Optional[Dict[str, Any]]:
        """Get artwork data from Ajax endpoint.
        
        Args:
            artwork_id: Pixiv artwork ID
            
        Returns:
            Artwork data dict or None if failed
        """
        try:
            url = f"{self.AJAX_BASE}/illust/{artwork_id}"
            response = self._make_request(url)
            data = response.json()
            
            if data.get("error"):
                logger.warning(f"Ajax API returned error for artwork {artwork_id}: {data.get('message')}")
                return None
            
            return data.get("body")
        except Exception as e:
            logger.error(f"Failed to fetch artwork via Ajax: {str(e)}")
            return None

    def get_ugoira_metadata(self, artwork_id: int) -> Optional[Dict[str, Any]]:
        """Get Ugoira (animation) metadata.
        
        Args:
            artwork_id: Pixiv artwork ID
            
        Returns:
            Ugoira metadata dict or None if failed
        """
        try:
            url = f"{self.AJAX_BASE}/illust/{artwork_id}/ugoira_meta"
            response = self._make_request(url)
            data = response.json()
            
            if data.get("error"):
                return None
            
            return data.get("body")
        except Exception as e:
            logger.error(f"Failed to fetch ugoira metadata: {str(e)}")
            return None

    def get_user_ajax(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get user data from Ajax endpoint.
        
        Args:
            user_id: Pixiv user ID
            
        Returns:
            User data dict or None if failed
        """
        try:
            url = f"{self.AJAX_BASE}/user/{user_id}"
            response = self._make_request(url)
            data = response.json()
            
            if data.get("error"):
                return None
            
            return data.get("body")
        except Exception as e:
            logger.error(f"Failed to fetch user via Ajax: {str(e)}")
            return None

    def parse_artwork_from_ajax(self, ajax_data: Dict[str, Any], artwork_id: int) -> Optional[ArtworkResponse]:
        """Parse Ajax response to ArtworkResponse model.
        
        Args:
            ajax_data: Ajax endpoint response data
            artwork_id: Artwork ID
            
        Returns:
            Parsed ArtworkResponse or None if parsing fails
        """
        try:
            # Author info
            author = AuthorInfo(
                id=ajax_data.get("userId", 0),
                name=ajax_data.get("userName", "Unknown"),
                avatar_url=ajax_data.get("profileImageUrl"),
            )

            # Images
            images = []
            page_count = ajax_data.get("pageCount", 1)
            illust_type = ajax_data.get("illustType", 0)  # 0=illust, 1=manga, 2=ugoira
            
            if illust_type == 2:
                # Ugoira (animation)
                ugoira_meta = self.get_ugoira_metadata(artwork_id)
                if ugoira_meta:
                    images.append(ImageInfo(
                        url=ugoira_meta.get("originalSrc"),  # ZIP file URL
                        thumbnail=ajax_data.get("urls", {}).get("thumb_mini"),
                        width=ajax_data.get("width"),
                        height=ajax_data.get("height"),
                    ))
            elif page_count == 1:
                # Single image
                urls = ajax_data.get("urls", {})
                original_url = urls.get("original")
                if original_url:
                    images.append(ImageInfo(
                        url=original_url,
                        thumbnail=urls.get("regular") or urls.get("small"),
                        width=ajax_data.get("width"),
                        height=ajax_data.get("height"),
                    ))
            else:
                # Multiple images - extract all page URLs
                base_url = ajax_data.get("urls", {}).get("original", "")
                if base_url:
                    # Replace p0 with p{i} for each page
                    for i in range(page_count):
                        page_url = re.sub(r"_p0\.", f"_p{i}.", base_url)
                        images.append(ImageInfo(
                            url=page_url,
                            thumbnail=re.sub(r"img-original", "img-master", page_url).replace(
                                re.search(r"\.(jpg|png|gif)", page_url).group(0),
                                "_master1200.jpg"
                            ) if re.search(r"\.(jpg|png|gif)", page_url) else None,
                        ))

            # Tags
            tags_data = ajax_data.get("tags", {})
            if isinstance(tags_data, dict):
                tags = [tag.get("tag", "") for tag in tags_data.get("tags", []) if tag.get("tag")]
            else:
                tags = []

            # Stats
            stats = ArtworkStats(
                likes=ajax_data.get("likeCount", 0),
                bookmarks=ajax_data.get("bookmarkCount", 0),
                views=ajax_data.get("viewCount", 0),
            )

            # Created date
            created_at = None
            create_date = ajax_data.get("createDate")
            if create_date:
                try:
                    created_at = datetime.fromisoformat(create_date.replace("Z", "+00:00"))
                except Exception:
                    pass

            # R-18 detection
            is_r18 = ajax_data.get("xRestrict", 0) > 0 or ajax_data.get("sl", 0) >= 6

            return ArtworkResponse(
                id=artwork_id,
                title=ajax_data.get("title", "Untitled"),
                author=author,
                images=images,
                tags=tags,
                stats=stats,
                created_at=created_at,
                is_r18=is_r18,
                page_count=page_count,
                description=ajax_data.get("description", ""),
                related_artworks=[],
            )
        except Exception as e:
            logger.error(f"Error parsing artwork from Ajax: {str(e)}", exc_info=True)
            return None

    async def get_artwork_html(self, artwork_id: int) -> Optional[ArtworkResponse]:
        """Get artwork data by scraping HTML (fallback method).
        
        Args:
            artwork_id: Pixiv artwork ID
            
        Returns:
            Parsed ArtworkResponse or None if failed
        """
        try:
            url = f"{self.BASE_URL}/artworks/{artwork_id}"
            response = await self.client.get(url, headers=self.headers)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, "lxml")
            
            # Try to extract JSON from meta tag
            meta_tag = soup.find("meta", {"id": "meta-preload-data"})
            if meta_tag and meta_tag.get("content"):
                data = json.loads(meta_tag["content"])
                illust_data = data.get("illust", {}).get(str(artwork_id))
                if illust_data:
                    return self.parse_artwork_from_ajax(illust_data, artwork_id)
            
            # Try Next.js data
            next_data_script = soup.find("script", {"id": "__NEXT_DATA__"})
            if next_data_script:
                next_data = json.loads(next_data_script.string)
                illust_data = (
                    next_data.get("props", {})
                    .get("pageProps", {})
                    .get("illust", {})
                )
                if illust_data:
                    return self.parse_artwork_from_ajax(illust_data, artwork_id)
            
            logger.warning(f"Could not extract artwork data from HTML for {artwork_id}")
            return None
            
        except Exception as e:
            logger.error(f"HTML scraping failed for artwork {artwork_id}: {str(e)}")
            return None

    async def get_artwork(self, artwork_id: int) -> Optional[ArtworkResponse]:
        """Get artwork information (Ajax priority, HTML fallback).
        
        Args:
            artwork_id: Pixiv artwork ID
            
        Returns:
            Parsed ArtworkResponse or None if failed
        """
        try:
            # Try Ajax endpoint first (faster and more reliable)
            logger.info(f"Fetching artwork {artwork_id} via Ajax endpoint")
            ajax_data = self.get_artwork_ajax(artwork_id)
            if ajax_data:
                artwork = self.parse_artwork_from_ajax(ajax_data, artwork_id)
                if artwork:
                    logger.info(f"Successfully fetched artwork {artwork_id} via Ajax")
                    return artwork
            
            # Fallback to HTML scraping
            logger.info(f"Falling back to HTML scraping for artwork {artwork_id}")
            artwork = await self.get_artwork_html(artwork_id)
            if artwork:
                logger.info(f"Successfully fetched artwork {artwork_id} via HTML")
                return artwork
            
            logger.error(f"All methods failed for artwork {artwork_id}")
            return None
            
        except Exception as e:
            logger.error(f"Error fetching artwork {artwork_id}: {str(e)}", exc_info=True)
            return None

    def download_image(self, url: str, output_path: str, artwork_id: int) -> bool:
        """Download image from Pixiv.
        
        Args:
            url: Image URL
            output_path: Output file path
            artwork_id: Artwork ID (for referer)
            
        Returns:
            True if successful, False otherwise
        """
        try:
            headers = {
                **self.headers,
                "Referer": f"{self.BASE_URL}/artworks/{artwork_id}"
            }
            
            response = self._make_request(url, headers=headers, stream=True)
            
            # Create directory if not exists
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            # Download with chunks
            with open(output_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=self.CHUNK_SIZE):
                    if chunk:
                        f.write(chunk)
            
            logger.info(f"Downloaded image to {output_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to download image from {url}: {str(e)}")
            return False

    def get_download_filename(self, url: str) -> str:
        """Extract filename from URL.
        
        Args:
            url: Image URL
            
        Returns:
            Filename
        """
        match = re.search(r"\d+_(p\d+|ugoira).*?\.(jpg|png|gif|zip)", url)
        if match:
            return match.group(0)
        return os.path.basename(url)
