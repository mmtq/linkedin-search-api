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
            with urllib.request.urlopen(f"{settings.CDP_URL}/json/version", timeout=1) as resp:
                return resp.status == 200
        except Exception:
            return False

    def ensure_running(self):
        with self._lock:
            if not self.is_ready():
                if not settings.has_chrome_binary:
                    # Cloud/Render environment: Native Playwright Chromium will be used directly
                    return

                print(f"Starting background Chrome Dev daemon (headless={self.headless})...")
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
                    for _ in range(30):
                        if self.is_ready():
                            print("Background Chrome Dev daemon is ready.")
                            break
                        time.sleep(0.5)
                except Exception as e:
                    print(f"Notice: Could not launch local Chrome binary ({e}). Falling back to native Playwright Chromium.")

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
    Injects the `li_at` cookie into the browser context if configured via LI_AT env var or li_at.txt.
    """
    li_at_cookie = settings.get_li_at_cookie()
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
            {
                "name": "li_at",
                "value": li_at_cookie,
                "domain": "www.linkedin.com",
                "path": "/",
                "httpOnly": True,
                "secure": True,
                "sameSite": "None",
            },
        ]
        try:
            context.add_cookies(cookies)
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
    context = browser.new_context(
        viewport={"width": 1920, "height": 1080},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        locale="en-US",
    )
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

