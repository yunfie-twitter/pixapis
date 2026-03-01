"""Pixiv HTML scraper implementation."""

import httpx
from bs4 import BeautifulSoup
import re
import json
from typing import Optional, Dict, Any, List
from datetime import datetime
import logging

from app.models import (
    ArtworkResponse, AuthorInfo, ImageInfo,
    ArtworkStats
)
from app.config import settings
from app.utils import parse_stat_number, extract_user_id_from_url

logger = logging.getLogger(__name__)


class PixivScraper:
    """Scraper for Pixiv artwork pages."""

    BASE_URL = "https://www.pixiv.net"
    ARTWORK_URL_TEMPLATE = "https://www.pixiv.net/artworks/{}"

    def __init__(self):
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Referer": "https://www.pixiv.net/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }

        cookies = {}
        if settings.pixiv_session:
            cookies["PHPSESSID"] = settings.pixiv_session

        self.client = httpx.AsyncClient(
            headers=self.headers,
            cookies=cookies,
            timeout=30.0,
            follow_redirects=True,
        )

    async def close(self):
        await self.client.aclose()

    async def fetch_html(self, url: str) -> Optional[str]:
        try:
            response = await self.client.get(url)
            response.raise_for_status()
            return response.text
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error fetching {url}: {e.response.status_code}")
            return None
        except Exception as e:
            logger.error(f"Error fetching {url}: {str(e)}")
            return None

    def extract_meta_preload_json(self, html: str) -> Optional[Dict[str, Any]]:
        """Extract preload JSON from <meta id=meta-preload-data content='...'>."""
        try:
            soup = BeautifulSoup(html, "lxml")
            meta_tag = soup.find("meta", {"id": "meta-preload-data"})
            if meta_tag and meta_tag.get("content"):
                return json.loads(meta_tag["content"])
            return None
        except Exception as e:
            logger.error(f"Error extracting meta-preload-data JSON: {str(e)}")
            return None

    def extract_next_data_json(self, html: str) -> Optional[Dict[str, Any]]:
        """Extract JSON from <script id="__NEXT_DATA__" type="application/json">."""
        try:
            soup = BeautifulSoup(html, "lxml")
            script = soup.find("script", {"id": "__NEXT_DATA__"})
            if not script:
                return None
            text = script.string or script.get_text(strip=False)
            if not text:
                return None
            return json.loads(text)
        except Exception as e:
            logger.error(f"Error extracting __NEXT_DATA__ JSON: {str(e)}")
            return None

    def _build_artwork_response(self, illust: Dict[str, Any], artwork_id: int) -> Optional[ArtworkResponse]:
        try:
            author = AuthorInfo(
                id=int(illust.get("userId") or 0),
                name=illust.get("userName") or "Unknown",
                avatar_url=illust.get("profileImageUrl"),
            )

            page_count = int(illust.get("pageCount") or 1)
            images = []

            urls = illust.get("urls") or {}
            if page_count == 1:
                original_url = urls.get("original")
                thumb_url = urls.get("small") or urls.get("thumb") or urls.get("regular")
                if original_url:
                    images.append(
                        ImageInfo(
                            url=original_url,
                            thumbnail=thumb_url,
                            width=illust.get("width"),
                            height=illust.get("height"),
                        )
                    )
            else:
                base_original = urls.get("original")
                if base_original:
                    for i in range(page_count):
                        images.append(ImageInfo(url=base_original.replace("_p0", f"_p{i}")))

            tags = [t.get("tag", "") for t in (illust.get("tags") or {}).get("tags", []) if t.get("tag")]

            stats = ArtworkStats(
                likes=int(illust.get("likeCount") or 0),
                bookmarks=int(illust.get("bookmarkCount") or 0),
                views=int(illust.get("viewCount") or 0),
            )

            created_at = None
            create_date = illust.get("createDate")
            if create_date:
                try:
                    created_at = datetime.fromisoformat(str(create_date).replace("Z", "+00:00"))
                except Exception:
                    created_at = None

            is_r18 = (illust.get("xRestrict") or 0) > 0 or ("R-18" in tags)

            return ArtworkResponse(
                id=artwork_id,
                title=illust.get("title") or "Untitled",
                author=author,
                images=images,
                tags=tags,
                stats=stats,
                created_at=created_at,
                is_r18=is_r18,
                page_count=page_count,
                description=illust.get("description") or "",
                related_artworks=[],
            )
        except Exception as e:
            logger.error(f"Error building ArtworkResponse: {str(e)}", exc_info=True)
            return None

    def parse_artwork_from_meta_preload(self, meta_data: Dict[str, Any], artwork_id: int) -> Optional[ArtworkResponse]:
        try:
            illust_key = str(artwork_id)
            illusts = (meta_data or {}).get("illust") or {}
            illust = illusts.get(illust_key)
            if not illust:
                return None
            return self._build_artwork_response(illust, artwork_id)
        except Exception as e:
            logger.error(f"Error parsing artwork from meta-preload-data: {str(e)}", exc_info=True)
            return None

    def parse_artwork_from_next_data(self, next_data: Dict[str, Any], artwork_id: int) -> Optional[ArtworkResponse]:
        """Try to locate illust data in __NEXT_DATA__.

        Pixiv's Next.js payload shape can change; this searches common locations.
        """
        try:
            illust_key = str(artwork_id)

            # Common: props.pageProps.preload.illust[ID]
            page_props = (((next_data or {}).get("props") or {}).get("pageProps") or {})
            preload = page_props.get("preload") or page_props.get("preloadData") or {}
            illusts = (preload.get("illust") or preload.get("illusts") or {})
            if isinstance(illusts, dict) and illust_key in illusts:
                return self._build_artwork_response(illusts[illust_key], artwork_id)

            # Another: props.pageProps.dehydratedState.queries[*].state.data.illust[ID]
            dehydrated = page_props.get("dehydratedState") or {}
            queries = dehydrated.get("queries") or []
            for q in queries:
                state = (q or {}).get("state") or {}
                data = state.get("data") or {}
                ill = (data.get("illust") or {})
                if isinstance(ill, dict) and illust_key in ill:
                    return self._build_artwork_response(ill[illust_key], artwork_id)

                # Sometimes data itself is an illust dict with id
                if isinstance(data, dict) and str(data.get("id")) == illust_key:
                    return self._build_artwork_response(data, artwork_id)

            return None
        except Exception as e:
            logger.error(f"Error parsing artwork from __NEXT_DATA__: {str(e)}", exc_info=True)
            return None

    def _extract_images_from_html(self, soup: BeautifulSoup) -> List[ImageInfo]:
        """Extract image URLs from HTML structure."""
        images = []
        
        # Try to extract original image URL from expand-full-size-illust link
        expand_links = soup.select('a.sc-440d5b2c-3.gtm-expand-full-size-illust, a[class*="expand-full-size"]')
        for link in expand_links:
            original_url = link.get('href', '')
            if original_url and 'i.pximg.net/img-original/' in original_url:
                # Try to get thumbnail from nearby img
                img = link.select_one('img.sc-440d5b2c-1, img[class*="sc-"]')
                thumb_url = img.get('src', '') if img else ''
                
                # Extract dimensions from style or attributes
                width = height = None
                if img:
                    width_str = img.get('width')
                    height_str = img.get('height')
                    if width_str:
                        try:
                            width = int(width_str)
                        except:
                            pass
                    if height_str:
                        try:
                            height = int(height_str)
                        except:
                            pass
                
                images.append(ImageInfo(
                    url=original_url,
                    thumbnail=thumb_url or original_url,
                    width=width,
                    height=height
                ))
        
        # If no expand links found, try regular image tags
        if not images:
            img_tags = soup.select('img.sc-440d5b2c-1, img[src*="i.pximg.net"]')
            for img in img_tags:
                src = img.get('src', '')
                if src and 'i.pximg.net' in src:
                    # Try to convert master1200 to original URL
                    original_url = src
                    if 'img-master' in src and '_master1200' in src:
                        # Convert: img-master/img/YYYY/MM/DD/HH/MM/SS/ID_p0_master1200.jpg
                        # To: img-original/img/YYYY/MM/DD/HH/MM/SS/ID_p0.jpg
                        original_url = src.replace('/img-master/', '/img-original/').replace('_master1200', '')
                    
                    width = height = None
                    width_str = img.get('width')
                    height_str = img.get('height')
                    if width_str:
                        try:
                            width = int(width_str)
                        except:
                            pass
                    if height_str:
                        try:
                            height = int(height_str)
                        except:
                            pass
                    
                    images.append(ImageInfo(
                        url=original_url,
                        thumbnail=src,
                        width=width,
                        height=height
                    ))
                    break  # Take first valid image
        
        return images

    def parse_artwork_from_html(self, html: str, artwork_id: int) -> Optional[ArtworkResponse]:
        try:
            soup = BeautifulSoup(html, "lxml")

            def meta_content(selector: str) -> Optional[str]:
                tag = soup.select_one(selector)
                return tag.get("content") if tag and tag.get("content") else None

            # Title: h1 with multiple possible classes -> og:title -> twitter:title
            title = "Untitled"
            title_elem = soup.select_one("h1.sc-965e5f82-3, h1.kANgwp, h1[class*='sc-']")
            if title_elem and title_elem.get_text(strip=True):
                title = title_elem.get_text(strip=True)
            else:
                title = meta_content('meta[property="og:title"]') or meta_content('meta[name="twitter:title"]') or title

            # Author: try user link + nearby name, else og:site_name fallback
            author_link = soup.select_one('a[href^="/users/"], a[data-gtm-value][href*="/users/"]')
            author_id = extract_user_id_from_url(author_link.get("href", "")) if author_link else 0

            author_name = "Unknown"
            # Try multiple selectors for author name
            author_name_elem = soup.select_one('.sc-76df3bd1-6, .hzQYGJ, a[data-gtm-value][href^="/users/"] div')
            if author_name_elem and author_name_elem.get_text(strip=True):
                author_name = author_name_elem.get_text(strip=True)
            else:
                # Alternative: try to get from meta
                og_site = meta_content('meta[property="og:site_name"]')
                if og_site:
                    author_name = og_site

            # Author avatar
            author_avatar = soup.select_one('a[href^="/users/"] img, .sc-653b72c8-0 img, div[role="img"] img')
            avatar_url = author_avatar.get("src") if author_avatar else None

            author = AuthorInfo(id=author_id, name=author_name, avatar_url=avatar_url)

            # Images: use improved extraction
            images = self._extract_images_from_html(soup)
            
            # Fallback to og:image if no images found
            if not images:
                og_image = meta_content('meta[property="og:image"]')
                if og_image:
                    images.append(ImageInfo(url=og_image, thumbnail=og_image))

            # Tags: multiple selectors
            tag_links = soup.select('a.gtm-new-work-tag-event-click, a[href*="/tags/"], .sc-2af5a06c-0 a')
            tags = []
            for a in tag_links:
                tag_text = a.get_text(strip=True)
                if tag_text and tag_text not in tags:
                    tags.append(tag_text)

            # Stats: improved extraction with multiple selectors
            likes = bookmarks = views = 0
            
            # Try primary selector
            stat_elements = soup.select('dl.sc-222c3018-1 dd, ul.sc-222c3018-0 dd')
            if len(stat_elements) >= 3:
                likes = parse_stat_number(stat_elements[0].get_text(strip=True))
                bookmarks = parse_stat_number(stat_elements[1].get_text(strip=True))
                views = parse_stat_number(stat_elements[2].get_text(strip=True))
            else:
                # Alternative: try individual icons/titles
                like_elem = soup.select_one('dd[title="いいね！"], dd[title*="like"]')
                bookmark_elem = soup.select_one('dd[title="ブックマーク"], dd[title*="bookmark"]')
                view_elem = soup.select_one('dd[title="閲覧数"], dd[title*="view"]')
                
                if like_elem:
                    likes = parse_stat_number(like_elem.get_text(strip=True))
                if bookmark_elem:
                    bookmarks = parse_stat_number(bookmark_elem.get_text(strip=True))
                if view_elem:
                    views = parse_stat_number(view_elem.get_text(strip=True))

            stats = ArtworkStats(likes=likes, bookmarks=bookmarks, views=views)

            # Created date
            created_at = None
            time_elem = soup.select_one("time[datetime]")
            if time_elem and time_elem.get("datetime"):
                try:
                    created_at = datetime.fromisoformat(time_elem.get("datetime").replace("Z", "+00:00"))
                except Exception:
                    created_at = None

            # R-18 detection
            is_r18 = bool(soup.select_one('.sc-d71ae5c0-0, [class*="R-18"]')) or "R-18" in tags

            # Description
            description = ""
            desc_elem = soup.select_one('p.sc-fcc502d1-1, p[id*="expandable-paragraph"]')
            if desc_elem:
                description = desc_elem.get_text(strip=True)

            return ArtworkResponse(
                id=artwork_id,
                title=title,
                author=author,
                images=images,
                tags=tags,
                stats=stats,
                created_at=created_at,
                is_r18=is_r18,
                page_count=max(1, len(images)) if images else 0,
                description=description,
                related_artworks=[],
            )
        except Exception as e:
            logger.error(f"Error parsing artwork from HTML: {str(e)}", exc_info=True)
            return None

    async def get_artwork(self, artwork_id: int) -> Optional[ArtworkResponse]:
        url = self.ARTWORK_URL_TEMPLATE.format(artwork_id)
        logger.info(f"Fetching artwork from {url}")

        html = await self.fetch_html(url)
        if not html:
            return None

        # 1) meta-preload-data
        meta_data = self.extract_meta_preload_json(html)
        if meta_data:
            artwork = self.parse_artwork_from_meta_preload(meta_data, artwork_id)
            if artwork:
                logger.info(f"Successfully parsed artwork {artwork_id} from meta-preload-data")
                return artwork

        # 2) __NEXT_DATA__
        next_data = self.extract_next_data_json(html)
        if next_data:
            artwork = self.parse_artwork_from_next_data(next_data, artwork_id)
            if artwork:
                logger.info(f"Successfully parsed artwork {artwork_id} from __NEXT_DATA__")
                return artwork

        # 3) Fallback: HTML
        logger.info(f"Falling back to HTML parsing for artwork {artwork_id}")
        artwork = self.parse_artwork_from_html(html, artwork_id)
        if artwork:
            logger.info(f"Successfully parsed artwork {artwork_id} from HTML")
        else:
            logger.warning(f"Failed to parse artwork {artwork_id}")
        return artwork
