import asyncio
import sys
from contextlib import asynccontextmanager
from typing import List, Optional

import uvicorn
from fastapi import FastAPI, Query, HTTPException
from pydantic import BaseModel, Field

from scraper import search_jobs, search_posts, chrome_manager

# Ensure UTF-8 output on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("\n" + "=" * 60)
    print("🚀 Starting background headless Chrome Dev daemon...")
    await asyncio.to_thread(chrome_manager.ensure_running)
    print("✅ Background Chrome Dev daemon is running and ready!")
    print("📖 Interactive API Docs available at: http://127.0.0.1:8000/docs")
    print("=" * 60 + "\n")
    yield
    print("\n--- Stopping background Chrome Dev daemon ---")
    await asyncio.to_thread(chrome_manager.stop)


app = FastAPI(
    title="LinkedIn Search & Scraping API",
    description="High-performance FastAPI service with a persistent headless Chrome browser daemon.",
    version="1.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------
# Pydantic Response Schemas
# ---------------------------------------------------------


class JobItem(BaseModel):
    title: Optional[str] = Field(None, description="Job title")
    company: Optional[str] = Field(None, description="Company name")
    location: Optional[str] = Field(None, description="Job location")
    url: Optional[str] = Field(None, description="LinkedIn job URL")


class JobsResponse(BaseModel):
    query: str
    location: str
    count: int
    jobs: List[JobItem]


class PostItem(BaseModel):
    author: Optional[str] = Field(None, description="Post author name")
    text: str = Field(..., description="Post content text")


class PostsResponse(BaseModel):
    query: str
    count: int
    posts: List[PostItem]


class SearchResponse(BaseModel):
    query: str
    location: str
    jobs_count: int
    posts_count: int
    jobs: List[JobItem]
    posts: List[PostItem]


# ---------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------


@app.get("/", tags=["General"])
def root():
    return {
        "service": "LinkedIn Scraping API",
        "status": "online",
        "browser_mode": "headless_daemon",
        "docs": "/docs",
        "endpoints": {
            "search_jobs": "/api/jobs?query=software%20engineer&location=Bangladesh&limit=10",
            "search_posts": "/api/posts?query=software%20engineer&limit=10",
            "combined_search": "/api/search?query=software%20engineer&location=Bangladesh&limit=10",
        },
    }


@app.get("/api/jobs", response_model=JobsResponse, tags=["LinkedIn Search"])
async def get_jobs(
    query: str = Query("software engineer", description="Search keyword for jobs"),
    location: str = Query("Bangladesh", description="Location filter for jobs"),
    limit: int = Query(10, ge=1, le=50, description="Max number of jobs to return"),
):
    """
    Search for LinkedIn job postings by keyword and location.
    Opens a fresh tab in the headless Chrome daemon, scrapes, and closes the tab.
    """
    try:
        jobs = await asyncio.to_thread(search_jobs, query=query, location=location, limit=limit)
        return {
            "query": query,
            "location": location,
            "count": len(jobs),
            "jobs": jobs,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error scraping jobs: {str(e)}")


@app.get("/api/posts", response_model=PostsResponse, tags=["LinkedIn Search"])
async def get_posts(
    query: str = Query("software engineer", description="Search keyword for posts/content"),
    limit: int = Query(10, ge=1, le=50, description="Max number of posts to return"),
):
    """
    Search for LinkedIn posts and articles by keyword.
    Opens a fresh tab in the headless Chrome daemon, scrapes, and closes the tab.
    """
    try:
        posts = await asyncio.to_thread(search_posts, query=query, limit=limit)
        return {
            "query": query,
            "count": len(posts),
            "posts": posts,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error scraping posts: {str(e)}")


@app.get("/api/search", response_model=SearchResponse, tags=["LinkedIn Search"])
async def search_all(
    query: str = Query("software engineer", description="Search keyword for jobs and posts"),
    location: str = Query("Bangladesh", description="Location filter for jobs"),
    limit: int = Query(10, ge=1, le=50, description="Max items per category"),
):
    """
    Simultaneously search for both jobs and posts with a single query.
    """
    try:
        jobs = await asyncio.to_thread(search_jobs, query=query, location=location, limit=limit)
        posts = await asyncio.to_thread(search_posts, query=query, limit=limit)
        return {
            "query": query,
            "location": location,
            "jobs_count": len(jobs),
            "posts_count": len(posts),
            "jobs": jobs,
            "posts": posts,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error during combined search: {str(e)}")


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)