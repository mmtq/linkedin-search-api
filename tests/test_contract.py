import unittest
from bs4 import BeautifulSoup

from app.models.schemas import (
    JobItem,
    PostItem,
    PostMedia,
    JobsResponse,
    PostsResponse,
    SearchResponse,
)
from app.services.parsers import (
    canonicalize_job_url,
    canonicalize_company_url,
    canonicalize_author_url,
    canonicalize_post_url,
    extract_post_urn_and_id,
    extract_body_links,
    extract_post_media,
    parse_jobs_html,
    parse_posts_html,
)
from app.main import app


class TestCanonicalizationHelpers(unittest.TestCase):
    """Unit tests for the id/url canonicalization helpers using small examples."""

    def test_canonicalize_job_url_with_numeric_id(self):
        # Known job_id takes precedence and produces canonical form without params
        raw = "https://www.linkedin.com/jobs/view/4468072140/?eBP=NON_CHARGEABLE&refId=abc%3D%3D"
        result = canonicalize_job_url(raw_url=raw, job_id="4468072140")
        self.assertEqual(result, "https://www.linkedin.com/jobs/view/4468072140")

    def test_canonicalize_job_url_without_job_id(self):
        # When job_id is None, strip query parameters
        raw = "https://www.linkedin.com/jobs/view/9999999999/?trackingId=123"
        result = canonicalize_job_url(raw_url=raw, job_id=None)
        self.assertEqual(result, "https://www.linkedin.com/jobs/view/9999999999")

    def test_canonicalize_job_url_relative_path(self):
        raw = "/jobs/view/4468072140/?refId=abc"
        result = canonicalize_job_url(raw_url=raw, job_id=None)
        self.assertEqual(result, "https://www.linkedin.com/jobs/view/4468072140")

    def test_canonicalize_company_url(self):
        raw = "https://www.linkedin.com/company/inovetix/life?trk=feed"
        result = canonicalize_company_url(raw)
        self.assertEqual(result, "https://www.linkedin.com/company/inovetix")

        # Plain company URL with trailing slash and query param
        raw2 = "https://www.linkedin.com/company/google/?trk=org"
        self.assertEqual(canonicalize_company_url(raw2), "https://www.linkedin.com/company/google")

        # Relative path
        raw3 = "/company/meta/about/"
        self.assertEqual(canonicalize_company_url(raw3), "https://www.linkedin.com/company/meta")

    def test_canonicalize_author_url(self):
        raw = "https://www.linkedin.com/in/manjunath-m-32702a291/?miniProfileUrn=urn%3Ali%3Afs_miniProfile%3A123"
        result = canonicalize_author_url(raw)
        self.assertEqual(result, "https://www.linkedin.com/in/manjunath-m-32702a291")

        raw_showcase = "https://www.linkedin.com/showcase/basingstoke-jobs-hampshire/?trk=view"
        self.assertEqual(canonicalize_author_url(raw_showcase), "https://www.linkedin.com/showcase/basingstoke-jobs-hampshire")

    def test_extract_post_urn_and_id(self):
        # Activity URN
        raw1 = '<div data-urn="urn:li:activity:7123456789012345678">...</div>'
        urn1, id1 = extract_post_urn_and_id(raw1)
        self.assertEqual(urn1, "urn:li:activity:7123456789012345678")
        self.assertEqual(id1, "7123456789012345678")

        # UGC Post URN
        raw2 = "shareId=0&highlightedUpdateUrn=urn%3Ali%3AugcPost%3A9876543210987654321"
        urn2, id2 = extract_post_urn_and_id(raw2)
        self.assertEqual(urn2, "urn:li:ugcPost:9876543210987654321")
        self.assertEqual(id2, "9876543210987654321")

        # No match
        urn3, id3 = extract_post_urn_and_id("<div>Plain post without urn</div>")
        self.assertIsNone(urn3)
        self.assertIsNone(id3)

    def test_canonicalize_post_url(self):
        # With URN
        url1 = canonicalize_post_url(post_urn="urn:li:activity:7123456789012345678")
        self.assertEqual(url1, "https://www.linkedin.com/feed/update/urn:li:activity:7123456789012345678/")

        # Fallback to raw permalink with query string removed
        url2 = canonicalize_post_url(raw_url="https://www.linkedin.com/feed/update/urn:li:share:123/?trk=feed")
        self.assertEqual(url2, "https://www.linkedin.com/feed/update/urn:li:share:123/")

        # Fallback to author recent activity
        url3 = canonicalize_post_url(author_url="https://www.linkedin.com/in/john-doe/?miniProfile=1")
        self.assertEqual(url3, "https://www.linkedin.com/in/john-doe/recent-activity/all/")

    def test_extract_body_links(self):
        html = """
        <div data-testid="expandable-text-box">
            Apply at <a href="https://example.com/jobs?source=linkedin">Job Link</a>
            or email <a href="mailto:jobs@example.com">jobs@example.com</a>
            Redirect: <a href="https://www.linkedin.com/safety/go/?url=https%3A%2F%2Flnkd.in%2Ftest123&trk=safe">lnkd.in</a>
            Duplicate: <a href="https://example.com/jobs?source=other">Job Link</a>
        </div>
        """
        soup = BeautifulSoup(html, "html.parser")
        links = extract_body_links(soup.select_one('[data-testid="expandable-text-box"]'))
        self.assertEqual(links, [
            "https://example.com/jobs",
            "mailto:jobs@example.com",
            "https://lnkd.in/test123",
        ])

    def test_extract_post_media(self):
        html = """
        <div class="card">
            <!-- Profile avatar: should be ignored -->
            <img src="https://media.licdn.com/dms/image/v2/profile-displayphoto-shrink_100_100/123.jpg" alt="Avatar" />
            <!-- Attached feed image: should be included -->
            <img src="https://media.licdn.com/dms/image/v2/feedshare-shrink_480/B4D123.jpg" alt="View image" />
            <!-- Video -->
            <video src="https://dms.licdn.com/playlist/vid123.mp4"></video>
        </div>
        """
        soup = BeautifulSoup(html, "html.parser")
        media = extract_post_media(soup.select_one(".card"))
        self.assertEqual(len(media), 2)
        self.assertEqual(media[0], {
            "type": "image",
            "url": "https://media.licdn.com/dms/image/v2/feedshare-shrink_480/B4D123.jpg",
            "alt": "View image",
        })
        self.assertEqual(media[1], {
            "type": "video",
            "url": "https://dms.licdn.com/playlist/vid123.mp4",
            "alt": None,
        })


