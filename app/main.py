import asyncio
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import settings
from app.core.browser import chrome_manager
from app.api.routes import router as api_router

# Ensure UTF-8 output on Windows console
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    cookie_present = bool(settings.get_li_at_cookie())
    cookie_status = "Configured (Authenticated)" if cookie_present else "Not set (Anonymous/Public)"
    print("\n" + "=" * 60)
    print(f"🚀 {settings.APP_NAME} v{settings.APP_VERSION}")
    print(f"🔑 LinkedIn Session Cookie (li_at): {cookie_status}")
    if settings.has_chrome_binary:
        print(f"🌐 Mode: Chrome Dev Daemon (CDP on {settings.CDP_URL})")
        await asyncio.to_thread(chrome_manager.ensure_running)
    else:
        print(f"🌐 Mode: Native Playwright Chromium (Cloud/Render Optimized)")
    print(f"📖 Interactive API Docs: http://{settings.HOST}:{settings.PORT}/docs")
    print("=" * 60 + "\n")
    yield
    print("\n--- Shutting down services ---")
    await asyncio.to_thread(chrome_manager.stop)


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        description="Modular FastAPI service with persistent headless Chrome daemon for LinkedIn scraping.",
        version=settings.APP_VERSION,
        lifespan=lifespan,
    )

    @app.get("/", tags=["General"])
    def root():
        return {
            "service": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "status": "online",
            "docs": "/docs",
            "endpoints": {
                "search_jobs": "/api/jobs?query=software%20engineer&location=Bangladesh&limit=10",
                "search_posts": "/api/posts?query=software%20engineer&limit=10",
                "combined_search": "/api/search?query=software%20engineer&location=Bangladesh&limit=10",
                "health": "/api/health",
            },
        }

    # Mount API routers
    app.include_router(api_router)

    return app


app = create_app()
