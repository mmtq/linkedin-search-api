import os
import sys
from pathlib import Path
from typing import Optional, List, Dict, Any
from pydantic import BaseModel


class Settings(BaseModel):
    # App info
    APP_NAME: str = "LinkedIn Search & Scraping API"
    APP_VERSION: str = "1.0.0"
    HOST: str = os.environ.get("HOST", "0.0.0.0")
    PORT: int = int(os.environ.get("PORT", "8000"))

    # Chrome & Playwright configuration
    CHROME_DEV_PATH: str = os.environ.get(
        "CHROME_DEV_PATH",
        r"C:\Program Files\Google\Chrome Dev\Application\chrome.exe"
        if sys.platform == "win32"
        else "google-chrome-stable",
    )
    PROFILE_DIR: Path = Path("linkedin-profile").resolve()
    DEBUG_PORT: int = int(os.environ.get("DEBUG_PORT", "9222"))
    CDP_URL: str = os.environ.get("CDP_URL", f"http://127.0.0.1:{DEBUG_PORT}")
    HEADLESS: bool = os.environ.get("HEADLESS", "true").lower() in ("true", "1", "yes")

    # Search defaults
    DEFAULT_QUERY: str = "software engineer"
    DEFAULT_LOCATION: str = "Bangladesh"

    def get_li_at_cookie(self) -> str:
        """
        Retrieves the li_at cookie with priority:
        1. LI_AT environment variable (recommended for Render/cloud deployment)
        2. LINKEDIN_LI_AT environment variable
        3. Local li_at.txt file
        """
        cookie = (
            os.environ.get("LI_AT", "").strip()
            or os.environ.get("LINKEDIN_LI_AT", "").strip()
        )
        if not cookie:
            for fname in ["li_at.txt", "li_at"]:
                cookie_file = Path(fname)
                if cookie_file.exists():
                    try:
                        cookie = cookie_file.read_text(encoding="utf-8").strip()
                        if cookie:
                            break
                    except Exception:
                        pass
        return cookie.strip().strip('"').strip("'")

    def get_all_auth_cookies(self) -> list:
        """
        Loads full cookie list from COOKIES_JSON env var, cookies.json file, or individual env vars.
        Allows passing full session state (li_at, JSESSIONID, bcookie, bscookie) for cloud deployment.
        """
        import json

        # 1. Try COOKIES_JSON env var
        cookies_raw = os.environ.get("COOKIES_JSON", "").strip()
        if not cookies_raw and Path("cookies.json").exists():
            try:
                cookies_raw = Path("cookies.json").read_text(encoding="utf-8").strip()
            except Exception:
                pass

        if cookies_raw:
            try:
                data = json.loads(cookies_raw)
                if isinstance(data, list):
                    return data
            except Exception as e:
                print(f"Notice: Could not parse COOKIES_JSON: {e}")

        # 2. Build from individual cookies
        cookies = []
        li_at = self.get_li_at_cookie()
        if li_at:
            cookies.append({
                "name": "li_at",
                "value": li_at,
                "domain": ".linkedin.com",
                "path": "/",
                "httpOnly": True,
                "secure": True,
                "sameSite": "None",
            })

        jsession = os.environ.get("JSESSIONID", "").strip().strip('"').strip("'")
        if jsession:
            cookies.append({
                "name": "JSESSIONID",
                "value": f'"{jsession}"' if not jsession.startswith('"') else jsession,
                "domain": ".linkedin.com",
                "path": "/",
                "httpOnly": False,
                "secure": True,
                "sameSite": "None",
            })

        bcookie = os.environ.get("BCOOKIE", "").strip().strip('"').strip("'")
        if bcookie:
            cookies.append({
                "name": "bcookie",
                "value": f'"{bcookie}"' if not bcookie.startswith('"') else bcookie,
                "domain": ".linkedin.com",
                "path": "/",
                "httpOnly": False,
                "secure": True,
                "sameSite": "None",
            })

        return cookies

    def get_storage_state(self) -> Optional[dict]:
        """
        Returns full storage state (cookies + localStorage) from:
        1. STORAGE_STATE environment variable (JSON or base64)
        2. state.json file in project root
        Automatically merges/updates `li_at` cookie from LI_AT / li_at.txt into state.
        """
        import json, base64
        state_data = None
        state_env = os.environ.get("STORAGE_STATE", "").strip()
        if state_env:
            try:
                if state_env.startswith("{"):
                    state_data = json.loads(state_env)
                else:
                    decoded = base64.b64decode(state_env).decode("utf-8")
                    state_data = json.loads(decoded)
            except Exception as e:
                print(f"Notice: Could not parse STORAGE_STATE env var: {e}")

        if not state_data:
            state_file = Path("state.json")
            if state_file.exists():
                try:
                    state_data = json.loads(state_file.read_text(encoding="utf-8"))
                except Exception as e:
                    print(f"Notice: Could not read state.json: {e}")

        if state_data and isinstance(state_data, dict):
            # Ensure li_at is present and up to date in cookies
            li_at = self.get_li_at_cookie()
            if li_at:
                cookies = state_data.get("cookies", [])
                cookies = [c for c in cookies if c.get("name") != "li_at"]
                cookies.append({
                    "name": "li_at",
                    "value": li_at,
                    "domain": ".linkedin.com",
                    "path": "/",
                    "httpOnly": True,
                    "secure": True,
                    "sameSite": "None",
                })
                state_data["cookies"] = cookies
            return state_data

        return None

    @property
    def has_chrome_binary(self) -> bool:
        return bool(self.CHROME_DEV_PATH and Path(self.CHROME_DEV_PATH).exists())


settings = Settings()