class TestBackwardCompatibility(unittest.TestCase):
    """Test that previous fields and their types are completely unchanged."""

    def test_job_item_backward_compatibility(self):
        # Instantiate JobItem with only the original fields
        job = JobItem(
            title="Senior Python Developer",
            company="Tech Corp",
            location="Remote",
            url="https://www.linkedin.com/jobs/view/12345678",
            description="Build scalable APIs with Python.",
        )
        data = job.model_dump()
        # Verify original fields
        self.assertEqual(data["title"], "Senior Python Developer")
        self.assertEqual(data["company"], "Tech Corp")
        self.assertEqual(data["location"], "Remote")
        self.assertEqual(data["url"], "https://www.linkedin.com/jobs/view/12345678")
        self.assertEqual(data["description"], "Build scalable APIs with Python.")

        # Verify all new fields are present and default to None
        self.assertIsNone(data["job_id"])
        self.assertIsNone(data["company_url"])
        self.assertIsNone(data["posted_text"])
        self.assertIsNone(data["posted_at"])
        self.assertIsNone(data["employment_type"])
        self.assertIsNone(data["seniority_level"])
        self.assertIsNone(data["workplace_type"])
        self.assertIsNone(data["page"])
        self.assertIsNone(data["scraped_at"])
        self.assertIsNone(data["job_function"])
        self.assertIsNone(data["industries"])
        self.assertIsNone(data["applicant_count_text"])
        self.assertIsNone(data["salary_text"])
        self.assertIsNone(data["apply_type"])
        self.assertIsNone(data["apply_url"])

    def test_post_item_backward_compatibility(self):
        # Instantiate PostItem with only original fields
        post = PostItem(
            author="Jane Smith",
            author_url="https://www.linkedin.com/in/janesmith",
            url="https://www.linkedin.com/feed/update/urn:li:activity:123/",
            text="We are hiring engineers!",
        )
        data = post.model_dump()
        # Verify original fields
        self.assertEqual(data["author"], "Jane Smith")
        self.assertEqual(data["author_url"], "https://www.linkedin.com/in/janesmith")
        self.assertEqual(data["url"], "https://www.linkedin.com/feed/update/urn:li:activity:123/")
        self.assertEqual(data["text"], "We are hiring engineers!")

        # Verify new fields default to None or empty lists
        self.assertIsNone(data["post_urn"])
        self.assertIsNone(data["post_id"])
        self.assertIsNone(data["author_headline"])
        self.assertIsNone(data["posted_text"])
        self.assertIsNone(data["posted_at"])
        self.assertIsNone(data["page"])
        self.assertIsNone(data["scraped_at"])
        self.assertEqual(data["links"], [])
        self.assertEqual(data["media"], [])
        self.assertIsNone(data["is_repost"])
        self.assertIsNone(data["original_author"])
        self.assertIsNone(data["original_url"])

    def test_response_envelopes_backward_compatibility(self):
        # JobsResponse
        jobs_resp = JobsResponse(
            query="python",
            location="global",
            sort_by="latest",
            pages_scraped=1,
            count=1,
            jobs=[JobItem(title="Developer", text="description")],
            status="ok",
            warnings=[],
            elapsed_seconds=1.234,
            started_at="2026-09-19T10:00:00Z",
        )
        data_j = jobs_resp.model_dump()
        self.assertEqual(data_j["query"], "python")
        self.assertEqual(data_j["count"], 1)
        self.assertEqual(data_j["status"], "ok")
        self.assertEqual(data_j["elapsed_seconds"], 1.234)

        # PostsResponse
        posts_resp = PostsResponse(
            query="hiring",
            sort_by="latest",
            pages_scraped=1,
            count=1,
            posts=[PostItem(text="Hello world")],
            status="ok",
            warnings=[],
            elapsed_seconds=0.987,
            started_at="2026-09-19T10:00:00Z",
        )
        data_p = posts_resp.model_dump()
        self.assertEqual(data_p["query"], "hiring")
        self.assertEqual(data_p["count"], 1)
        self.assertEqual(data_p["status"], "ok")


