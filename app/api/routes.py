import asyncio
from typing import Optional
from fastapi import APIRouter, Query, HTTPException

from app.models.schemas import (
    JobsResponse,
    PostsResponse,
    SearchResponse,
    HealthResponse,
)
from app.services.linkedin_scraper import scraper_service
from app.core.browser import chrome_manager
from app.core.config import settings

router = APIRouter(prefix="/api", tags=["LinkedIn Search"])


@router.get("/jobs", response_model=JobsResponse)
async def get_jobs(
    query: str = Query("software engineer", description="Search keyword for jobs"),
    location: str = Query("Bangladesh", description="Location filter for jobs"),
    pages: int = Query(5, ge=1, le=10, description="Number of pages to scrape (e.g. 1 to 5)"),
    sort_by: str = Query("latest", pattern="^(latest|relevant)$", description="Sort order: 'latest' (Date Descending) or 'relevant'"),
    limit: Optional[int] = Query(None, ge=1, le=150, description="Optional cap on total jobs returned"),
):
    """
    Search for LinkedIn job postings across multiple pages sorted by most recent (or relevant).
    Browses with human-like progressive scrolling and non-uniform delays.
    """
    try:
        sort_latest = sort_by.lower() == "latest"
        jobs = await asyncio.to_thread(
            scraper_service.search_jobs,
            query=query,
            location=location,
            pages=pages,
            limit=limit,
            sort_by_latest=sort_latest,
        )
        return {
            "query": query,
            "location": location,
            "sort_by": sort_by,
            "pages_scraped": pages,
            "count": len(jobs),
            "jobs": jobs,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error scraping jobs: {str(e)}")


@router.get("/posts", response_model=PostsResponse)
async def get_posts(
    query: str = Query("software engineer", description="Search keyword for posts/content"),
    pages: int = Query(5, ge=1, le=10, description="Number of pages to scrape (e.g. 1 to 5)"),
    sort_by: str = Query("latest", pattern="^(latest|relevant)$", description="Sort order: 'latest' (Date Posted) or 'relevant'"),
    limit: Optional[int] = Query(None, ge=1, le=100, description="Optional cap on total posts returned"),
):
    """
    Search for LinkedIn posts and articles across multiple pages sorted by most recent (or relevant).
    Browses with human-like scrolling, 'Load more' triggering, and natural pauses.
    """
    try:
        sort_latest = sort_by.lower() == "latest"
        posts = await asyncio.to_thread(
            scraper_service.search_posts,
            query=query,
            pages=pages,
            limit=limit,
            sort_by_latest=sort_latest,
        )
        return {
            "query": query,
            "sort_by": sort_by,
            "pages_scraped": pages,
            "count": len(posts),
            "posts": posts,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error scraping posts: {str(e)}")


@router.get("/search", response_model=SearchResponse)
async def search_all(
    query: str = Query("software engineer", description="Search keyword for jobs and posts"),
    location: str = Query("Bangladesh", description="Location filter for jobs"),
    pages: int = Query(5, ge=1, le=10, description="Number of pages to scrape per category (1-5)"),
    sort_by: str = Query("latest", pattern="^(latest|relevant)$", description="Sort order: 'latest' or 'relevant'"),
    limit: Optional[int] = Query(None, ge=1, le=100, description="Optional cap per category"),
):
    """
    Simultaneously search for both jobs and posts across multiple pages sorted by latest.
    """
    try:
        sort_latest = sort_by.lower() == "latest"
        jobs = await asyncio.to_thread(
            scraper_service.search_jobs,
            query=query,
            location=location,
            pages=pages,
            limit=limit,
            sort_by_latest=sort_latest,
        )
        posts = await asyncio.to_thread(
            scraper_service.search_posts,
            query=query,
            pages=pages,
            limit=limit,
            sort_by_latest=sort_latest,
        )
        return {
            "query": query,
            "location": location,
            "sort_by": sort_by,
            "pages_scraped": pages,
            "jobs_count": len(jobs),
            "posts_count": len(posts),
            "jobs": jobs,
            "posts": posts,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error during combined search: {str(e)}")


@router.get("/health", response_model=HealthResponse, tags=["System"])
def get_health():
    """
    Health check endpoint verifying daemon, browser engine, and authentication status.
    """
    return {
        "status": "healthy",
        "browser_ready": chrome_manager.is_ready() or not settings.has_chrome_binary,
        "authenticated": bool(settings.get_li_at_cookie()),
    }
