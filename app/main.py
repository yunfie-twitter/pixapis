"""FastAPI application entry point for Pixiv API scraper."""

from fastapi import FastAPI, HTTPException, status, Query, Path
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
import logging
from contextlib import asynccontextmanager
from typing import Optional, List
import io

from app.models import ArtworkResponse, HealthResponse, ErrorResponse
from app.scraper import PixivScraper
from app.pixiv_api import PixivAppAPI
from app.config import settings

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize scraper and API client
scraper = PixivScraper()
api_client: Optional[PixivAppAPI] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    global api_client
    
    # Startup
    logger.info(f"Starting Pixiv API Service v{settings.version}")
    logger.info(f"Workers: {settings.api_workers}")
    logger.info(f"Cache enabled: {settings.redis_url is not None}")
    logger.info(f"Official API enabled: {settings.use_official_api}")
    
    # Initialize official API client if enabled and refresh_token is available
    if settings.use_official_api and settings.pixiv_refresh_token:
        try:
            api_client = PixivAppAPI(refresh_token=settings.pixiv_refresh_token)
            api_client.auth()
            logger.info("Official Pixiv API client initialized successfully")
        except Exception as e:
            logger.warning(f"Failed to initialize official API client: {e}")
            logger.warning("Will fallback to HTML scraping only")
            api_client = None
    else:
        logger.info("Official API disabled or refresh_token not set, using HTML scraping only")
    
    yield
    
    # Shutdown
    logger.info("Shutting down Pixiv API Service")
    await scraper.close()


app = FastAPI(
    title="Pixiv API",
    description="Pixiv artwork metadata and image URL extraction API with official API support",
    version=settings.version,
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """Health check endpoint."""
    return HealthResponse(
        status="ok",
        version=settings.version
    )


@app.get("/artworks/{artwork_id}", 
         response_model=ArtworkResponse, 
         responses={
             404: {"model": ErrorResponse, "description": "Artwork not found"},
             403: {"model": ErrorResponse, "description": "Access forbidden (R-18 or private)"},
             500: {"model": ErrorResponse, "description": "Scraping failed"},
         },
         tags=["Artworks"])
async def get_artwork(
    artwork_id: int = Path(..., description="Pixiv artwork ID"),
    force_scraping: bool = Query(False, description="Force HTML scraping instead of using API"),
    include_related: bool = Query(False, description="Include related artworks (requires API)")
):
    """Get artwork information by ID.
    
    Args:
        artwork_id: Pixiv artwork ID (e.g., 141733795)
        force_scraping: Force HTML scraping mode (bypass API)
        include_related: Include related artworks list
    
    Returns:
        ArtworkResponse with metadata and image URLs
    
    Raises:
        HTTPException: 404 if artwork not found, 403 if access forbidden, 500 on scraping error
    """
    try:
        logger.info(f"Fetching artwork {artwork_id}")
        artwork = None
        
        # Try official API first (if enabled and not forced to scrape)
        if not force_scraping and api_client:
            try:
                logger.info(f"Trying official API for artwork {artwork_id}")
                artwork = await api_client.get_artwork(artwork_id)
                if artwork:
                    logger.info(f"Successfully fetched artwork {artwork_id} from official API")
                    
                    # Get related artworks if requested
                    if include_related:
                        try:
                            related_data = api_client.illust_related(artwork_id)
                            related_ids = [
                                illust.get("id") 
                                for illust in related_data.get("illusts", [])[:10]
                                if illust.get("id")
                            ]
                            artwork.related_artworks = related_ids
                        except Exception as e:
                            logger.warning(f"Failed to fetch related artworks: {e}")
            except Exception as e:
                logger.warning(f"Official API failed for artwork {artwork_id}: {e}")
        
        # Fallback to HTML scraping
        if not artwork:
            logger.info(f"Using HTML scraping for artwork {artwork_id}")
            artwork = await scraper.get_artwork(artwork_id)
        
        if not artwork:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Artwork {artwork_id} not found"
            )
        
        return artwork
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching artwork {artwork_id}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch artwork: {str(e)}"
        )


@app.get("/artworks/{artwork_id}/pages/{page_number}",
         tags=["Artworks"],
         summary="Get specific page of multi-page artwork")
