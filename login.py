"""
LinkedIn One-Time Login Helper
==============================
Run this ONCE to log into LinkedIn inside a visible Playwright browser.
The session is saved to the `linkedin-profile/` directory and reused
by the scraper on every subsequent run — no more cookie copying needed.

Usage:
    python login.py

Steps:
    1. A real Chrome window will open to linkedin.com/login
    2. Log in with your credentials (or via Google/SSO)
    3. Complete any 2FA / CAPTCHA if prompted
    4. Once you see your LinkedIn feed, press ENTER in this terminal
    5. The session is saved — you're done!
"""

import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

PROFILE_DIR = Path("linkedin-profile")
PROFILE_DIR.mkdir(parents=True, exist_ok=True)


def main():
    print("=" * 60)
    print(" LinkedIn One-Time Login")
    print("=" * 60)
    print()
    print("A browser window will open. Please:")
    print("  1. Log in with your LinkedIn credentials")
    print("  2. Complete any 2FA or CAPTCHA")
    print("  3. Wait until you see your LinkedIn feed")
    print("  4. Come back here and press ENTER")
    print()

    with sync_playwright() as p:
        # Launch a VISIBLE (non-headless) persistent context
        context = p.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            headless=False,  # Visible window so you can log in
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
            ],
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/130.0.0.0 Safari/537.36"
            ),
        )

        # Open LinkedIn login page
        page = context.new_page()
        page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")

        print("Browser opened. Log in now...")
        print()
        input(">>> Press ENTER here once you see your LinkedIn feed: ")
        print()

        # Verify we're authenticated
        current_url = page.url
        cookies = context.cookies()
        li_at_cookie = next((c for c in cookies if c["name"] == "li_at"), None)

        if li_at_cookie:
            print(f"✅ Login successful! li_at captured.")
            print(f"   Session saved to: {PROFILE_DIR.resolve()}")
            print()
            print("   The scraper will now use this session automatically.")
            print("   You do NOT need to copy/paste li_at.txt anymore.")
            print()
            # Also write it to li_at.txt for compatibility
            Path("li_at.txt").write_text(li_at_cookie["value"], encoding="utf-8")
            print("   Also saved to li_at.txt for reference.")
        else:
            print("⚠️  Could not find li_at cookie. Are you logged in?")
            print(f"   Current URL: {current_url}")
            print("   Try running this script again and ensure you're fully logged in.")

        # Close — Playwright auto-saves all session state to disk
        context.close()
        print()
        print("Browser closed. Session persisted to disk.")


if __name__ == "__main__":
    main()
