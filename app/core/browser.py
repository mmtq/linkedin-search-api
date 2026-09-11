import os
import threading
from pathlib import Path
from typing import Optional, Tuple

from playwright.sync_api import Playwright, Browser, BrowserContext

from app.core.config import settings


# ---------------------------------------------------------------------------
# Stub chrome_manager — kept for backward-compat with linkedin_scraper.py imports.
# Persistent context doesn't need an external Chrome daemon.
# ---------------------------------------------------------------------------
class _NoOpChromeManager:
    def ensure_running(self):
        pass

    def stop(self):
        pass


chrome_manager = _NoOpChromeManager()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_stored_li_at(context: BrowserContext) -> Optional[str]:
    """Returns the li_at value currently stored in the persistent profile cookies."""
    try:
        for c in context.cookies():
            if c["name"] == "li_at" and "linkedin.com" in c.get("domain", ""):
                return c["value"]
    except Exception:
        pass
    return None


def inject_auth_cookies(context: BrowserContext):
    """
    Injects the li_at cookie into the browser context.
    JSESSIONID is NOT hardcoded — it is captured naturally by the persistent
    profile on the first authenticated navigation and saved to disk for all
    future runs automatically.
    """
    li_at = settings.get_li_at_cookie()
    if not li_at:
        print("Warning: No li_at cookie found in li_at.txt or env. Authentication will fail.", flush=True)
        return
    try:
        context.add_cookies([
            {
                "name": "li_at",
                "value": li_at,
                "domain": ".linkedin.com",
                "path": "/",
                "httpOnly": True,
                "secure": True,
                "sameSite": "None",
            }
        ])
        print("  -> li_at injected into persistent profile.", flush=True)
    except Exception as e:
        print(f"Notice: Could not inject li_at cookie: {e}", flush=True)


# ---------------------------------------------------------------------------
# Session creation / teardown
# ---------------------------------------------------------------------------

def create_browser_session(p: Playwright) -> Tuple[None, BrowserContext, bool]:
    """
    Creates a **persistent** browser context rooted at `linkedin-profile/`.

    First run
    ---------
    Profile directory is empty. li_at is injected from li_at.txt.
    LinkedIn sets JSESSIONID and all other session cookies on first page load.
    Playwright automatically saves all of this to disk.

    Subsequent runs
    ---------------
    Full session state (cookies, localStorage, IndexedDB, JSESSIONID) is
    reloaded from disk. li_at is only re-injected when li_at.txt changes.
    LinkedIn sees the exact same browser/device fingerprint → li_at stays stable.
    """
    profile_dir = settings.PROFILE_DIR
    Path(profile_dir).mkdir(parents=True, exist_ok=True)

    launch_kwargs: dict = {
        "headless": settings.HEADLESS,
        "args": [
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
        ],
        "viewport": {"width": 1920, "height": 1080},
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/130.0.0.0 Safari/537.36"
        ),
        "locale": settings.LOCALE,
        "timezone_id": settings.TIMEZONE,
        "extra_http_headers": {"accept-language": "en-US,en;q=0.9"},
    }

    if settings.PROXY_SERVER:
        proxy_config = {"server": settings.PROXY_SERVER}
        if settings.PROXY_USERNAME and settings.PROXY_PASSWORD:
            proxy_config["username"] = settings.PROXY_USERNAME
            proxy_config["password"] = settings.PROXY_PASSWORD
        launch_kwargs["proxy"] = proxy_config

    # `launch_persistent_context` takes user_data_dir as the first positional arg
    context = p.chromium.launch_persistent_context(str(profile_dir), **launch_kwargs)

    # Hide automation signals in every page opened in this context
    try:
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins',   { get: () => [1, 2, 3] });
            window.chrome = { runtime: {} };
        """)
    except Exception:
        pass

    # Only inject li_at from file if the profile has NO existing session at all.
    # Once login.py has been used to log in, the profile has its OWN independent
    # session. We must NOT overwrite it with the li_at from your real browser tab —
    # that would make both share one token and cause LinkedIn to rotate/invalidate it.
    stored_li_at = _get_stored_li_at(context)

    if not stored_li_at:
        # Profile is empty — either first ever run, or profile was wiped.
        # Seed from li_at.txt as a last resort (user should prefer using login.py).
        current_li_at = settings.get_li_at_cookie()
        if current_li_at:
            print("Persistent profile is empty — seeding li_at from li_at.txt...", flush=True)
            print("  TIP: Run `python login.py` once for a more stable independent session.", flush=True)
            inject_auth_cookies(context)
        else:
            print("Warning: No li_at in profile or li_at.txt. Run `python login.py` to log in.", flush=True)
    else:
        print("Persistent profile loaded with existing session. Ready.", flush=True)

    # persistent context owns its browser internally; no separate Browser object needed
    return None, context, False


def close_browser_session(browser, context: BrowserContext, is_cdp: bool = False):
    """
    Closes the persistent browser context.
    Playwright automatically flushes all session state to disk before closing.
    """
    try:
        context.close()
    except Exception:
        pass
    # browser is None for persistent context — nothing extra to close
    if browser is not None:
        try:
            browser.close()
        except Exception:
            pass
