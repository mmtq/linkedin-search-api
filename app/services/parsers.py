import re
import urllib.parse
from datetime import datetime, timezone
from typing import List, Dict, Optional, Any, Tuple
from bs4 import BeautifulSoup


# ---------------------------------------------------------------------------
# Canonicalization and Extraction Helpers
# ---------------------------------------------------------------------------

def canonicalize_job_url(raw_url: Optional[str] = None, job_id: Optional[str] = None) -> Optional[str]:
    """
    Returns canonical form https://www.linkedin.com/jobs/view/<job_id> when job_id is known.
    Otherwise returns raw_url minus query string.
    """
    if job_id and str(job_id).strip().isdigit():
        return f"https://www.linkedin.com/jobs/view/{str(job_id).strip()}"
    if not raw_url:
        return None
    clean = raw_url.strip().split("?")[0].rstrip("/")
    if not clean:
        return None
    if not clean.startswith("http"):
        clean = "https://www.linkedin.com" + ("" if clean.startswith("/") else "/") + clean
    return clean


def canonicalize_company_url(raw_url: Optional[str]) -> Optional[str]:
    """
    Returns LinkedIn company page URL without query string or subpaths like /life.
    """
    if not raw_url:
        return None
    clean = raw_url.strip().split("?")[0].rstrip("/")
    if not clean:
        return None
    if not clean.startswith("http"):
        clean = "https://www.linkedin.com" + ("" if clean.startswith("/") else "/") + clean
    # Strip subpaths like /life, /about, /jobs, /people
    clean = re.sub(r"/(?:life|about|jobs|people|posts)/?$", "", clean)
    return clean


def canonicalize_author_url(raw_url: Optional[str]) -> Optional[str]:
    """
    Returns LinkedIn author profile URL without query string.
    """
    if not raw_url:
        return None
    clean = raw_url.strip().split("?")[0].rstrip("/")
    if not clean:
        return None
    if not clean.startswith("http"):
        clean = "https://www.linkedin.com" + ("" if clean.startswith("/") else "/") + clean
    return clean


