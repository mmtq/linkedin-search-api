from typing import List, Dict, Optional, Any
from bs4 import BeautifulSoup


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
            # Check direct child or parent container
            curr = tag
            for _ in range(6):
                curr = curr.parent
                if not curr:
                    break
                
                # Check for explicit expandable text box or paragraph inside this container
                desc_box = curr.select_one('[data-testid="expandable-text-box"], p[componentkey], span.break-words, .text-body-medium')
                if desc_box:
                    desc_text = desc_box.get_text("\n", strip=True)
                    if len(desc_text) > 80:
                        return desc_text

                full_text = curr.get_text("\n", strip=True)
                if len(full_text) > 120:
                    # Clean leading header if present
                    for kw in header_keywords:
                        if full_text.lower().startswith(kw):
                            full_text = full_text[len(kw):].strip()
                            break
                    if len(full_text) > 80:
                        return full_text

    return None


def parse_jobs_html(html: str) -> List[Dict[str, Any]]:
    """
    Parses LinkedIn job search results HTML into structured dictionaries.
    """
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    seen = set()

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

        link_el = (
            card.select_one("a.job-card-list__title--link")
            or card.select_one("a.job-card-container__link")
            or card.select_one("a.base-card__full-link")
            or card.select_one("a[href*='/jobs/view/']")
        )
        url = None
        if link_el and link_el.get("href"):
            raw_url = link_el.get("href").strip()
            if raw_url.startswith("http"):
                url = raw_url.split("?")[0]
            else:
                url = "https://www.linkedin.com" + raw_url.split("?")[0]

        unique_key = url or (title, company)
        if title and unique_key not in seen:
            seen.add(unique_key)
            jobs.append({
                "title": title,
                "company": company,
                "location": location,
                "url": url,
                "description": None,
            })

    return jobs


def parse_posts_html(html: str) -> List[Dict[str, Any]]:
    """
    Parses LinkedIn post search results HTML into structured dictionaries,
    extracting author, author_url, direct post permalink URL, and complete post text.
    """
    import re

    soup = BeautifulSoup(html, "html.parser")
    posts = []
    seen = set()

    containers = soup.select(
        "div[role='listitem'], "
        "div.feed-shared-update-v2, "
        "div[data-view-name*='feed'], "
        "div[componentkey*='expanded'], "
        "li.artdeco-card"
    )

    for c in containers:
        # 1. Author and Author profile URL (user profile, company, or showcase)
        author_el = (
            c.select_one("a[href*='/in/']")
            or c.select_one("a[href*='/company/']")
            or c.select_one("a[href*='/showcase/']")
        )
        author = author_el.get_text(" ", strip=True) if author_el else None
        if author and "•" in author:
            author = author.split("•")[0].strip()

        author_url = None
        if author_el and author_el.get("href"):
            raw_author_url = author_el.get("href").strip()
            if raw_author_url.startswith("http"):
                author_url = raw_author_url.split("?")[0]
            else:
                author_url = "https://www.linkedin.com" + raw_author_url.split("?")[0]

        # 2. Direct Post Permalink URL Extraction
        post_url = None

        # 2a. Direct hrefs
        for a in c.find_all("a", href=True):
            href = a["href"].strip()
            if "/feed/update/" in href or "/posts/" in href:
                post_url = href.split("?")[0]
                break
            if "highlightedUpdateUrn=" in href:
                m = re.search(r"highlightedUpdateUrn=urn%3Ali%3Aactivity%3A(\d+)", href)
                if m:
                    post_url = f"https://www.linkedin.com/feed/update/urn:li:activity:{m.group(1)}/"
                    break

        # 2b. Extract from SDUI FeTranslationUrn / data attributes
        if not post_url:
            card_html = str(c)
            if (m_share := re.search(r"shareId=(\d+)", card_html)):
                post_url = f"https://www.linkedin.com/feed/update/urn:li:share:{m_share.group(1)}/"
            elif (m_ugc := re.search(r"ugcPostId=(\d+)", card_html)):
                post_url = f"https://www.linkedin.com/feed/update/urn:li:ugcPost:{m_ugc.group(1)}/"
            elif (m_post := re.search(r"postId=(\d+)", card_html)):
                post_url = f"https://www.linkedin.com/feed/update/urn:li:activity:{m_post.group(1)}/"
            elif (m_urn := re.search(r"urn:li:(?:activity|ugcPost|share):(\d+)", card_html)):
                post_url = f"https://www.linkedin.com/feed/update/{m_urn.group(0)}/"

        # 2c. Fallback to author's recent activity stream if direct post ID not present
        if not post_url and author_url:
            post_url = f"{author_url.rstrip('/')}/recent-activity/all/"

        # 3. Text content extraction
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
                posts.append({
                    "author": author,
                    "author_url": author_url,
                    "url": post_url,
                    "text": cleaned,
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
                    "author_url": None,
                    "url": None,
                    "text": raw,
                })

    return posts
