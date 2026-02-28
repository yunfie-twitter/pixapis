"""FastAPI application entry point for Pixiv API scraper."""

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import logging
from contextlib import asynccontextmanager

from app.models import ArtworkResponse, HealthResponse, ErrorResponse
from app.scraper import PixivScraper
from app.config import settings

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize scraper instance
scraper = PixivScraper()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Startup
    logger.info(f"Starting Pixiv API Service v{settings.version}")
    logger.info(f"Workers: {settings.api_workers}")
    logger.info(f"Cache enabled: {settings.redis_url is not None}")
    
    yield
    
    # Shutdown
    logger.info("Shutting down Pixiv API Service")
    await scraper.close()


app = FastAPI(
    title="Pixiv API",
    description="Pixiv artwork metadata and image URL extraction API",
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
async def get_artwork(artwork_id: int):
    """Get artwork information by ID.
    
    Args:
        artwork_id: Pixiv artwork ID (e.g., 141733795)
    
    Returns:
        ArtworkResponse with metadata and image URLs
    
    Raises:
        HTTPException: 404 if artwork not found, 403 if access forbidden, 500 on scraping error
    """
    try:
        logger.info(f"Fetching artwork {artwork_id}")
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
