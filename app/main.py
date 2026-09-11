import asyncio
import sys
import time
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

    @app.middleware("http")
    async def log_requests(request, call_next):
        start_time = time.time()
        client_host = request.client.host if request.client else "unknown"
        query_str = f"?{request.url.query}" if request.url.query else ""
        print(f"\n📥 [{time.strftime('%H:%M:%S')}] Incoming {request.method} {request.url.path}{query_str} from {client_host}", flush=True)
        
        try:
            response = await call_next(request)
            process_time = round(time.time() - start_time, 2)
            print(f"📤 [{time.strftime('%H:%M:%S')}] Completed {request.method} {request.url.path} -> {response.status_code} ({process_time}s)", flush=True)
            return response
        except Exception as e:
            process_time = round(time.time() - start_time, 2)
            print(f"❌ [{time.strftime('%H:%M:%S')}] Failed {request.method} {request.url.path} -> {e} ({process_time}s)", flush=True)
            raise e

    @app.get("/", tags=["General"])
    def root():
        from pathlib import Path

        profile_cookies_db = Path(settings.PROFILE_DIR) / "Default" / "Cookies"
        if profile_cookies_db.exists():
            authenticated = True
            session_source = "persistent_profile"
            action_required = None
        elif settings.get_li_at_cookie():
            authenticated = True
            session_source = "li_at_file"
            action_required = None
        else:
            authenticated = False
            session_source = "none"
            action_required = "Run `python login.py` to authenticate, then restart the server."

        return {
            "service": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "status": "online",
            "authenticated": authenticated,
            "session_source": session_source,
            "action_required": action_required,
            "docs": "/docs",
            "endpoints": {
                "search_jobs": "/api/jobs?query=software%20engineer&location=Bangladesh&limit=10",
                "search_posts": "/api/posts?query=software%20engineer&limit=10",
                "search_all": "/api/search?query=software%20engineer&location=Bangladesh&limit=10",
            },
        }


    # Mount API routers
    app.include_router(api_router)

    return app


app = create_app()
