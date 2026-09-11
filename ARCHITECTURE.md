# LinkedIn Search & Scraping API — System Architecture

## Overview

A **FastAPI** service that scrapes LinkedIn job postings and posts using a **persistent headless Chromium** session managed by Playwright. The key design goal is a **stable, long-lived authenticated session** that doesn't require manual cookie refreshing.

---

## Project Structure

```
testingLinkedIn/
├── main.py                        # Entry point (uvicorn runner)
├── login.py                       # One-time interactive login tool
├── li_at.txt                      # Fallback cookie file (if not using login.py)
├── linkedin-profile/              # Persistent Chromium profile (session saved to disk)
├── requirements.txt
└── app/
    ├── main.py                    # FastAPI app factory + middleware + lifespan
    ├── api/
    │   └── routes.py              # API endpoints (/jobs, /posts, /search)
    ├── core/
    │   ├── config.py              # Settings (env vars, paths, defaults)
    │   ├── browser.py             # Playwright persistent context management
    │   └── exceptions.py          # Custom exception hierarchy
    ├── models/
    │   └── schemas.py             # Pydantic request/response models
    └── services/
        ├── linkedin_scraper.py    # Core scraping logic
        └── parsers.py             # BeautifulSoup HTML parsers
```

---

## 1. Entry Point — `main.py`

```python
uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=True)
```

Starts the Uvicorn ASGI server. All configuration (host, port) comes from `Settings` in `config.py`, which reads environment variables with sane defaults.

---

## 2. FastAPI Application — `app/main.py`

### App Factory (`create_app`)
Uses a factory pattern so the app is testable and composable. The `lifespan` context manager handles startup/shutdown.

### Lifespan
```
Startup:
  → Print session status (authenticated or not)
  → chrome_manager.ensure_running() [no-op in persistent context mode]

Shutdown:
  → chrome_manager.stop() [no-op]
```

### HTTP Request Logging Middleware
Every request/response is logged with method, path, query string, client IP, status code, and duration. Uses `flush=True` to ensure real-time visibility in terminal.

### Root Endpoint (`GET /`)
Returns service metadata **plus live session status** by checking whether `linkedin-profile/Default/Cookies` exists on disk. No scraping needed — it's a fast filesystem check.

```json
{
  "authenticated": true,
  "session_source": "persistent_profile",
  "action_required": null,
  "endpoints": { ... }
}
```

---

## 3. Authentication System

This is the most critical part of the design. The root problem with LinkedIn scraping is **session rotation** — LinkedIn invalidates `li_at` when it detects suspicious session usage.

### Why sessions get invalidated

| Cause | Description |
|---|---|
| Shared `li_at` | Copying cookie from real browser + using it in headless Playwright = LinkedIn sees 1 session from 2 different browser fingerprints → forced re-auth |
| Fresh context each run | Every new `launch()` + `new_context()` has no history, no localStorage, no JSESSIONID → LinkedIn treats it as a new unknown device |
| Hardcoded JSESSIONID | `JSESSIONID` is a CSRF token tightly paired with `li_at`. Using a wrong/stale one causes redirect loops |

### Solution — Persistent Chromium Profile

`launch_persistent_context(user_data_dir)` saves the entire browser state to `linkedin-profile/` on disk:
- Cookies (including `li_at`, `JSESSIONID`, `bcookie`, `bscookie`, etc.)
- `localStorage` and `IndexedDB` (LinkedIn stores auth tokens here)
- Browser fingerprint (same "device" every run)

**First run:** Profile is empty → inject `li_at` → navigate to `/feed/` → LinkedIn sets `JSESSIONID` and all session cookies → everything saved to disk.

**Subsequent runs:** Profile loaded from disk → LinkedIn sees same device → `li_at` stays stable indefinitely.

### `login.py` — One-Time Interactive Login

```
python login.py
```

Opens a **visible** (non-headless) Chromium window to `linkedin.com/login`. The user logs in manually (handles 2FA, CAPTCHA, SSO). On pressing ENTER, Playwright saves the full authenticated session to `linkedin-profile/` and also writes `li_at` to `li_at.txt` for reference. This is the **recommended setup method** — it gives the scraper its own independent session, completely separate from the user's real browser.

### `li_at.txt` — Fallback

If `linkedin-profile/` is empty and no `LI_AT` env var is set, the scraper seeds the profile from `li_at.txt`. This is a last resort — it works but risks session sharing if the same cookie is active in a real browser tab.

### Cookie Injection Logic (`browser.py`)

```python
stored = _get_stored_li_at(context)   # Read from profile on disk

if not stored:
    inject from li_at.txt             # Profile is empty — first run
elif stored != current_li_at_file:
    inject updated value              # li_at.txt was manually updated
else:
    pass                              # Valid session on disk — do nothing
```

> **Rule:** Never overwrite a valid stored session with `li_at.txt`. That would merge two independent sessions and trigger rotation.