async def get_artwork_page(
    artwork_id: int = Path(..., description="Pixiv artwork ID"),
    page_number: int = Path(..., description="Page number (0-indexed)", ge=0)
):
    """Get specific page information from multi-page artwork.
    
    Returns only the URL and metadata for the specified page.
    """
    try:
        artwork = await scraper.get_artwork(artwork_id)
        
        if not artwork:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Artwork {artwork_id} not found"
            )
        
        if page_number >= len(artwork.images):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Page {page_number} does not exist (artwork has {len(artwork.images)} pages)"
            )
        
        return {
            "artwork_id": artwork_id,
            "page_number": page_number,
            "total_pages": len(artwork.images),
            "image": artwork.images[page_number]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching page {page_number} of artwork {artwork_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@app.get("/artworks/{artwork_id}/download",
         tags=["Artworks"],
         summary="Download artwork image(s)")
async def download_artwork(
    artwork_id: int = Path(..., description="Pixiv artwork ID"),
    page: Optional[int] = Query(None, description="Specific page to download (for multi-page artworks)", ge=0),
    thumbnail: bool = Query(False, description="Download thumbnail instead of original")
):
    """Download artwork image.
    
    For single-page artworks, downloads the image directly.
    For multi-page artworks, specify page parameter or get ZIP of all pages.
    """
    try:
        artwork = await scraper.get_artwork(artwork_id)
        
        if not artwork:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Artwork {artwork_id} not found"
            )
        
        if not artwork.images:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No images available for this artwork"
            )
        
        # Determine which image to download
        if page is not None:
            if page >= len(artwork.images):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Page {page} does not exist"
                )
            image = artwork.images[page]
        else:
            # Default to first image for single-page, or require page param for multi-page
            if len(artwork.images) > 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Multi-page artwork ({len(artwork.images)} pages). Specify 'page' parameter."
                )
            image = artwork.images[0]
        
        # Get URL (thumbnail or original)
        url = image.thumbnail if thumbnail and image.thumbnail else image.url
        
        if not url:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Image URL not available"
            )
        
        # Get filename
        filename = scraper.get_download_filename(url)
        
        # Return download info (client should download with proper headers)
        return {
            "artwork_id": artwork_id,
            "page": page or 0,
            "url": url,
            "filename": filename,
            "referer": f"https://www.pixiv.net/artworks/{artwork_id}",
            "note": "Use the provided URL with 'Referer' header set to download the image"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error preparing download for artwork {artwork_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@app.get("/ranking",
         tags=["Ranking"],
         summary="Get illustration ranking")
async def get_ranking(
    mode: str = Query("day", description="Ranking mode: day, week, month, day_male, day_female, week_original, week_rookie, day_manga"),
    date: Optional[str] = Query(None, description="Date in YYYY-MM-DD format"),
    offset: Optional[int] = Query(None, description="Pagination offset"),
):
    """Get illustration ranking.
    
    Requires official API to be enabled.
    """
    if not api_client:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Official API not available. Please set PIXIV_REFRESH_TOKEN."
        )
    
    try:
        result = api_client.illust_ranking(mode=mode, date=date, offset=offset)
        return result
    except Exception as e:
        logger.error(f"Error fetching ranking: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch ranking: {str(e)}"
        )


@app.get("/search",
         tags=["Search"],
         summary="Search illustrations")
async def search_illustrations(
    word: str = Query(..., description="Search keyword"),
    search_target: str = Query("partial_match_for_tags", description="Search target: partial_match_for_tags, exact_match_for_tags, title_and_caption"),
    sort: str = Query("date_desc", description="Sort order: date_desc, date_asc, popular_desc"),
    duration: Optional[str] = Query(None, description="Duration filter: within_last_day, within_last_week, within_last_month"),
    offset: Optional[int] = Query(None, description="Pagination offset"),
):
    """Search illustrations by keyword.
    
    Requires official API to be enabled.
    """
    if not api_client:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Official API not available. Please set PIXIV_REFRESH_TOKEN."
        )
    
    try:
        result = api_client.search_illust(
            word=word,
            search_target=search_target,
            sort=sort,
            duration=duration,
            offset=offset
        )
        return result
    except Exception as e:
        logger.error(f"Error searching illustrations: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to search illustrations: {str(e)}"
        )


@app.get("/users/{user_id}",
         tags=["Users"],
         summary="Get user detail")
async def get_user_detail(
    user_id: int = Path(..., description="Pixiv user ID"),
    force_scraping: bool = Query(False, description="Force Ajax scraping instead of API")
):
    """Get user detail information.
    
    Uses official API if available, falls back to Ajax endpoint.
    """
    try:
        # Try official API first
        if not force_scraping and api_client:
            try:
                result = api_client.user_detail(user_id)
                return result
            except Exception as e:
                logger.warning(f"Official API failed for user {user_id}: {e}")
        
        # Fallback to Ajax endpoint
        user_data = scraper.get_user_ajax(user_id)
        if user_data:
            return {"user": user_data}
        
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User {user_id} not found"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching user detail: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch user detail: {str(e)}"
        )


@app.get("/users/{user_id}/illusts",
         tags=["Users"],
         summary="Get user illustrations")
async def get_user_illustrations(
    user_id: int = Path(..., description="Pixiv user ID"),
    type: str = Query("illust", description="Content type: illust, manga"),
    offset: Optional[int] = Query(None, description="Pagination offset"),
):
    """Get user's illustration list.
    
    Requires official API to be enabled.
    """
    if not api_client:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Official API not available. Please set PIXIV_REFRESH_TOKEN."
        )
    
    try:
        result = api_client.user_illusts(user_id=user_id, type=type, offset=offset)
        return result
    except Exception as e:
        logger.error(f"Error fetching user illustrations: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch user illustrations: {str(e)}"
        )


@app.get("/recommended",
         tags=["Recommendations"],
         summary="Get recommended illustrations")
async def get_recommended(
    content_type: str = Query("illust", description="Content type: illust, manga"),
    include_ranking_label: bool = Query(True, description="Include ranking label"),
    offset: Optional[int] = Query(None, description="Pagination offset"),
):
    """Get recommended illustrations.
    
    Requires official API to be enabled.
    """
    if not api_client:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Official API not available. Please set PIXIV_REFRESH_TOKEN."
        )
    
    try:
        result = api_client.illust_recommended(
            content_type=content_type,
            include_ranking_label=include_ranking_label,
            offset=offset
        )
        return result
    except Exception as e:
        logger.error(f"Error fetching recommended illustrations: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch recommended illustrations: {str(e)}"
        )


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler."""
    logger.error(f"Unhandled exception: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=ErrorResponse(
            error="Internal server error",
            detail=str(exc)
        ).model_dump()
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
        log_level=settings.log_level.lower()
    )