class TestOpenAPISchema(unittest.TestCase):
    """The OpenAPI schema (Pydantic models) must reflect the new fields."""

    def test_openapi_schema_contains_new_fields(self):
        schema = app.openapi()
        components = schema["components"]["schemas"]

        # JobItem fields
        job_props = components["JobItem"]["properties"]
        expected_job_fields = [
            "title", "company", "location", "url", "description",
            "job_id", "company_url", "posted_text", "posted_at",
            "employment_type", "seniority_level", "workplace_type",
            "page", "scraped_at", "job_function", "industries",
            "applicant_count_text", "salary_text", "apply_type", "apply_url",
        ]
        for f in expected_job_fields:
            self.assertIn(f, job_props, f"Missing field '{f}' in JobItem schema")

        # PostItem fields
        post_props = components["PostItem"]["properties"]
        expected_post_fields = [
            "author", "author_url", "url", "text",
            "post_urn", "post_id", "author_headline",
            "posted_text", "posted_at", "page", "scraped_at",
            "links", "media", "is_repost", "original_author", "original_url",
        ]
        for f in expected_post_fields:
            self.assertIn(f, post_props, f"Missing field '{f}' in PostItem schema")

        # Envelope fields on JobsResponse
        jobs_resp_props = components["JobsResponse"]["properties"]
        for f in ["status", "warnings", "elapsed_seconds", "started_at"]:
            self.assertIn(f, jobs_resp_props, f"Missing envelope field '{f}' in JobsResponse")

        # Envelope fields on PostsResponse
        posts_resp_props = components["PostsResponse"]["properties"]
        for f in ["status", "warnings", "elapsed_seconds", "started_at"]:
            self.assertIn(f, posts_resp_props, f"Missing envelope field '{f}' in PostsResponse")

        # Envelope fields on SearchResponse
        search_resp_props = components["SearchResponse"]["properties"]
        for f in ["status", "warnings", "elapsed_seconds", "started_at"]:
            self.assertIn(f, search_resp_props, f"Missing envelope field '{f}' in SearchResponse")


