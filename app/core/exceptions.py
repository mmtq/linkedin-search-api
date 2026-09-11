"""
Custom exception hierarchy for the LinkedIn Scraper API.
"""


class LinkedInScraperError(Exception):
    """Base class for all scraper errors."""
    pass


class SessionExpiredException(LinkedInScraperError):
    """
    Raised when the LinkedIn session is expired, invalid, or requires re-authentication.

    This happens when:
    - li_at cookie is expired or revoked by LinkedIn
    - The browser was redirected to /login, /authwall, or /checkpoint
    - ERR_TOO_MANY_REDIRECTS persists after retry (classic expired-session symptom)

    Resolution:
    - If running locally: run `python login.py` to re-authenticate
    - If running on VPS: re-run login.py locally and scp the profile folder back
    - If using li_at.txt fallback: update li_at.txt with a fresh cookie from your browser
    """
    def __init__(self, redirect_url: str = "", detail: str = ""):
        self.redirect_url = redirect_url
        self.detail = detail or (
            f"LinkedIn session expired or invalid. "
            f"{'Redirected to: ' + redirect_url + '. ' if redirect_url else ''}"
            "Re-authenticate by running `python login.py` and restarting the server."
        )
        super().__init__(self.detail)


class ScraperNavigationError(LinkedInScraperError):
    """
    Raised when a page navigation fails for a non-auth reason
    (network error, timeout after retries, etc.)
    """
    def __init__(self, url: str, cause: str):
        self.url = url
        self.cause = cause
        super().__init__(f"Navigation failed for {url}: {cause}")


class NoResultsError(LinkedInScraperError):
    """
    Raised when a search returns zero results after a successful authenticated scrape.
    This is not an error per se but lets callers distinguish 'blocked' from 'empty'.
    """
    def __init__(self, query: str):
        super().__init__(f"No results found for query: '{query}'")
