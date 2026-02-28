"""Utility functions for scraping and data processing."""

import re
from typing import Optional


def parse_stat_number(text: str) -> int:
    """Parse statistic numbers from text.
    
    Handles formats like:
    - '225'
    - '1,234'
    - '1.5K' -> 1500
    - '2.3M' -> 2300000
    
    Args:
        text: Text containing number
        
    Returns:
        Parsed integer value
    """
    if not text:
        return 0
    
    # Remove commas
    text = text.replace(',', '').strip()
    
    # Handle K (thousands)
    if 'K' in text.upper():
        try:
            num = float(text.upper().replace('K', ''))
            return int(num * 1000)
        except:
            return 0
    
    # Handle M (millions)
    if 'M' in text.upper():
        try:
            num = float(text.upper().replace('M', ''))
            return int(num * 1000000)
        except:
            return 0
    
    # Handle regular numbers
    try:
        return int(text)
    except:
        return 0


def extract_user_id_from_url(url: str) -> int:
    """Extract user ID from Pixiv user URL.
    
    Args:
        url: URL like '/users/12345' or 'https://www.pixiv.net/users/12345'
        
    Returns:
        User ID as integer, or 0 if not found
    """
    if not url:
        return 0
    
    match = re.search(r'/users/(\d+)', url)
    if match:
        return int(match.group(1))
    
    return 0


def extract_artwork_id_from_url(url: str) -> Optional[int]:
    """Extract artwork ID from Pixiv artwork URL.
    
    Args:
        url: URL like '/artworks/12345' or 'https://www.pixiv.net/artworks/12345'
        
    Returns:
        Artwork ID as integer, or None if not found
    """
    if not url:
        return None
    
    match = re.search(r'/artworks/(\d+)', url)
    if match:
        return int(match.group(1))
    
    return None


def sanitize_filename(filename: str) -> str:
    """Sanitize filename by removing invalid characters.
    
    Args:
        filename: Original filename
        
    Returns:
        Sanitized filename safe for filesystem
    """
    # Remove or replace invalid characters
    invalid_chars = r'[<>:"/\\|?*]'
    sanitized = re.sub(invalid_chars, '_', filename)
    
    # Limit length
    if len(sanitized) > 255:
        sanitized = sanitized[:255]
    
    return sanitized