---

## 4. Browser Session — `app/core/browser.py`

### `create_browser_session(p: Playwright)`

Launches a persistent Chromium context with:

| Setting | Value | Reason |
|---|---|---|
| `headless` | `True` (prod) | No display needed |
| `--disable-blink-features=AutomationControlled` | ✅ | Hides CDP automation flag |
| `user_agent` | Chrome 130 on Win10 | Matches a real browser |
| `viewport` | 1920×1080 | Looks like a desktop user |
| `locale` / `timezone_id` | Configurable | Matches server location |
| `add_init_script` | Patches `navigator.webdriver`, `plugins`, `window.chrome` | Client-side anti-detection |

Returns `(None, context, False)` — `browser` is `None` because persistent context owns its browser internally.

### `close_browser_session(browser, context)`

Calls `context.close()` — Playwright automatically flushes all session state to disk before closing. This is what makes persistence work.

### `_NoOpChromeManager` (stub)

The old `ChromeProcessManager` (which launched a Chrome Dev daemon via CDP) was replaced with a no-op stub to maintain backward-compatible imports. Persistent context doesn't need an external Chrome process.

---

## 5. Scraper Service — `app/services/linkedin_scraper.py`

### Session Warmup — `_warmup_session()`

Before hitting any search URL, the scraper visits `linkedin.com/feed/` first.

**Why:** LinkedIn's search endpoints (`/search/results/content/`, `/jobs/search/`) require an established session context. On a fresh profile load, going directly to a search URL can result in `ERR_TOO_MANY_REDIRECTS`.

**Auth detection:** If the warmup lands on `/login`, `/authwall`, `/checkpoint`, or `/uas/authenticate` → raises `SessionExpiredException` immediately. No point attempting the actual search.

### Safe Navigation — `_safe_goto()`

```
1. goto(url, wait_until="commit")   ← "commit" = fires as soon as 1st byte received
                                      avoids false redirect errors from LinkedIn's SPA routing
2. wait_for_load_state("domcontentloaded")
3. Check landed URL for auth indicators
   → If auth page: raise SessionExpiredException (no retry)
   → If network error / timeout: inject cookies + retry once
   → If retry fails: raise ScraperNavigationError
```

> **Key insight:** `wait_until="commit"` instead of `"load"` or `"networkidle"` — LinkedIn is a React SPA that does client-side routing. Waiting for full load triggers false "too many redirects" because the SPA fires multiple internal navigations after the first response.

### Jobs Scraper — `search_jobs()`

```
For each page (offset 0, 25, 50...):
  1. Navigate to /jobs/search/?keywords=...&location=...&sortBy=DD&start=N
  2. Locate job cards (multiple CSS selectors for different LinkedIn layouts)
  3. For each card:
     a. scroll_into_view → click (loads description pane)
     b. Click "See more" to expand truncated description
     c. Extract full description text from #job-details
     d. Store by job ID, URL, and title for deduplication
  4. Parse full page HTML with BeautifulSoup
  5. Enrich parsed jobs with captured descriptions
  6. Fallback: for any job still missing description → open direct job URL in new page
  7. Accumulate unique jobs (deduped by URL or title+company)
  8. Stop if no new jobs found or limit reached
```

**Human-like behavior:** `human_sleep(min, max)` — random uniform delays between all actions to mimic real browsing pace.

### Posts Scraper — `search_posts()`

```
1. Navigate to /search/results/content/?keywords=...&sortBy="date_posted"
2. For each batch (page):
   a. scroll to bottom (triggers lazy-load)
   b. Click "Load more" / "আরও লোড করুন" button
   c. Expand all inline "... see more" buttons (JS evaluate)
   d. Parse page HTML → extract unique posts
3. Accumulate unique posts (deduped by text content)
4. Stop when limit reached
```

**Multilingual button detection:** Handles both English (`Load more`, `See more results`) and Bengali (`আরও লোড করুন`, `আরও দেখুন`) LinkedIn UI variants.

---

## 6. HTML Parsers — `app/services/parsers.py`

Stateless functions that receive raw HTML strings and return structured data. Using **BeautifulSoup** to parse the rendered DOM after JavaScript execution.

| Function | Input | Output |
|---|---|---|
| `parse_jobs_html(html)` | Full page HTML | `List[JobItem]` — title, company, location, URL |
| `parse_posts_html(html)` | Full page HTML | `List[PostItem]` — author, author_url, post_url, text |
| `extract_job_description_from_html(html)` | Job detail page HTML | `str` — full description text |

Parsers are isolated from browser logic — they can be tested independently with saved HTML files (e.g., `jobs.html`, `posts.html`).

---

## 7. Error Handling — `app/core/exceptions.py`

Three-level exception hierarchy:

