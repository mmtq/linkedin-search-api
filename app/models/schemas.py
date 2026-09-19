from typing import List, Optional, Literal
from pydantic import BaseModel, Field


class PostMedia(BaseModel):
    type: Literal["image", "video", "document"] = Field(..., description="Media type: image, video, or document")
    url: Optional[str] = Field(None, description="Media direct URL")
    alt: Optional[str] = Field(None, description="Alt text or description of the media")


class JobItem(BaseModel):
    # Core existing fields (backward compatible)
    title: Optional[str] = Field(None, description="Job title")
    company: Optional[str] = Field(None, description="Company name")
    location: Optional[str] = Field(None, description="Job location")
    url: Optional[str] = Field(None, description="Canonical LinkedIn job URL without query parameters")
    description: Optional[str] = Field(None, description="Full job description text")

    # New optional fields
    job_id: Optional[str] = Field(None, description="Numeric LinkedIn job ID as a string")
    company_url: Optional[str] = Field(None, description="LinkedIn company page URL without query parameters")
    posted_text: Optional[str] = Field(None, description="Posting date as displayed, e.g. '2 days ago'")
    posted_at: Optional[str] = Field(None, description="ISO-8601 UTC date/time if directly available on page")
    employment_type: Optional[str] = Field(None, description="Employment type as displayed, e.g. 'Full-time'")
    seniority_level: Optional[str] = Field(None, description="Seniority level as displayed")
    workplace_type: Optional[str] = Field(None, description="Workplace type as displayed, e.g. 'Hybrid', 'Remote', 'On-site'")
    page: Optional[int] = Field(None, description="1-based results page the item came from")
    scraped_at: Optional[str] = Field(None, description="ISO-8601 UTC time the item was read")

    # Lower priority optional fields
    job_function: Optional[str] = Field(None, description="Job function if present")
    industries: Optional[str] = Field(None, description="Industries if present")
    applicant_count_text: Optional[str] = Field(None, description="Applicant count as displayed, e.g. '31 applicants'")
    salary_text: Optional[str] = Field(None, description="Salary text as displayed")
    apply_type: Optional[Literal["easy_apply", "external"]] = Field(None, description="Application type: 'easy_apply' or 'external'")
    apply_url: Optional[str] = Field(None, description="Direct application URL if directly present without extra request")


class JobsResponse(BaseModel):
    query: str
    location: str
    sort_by: str = Field("latest", description="Sort order used")
    pages_scraped: int = Field(..., description="Number of pages scraped")
    count: int = Field(..., description="Total unique jobs collected")
    jobs: List[JobItem]

    # Response envelope additions
    status: Literal["ok", "partial", "empty"] = Field("ok", description="Search status: 'ok', 'partial', or 'empty'")
    warnings: List[str] = Field(default_factory=list, description="Warnings encountered during search")
    elapsed_seconds: float = Field(..., description="Execution time in seconds")
    started_at: str = Field(..., description="ISO-8601 UTC timestamp when search started")


class PostItem(BaseModel):
    # Core existing fields (backward compatible)
    author: Optional[str] = Field(None, description="Post author name")
    author_url: Optional[str] = Field(None, description="LinkedIn author profile URL without query string")
    url: Optional[str] = Field(None, description="Canonical permalink or activity URL for this post without query string")
    text: str = Field(..., description="Post content text")

    # New optional fields
    post_urn: Optional[str] = Field(None, description="Post URN (e.g. urn:li:activity:7123456789012345678)")
    post_id: Optional[str] = Field(None, description="Numeric digits of the post URN")
    author_headline: Optional[str] = Field(None, description="Author headline as displayed")
    posted_text: Optional[str] = Field(None, description="Posting date as displayed, e.g. '21m'")
    posted_at: Optional[str] = Field(None, description="ISO-8601 UTC date/time if directly available on page")
    page: Optional[int] = Field(None, description="1-based results page the item came from")
    scraped_at: Optional[str] = Field(None, description="ISO-8601 UTC time the item was read")
    links: List[str] = Field(default_factory=list, description="External hrefs inside post body (de-duplicated, ordered)")
    media: List[PostMedia] = Field(default_factory=list, description="Media items inside post")

    # Lower priority optional fields
    is_repost: Optional[bool] = Field(None, description="Whether this post is a repost")
    original_author: Optional[str] = Field(None, description="Original author name if a repost")
    original_url: Optional[str] = Field(None, description="Original post URL if a repost")


class PostsResponse(BaseModel):
    query: str
    sort_by: str = Field("latest", description="Sort order used")
    pages_scraped: int = Field(..., description="Number of pages scraped")
    count: int = Field(..., description="Total unique posts collected")
    posts: List[PostItem]

    # Response envelope additions
    status: Literal["ok", "partial", "empty"] = Field("ok", description="Search status: 'ok', 'partial', or 'empty'")
    warnings: List[str] = Field(default_factory=list, description="Warnings encountered during search")
    elapsed_seconds: float = Field(..., description="Execution time in seconds")
    started_at: str = Field(..., description="ISO-8601 UTC timestamp when search started")


class SearchResponse(BaseModel):
    query: str
    location: str
    sort_by: str = Field("latest", description="Sort order used")
    pages_scraped: int = Field(..., description="Number of pages scraped per category")
    jobs_count: int
    posts_count: int
    jobs: List[JobItem]
    posts: List[PostItem]

    # Response envelope additions
    status: Literal["ok", "partial", "empty"] = Field("ok", description="Search status: 'ok', 'partial', or 'empty'")
    warnings: List[str] = Field(default_factory=list, description="Warnings encountered during search")
    elapsed_seconds: float = Field(..., description="Execution time in seconds")
    started_at: str = Field(..., description="ISO-8601 UTC timestamp when search started")
