import os
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from urllib.parse import quote
from typing import List, Dict, Optional, Any

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, BrowserContext, Page


CHROME_DEV_PATH = r"C:\Program Files\Google\Chrome Dev\Application\chrome.exe"
PROFILE_DIR = Path("linkedin-profile").resolve()
DEBUG_PORT = 9222
CDP_URL = f"http://127.0.0.1:{DEBUG_PORT}"


def build_jobs_url(query: str, location: str) -> str:
    return (
        "https://www.linkedin.com/jobs/search/"
        f"?keywords={quote(query)}"
        f"&location={quote(location)}"
    )


def build_posts_url(query: str) -> str:
    return (
        "https://www.linkedin.com/search/results/content/"
        f"?keywords={quote(query)}"
    )


def parse_jobs(html: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    seen = set()

    cards = soup.select(
        "li[data-occludable-job-id], "
        "div.job-card-container, "
        "div.jobs-search-results-list__list-item, "
        "div.base-card, "
        "li.jobs-search-results__list-item, "
        "div.job-card-list"
    )

    for card in cards:
        title_el = (
            card.select_one("a.job-card-list__title--link")
            or card.select_one("a.job-card-container__link")
            or card.select_one(".artdeco-entity-lockup__title")
            or card.select_one("h3.base-search-card__title")
            or card.select_one("h3")
            or card.select_one("strong")
        )
        title = title_el.get_text(" ", strip=True) if title_el else None

        company_el = (
            card.select_one(".artdeco-entity-lockup__subtitle")
            or card.select_one(".job-card-container__primary-description")
            or card.select_one(".job-card-container__company-name")
            or card.select_one("h4.base-search-card__subtitle")
            or card.select_one("h4")
        )
        company = company_el.get_text(" ", strip=True) if company_el else None

        loc_el = (
            card.select_one(".artdeco-entity-lockup__caption")
            or card.select_one(".job-card-container__metadata-item")
            or card.select_one("span.job-search-card__location")
            or card.select_one(".job-card-container__metadata-wrapper")
        )
        location = loc_el.get_text(" ", strip=True) if loc_el else None

        link_el = (
            card.select_one("a.job-card-list__title--link")
            or card.select_one("a.job-card-container__link")
            or card.select_one("a.base-card__full-link")
            or card.select_one("a[href*='/jobs/view/']")
        )
        url = None
        if link_el and link_el.get("href"):
            raw_url = link_el.get("href").strip()
            if raw_url.startswith("http"):
                url = raw_url.split("?")[0]
            else:
                url = "https://www.linkedin.com" + raw_url.split("?")[0]

        unique_key = url or (title, company)
        if title and unique_key not in seen:
            seen.add(unique_key)
            jobs.append({
                "title": title,
                "company": company,
                "location": location,
                "url": url,
            })

    return jobs


def parse_posts(html: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    posts = []
    seen = set()

    # Match post containers across SDUI and classic LinkedIn
    containers = soup.select(
        "div[role='listitem'], "
        "div.feed-shared-update-v2, "
        "div[data-view-name*='feed'], "
        "div[componentkey*='expanded'], "
        "li.artdeco-card"
    )

    for c in containers:
        # Extract author
        author_el = c.select_one("a[href*='/in/']")
        author = author_el.get_text(" ", strip=True) if author_el else None
        if author and "•" in author:
            author = author.split("•")[0].strip()

        # Extract post text with fallbacks
        text_el = (
            c.select_one("[data-testid='expandable-text-box']")
            or c.select_one("p[componentkey]")
            or c.select_one(".update-components-text")
            or c.select_one(".feed-shared-update-v2__description")
            or c.select_one(".feed-shared-inline-show-more-text")
            or c.select_one("span.break-words")
        )

        if not text_el:
            # Fallback to finding paragraphs with actual content
            for p in c.find_all("p"):
                txt_candidate = p.get_text(" ", strip=True)
                if len(txt_candidate) > 40 and not txt_candidate.startswith("http"):
                    text_el = p
                    break

        if text_el:
            raw_text = text_el.get_text(" ", strip=True)
            cleaned = (
                raw_text.replace("… more", "")
                .replace("... more", "")
                .replace("… see more", "")
                .replace("... see more", "")
                .strip()
            )

            if len(cleaned) > 35 and cleaned not in seen:
                seen.add(cleaned)
                posts.append({
                    "author": author,
                    "text": cleaned,
                })

    # Also check standalone text boxes if containers were missed
    if len(posts) < 5:
        for box in soup.select("[data-testid='expandable-text-box'], p[componentkey], .update-components-text"):
            raw = box.get_text(" ", strip=True).replace("… more", "").replace("... more", "").strip()
            if len(raw) > 35 and raw not in seen:
                seen.add(raw)
                posts.append({
                    "author": None,
                    "text": raw,
                })

    return posts


class ChromeProcessManager:
    def __init__(self, headless: bool = True):
        self.headless = headless
        self.process: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()

    def is_ready(self) -> bool:
        try:
            with urllib.request.urlopen(f"{CDP_URL}/json/version", timeout=1) as resp:
                return resp.status == 200
        except Exception:
            return False

    def ensure_running(self):
        with self._lock:
            if not self.is_ready():
                print(f"Starting background Chrome Dev (headless={self.headless})...")
                cmd = [
                    CHROME_DEV_PATH,
                    f"--remote-debugging-port={DEBUG_PORT}",
                    f"--user-data-dir={PROFILE_DIR}",
                    "--no-first-run",
                    "--no-default-browser-check",
                ]
                if self.headless:
                    cmd.append("--headless=new")

                self.process = subprocess.Popen(cmd)

                for _ in range(30):
                    if self.is_ready():
                        print("Background Chrome Dev is ready.")
                        break
                    time.sleep(0.5)

    def stop(self):
        with self._lock:
            if self.process:
                try:
                    self.process.terminate()
                except Exception:
                    pass
                self.process = None


chrome_manager = ChromeProcessManager(headless=True)


def _inject_cookie_if_needed(context: BrowserContext):
    li_at_cookie = os.environ.get("LINKEDIN_LI_AT", "").strip()
    li_at_file = Path("li_at.txt")
    if not li_at_cookie and li_at_file.exists():
        li_at_cookie = li_at_file.read_text(encoding="utf-8").strip()

    if li_at_cookie:
        cookies = [
            {
                "name": "li_at",
                "value": li_at_cookie,
                "domain": ".linkedin.com",
                "path": "/",
                "httpOnly": True,
                "secure": True,
                "sameSite": "None",
            },
            {
                "name": "li_at",
                "value": li_at_cookie,
                "domain": ".www.linkedin.com",
                "path": "/",
                "httpOnly": True,
                "secure": True,
                "sameSite": "None",
            },
        ]
        context.add_cookies(cookies)


def search_jobs(query: str, location: str = "", limit: int = 10) -> List[Dict[str, Any]]:
    chrome_manager.ensure_running()

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP_URL)
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        _inject_cookie_if_needed(context)

        # Open dedicated tab for this request
        page = context.new_page()
        try:
            url = build_jobs_url(query, location)
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(2500)

            # Scroll through the left-pane job list to trigger infinite load
            scroll_steps = max(5, (limit // 2) + 1)
            for i in range(1, scroll_steps + 1):
                page.evaluate(f"""
                    const container = document.querySelector('.jobs-search-results-list') || document.querySelector('.scaffold-layout__list') || document.querySelector('ul.scaffold-layout__list-container');
                    if (container) {{
                        container.scrollTop = container.scrollHeight * ({i} / {scroll_steps});
                    }} else {{
                        window.scrollBy(0, 1000);
                    }}
                """)
                page.wait_for_timeout(1000)

            html = page.content()
            Path("jobs.html").write_text(html, encoding="utf-8")
            jobs = parse_jobs(html)
            return jobs[:limit]
        finally:
            page.close()
            browser.close()


def search_posts(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    chrome_manager.ensure_running()

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP_URL)
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        _inject_cookie_if_needed(context)

        # Open dedicated tab for this request
        page = context.new_page()
        try:
            url = build_posts_url(query)
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(2500)

            # Scroll and click 'Load more' button dynamically based on requested limit
            needed_batches = max(2, (limit // 3) + 1)
            for _ in range(needed_batches):
                page.mouse.wheel(0, 1500)
                page.wait_for_timeout(1000)

                # Click 'Load more' or 'Show more results' button if present
                load_more_btn = page.locator("button").filter(has_text="Load more")
                if load_more_btn.count() > 0:
                    try:
                        load_more_btn.first.scroll_into_view_if_needed()
                        load_more_btn.first.click()
                        page.wait_for_timeout(2000)
                    except Exception:
                        pass

            html = page.content()
            Path("posts.html").write_text(html, encoding="utf-8")
            posts = parse_posts(html)
            return posts[:limit]
        finally:
            page.close()
            browser.close()
