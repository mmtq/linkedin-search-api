import random
import re
import time
from pathlib import Path
from urllib.parse import quote
from typing import List, Dict, Optional, Any

from playwright.sync_api import sync_playwright

from app.core.config import settings
from app.core.browser import create_browser_session, close_browser_session, chrome_manager
from app.core.exceptions import SessionExpiredException, ScraperNavigationError
from app.services.parsers import parse_jobs_html, parse_posts_html, extract_job_description_from_html


def build_jobs_url(query: str, location: str, start: int = 0, sort_by_latest: bool = True) -> str:
    sort_param = "&sortBy=DD" if sort_by_latest else ""
    return (
        "https://www.linkedin.com/jobs/search/"
        f"?keywords={quote(query)}"
        f"&location={quote(location)}"
        f"{sort_param}"
        f"&start={start}"
    )


def build_posts_url(query: str, page_num: Optional[int] = None, sort_by_latest: bool = True) -> str:
    sort_param = '&sortBy=%22date_posted%22' if sort_by_latest else ""
    page_param = f"&page={page_num}" if page_num and page_num > 1 else ""
    return (
        "https://www.linkedin.com/search/results/content/"
        f"?keywords={quote(query)}"
        f"{sort_param}"
        f"{page_param}"
    )


def human_sleep(min_s: float = 1.5, max_s: float = 3.0):
    """Introduce natural, non-uniform human browsing delay."""
    time.sleep(random.uniform(min_s, max_s))


def _find_feed_load_more_btn(page):
    """
    Finds the main feed pagination 'Load more' / 'আরও লোড করুন' button locator,
    excluding inline post truncation buttons (... see more / … আরও).
    """
    try:
        for b in page.locator("button, [role='button'], a.artdeco-button").all():
            try:
                t = (b.text_content() or "").strip()
                if not t or "…" in t or "..." in t or t in ("আরও দেখুন", "See more", "see more"):
                    continue
                if (
                    "আরও লোড করুন" in t
                    or "লোড" in t
                    or "load more" in t.lower()
                    or "see more results" in t.lower()
                    or "show more results" in t.lower()
                ):
                    return b
            except Exception:
                continue
    except Exception:
        pass
    return None


def _expand_all_inline_posts(page):
    """
    Expands all truncated '... see more' / '… আরও' inline buttons across all rendered posts
    so the full, 100% untruncated post content is exposed in the DOM without navigating away.
    """
    try:
        page.evaluate("""() => {
            const buttons = Array.from(document.querySelectorAll('button, [role="button"], a.artdeco-button')).filter(b => {
                const t = (b.innerText || '').trim();
                return (
                    t.includes('…') || 
                    t.includes('...') || 
                    t.toLowerCase().includes('see more') || 
                    t.toLowerCase().includes('show more') || 
                    t === '… আরও' || 
                    t === 'আরও দেখুন'
                ) && !t.includes('আরও লোড করুন') && !t.toLowerCase().includes('load more');
            });
            buttons.forEach(b => {
                try { b.click(); } catch(e) {}
            });
        }""")
    except Exception:
        pass


def _warmup_session(page, context, timeout: int = 30000):
    """
    Visits linkedin.com/feed/ to warm up the authenticated session before
    hitting search/content endpoints. Required on the first run of a new
    persistent profile.

    Raises SessionExpiredException if LinkedIn redirects to a login/auth page,
    which means the stored session is expired and re-authentication is needed.
    """
    try:
        print("  -> Warming up session via linkedin.com/feed/ ...", flush=True)
        page.goto("https://www.linkedin.com/feed/", wait_until="commit", timeout=timeout)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=15000)
        except Exception:
            pass
        current_url = page.url
        auth_indicators = ("login", "authwall", "checkpoint", "signup", "uas/authenticate")
        if any(ind in current_url for ind in auth_indicators):
            print(f"  -> Session expired: warmup redirected to {current_url}", flush=True)
            raise SessionExpiredException(redirect_url=current_url)
        print(f"  -> Session warm-up OK ({current_url[:60]})", flush=True)
        human_sleep(1.5, 2.5)
    except SessionExpiredException:
        raise  # Re-raise without swallowing
    except Exception as e:
        # Network hiccup during warmup — log and continue; the main nav will catch auth issues
        print(f"  -> Warm-up note (non-fatal): {e}", flush=True)


