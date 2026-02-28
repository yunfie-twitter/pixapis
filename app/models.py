"""Pydantic models for API request/response validation."""

from pydantic import BaseModel, Field, HttpUrl
from typing import List, Optional
from datetime import datetime


class AuthorInfo(BaseModel):
    """Author/artist information."""
    id: int = Field(..., description="Pixiv user ID")
    name: str = Field(..., description="User display name")
    avatar_url: Optional[HttpUrl] = Field(None, description="Profile image URL")


class ImageInfo(BaseModel):
    """Image URL information."""
    url: HttpUrl = Field(..., description="Original/full-size image URL")
    thumbnail: Optional[HttpUrl] = Field(None, description="Thumbnail image URL")
    width: Optional[int] = Field(None, description="Image width in pixels")
    height: Optional[int] = Field(None, description="Image height in pixels")


class ArtworkStats(BaseModel):
    """Artwork statistics."""
    likes: int = Field(0, description="Number of likes (いいね)")
    bookmarks: int = Field(0, description="Number of bookmarks")
    views: int = Field(0, description="Number of views")


class RelatedArtwork(BaseModel):
    """Related/recommended artwork info."""
    id: int = Field(..., description="Artwork ID")
    title: str = Field(..., description="Artwork title")
    thumbnail: HttpUrl = Field(..., description="Thumbnail URL")
    author_id: int = Field(..., description="Author user ID")


class ArtworkResponse(BaseModel):
    """Complete artwork information response."""
    id: int = Field(..., description="Pixiv artwork ID")
    title: str = Field(..., description="Artwork title")
    author: AuthorInfo = Field(..., description="Author information")
    images: List[ImageInfo] = Field(..., description="List of image URLs (multiple for manga/series)")
    tags: List[str] = Field(default_factory=list, description="List of tags")
    stats: ArtworkStats = Field(..., description="Engagement statistics")
    created_at: Optional[datetime] = Field(None, description="Upload timestamp (ISO 8601)")
    is_r18: bool = Field(False, description="Whether artwork is R-18 rated")
    page_count: int = Field(1, description="Number of pages/images")
    description: Optional[str] = Field(None, description="Artwork description/caption")
    related_artworks: List[RelatedArtwork] = Field(default_factory=list, description="Related artworks")

    class Config:
        json_schema_extra = {
            "example": {
                "id": 141733795,
                "title": "2/28はビスケットの日!",
                "author": {
                    "id": 68480688,
                    "name": "妖夢くん",
                    "avatar_url": "https://i.pximg.net/user-profile/img/2023/03/03/11/18/07/24102903_8946584d254cd4ce034203c320fdf07b_50.png"
                },
                "images": [
                    {
                        "url": "https://i.pximg.net/img-original/img/2026/02/28/17/33/10/141733795_p0.jpg",
                        "thumbnail": "https://i.pximg.net/c/250x250_80_a2/img-master/img/2026/02/28/17/33/10/141733795_p0_square1200.jpg"
                    }
                ],
                "tags": ["東方", "東方Project", "アリス・マーガトロイド"],
                "stats": {
                    "likes": 225,
                    "bookmarks": 308,
                    "views": 2146
                },
                "created_at": "2026-02-28T08:33:00Z",
                "is_r18": False,
                "page_count": 1
            }
        }


class HealthResponse(BaseModel):
    """Health check response."""
    status: str = Field(..., description="Service status")
    version: str = Field(..., description="API version")


class ErrorResponse(BaseModel):
    """Error response model."""
    error: str = Field(..., description="Error type")
    detail: str = Field(..., description="Detailed error message")
