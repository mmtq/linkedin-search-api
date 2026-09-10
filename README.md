# LinkedIn Search & Scraping API Service

A modular, production-ready FastAPI web service with automated Playwright browser automation for scraping LinkedIn jobs and posts with full descriptions, permalinks, and human-like browsing pagination.

---

## 🚀 Features

- **Jobs Scraping (`/api/jobs`)**:
  - Multi-page pagination (Pages 1–5+).
  - Sorted by latest (`sortBy=DD`).
  - Direct navigable job URLs (`https://www.linkedin.com/jobs/view/{job_id}/`).
  - 100% full, un-truncated job descriptions via multi-lingual SDUI extraction and fallback direct fetching.
- **Posts Scraping (`/api/posts`)**:
  - Stream pagination with multi-lingual "Load more" button automation.
  - Sorted by latest (`sortBy="date_posted"`).
  - Exact direct post permalinks (`/feed/update/urn:li:share:...` / `activity:...`).
  - 100% full un-truncated post text via automated inline expansion.
- **Dual-Mode Browser Support**:
  - **Local Dev**: Connects via CDP to Chrome Dev daemon.
  - **Cloud/Render**: Runs native headless Playwright Chromium with anti-detection flags inside Linux containers.
- **Interactive Documentation**: Swagger UI at `/docs`.

---

## 🔐 Authentication (`li_at` Cookie)

The service supports LinkedIn session authentication via the `li_at` cookie. The cookie is read with the following priority:

1. **`LI_AT` environment variable** (Recommended for Render and cloud hosting).
2. **`LINKEDIN_LI_AT` environment variable**.
3. **`li_at.txt` file** in the project root (for local testing).

---

## 🌐 Deploying to Render (Step-by-Step)

### Option 1: Render Docker Deployment (Recommended)

1. **Push your repository** to GitHub or GitLab.
2. Go to your [Render Dashboard](https://dashboard.render.com/) and click **New + > Web Service**.
3. Connect your repository.
4. Set the following settings:
   - **Environment**: `Docker`
   - **Dockerfile Path**: `Dockerfile`
   - **Plan**: `Starter` (or higher, recommended for browser automation)
5. Under **Environment Variables**, add:
   - `LI_AT`: `your_linkedin_li_at_cookie_value_here`
   - `HEADLESS`: `true`
6. Click **Create Web Service**.

---

### Option 2: Render Blueprint (`render.yaml`)

1. Connect your repo to Render Blueprints.
2. Render will automatically detect [render.yaml](file:///e:/testingLinkedIn/render.yaml).
3. In the Render dashboard, input your `LI_AT` environment variable when prompted.

---

## 💻 Local Development

### 1. Install Dependencies
```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. Configure `li_at`
Either create a `li_at.txt` file in the project root containing your LinkedIn session cookie, or set the environment variable:
```bash
# Windows PowerShell:
$env:LI_AT="your_cookie_value"

# Linux / macOS:
export LI_AT="your_cookie_value"
```

### 3. Run FastAPI Server
```bash
python main.py
```
Open your browser at `http://127.0.0.1:8000/docs` to test endpoints interactively.

---

## 📡 API Endpoints

| Endpoint | Method | Parameters | Description |
| :--- | :--- | :--- | :--- |
| `/api/jobs` | `GET` | `query`, `location`, `pages`, `limit`, `sort_by_latest` | Scrapes jobs with full descriptions and direct URLs |
| `/api/posts` | `GET` | `query`, `pages`, `limit`, `sort_by_latest` | Scrapes posts with direct permalinks and full text |
| `/api/search` | `GET` | `query`, `location`, `pages`, `limit`, `sort_by_latest` | Scrapes both jobs and posts in a single combined response |
| `/api/health` | `GET` | — | Health check returning service status, cookie status, and browser mode |
