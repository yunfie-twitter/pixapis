"""Pixiv HTML scraper implementation."""

import httpx
from bs4 import BeautifulSoup
import re
import json
from typing import Optional, List, Dict, Any
from datetime import datetime
import logging
from functools import lru_cache

from app.models import (
    ArtworkResponse, AuthorInfo, ImageInfo, 
    ArtworkStats, RelatedArtwork
)
from app.config import settings
from app.utils import parse_stat_number, extract_user_id_from_url

logger = logging.getLogger(__name__)


class PixivScraper:
    """Scraper for Pixiv artwork pages."""
    
    BASE_URL = "https://www.pixiv.net"
    ARTWORK_URL_TEMPLATE = "https://www.pixiv.net/artworks/{}"
    
    def __init__(self):
        """Initialize scraper with HTTP client."""
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://www.pixiv.net/',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'ja,en-US;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }
        
        # Add Pixiv session cookie if available (for R-18 content)
        cookies = {}
        if settings.pixiv_session:
            cookies['PHPSESSID'] = settings.pixiv_session
        
        self.client = httpx.AsyncClient(
            headers=self.headers,
            cookies=cookies,
            timeout=30.0,
            follow_redirects=True
        )
    
    async def close(self):
        """Close HTTP client."""
        await self.client.aclose()
    
    async def fetch_html(self, url: str) -> Optional[str]:
        """Fetch HTML content from URL.
        
        Args:
            url: Target URL
            
        Returns:
            HTML content as string, or None on error
        """
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
    
    def extract_meta_json(self, html: str) -> Optional[Dict[str, Any]]:
        """Extract preload data from meta tag.
        
        Pixiv embeds artwork data in <meta id="meta-preload-data"> tag.
        
        Args:
            html: HTML content
            
        Returns:
            Parsed JSON data or None
        """
        try:
            soup = BeautifulSoup(html, 'lxml')
            meta_tag = soup.find('meta', {'id': 'meta-preload-data'})
            
            if meta_tag and meta_tag.get('content'):
                data = json.loads(meta_tag['content'])
                return data
            
            return None
        except Exception as e:
            logger.error(f"Error extracting meta JSON: {str(e)}")
            return None
    
    def parse_artwork_from_meta(self, meta_data: Dict[str, Any], artwork_id: int) -> Optional[ArtworkResponse]:
        """Parse artwork data from meta preload JSON.
        
        Args:
            meta_data: Parsed meta-preload-data content
            artwork_id: Artwork ID
            
        Returns:
            ArtworkResponse or None
        """
        try:
            # Extract artwork data from nested structure
            illust_key = str(artwork_id)
            if 'illust' not in meta_data or illust_key not in meta_data['illust']:
                return None
            
            illust = meta_data['illust'][illust_key]
            
            # Extract author info
            author = AuthorInfo(
                id=illust.get('userId', 0),
                name=illust.get('userName', 'Unknown'),
                avatar_url=illust.get('profileImageUrl')
            )
            
            # Extract images
            images = []
            page_count = illust.get('pageCount', 1)
            
            if page_count == 1:
                # Single image
                original_url = illust.get('urls', {}).get('original')
                thumb_url = illust.get('urls', {}).get('small')
                
                if original_url:
                    images.append(ImageInfo(
                        url=original_url,
                        thumbnail=thumb_url,
                        width=illust.get('width'),
                        height=illust.get('height')
                    ))
            else:
                # Multiple images (manga)
                base_url = illust.get('urls', {}).get('original', '')
                if base_url:
                    # Replace _p0 with _p{i} for each page
                    for i in range(page_count):
                        page_url = base_url.replace('_p0', f'_p{i}')
                        images.append(ImageInfo(
                            url=page_url,
                            thumbnail=None
                        ))
            
            # Extract tags
            tags = [tag.get('tag', '') for tag in illust.get('tags', {}).get('tags', [])]
            
            # Extract stats
            stats = ArtworkStats(
                likes=illust.get('likeCount', 0),
                bookmarks=illust.get('bookmarkCount', 0),
                views=illust.get('viewCount', 0)
            )
            
            # Parse datetime
            created_at = None
            if 'createDate' in illust:
                try:
                    created_at = datetime.fromisoformat(illust['createDate'].replace('Z', '+00:00'))
                except:
                    pass
            
            # Check R-18 rating
            is_r18 = illust.get('xRestrict', 0) > 0 or 'R-18' in tags
            
            return ArtworkResponse(
                id=artwork_id,
                title=illust.get('title', 'Untitled'),
                author=author,
                images=images,
                tags=tags,
                stats=stats,
                created_at=created_at,
                is_r18=is_r18,
                page_count=page_count,
                description=illust.get('description', ''),
                related_artworks=[]
            )
        
        except Exception as e:
            logger.error(f"Error parsing artwork from meta: {str(e)}", exc_info=True)
            return None
    
    def parse_artwork_from_html(self, html: str, artwork_id: int) -> Optional[ArtworkResponse]:
        """Fallback: Parse artwork from HTML structure.
        
        Args:
            html: HTML content
            artwork_id: Artwork ID
            
        Returns:
            ArtworkResponse or None
        """
        try:
            soup = BeautifulSoup(html, 'lxml')
            
            # Extract title
            title_elem = soup.select_one('h1.sc-965e5f82-3, h1')
            title = title_elem.get_text(strip=True) if title_elem else 'Untitled'
            
            # Extract author
            author_link = soup.select_one('a[href*="/users/"]')
            author_id = 0
            author_name = 'Unknown'
            
            if author_link:
                author_id = extract_user_id_from_url(author_link.get('href', ''))
                author_name_elem = soup.select_one('.sc-76df3bd1-6, a[data-gtm-value]')
                if author_name_elem:
                    author_name = author_name_elem.get_text(strip=True)
            
            author_avatar = soup.select_one('img[alt*="のイラスト"], .sc-653b72c8-0 img')
            avatar_url = author_avatar.get('src') if author_avatar else None
            
            author = AuthorInfo(
                id=author_id,
                name=author_name,
                avatar_url=avatar_url
            )
            
            # Extract images from meta og:image as fallback
            og_image = soup.select_one('meta[property="og:image"]')
            images = []
            
            if og_image:
                img_url = og_image.get('content')
                if img_url:
                    # Convert to original URL
                    original_url = img_url.replace('/c/250x250_80_a2/img-master/', '/img-original/')
                    original_url = re.sub(r'_master\d+\.', '_p0.', original_url)
                    original_url = re.sub(r'_square\d+\.', '_p0.', original_url)
                    
                    images.append(ImageInfo(
                        url=original_url,
                        thumbnail=img_url
                    ))
            
            # Extract tags
            tag_links = soup.select('a.gtm-new-work-tag-event-click, a[href*="/tags/"]')
            tags = [link.get_text(strip=True) for link in tag_links if link.get_text(strip=True)]
            
            # Extract stats
            stat_elements = soup.select('dl.sc-222c3018-1 dd, dd[title]')
            likes = bookmarks = views = 0
            
            if len(stat_elements) >= 3:
                likes = parse_stat_number(stat_elements[0].get_text(strip=True))
                bookmarks = parse_stat_number(stat_elements[1].get_text(strip=True))
                views = parse_stat_number(stat_elements[2].get_text(strip=True))
            
            stats = ArtworkStats(likes=likes, bookmarks=bookmarks, views=views)
            
            # Extract timestamp
            time_elem = soup.select_one('time[datetime]')
            created_at = None
            
            if time_elem:
                try:
                    created_at = datetime.fromisoformat(time_elem.get('datetime').replace('Z', '+00:00'))
                except:
                    pass
            
            # Check R-18
            is_r18 = bool(soup.select_one('.sc-d71ae5c0-0, [class*="R-18"]'))
            
            return ArtworkResponse(
                id=artwork_id,
                title=title,
                author=author,
                images=images,
                tags=tags,
                stats=stats,
                created_at=created_at,
                is_r18=is_r18,
                page_count=len(images),
                description='',
                related_artworks=[]
            )
        
        except Exception as e:
            logger.error(f"Error parsing artwork from HTML: {str(e)}", exc_info=True)
            return None
    
    async def get_artwork(self, artwork_id: int) -> Optional[ArtworkResponse]:
        """Get artwork information by ID.
        
        Args:
            artwork_id: Pixiv artwork ID
            
        Returns:
            ArtworkResponse or None if not found
        """
        url = self.ARTWORK_URL_TEMPLATE.format(artwork_id)
        logger.info(f"Fetching artwork from {url}")
        
        html = await self.fetch_html(url)
        if not html:
            return None
        
        # Try meta JSON first (more reliable)
        meta_data = self.extract_meta_json(html)
        if meta_data:
            artwork = self.parse_artwork_from_meta(meta_data, artwork_id)
            if artwork:
                logger.info(f"Successfully parsed artwork {artwork_id} from meta JSON")
                return artwork
        
        # Fallback to HTML parsing
        logger.info(f"Falling back to HTML parsing for artwork {artwork_id}")
        artwork = self.parse_artwork_from_html(html, artwork_id)
        
        if artwork:
            logger.info(f"Successfully parsed artwork {artwork_id} from HTML")
        else:
            logger.warning(f"Failed to parse artwork {artwork_id}")
        
        return artwork