```
LinkedInScraperError (base)
├── SessionExpiredException
│     raised when: /login, /authwall, /checkpoint detected during warmup or navigation
│     HTTP response: 401 with { error, message, redirect_url }
│
├── ScraperNavigationError
│     raised when: network error / timeout persists after one retry
│     HTTP response: 503 with { error, message, url }
│
└── NoResultsError (informational, not currently raised to API layer)
```

### Route-level handler — `_handle_scraper_error()`

A single shared function in `routes.py` that catches known exception types and maps them to appropriate HTTP status codes. Unrecognized exceptions fall through to `500`.

---

## 8. API Routes — `app/api/routes.py`

### `GET /api/jobs`
| Param | Default | Description |
|---|---|---|
| `query` | `software engineer` | Search keywords |
| `location` | `Bangladesh` | Location filter |
| `pages` | `5` | Pages to scrape (1–10) |
| `sort_by` | `latest` | `latest` or `relevant` |
| `limit` | `None` | Cap on results (max 150) |

### `GET /api/posts`
Same as jobs but without `location`. Max `limit` is 100. Paginates via "Load more" clicks instead of URL offset.

### `GET /api/search` — Parallel
```python
jobs, posts = await asyncio.gather(
    asyncio.to_thread(scraper_service.search_jobs, ...),
    asyncio.to_thread(scraper_service.search_posts, ...),
)
```
Both scrapers run **simultaneously** in separate OS threads. Each thread creates its own independent `sync_playwright()` context — no shared state. Total time ≈ `max(jobs_time, posts_time)` instead of `jobs_time + posts_time`.

---

## 9. Data Models — `app/models/schemas.py`

```
JobItem         title, company, location, url, description
JobsResponse    query, location, sort_by, pages_scraped, count, jobs[]

PostItem        author, author_url, url, text
PostsResponse   query, sort_by, pages_scraped, count, posts[]

SearchResponse  query, location, sort_by, pages_scraped,
                jobs_count, posts_count, jobs[], posts[]
```

All fields use Pydantic v2 with `Optional` + `Field(description=...)` for auto-generated OpenAPI docs at `/docs`.

---

## 10. Configuration — `app/core/config.py`

All settings are Pydantic `BaseModel` fields reading from environment variables with defaults:

| Setting | Env Var | Default |
|---|---|---|
| Host/Port | `HOST`, `PORT` | `0.0.0.0:8000` |
| Headless mode | `HEADLESS` | `true` |
| Profile directory | — | `linkedin-profile/` (relative) |
| Timezone | `TIMEZONE` | `Asia/Dhaka` |
| Locale | `LOCALE` | `en-US` |
| li_at cookie | `LI_AT` or `LINKEDIN_LI_AT` | reads `li_at.txt` |
| Proxy | `PROXY_SERVER`, `PROXY_USERNAME`, `PROXY_PASSWORD` | none |

`get_li_at_cookie()` priority: `LI_AT` env → `LINKEDIN_LI_AT` env → `li_at.txt` → `li_at` file.

---

## 11. Deployment

### Local (Recommended)

```bash
python login.py          # One-time: log in via visible browser
python main.py           # Start API server
# Expose via ngrok: ngrok http 8000
```

`linkedin-profile/` persists on your disk forever. Session survives restarts.

### VPS (Ubuntu)

```bash
# On local PC: log in, then copy profile to VPS
python login.py
scp -r linkedin-profile/ user@vps-ip:~/linkedin-app/linkedin-profile/

# On VPS: start as systemd service
sudo systemctl start linkedin-api
```

Profile lives on VPS disk, survives reboots. Re-login needed only if LinkedIn invalidates the session (weeks/months of stability expected).

### Render / Cloud (Not Recommended)

Ephemeral filesystem — `linkedin-profile/` is wiped on every deploy. Falls back to `li_at` env var, which is unstable due to fingerprint changes between deploys. Requires paid persistent disk to work reliably.

---

## Request Flow Diagram

```
Client Request
     │
     ▼
FastAPI (uvicorn)
     │  HTTP middleware logs request
     ▼
routes.py  (/api/jobs | /api/posts | /api/search)
     │  asyncio.to_thread → offload sync Playwright to thread pool
     ▼
linkedin_scraper.py
     │
     ├─ create_browser_session()
     │    └─ launch_persistent_context(linkedin-profile/)
     │         └─ load saved cookies, localStorage, JSESSIONID from disk
     │
     ├─ _warmup_session()  → GET linkedin.com/feed/
     │    └─ if /login detected → raise SessionExpiredException
     │
     ├─ _safe_goto(search_url)
     │    └─ wait_until="commit" (SPA-safe)
     │    └─ check for auth redirect
     │    └─ retry once on network error
     │
     ├─ scrape + parse HTML (BeautifulSoup)
     │
     └─ close_browser_session()
          └─ context.close() → auto-saves session state to disk

     │
     ▼
routes.py
     │  catch SessionExpiredException → 401
     │  catch ScraperNavigationError  → 503
     │  catch Exception               → 500
     ▼
JSON Response to Client
```