class TestHTMLParsingWithSavedExamples(unittest.TestCase):
    """Test parsing using realistic HTML snippets."""

    def test_parse_job_card_snippet(self):
        html_snippet = """
        <li data-occludable-job-id="4468072140" class="scaffold-layout__list-item">
            <div class="job-card-container" data-job-id="4468072140">
                <div class="artdeco-entity-lockup__title">
                    <a class="job-card-list__title--link" href="/jobs/view/4468072140/?trackingId=abc">
                        <strong>Lead Backend Engineer</strong>
                    </a>
                </div>
                <div class="artdeco-entity-lockup__subtitle">
                    <span>Acme Corp</span>
                </div>
                <div class="artdeco-entity-lockup__caption">
                    <span>San Francisco, CA (Hybrid)</span>
                </div>
                <ul class="job-card-list__footer-wrapper">
                    <li class="job-card-container__footer-item">
                        <time datetime="2026-09-19">3 days ago</time>
                    </li>
                    <li class="job-card-container__footer-item">
                        <span>Easy Apply</span>
                    </li>
                </ul>
            </div>
        </li>
        """
        jobs = parse_jobs_html(html_snippet, page_num=2)
        self.assertEqual(len(jobs), 1)
        j = jobs[0]
        self.assertEqual(j["title"], "Lead Backend Engineer")
        self.assertEqual(j["company"], "Acme Corp")
        self.assertEqual(j["location"], "San Francisco, CA (Hybrid)")
        self.assertEqual(j["workplace_type"], "Hybrid")
        self.assertEqual(j["job_id"], "4468072140")
        self.assertEqual(j["url"], "https://www.linkedin.com/jobs/view/4468072140")
        self.assertEqual(j["posted_text"], "3 days ago")
        self.assertEqual(j["posted_at"], "2026-09-19")
        self.assertEqual(j["apply_type"], "easy_apply")
        self.assertEqual(j["page"], 2)
        self.assertIsNotNone(j["scraped_at"])

    def test_parse_post_snippet(self):
        html_snippet = """
        <div role="listitem" class="feed-shared-update-v2" data-urn="urn:li:activity:7891234567891234567">
            <a href="https://www.linkedin.com/in/alice-dev/?miniProfileUrn=123" aria-label="View Alice Dev’s profile">
                <span>Alice Dev</span>
            </a>
            <div class="update-components-actor__description">
                <span>Senior Staff Architect</span>
            </div>
            <p>1h •</p>
            <div data-testid="expandable-text-box">
                Excited to announce our new open source project! Check it out:
                <a href="https://github.com/example/repo?branch=main">https://github.com/example/repo</a>
            </div>
            <img class="feedshare-shrink_480" src="https://media.licdn.com/dms/image/v2/feedshare-shrink_480/B4D.jpg" alt="Architecture Diagram" />
        </div>
        """
        posts = parse_posts_html(html_snippet, page_num=1)
        self.assertEqual(len(posts), 1)
        p = posts[0]
        self.assertEqual(p["author"], "Alice Dev")
        self.assertEqual(p["author_headline"], "Senior Staff Architect")
        self.assertEqual(p["author_url"], "https://www.linkedin.com/in/alice-dev")
        self.assertEqual(p["post_urn"], "urn:li:activity:7891234567891234567")
        self.assertEqual(p["post_id"], "7891234567891234567")
        self.assertEqual(p["url"], "https://www.linkedin.com/feed/update/urn:li:activity:7891234567891234567/")
        self.assertEqual(p["posted_text"], "1h")
        self.assertEqual(p["page"], 1)
        self.assertEqual(p["links"], ["https://github.com/example/repo"])
        self.assertEqual(len(p["media"]), 1)
        self.assertEqual(p["media"][0]["type"], "image")
        self.assertEqual(p["media"][0]["alt"], "Architecture Diagram")


if __name__ == "__main__":
    unittest.main()
