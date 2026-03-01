"""Application configuration."""

import os
from typing import Optional
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings."""

    # API settings
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_workers: int = 4
    version: str = "1.0.0"

    # Pixiv authentication (for HTML scraping)
    pixiv_session: Optional[str] = None

    # Pixiv official API settings
    pixiv_refresh_token: Optional[str] = None
    use_official_api: bool = True  # Prefer official API over HTML scraping

    # Cache settings
    redis_url: Optional[str] = None
    cache_ttl: int = 3600

    # Logging
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


settings = Settings()
