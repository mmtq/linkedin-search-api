import asyncio
import time
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Query, HTTPException

from app.models.schemas import (
    JobsResponse,
    PostsResponse,
    SearchResponse,
)
from app.services.linkedin_scraper import scraper_service
from app.core.exceptions import SessionExpiredException, ScraperNavigationError

router = APIRouter(prefix="/api", tags=["LinkedIn Search"])


# ---------------------------------------------------------------------------
# Shared error handler helpers
# ---------------------------------------------------------------------------

SESSION_EXPIRED_HINT = (
    "LinkedIn session is unusable (logged out, expired, blocked, or verification required). "
    "Re-authenticate by running `python login.py` on the server and restarting. "
    "If using li_at.txt fallback: update it with a fresh cookie from your browser."
)


def _handle_scraper_error(e: Exception, context: str) -> None:
    """
    Converts known scraper exceptions into appropriate HTTP errors.
    Returns HTTP 503 when the session is unusable or navigation fails.
    Falls through to a generic 500 for unexpected errors.
    """
    if isinstance(e, SessionExpiredException):
        print(f"🔒 [AUTH ERROR] {context}: {e}", flush=True)
        raise HTTPException(
            status_code=503,
            detail={
                "error": "session_unusable",
                "message": SESSION_EXPIRED_HINT,
                "redirect_url": e.redirect_url or None,
            },
        )
    if isinstance(e, ScraperNavigationError):
        print(f"🌐 [NAV ERROR] {context}: {e}", flush=True)
        raise HTTPException(
            status_code=503,
            detail={
                "error": "navigation_failed",
                "message": f"LinkedIn navigation error: {e.cause}",
                "url": e.url,
            },
        )
    # Unexpected error
    print(f"❌ [ERROR] {context}: {e}", flush=True)
    raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

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
    print(f"💼 [JOBS REQUEST] Query='{query}' | Location='{location}' | Pages={pages} | Limit={limit} | Sort={sort_by}", flush=True)
    started_at = datetime.now(timezone.utc).isoformat()
    t0 = time.perf_counter()
    warnings = []

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
        count = len(jobs)
        status = "empty" if count == 0 else "ok"
        elapsed = round(time.perf_counter() - t0, 3)
        print(f"💼 [JOBS COMPLETE] Found {count} jobs successfully in {elapsed}s.", flush=True)
        return {
            "query": query,
            "location": location,
            "sort_by": sort_by,
            "pages_scraped": pages,
            "count": count,
            "jobs": jobs,
            "status": status,
            "warnings": warnings,
            "elapsed_seconds": elapsed,
            "started_at": started_at,
        }
    except (SessionExpiredException, ScraperNavigationError) as e:
        _handle_scraper_error(e, f"JOBS query='{query}'")
    except Exception as e:
        _handle_scraper_error(e, f"JOBS query='{query}'")


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
    print(f"📝 [POSTS REQUEST] Query='{query}' | Pages={pages} | Limit={limit} | Sort={sort_by}", flush=True)
    started_at = datetime.now(timezone.utc).isoformat()
    t0 = time.perf_counter()
    warnings = []

    try:
        sort_latest = sort_by.lower() == "latest"
        posts = await asyncio.to_thread(
            scraper_service.search_posts,
            query=query,
            pages=pages,
            limit=limit,
            sort_by_latest=sort_latest,
        )
        count = len(posts)
        status = "empty" if count == 0 else "ok"
        elapsed = round(time.perf_counter() - t0, 3)
        print(f"📝 [POSTS COMPLETE] Found {count} posts successfully in {elapsed}s.", flush=True)
        return {
            "query": query,
            "sort_by": sort_by,
            "pages_scraped": pages,
            "count": count,
            "posts": posts,
            "status": status,
            "warnings": warnings,
            "elapsed_seconds": elapsed,
            "started_at": started_at,
        }
    except (SessionExpiredException, ScraperNavigationError) as e:
        _handle_scraper_error(e, f"POSTS query='{query}'")
    except Exception as e:
        _handle_scraper_error(e, f"POSTS query='{query}'")


@router.get("/search", response_model=SearchResponse)
async def search_all(
    query: str = Query("software engineer", description="Search keyword for both jobs and posts"),
    location: str = Query("Bangladesh", description="Location filter for jobs"),
    pages: int = Query(5, ge=1, le=10, description="Pages to scrape per category"),
    sort_by: str = Query("latest", pattern="^(latest|relevant)$", description="'latest' or 'relevant'"),
    limit: Optional[int] = Query(None, ge=1, le=100, description="Optional cap per category"),
):
    """
    Search jobs AND posts simultaneously in parallel.
    Both scrapers run in separate threads concurrently via asyncio.gather,
    cutting total response time roughly in half versus sequential execution.
    """
    print(f"🔎 [SEARCH] Query='{query}' | Location='{location}' | Pages={pages} | Limit={limit} | Sort={sort_by}", flush=True)
    started_at = datetime.now(timezone.utc).isoformat()
    t0 = time.perf_counter()
    warnings = []
    sort_latest = sort_by.lower() == "latest"

    try:
        jobs, posts = await asyncio.gather(
            asyncio.to_thread(
                scraper_service.search_jobs,
                query=query,
                location=location,
                pages=pages,
                limit=limit,
                sort_by_latest=sort_latest,
            ),
            asyncio.to_thread(
                scraper_service.search_posts,
                query=query,
                pages=pages,
                limit=limit,
                sort_by_latest=sort_latest,
            ),
        )
        total = len(jobs) + len(posts)
        status = "empty" if total == 0 else "ok"
        elapsed = round(time.perf_counter() - t0, 3)
        print(f"🔎 [SEARCH DONE] {len(jobs)} jobs + {len(posts)} posts in {elapsed}s.", flush=True)
        return {
            "query": query,
            "location": location,
            "sort_by": sort_by,
            "pages_scraped": pages,
            "jobs_count": len(jobs),
            "posts_count": len(posts),
            "jobs": jobs,
            "posts": posts,
            "status": status,
            "warnings": warnings,
            "elapsed_seconds": elapsed,
            "started_at": started_at,
        }
    except (SessionExpiredException, ScraperNavigationError, Exception) as e:
        _handle_scraper_error(e, f"SEARCH query='{query}'")