def extract_post_urn_and_id(raw_str: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Extracts post_urn (e.g. urn:li:activity:7123456789012345678) and its numeric post_id digits.
    Returns (None, None) if not present.
    """
    if not raw_str:
        return None, None
    m = re.search(r"\b(urn:li:(?:activity|ugcPost|share):(\d+))\b", raw_str)
    if m:
        return m.group(1), m.group(2)
    m2 = re.search(r"highlightedUpdateUrn=urn%3Ali%3A(activity|ugcPost|share)%3A(\d+)", raw_str)
    if m2:
        return f"urn:li:{m2.group(1)}:{m2.group(2)}", m2.group(2)
    m3 = re.search(r"(?:shareId|ugcPostId|postId)=(\d+)", raw_str)
    if m3:
        digits = m3.group(1)
        if "shareId" in raw_str:
            return f"urn:li:share:{digits}", digits
        if "ugcPostId" in raw_str:
            return f"urn:li:ugcPost:{digits}", digits
        return f"urn:li:activity:{digits}", digits
    return None, None


def canonicalize_post_url(
    post_urn: Optional[str] = None,
    raw_url: Optional[str] = None,
    author_url: Optional[str] = None,
) -> Optional[str]:
    """
    Returns canonical post permalink without query string.
    Falls back to author's recent-activity feed if direct permalink is not present.
    """
    if post_urn:
        return f"https://www.linkedin.com/feed/update/{post_urn}/"
    if raw_url:
        clean = raw_url.strip().split("?")[0]
        if "/feed/update/" in clean or "/posts/" in clean:
            if clean.startswith("http"):
                return clean.rstrip("/") + "/"
            return f"https://www.linkedin.com{clean}".rstrip("/") + "/"
    if author_url:
        c_author = canonicalize_author_url(author_url)
        if c_author:
            return f"{c_author}/recent-activity/all/"
    return None


def extract_body_links(text_el) -> List[str]:
    """
    Extracts external hrefs inside post body text (de-duplicated, original order preserved),
    unwrapping LinkedIn safety redirects (safety/go/?url=...).
    """
    if not text_el:
        return []
    links: List[str] = []
    for a in text_el.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href == "#":
            continue
        m_safe = re.search(r"[?&]url=([^&]+)", href)
        if m_safe:
            href = urllib.parse.unquote(m_safe.group(1))
        else:
            href = href.split("?")[0]
        if href and href not in links:
            links.append(href)
    return links


def extract_post_media(container) -> List[Dict[str, Optional[str]]]:
    """
    Extracts post media items matching {type: 'image' | 'video' | 'document', url, alt}.
    Excludes profile avatars, company logos, and icon sprites.
    """
    if not container:
        return []
    media: List[Dict[str, Optional[str]]] = []
    seen_urls = set()

    # Images
    for img in container.find_all("img"):
        src = img.get("src") or ""
        if not src or src in seen_urls:
            continue
        alt = img.get("alt") or None
        is_avatar = any(x in src for x in ["profile-displayphoto", "company-logo", "ghost", "data:image"])
        is_media = (
            "feedshare" in src
            or "feedshare-shrink" in src
            or "dms/image" in src
            or (alt and "view image" in alt.lower())
            or "update-components-image" in " ".join(img.get("class", []))
        )
        if is_media and not is_avatar:
            seen_urls.add(src)
            media.append({"type": "image", "url": src, "alt": alt})

    # Videos
    for vid in container.find_all("video"):
        src = vid.get("src")
        if src and src not in seen_urls:
            seen_urls.add(src)
            media.append({"type": "video", "url": src, "alt": None})

    return media


# ---------------------------------------------------------------------------
# Job Description and Search Parsers
# ---------------------------------------------------------------------------

def extract_job_description_from_html(html: str) -> Optional[str]:
    """
    Extracts the full job description from job search right-pane details or standalone job view HTML.
    Supports both classical LinkedIn DOM structures and modern SDUI components across multiple languages.
    """
    soup = BeautifulSoup(html, "html.parser")
    
    # 1. Check standard LinkedIn job details selectors
    candidates = soup.select(
        "#job-details, "
        ".jobs-description-content__text, "
        "article.jobs-description__container, "
        ".jobs-box__html-content, "
        ".show-more-less-html__markup, "
        ".description__text, "
        "section.show-more-less-html, "
        ".jobs-description"
    )
    for c in candidates:
        txt = c.get_text("\n", strip=True)
        if len(txt) > 80:
            return txt

    # 2. Check SDUI text containers under 'About the job' / 'জব সম্পর্কে' in multiple languages
    header_keywords = [
        "about the job", "about this job", "job description", "the role", "about the role",
        "জব সম্পর্কে", "কাজের বিবরণ", "চাকরির বিবরণ", "চাকরি সম্পর্কে",
        "sobre el empleo", "à propos de l'offre d'emploi", "über die stelle"
    ]
    for tag in soup.find_all(["h1", "h2", "h3", "h4", "div", "strong", "span", "p"]):
        t = tag.get_text(strip=True).lower()
        if any(t == kw or t.startswith(kw + ":") for kw in header_keywords):
            curr = tag
            for _ in range(6):
                curr = curr.parent
                if not curr:
                    break
                
                desc_box = curr.select_one('[data-testid="expandable-text-box"], p[componentkey], span.break-words, .text-body-medium')
                if desc_box:
                    desc_text = desc_box.get_text("\n", strip=True)
                    if len(desc_text) > 80:
                        return desc_text

                full_text = curr.get_text("\n", strip=True)
                if len(full_text) > 120:
                    for kw in header_keywords:
                        if full_text.lower().startswith(kw):
                            full_text = full_text[len(kw):].strip()
                            break
                    if len(full_text) > 80:
                        return full_text

    return None


def parse_jobs_html(html: str, page_num: int = 1) -> List[Dict[str, Any]]:
    """
    Parses LinkedIn job search results HTML into structured dictionaries adhering to the JobItem contract.
    """
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    seen = set()
    now_utc = datetime.now(timezone.utc).isoformat()

    cards = soup.select(
        "li[data-occludable-job-id], "
        "div.job-card-container, "
        "div.jobs-search-results-list__list-item, "
        "div.base-card, "
        "li.jobs-search-results__list-item, "
        "div.job-card-list"
    )

    for card in cards:
        title_el = (
            card.select_one("a.job-card-list__title--link")
            or card.select_one("a.job-card-container__link")
            or card.select_one(".artdeco-entity-lockup__title")
            or card.select_one("h3.base-search-card__title")
            or card.select_one("h3")
            or card.select_one("strong")
        )
        title = title_el.get_text(" ", strip=True) if title_el else None

        company_el = (
            card.select_one(".artdeco-entity-lockup__subtitle")
            or card.select_one(".job-card-container__primary-description")
            or card.select_one(".job-card-container__company-name")
            or card.select_one("h4.base-search-card__subtitle")
            or card.select_one("h4")
        )
        company = company_el.get_text(" ", strip=True) if company_el else None

        loc_el = (
            card.select_one(".artdeco-entity-lockup__caption")
            or card.select_one(".job-card-container__metadata-item")
            or card.select_one("span.job-search-card__location")
            or card.select_one(".job-card-container__metadata-wrapper")
        )
        location = loc_el.get_text(" ", strip=True) if loc_el else None

        workplace_type = None
        if location:
            m_wp = re.search(r"\((Hybrid|On-site|Remote)\)", location, re.IGNORECASE)
            if m_wp:
                workplace_type = m_wp.group(1).title()

        card_occludable_id = card.get("data-occludable-job-id") or ""
        card_job_id = card.get("data-job-id") or ""
        link_el = (
            card.select_one("a.job-card-list__title--link")
            or card.select_one("a.job-card-container__link")
            or card.select_one("a.base-card__full-link")
            or card.select_one("a[href*='/jobs/view/']")
        )
        raw_href = link_el.get("href", "").strip() if link_el else ""
        m_id = (
            re.search(r"/jobs/view/(\d+)", raw_href)
            or re.search(r"currentJobId=(\d+)", raw_href)
            or re.search(r"(\d{8,})", card_occludable_id)
            or re.search(r"(\d{8,})", card_job_id)
        )
        job_id = m_id.group(1) if m_id else None
        url = canonicalize_job_url(raw_href, job_id)

        comp_a = card.select_one("a[href*='/company/']")
        company_url = canonicalize_company_url(comp_a.get("href")) if comp_a else None

        posted_text = None
        posted_at = None
        time_tag = card.find("time")
        if time_tag:
            hidden_span = time_tag.find(class_="visually-hidden")
            hidden_txt = hidden_span.get_text(strip=True) if hidden_span else ""
            raw_time_txt = time_tag.get_text(" ", strip=True)
            if hidden_txt:
                raw_time_txt = raw_time_txt.replace(hidden_txt, "").strip()
            posted_text = raw_time_txt
            dt_val = time_tag.get("datetime")
            if dt_val:
                posted_at = dt_val.strip()

        apply_type = None
        footer_items = [li.get_text(" ", strip=True).lower() for li in card.select(".job-card-container__footer-item, .job-card-list__footer-wrapper li")]
        if any("easy apply" in fi for fi in footer_items):
            apply_type = "easy_apply"

        unique_key = job_id or url or (title, company)
        if title and unique_key not in seen:
            seen.add(unique_key)
            jobs.append({
                "title": title,
                "company": company,
                "location": location,
                "url": url,
                "description": None,
                "job_id": job_id,
                "company_url": company_url,
                "posted_text": posted_text,
                "posted_at": posted_at,
                "employment_type": None,
                "seniority_level": None,
                "workplace_type": workplace_type,
                "page": page_num,
                "scraped_at": now_utc,
                "job_function": None,
                "industries": None,
                "applicant_count_text": None,
                "salary_text": None,
                "apply_type": apply_type,
                "apply_url": None,
            })

    return jobs


def parse_posts_html(html: str, page_num: int = 1) -> List[Dict[str, Any]]:
    """
    Parses LinkedIn post search results HTML into structured dictionaries adhering to the PostItem contract.
    """
    soup = BeautifulSoup(html, "html.parser")
    posts = []
    seen = set()
    now_utc = datetime.now(timezone.utc).isoformat()

    containers = soup.select(
        "div[role='listitem'], "
        "div.feed-shared-update-v2, "
        "div[data-view-name*='feed'], "
        "div[componentkey*='expanded'], "
        "li.artdeco-card"
    )

    for c in containers:
        # 1. Author and Author profile URL
        author_links = c.select("a[href*='/in/'], a[href*='/company/'], a[href*='/showcase/']")
        raw_author_url = None
        for al in author_links:
            h = al.get("href", "").strip()
            if h and not h.endswith("/posts") and not h.endswith("/detail"):
                raw_author_url = h
                break
        author_url = canonicalize_author_url(raw_author_url)

        author = None
        for al in author_links:
            txt = al.get_text(" ", strip=True)
            if txt and not txt.startswith("http"):
                author = txt.split("•")[0].strip()
                if author:
                    break
            # Fallback to aria-label
            aria = al.get("aria-label", "")
            if "profile" in aria.lower():
                m_a = re.search(r"View\s+(.+?)(?:’s|'s)?\s+profile", aria, re.IGNORECASE)
                if m_a:
                    author = m_a.group(1).strip()
                    break

        # If still no author, check first paragraph in container
        if not author:
            first_p = c.select_one("p")
            if first_p:
                fp_txt = first_p.get_text(" ", strip=True)
                if fp_txt and len(fp_txt) < 60 and not fp_txt.startswith("•") and not re.match(r"^\d+[smhdwy]", fp_txt):
                    author = fp_txt

        # 2. Author Headline
        author_headline = None
        headline_el = (
            c.select_one(".update-components-actor__description")
            or c.select_one(".feed-shared-actor__description")
            or c.select_one(".update-components-actor__headline")
        )
        if headline_el:
            author_headline = headline_el.get_text(" ", strip=True)
        else:
            all_ps = c.find_all("p")
            for p in all_ps[1:4]:
                pt = p.get_text(" ", strip=True)
                if (
                    pt
                    and pt != author
                    and not pt.startswith("•")
                    and not re.match(r"^(\d+[smhdwy]|\d+\s+(?:minute|hour|day|week|month|year)s?\s+ago|just now)\s*(?:•.*)?$", pt, re.IGNORECASE)
                    and len(pt) < 140
                    and "like" not in pt.lower()
                    and "follow" not in pt.lower()
                ):
                    author_headline = pt
                    break

        # 3. Post URN and Post ID
        post_urn, post_id = extract_post_urn_and_id(str(c))

        # 4. Direct Post Permalink URL
        raw_post_url = None
        for a in c.find_all("a", href=True):
            href = a["href"].strip()
            if "/feed/update/" in href or "/posts/" in href:
                raw_post_url = href
                break
            if "highlightedUpdateUrn=" in href:
                raw_post_url = href
                break

        post_url = canonicalize_post_url(post_urn, raw_post_url, author_url)

        # 5. Posted Text
        posted_text = None
        for s in c.find_all(["p", "span", "time", "div"]):
            t = s.get_text(" ", strip=True)
            m_time = re.match(r"^(\d+[smhdwy]|\d+\s+(?:minute|hour|day|week|month|year)s?\s+ago|just now)\s*(?:•.*)?$", t, re.IGNORECASE)
            if m_time:
                posted_text = m_time.group(1).strip()
                break

        # 6. Text content extraction
        text_el = (
            c.select_one("[data-testid='expandable-text-box']")
            or c.select_one("p[componentkey]")
            or c.select_one(".update-components-text")
            or c.select_one(".feed-shared-update-v2__description")
            or c.select_one(".feed-shared-inline-show-more-text")
            or c.select_one("span.break-words")
        )

        if not text_el:
            for p in c.find_all("p"):
                txt_candidate = p.get_text(" ", strip=True)
                if len(txt_candidate) > 40 and not txt_candidate.startswith("http"):
                    text_el = p
                    break

        if text_el:
            raw_text = text_el.get_text(" ", strip=True)
            cleaned = (
                raw_text.replace("… more", "")
                .replace("... more", "")
                .replace("… see more", "")
                .replace("... see more", "")
                .replace("… আরও", "")
                .replace("... আরও", "")
                .strip()
            )

            if len(cleaned) > 35 and cleaned not in seen:
                seen.add(cleaned)
                links = extract_body_links(text_el)
                media = extract_post_media(c)

                posts.append({
                    "author": author,
                    "author_headline": author_headline,
                    "author_url": author_url,
                    "url": post_url,
                    "text": cleaned,
                    "post_urn": post_urn,
                    "post_id": post_id,
                    "posted_text": posted_text,
                    "posted_at": None,
                    "page": page_num,
                    "scraped_at": now_utc,
                    "links": links,
                    "media": media,
                    "is_repost": None,
                    "original_author": None,
                    "original_url": None,
                })

    if len(posts) < 5:
        for box in soup.select("[data-testid='expandable-text-box'], p[componentkey], .update-components-text"):
            raw = (
                box.get_text(" ", strip=True)
                .replace("… more", "")
                .replace("... more", "")
                .replace("… আরও", "")
                .strip()
            )
            if len(raw) > 35 and raw not in seen:
                seen.add(raw)
                posts.append({
                    "author": None,
                    "author_headline": None,
                    "author_url": None,
                    "url": None,
                    "text": raw,
                    "post_urn": None,
                    "post_id": None,
                    "posted_text": None,
                    "posted_at": None,
                    "page": page_num,
                    "scraped_at": now_utc,
                    "links": extract_body_links(box),
                    "media": [],
                    "is_repost": None,
                    "original_author": None,
                    "original_url": None,
                })

    return posts