def _safe_goto(page, context, url: str, timeout: int = 40000):
    """
    Navigates safely to LinkedIn URLs preserving the authenticated session state.
    Uses 'commit' wait state to accommodate LinkedIn's SPA client-side transitions.

    Raises:
        SessionExpiredException: if LinkedIn redirects to an auth/login page.
        ScraperNavigationError: if navigation fails for non-auth reasons after retry.
    """
    auth_indicators = ("login", "authwall", "checkpoint", "signup", "uas/authenticate")

    def _check_auth_redirect(pg):
        """Raise SessionExpiredException if the page landed on a login/auth URL."""
        landed = pg.url
        if any(ind in landed for ind in auth_indicators):
            raise SessionExpiredException(redirect_url=landed)

    try:
        page.goto(url, wait_until="commit", timeout=timeout)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=15000)
        except Exception:
            pass
        _check_auth_redirect(page)
        return page
    except SessionExpiredException:
        raise  # Bubble up immediately — no retry will fix an expired session
    except Exception as e:
        err_msg = str(e)
        if "ERR_TOO_MANY_REDIRECTS" in err_msg or "net::ERR_" in err_msg or "Timeout" in err_msg:
            print(f"Notice: Navigation retry on ({err_msg[:120]}). Re-verifying session...", flush=True)
            from app.core.browser import inject_auth_cookies
            inject_auth_cookies(context)
            time.sleep(2.0)
            try:
                page.goto(url, wait_until="commit", timeout=timeout)
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=15000)
                except Exception:
                    pass
                _check_auth_redirect(page)
                return page
            except SessionExpiredException:
                raise
            except Exception as retry_err:
                raise ScraperNavigationError(url=url, cause=str(retry_err)) from retry_err
        else:
            raise ScraperNavigationError(url=url, cause=err_msg) from e


