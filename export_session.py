"""
Utility script to export your full authenticated LinkedIn session state (50+ cookies, session tokens, localStorage)
from your local Chrome Dev browser to `state.json`.

Usage:
    python export_session.py
"""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright
from app.core.config import settings

def export():
    print("Connecting to local Chrome Dev session...")
    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(settings.CDP_URL)
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            state = ctx.storage_state()
            li_at = settings.get_li_at_cookie()
            cookies = state.get("cookies", [])
            has_li_at = any(c.get("name") == "li_at" for c in cookies)
            if not has_li_at and li_at:
                cookies.append({
                    "name": "li_at",
                    "value": li_at,
                    "domain": ".linkedin.com",
                    "path": "/",
                    "httpOnly": True,
                    "secure": True,
                    "sameSite": "None",
                })
                state["cookies"] = cookies
            
            import json
            Path("state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
            cookies_count = len(state.get("cookies", []))
            print(f"✅ Successfully exported {cookies_count} session cookies (including li_at) to state.json!")
            print("👉 You can now commit state.json to Git, or paste its contents into Render as STORAGE_STATE.")
    except Exception as e:
        print(f"❌ Error exporting session: {e}")
        print("Make sure your Chrome Dev daemon or the FastAPI app is running.")

if __name__ == "__main__":
    export()
