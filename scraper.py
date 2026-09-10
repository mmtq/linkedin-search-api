"""
Backward compatibility proxy module.
Core implementation has moved to `app/services/linkedin_scraper.py` and `app/core/browser.py`.
"""

from app.services.linkedin_scraper import (
    search_jobs,
    search_posts,
    build_jobs_url,
    build_posts_url,
    scraper_service,
)
from app.services.parsers import parse_jobs_html as parse_jobs, parse_posts_html as parse_posts
from app.core.browser import chrome_manager
from app.core.config import settings

CDP_URL = settings.CDP_URL

__all__ = [
    "search_jobs",
    "search_posts",
    "parse_jobs",
    "parse_posts",
    "build_jobs_url",
    "build_posts_url",
    "chrome_manager",
    "scraper_service",
    "CDP_URL",
]