class LinkedInScraperService:
    """
    High-level scraping service that interacts with the headless Chrome daemon via Playwright,
    supporting multi-page pagination (Pages 1-5+), latest sorting, and human-like browsing patterns.
    """

    @staticmethod
    def search_jobs(
        query: str,
        location: str = "",
        pages: int = 5,
        limit: Optional[int] = None,
        sort_by_latest: bool = True,
    ) -> List[Dict[str, Any]]:
        chrome_manager.ensure_running()

        all_jobs: List[Dict[str, Any]] = []
        seen_keys = set()

        with sync_playwright() as p:
            browser, context, is_cdp = create_browser_session(p)
            page = context.new_page()
            try:
                page.set_viewport_size({"width": 1920, "height": 1080})

                # Warm up session through /feed/ before hitting search endpoints
                _warmup_session(page, context)

                for page_idx in range(pages):
                    start_offset = page_idx * 25
                    url = build_jobs_url(query, location, start=start_offset, sort_by_latest=sort_by_latest)
                    print(f"🔍 Scraping Jobs [Page {page_idx + 1}/{pages}]: {url}", flush=True)

                    page = _safe_goto(page, context, url, timeout=40000)
                    human_sleep(2.0, 3.5)

                    # Human-like progressive scrolling down the jobs list panel & clicking cards to capture descriptions
                    cards_loc = page.locator('li[data-occludable-job-id], div.job-card-container, div.jobs-search-results-list__list-item, div.base-card')
                    card_count = cards_loc.count()
                    descriptions_by_id = {}
                    descriptions_by_url = {}
                    descriptions_by_title = {}

                    needed_limit = (limit - len(all_jobs)) if limit else card_count
                    cards_to_process = min(card_count, needed_limit) if limit else card_count

                    for i in range(cards_to_process):
                        try:
                            card = cards_loc.nth(i)
                            try:
                                card.scroll_into_view_if_needed(timeout=2000)
                            except Exception:
                                pass
                            try:
                                card.click(timeout=2000, force=True)
                            except Exception:
                                pass
                            human_sleep(0.2, 0.4)

                            # Expand the job description pane completely (clicks 'See more' / 'আরও দেখুন')
                            page.evaluate("""() => {
                                const btn = document.querySelector('.jobs-description__footer-button') || 
                                            document.querySelector('button[aria-label*="See more"]') ||
                                            document.querySelector('button[aria-label*="Show more"]') ||
                                            document.querySelector('.jobs-description button') ||
                                            Array.from(document.querySelectorAll('button, a')).find(b => {
                                                const t = (b.innerText || '').trim().toLowerCase();
                                                return t.includes('see more') || t.includes('show more') || t.includes('আরও দেখুন');
                                            });
                                if (btn) {
                                    try { btn.click(); } catch(e) {}
                                }
                            }""")
                            human_sleep(0.3, 0.5)

                            # Extract complete un-truncated description text from details pane
                            desc = page.evaluate("""() => {
                                const el = document.querySelector('#job-details') || 
                                           document.querySelector('.jobs-description-content__text') || 
                                           document.querySelector('article.jobs-description__container') ||
                                           document.querySelector('.jobs-box__html-content') ||
                                           document.querySelector('.jobs-description');
                                return el ? el.innerText.trim() : null;
                            }""")

                            if not desc:
                                # Fallback to parser on right details container HTML
                                desc = extract_job_description_from_html(page.content())

                            link_el = card.locator("a[href*='/jobs/view/'], a.job-card-list__title--link, a.job-card-container__link").first
                            raw_href = link_el.get_attribute("href") if link_el.count() > 0 else ""
                            
                            # Extract numeric job ID from href or attributes
                            card_occludable_id = card.get_attribute("data-occludable-job-id") or ""
                            card_job_id = card.get_attribute("data-job-id") or ""
                            m_id = (
                                re.search(r"/jobs/view/(\d+)", raw_href)
                                or re.search(r"currentJobId=(\d+)", raw_href)
                                or re.search(r"(\d{8,})", card_occludable_id)
                                or re.search(r"(\d{8,})", card_job_id)
                            )
                            job_id = m_id.group(1) if m_id else None

                            clean_url = None
                            if raw_href:
                                clean_url = raw_href.split("?")[0]
                                if not clean_url.startswith("http"):
                                    clean_url = "https://www.linkedin.com" + clean_url

                            title_el = card.locator("a.job-card-list__title--link, a.job-card-container__link, strong, h3").first
                            title = (title_el.text_content() or "").strip() if title_el.count() > 0 else None

                            if desc and len(desc) > 80:
                                if job_id:
                                    descriptions_by_id[job_id] = desc
                                if clean_url:
                                    descriptions_by_url[clean_url] = desc
                                if title:
                                    descriptions_by_title[title] = desc
                        except Exception:
                            pass

                    # Final brief settling pause before parsing HTML
                    human_sleep(0.6, 1.2)
                    html = page.content()
                    page_jobs = parse_jobs_html(html)

                    # Enrich jobs with captured descriptions
                    for j in page_jobs:
                        j_url = j.get("url") or ""
                        j_title = j.get("title") or ""
                        m_jid = re.search(r"/jobs/view/(\d+)", j_url) or re.search(r"(\d{8,})", j_url)
                        j_id = m_jid.group(1) if m_jid else None

                        j_desc = (
                            (descriptions_by_id.get(j_id) if j_id else None)
                            or descriptions_by_url.get(j_url)
                            or descriptions_by_title.get(j_title)
                            or None
                        )
                        j["description"] = j_desc

                    # Guaranteed 100% fallback: if any job description is still None, fetch direct view URL
                    needed_limit = (limit - len(all_jobs)) if limit else len(page_jobs)
                    target_jobs = page_jobs[:max(1, needed_limit)] if limit else page_jobs

                    for j in target_jobs:
                        if not j.get("description") and j.get("url"):
                            try:
                                print(f"  -> 📄 Direct fetching missing description for: {j.get('title')}", flush=True)
                                direct_page = context.new_page()
                                try:
                                    direct_page = _safe_goto(direct_page, context, j["url"], timeout=20000)
                                    direct_page.evaluate("window.scrollBy(0, 400)")
                                    human_sleep(0.5, 0.8)
                                    
                                    # Expand "See more" / "Show more" button if present
                                    direct_page.evaluate("""() => {
                                        const btns = Array.from(document.querySelectorAll('button, a'));
                                        const seeMore = btns.find(b => {
                                            const t = (b.innerText || '').trim().toLowerCase();
                                            return t.includes('see more') || t.includes('show more') || t.includes('আরও');
                                        });
                                        if (seeMore) {
                                            try { seeMore.click(); } catch(e) {}
                                        }
                                    }""")
                                    human_sleep(0.3, 0.5)

                                    direct_desc = extract_job_description_from_html(direct_page.content())
                                    if direct_desc:
                                        j["description"] = direct_desc
                                finally:
                                    try:
                                        direct_page.close()
                                    except Exception:
                                        pass
                            except Exception as fetch_err:
                                print(f"  -> Fallback fetch note: {fetch_err}", flush=True)

                    # Accumulate unique jobs
                    new_on_page = 0
                    for j in page_jobs:
                        key = j["url"] or (j["title"], j["company"])
                        if key not in seen_keys:
                            seen_keys.add(key)
                            all_jobs.append(j)
                            new_on_page += 1

                    print(f"  -> ✅ Page {page_idx + 1} added {new_on_page} new jobs (with descriptions). Total: {len(all_jobs)}", flush=True)

                    # Stop if no new jobs were found on the page or limit is reached
                    if new_on_page == 0:
                        break
                    if limit and len(all_jobs) >= limit:
                        all_jobs = all_jobs[:limit]
                        break

                    # Natural pause before navigating to next page
                    if page_idx < pages - 1:
                        human_sleep(2.0, 3.8)

                try:
                    Path("jobs.html").write_text(page.content(), encoding="utf-8")
                except Exception:
                    pass
                return all_jobs
            finally:
                try:
                    page.close()
                except Exception:
                    pass
                close_browser_session(browser, context, is_cdp)

    @staticmethod
    def search_posts(
        query: str,
        pages: int = 5,
        limit: Optional[int] = None,
        sort_by_latest: bool = True,
    ) -> List[Dict[str, Any]]:
        chrome_manager.ensure_running()

        all_posts: List[Dict[str, Any]] = []
        seen_texts = set()

        with sync_playwright() as p:
            browser, context, is_cdp = create_browser_session(p)
            page = context.new_page()
            try:
                # Warm up session through /feed/ before hitting search endpoints
                _warmup_session(page, context)

                # Open initial content search URL sorted by latest
                url = build_posts_url(query, page_num=None, sort_by_latest=sort_by_latest)
                print(f"🔍 Scraping Posts (up to {pages} pages/batches): {url}", flush=True)

                page = _safe_goto(page, context, url, timeout=40000)
                human_sleep(3.0, 4.0)

                for round_num in range(1, pages + 1):
                    # Scroll down to reveal new content and the load-more trigger
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    human_sleep(2.0, 2.8)

                    loc = (
                        page.locator("button").filter(has_text="আরও লোড করুন")
                        .or_(page.locator("button").filter(has_text="Load more"))
                        .or_(page.locator("button").filter(has_text="See more results"))
                        .or_(page.locator("button").filter(has_text="Show more results"))
                        .or_(page.locator("button._704ac4e0"))
                    )

                    if loc.count() > 0:
                        try:
                            try:
                                loc.first.scroll_into_view_if_needed(timeout=2000)
                            except Exception:
                                pass
                            loc.first.click(timeout=2000, force=True)
                            print(f"  -> 📜 Successfully clicked load more on batch {round_num}", flush=True)
                            human_sleep(3.0, 4.0)
                        except Exception as e:
                            print(f"  -> Click note on batch {round_num}: {e}", flush=True)

                    # Expand all inline "... see more" / "… আরও" buttons to get 100% full text
                    _expand_all_inline_posts(page)
                    human_sleep(0.5, 0.9)

                    html = page.content()
                    page_posts = parse_posts_html(html)

                    # Accumulate unique posts
                    new_on_page = 0
                    for post in page_posts:
                        txt = post["text"]
                        if txt not in seen_texts:
                            seen_texts.add(txt)
                            all_posts.append(post)
                            new_on_page += 1

                    print(f"  -> ✅ Batch {round_num} added {new_on_page} new posts. Total: {len(all_posts)}", flush=True)

                    if limit and len(all_posts) >= limit:
                        all_posts = all_posts[:limit]
                        break

                    if round_num < pages:
                        human_sleep(1.5, 2.2)

                try:
                    Path("posts.html").write_text(page.content(), encoding="utf-8")
                except Exception:
                    pass
                return all_posts
            finally:
                try:
                    page.close()
                except Exception:
                    pass
                close_browser_session(browser, context, is_cdp)


scraper_service = LinkedInScraperService()
