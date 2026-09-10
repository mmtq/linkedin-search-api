import os
import sys
from pathlib import Path
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
        return cookie

    @property
    def has_chrome_binary(self) -> bool:
        return bool(self.CHROME_DEV_PATH and Path(self.CHROME_DEV_PATH).exists())


settings = Settings()

