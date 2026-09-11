from typing import List, Optional
from pydantic import BaseModel, Field


class JobItem(BaseModel):
    title: Optional[str] = Field(None, description="Job title")
    company: Optional[str] = Field(None, description="Company name")
    location: Optional[str] = Field(None, description="Job location")
    url: Optional[str] = Field(None, description="LinkedIn job URL")
    description: Optional[str] = Field(None, description="Full job description text")


class JobsResponse(BaseModel):
    query: str
    location: str
    sort_by: str = Field("latest", description="Sort order used")
    pages_scraped: int = Field(..., description="Number of pages scraped")
    count: int = Field(..., description="Total unique jobs collected")
    jobs: List[JobItem]


class PostItem(BaseModel):
    author: Optional[str] = Field(None, description="Post author name")
    author_url: Optional[str] = Field(None, description="LinkedIn author profile URL")
    url: Optional[str] = Field(None, description="Navigable URL for this post/activity")
    text: str = Field(..., description="Post content text")


class PostsResponse(BaseModel):
    query: str
    sort_by: str = Field("latest", description="Sort order used")
    pages_scraped: int = Field(..., description="Number of pages scraped")
    count: int = Field(..., description="Total unique posts collected")
    posts: List[PostItem]


class SearchResponse(BaseModel):
    query: str
    location: str
    sort_by: str = Field("latest", description="Sort order used")
    pages_scraped: int = Field(..., description="Number of pages scraped per category")
    jobs_count: int
    posts_count: int
    jobs: List[JobItem]
    posts: List[PostItem]

