import os
import subprocess
import threading
import time
import urllib.request
from typing import Optional, Tuple

from playwright.sync_api import Playwright, Browser, BrowserContext

from app.core.config import settings


class ChromeProcessManager:
    """
    Manages the background headless Chrome Dev process with CDP debugging enabled
    when running in environments where Chrome Dev binary is installed locally.
    """

    def __init__(self, headless: bool = True):
        self.headless = headless
        self.process: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()

    def is_ready(self) -> bool:
        try:
            with urllib.request.urlopen(f"{settings.CDP_URL}/json/version", timeout=0.5) as resp:
                return resp.status == 200
        except Exception:
            return False

    def ensure_running(self):
        with self._lock:
            if not self.is_ready():
                if not settings.has_chrome_binary:
                    # Cloud/Render environment: Native Playwright Chromium will be used directly
                    return

                if str(settings.DEBUG_PORT) not in settings.CDP_URL:
                    # Custom CDP URL configured; do not spawn local daemon
                    return

                print(f"Starting background Chrome Dev daemon (headless={self.headless})...", flush=True)
                cmd = [
                    settings.CHROME_DEV_PATH,
                    f"--remote-debugging-port={settings.DEBUG_PORT}",
                    f"--user-data-dir={settings.PROFILE_DIR}",
                    "--no-first-run",
                    "--no-default-browser-check",
                ]
                if self.headless:
                    cmd.append("--headless=new")

                try:
                    self.process = subprocess.Popen(cmd)
                    for _ in range(10):
                        if self.is_ready():
                            print("Background Chrome Dev daemon is ready.", flush=True)
                            break
                        time.sleep(0.3)
                except Exception as e:
                    print(f"Notice: Could not launch local Chrome binary ({e}). Falling back to native Playwright Chromium.", flush=True)

    def stop(self):
        with self._lock:
            if self.process:
                try:
                    self.process.terminate()
                except Exception:
                    pass
                self.process = None


chrome_manager = ChromeProcessManager(headless=settings.HEADLESS)


def inject_auth_cookies(context: BrowserContext):
    """
    Injects authentication cookies into the browser context from:
    1. COOKIES_JSON env var / cookies.json
    2. LI_AT, JSESSIONID, BCOOKIE env vars
    3. Local li_at.txt file
    """
    cookies = settings.get_all_auth_cookies()
    if cookies:
        try:
            # Filter and sanitize cookies for Playwright
            cleaned = []
            for c in cookies:
                if isinstance(c, dict) and "name" in c and "value" in c:
                    cookie_dict = {
                        "name": str(c["name"]).strip(),
                        "value": str(c["value"]).strip(),
                        "domain": str(c.get("domain") or ".linkedin.com"),
                        "path": str(c.get("path") or "/"),
                    }
                    if "httpOnly" in c:
                        cookie_dict["httpOnly"] = bool(c["httpOnly"])
                    if "secure" in c:
                        cookie_dict["secure"] = bool(c["secure"])
                    cleaned.append(cookie_dict)
            if cleaned:
                context.add_cookies(cleaned)
        except Exception as e:
            print(f"Notice: Could not inject cookies into context: {e}")


def create_browser_session(p: Playwright) -> Tuple[Browser, BrowserContext, bool]:
    """
    Creates and returns a browser session (browser, context, is_cdp).
    Works universally:
    - On Windows / local dev: Connects via CDP to Chrome Dev if daemon is running.
    - On Render / Linux / Docker: Launches native Playwright Chromium with anti-bot arguments.
    Automatically injects li_at auth cookies into the context.
    """
    chrome_manager.ensure_running()

    if chrome_manager.is_ready():
        try:
            browser = p.chromium.connect_over_cdp(settings.CDP_URL)
            context = browser.contexts[0] if browser.contexts else browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
            )
            inject_auth_cookies(context)
            return browser, context, True
        except Exception as e:
            print(f"CDP connect failed ({e}), falling back to native Chromium...")

    # Native Playwright Chromium (Standard for Linux / Render / Docker deployment)
    storage_state = settings.get_storage_state()
    browser = p.chromium.launch(
        headless=settings.HEADLESS,
        args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
        ],
    )
    
    context_kwargs = {
        "viewport": {"width": 1920, "height": 1080},
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        "locale": "en-US",
        "extra_http_headers": {
            "accept-language": "en-US,en;q=0.9",
        },
    }
    if storage_state:
        context_kwargs["storage_state"] = storage_state

    context = browser.new_context(**context_kwargs)
    
    # Hide automation flags
    try:
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)
    except Exception:
        pass

    # Ensure any active li_at or custom auth cookies are injected/updated
    inject_auth_cookies(context)

    return browser, context, False


def close_browser_session(browser: Browser, context: BrowserContext, is_cdp: bool):
    """
    Cleans up browser resources after a scraping run.
    """
    try:
        if not is_cdp:
            context.close()
            browser.close()
    except Exception:
        pass

