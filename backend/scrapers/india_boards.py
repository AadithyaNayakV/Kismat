"""India job boards: Internshala, Shine, Freshersworld (plain HTML, BeautifulSoup) and
Naukri, Foundit (JavaScript-rendered, Playwright).

Ground rules for every site here:
- robots.txt is checked before every request (HttpClient(respect_robots=True)). In the
  browser, requests to robots-disallowed paths on the site are aborted.
- 2–5 s randomized delay between requests (settings.SCRAPE_DELAY_RANGE).
- A realistic, rotating User-Agent on every request / browser context.
- Pagination stops at settings.INDIA_MAX_PAGES, on an empty page, or when a page
  repeats jobs already seen.
- If a site blocks us (403 / bot protection), the feed fails with a clear message.
  There is deliberately no attempt to get around bot protection.
- Recruiter e-mails and phone numbers that some pages embed are never stored.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Callable, Iterable, Optional
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup

from config import settings
from db.models import Job
from scrapers.base import Feed, HttpClient, PartialResult, random_user_agent
from scrapers.normalize import clean_text, normalize

log = logging.getLogger("scrapers.india")

# Which listings to read. Slugs are the site's own URL words.
INTERNSHALA_INTERNSHIPS = ["python", "software-development", "web-development", "data-science"]
INTERNSHALA_JOBS = ["python", "software-development"]
FRESHERSWORLD_CATEGORIES = [
    "it-software-job-vacancies",
    "internship-job-vacancies",
    "analyst-analytics-job-vacancies",
    "core-technical-job-vacancies",
    "bsc-bca-bbm-job-vacancies",
]
INDIA_FEED_INTERVAL_HOURS = 4


class SiteBlocked(Exception):
    """The site refused us (bot protection / 403)."""


def _slug(query: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")


def _client() -> HttpClient:
    return HttpClient(delay_range=settings.SCRAPE_DELAY_RANGE, respect_robots=True)


def _html(client: HttpClient, url: str) -> str:
    resp = client.get(url, headers={"Accept": "text/html,application/xhtml+xml"})
    return resp.text


def paginate(page_urls: Iterable[str], fetch_page: Callable[[str], list[Job]],
             max_pages: int = 0) -> list[Job]:
    """Fetch pages in order. Stops on an empty page or a page with no new jobs.
    A failure after the first page keeps what was collected (PartialResult)."""
    jobs: dict[str, Job] = {}
    for i, url in enumerate(page_urls):
        if max_pages and i >= max_pages:
            break
        try:
            page_jobs = fetch_page(url)
        except Exception as exc:
            if i == 0:
                raise
            raise PartialResult(list(jobs.values()), f"{url} failed: {type(exc).__name__}: {exc}") from exc
        fresh = [j for j in page_jobs if j.job_id not in jobs]
        for j in fresh:
            jobs[j.job_id] = j
        if not fresh:
            break
    return list(jobs.values())


def run_many(tasks: list[Callable[[], list[Job]]]) -> list[Job]:
    """Run several listing crawls for one feed. If some fail, keep the rest and flag
    the run as partial; if all fail, raise the first error."""
    jobs: list[Job] = []
    errors: list[str] = []
    first_exc: Optional[Exception] = None
    for task in tasks:
        try:
            jobs.extend(task())
        except PartialResult as partial:
            jobs.extend(partial.jobs)
            errors.append(str(partial))
        except Exception as exc:
            first_exc = first_exc or exc
            errors.append(f"{type(exc).__name__}: {exc}")
    if errors:
        if not jobs and first_exc:
            raise first_exc
        raise PartialResult(jobs, "; ".join(errors)[:400])
    return jobs


# --- Internshala --------------------------------------------------------------------

def _parse_internshala(html: str, kind: str) -> list[Job]:
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    for card in soup.select(".individual_internship[internshipid]"):
        link = card.select_one("a.job-title-href")
        if not link:
            continue
        title = link.get_text(" ", strip=True)
        company = card.select_one(".company-name")
        locations = [a.get_text(" ", strip=True) for a in card.select(".locations a")]
        salary_el = card.select_one(".stipend") or card.select_one(".row-1-item span.mobile") \
            or card.select_one(".row-1-item span.desktop")
        posted = card.select_one(".detail-row-2 .color-labels span")
        skills = [s.get_text(strip=True) for s in card.select(".job_skill")]
        labels = [s.get_text(" ", strip=True) for s in card.select(".gray-labels span")]
        remote = any("work from home" in l.lower() for l in locations) or None
        job = normalize(
            title=title,
            company=company.get_text(" ", strip=True) if company else "",
            apply_link=urljoin("https://internshala.com/", link.get("href", "")),
            source="Internshala",
            location=", ".join(locations) or ("Remote" if remote else ""),
            description=card.select_one(".about_job .text").get_text(" ", strip=True)
            if card.select_one(".about_job .text") else "",
            salary=salary_el.get_text(" ", strip=True) if salary_el else "",
            posted=posted.get_text(strip=True) if posted else None,
            tags=skills,
            type_hints=" ".join(labels) + (" internship" if kind == "internships" else ""),
            remote=remote,
        )
        if job:
            jobs.append(job)
    return jobs


def _internshala_listing(kind: str, slug: str) -> Callable[[], list[Job]]:
    suffix = "internship" if kind == "internships" else "jobs"

    def crawl() -> list[Job]:
        client = _client()
        base = f"https://internshala.com/{kind}/{slug}-{suffix}/"
        urls = [base] + [f"{base}page-{n}/" for n in range(2, settings.INDIA_MAX_PAGES + 1)]
        return paginate(urls, lambda u: _parse_internshala(_html(client, u), kind))
    return crawl


def fetch_internshala_internships() -> list[Job]:
    return run_many([_internshala_listing("internships", s) for s in INTERNSHALA_INTERNSHIPS])


def fetch_internshala_jobs() -> list[Job]:
    return run_many([_internshala_listing("jobs", s) for s in INTERNSHALA_JOBS])


# --- Shine (Next.js page; job list is embedded as JSON in __NEXT_DATA__) -------------

_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def _parse_shine(html: str) -> list[Job]:
    m = _NEXT_DATA.search(html)
    if not m:
        raise ValueError("Shine page structure changed: __NEXT_DATA__ not found")
    data = json.loads(m.group(1))
    try:
        results = data["props"]["pageProps"]["initialState"]["jsrp"]["searchresult"]["data"]["results"]
    except (KeyError, TypeError):
        raise ValueError("Shine page structure changed: results not found")
    jobs = []
    for r in results or []:
        slug = r.get("jSlug")
        if not slug:
            continue
        job = normalize(
            title=r.get("jJT"),
            company=r.get("jCName"),
            apply_link=f"https://www.shine.com/jobs/{slug}",
            source="Shine",
            location=", ".join(r.get("jLoc") or []),
            description=r.get("jJD"),  # jRE / jRP (recruiter e-mail/phone) deliberately ignored
            salary=r.get("jSal") or "",
            posted=r.get("jPDate"),
            deadline=r.get("jExpDate"),
            tags=[r.get("jInd"), *(k.strip() for k in (r.get("jKwd") or "").split(","))],
            type_hints="internship" if r.get("jEType") == 3 else ("work from home" if r.get("jEType") == 4 else ""),
            remote=True if r.get("jEType") == 4 else None,
        )
        if job:
            jobs.append(job)
    return jobs


def fetch_shine() -> list[Job]:
    def listing(query: str):
        def crawl():
            client = _client()
            base = f"https://www.shine.com/job-search/{_slug(query)}-jobs"
            urls = [base] + [f"{base}-{n}" for n in range(2, settings.INDIA_MAX_PAGES + 1)]
            return paginate(urls, lambda u: _parse_shine(_html(client, u)))
        return crawl
    return run_many([listing(q) for q in settings.INDIA_QUERIES])


# --- Freshersworld --------------------------------------------------------------------
# Category pages are server-rendered (20 jobs each). "Load more" goes through URLs that
# robots.txt disallows (/jobs/getjobs, *ajax_*), and ?page=N returns page 1 again, so we
# read several categories instead of paging.

def _parse_freshersworld(html: str, category: str) -> list[Job]:
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    for card in soup.select(".job-container[job_id]"):
        url = card.get("job_display_url") or ""
        raw_title = card.select_one(".seo_title")
        title = raw_title.get_text(" ", strip=True) if raw_title else ""
        title = re.sub(r"\s*(Less|More)\s*$", "", title)
        title = re.split(r"\s+Jobs?\s+Opening\s+in\s+", title, maxsplit=1)[0]
        company = card.select_one(".company-name")
        location = card.select_one(".job-location")
        details = [s.get_text(" ", strip=True) for s in card.select(".qualifications")]
        salary = next((d for d in details if re.search(r"\d", d) and re.search(r"(?i)monthly|yearly|lpa|month|annum", d)), "")
        exp = card.select_one(".experience")
        posted = card.select_one(".ago-text")
        desc = card.select_one(".desc")
        job = normalize(
            title=title,
            company=company.get_text(" ", strip=True) if company else "",
            apply_link=url,
            source="Freshersworld",
            location=location.get_text(" ", strip=True) if location else "",
            description=" ".join(filter(None, [
                desc.get_text(" ", strip=True) if desc else "",
                f"Experience: {exp.get_text(strip=True)}" if exp else "",
                f"Qualification: {details[-1]}" if details else "",
            ])),
            salary=salary,
            posted=posted.get_text(strip=True) if posted else None,
            type_hints="internship" if category.startswith(("internship", "apprenticeship")) else "",
        )
        if job:
            jobs.append(job)
    return jobs


def fetch_freshersworld() -> list[Job]:
    def listing(category: str):
        def crawl():
            client = _client()
            return _parse_freshersworld(
                _html(client, f"https://www.freshersworld.com/jobs/category/{category}"), category)
        return crawl
    return run_many([listing(c) for c in FRESHERSWORLD_CATEGORIES])


# --- Headless browser helper (Naukri, Foundit) -----------------------------------------

class Browser:
    """Playwright Chromium with robots.txt enforcement on the target site."""

    def __init__(self, site_host: str):
        self.site_host = site_host
        self.robots = HttpClient()  # only used for robots.txt lookups
        self._pw = self._browser = self._context = None
        self._last = 0.0

    def __enter__(self) -> "Browser":
        from playwright.sync_api import sync_playwright  # imported lazily: optional dependency

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=True)
        self._context = self._browser.new_context(
            user_agent=random_user_agent(), locale="en-IN",
            viewport={"width": 1366, "height": 900},
        )
        self._context.route("**/*", self._route)
        return self

    def __exit__(self, *exc) -> None:
        for obj in (self._context, self._browser):
            try:
                obj and obj.close()
            except Exception:
                pass
        if self._pw:
            self._pw.stop()

    def _route(self, route) -> None:
        req = route.request
        if req.resource_type in ("image", "media", "font"):
            return route.abort()
        if self.site_host in req.url and not self.robots.allowed(req.url):
            log.debug("robots.txt: blocked browser request %s", req.url)
            return route.abort()
        return route.continue_()

    def html(self, url: str, wait_selector: str, timeout_ms: int = 45000) -> str:
        import random
        import time

        if not self.robots.allowed(url):
            raise PermissionError(f"robots.txt disallows {url}")
        gap = random.uniform(*settings.SCRAPE_DELAY_RANGE)
        if self._last and time.monotonic() - self._last < gap:
            time.sleep(gap - (time.monotonic() - self._last))
        page = self._context.new_page()
        try:
            resp = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            status = resp.status if resp else 0
            if status in (401, 403, 429) or "access denied" in (page.title() or "").lower():
                raise SiteBlocked(f"{self.site_host} refused the request (HTTP {status}, bot protection)")
            try:
                page.wait_for_selector(wait_selector, timeout=20000)
            except Exception:
                pass  # parse whatever rendered; an empty result ends pagination
            return page.content()
        finally:
            self._last = time.monotonic()
            page.close()


# --- Naukri (JS-rendered) ---------------------------------------------------------------
# Built from Naukri's known search-page markup. It could not be test-run while this was
# written because naukri.com's robots.txt disallows AI-assistant user agents from reading
# its pages. Naukri also uses strong bot protection, so it may be refused from
# GitHub's servers; the feed then just shows as failed in the run summary.

NAUKRI_CARD = "div.srp-jobtuple-wrapper, article.jobTuple, div.cust-job-tuple"


def _text(el, selector: str) -> str:
    found = el.select_one(selector)
    return found.get_text(" ", strip=True) if found else ""


def _parse_naukri(html: str) -> list[Job]:
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    for card in soup.select(NAUKRI_CARD):
        link = card.select_one("a.title") or card.select_one("a[href*='job-listings']")
        if not link:
            continue
        tags = [li.get_text(strip=True) for li in card.select("ul.tags-gt li, ul.tags li")]
        location = _text(card, ".locWdth, .loc-wrap, .location, .loc")
        job = normalize(
            title=link.get("title") or link.get_text(" ", strip=True),
            company=_text(card, "a.comp-name, .comp-name, .companyInfo a.subTitle"),
            apply_link=urljoin("https://www.naukri.com/", link.get("href", "")),
            source="Naukri",
            location=location,
            description=" ".join(filter(None, [
                _text(card, ".job-desc, .job-description"),
                f"Experience: {_text(card, '.expwdth, .exp-wrap, .experience')}",
            ])),
            salary=_text(card, ".sal-wrap span, .salary, .sal"),
            posted=_text(card, ".job-post-day, .type br + span, .jobTupleFooter .fleft span") or None,
            tags=tags,
            remote=True if re.search(r"(?i)remote|work from home", location) else None,
        )
        if job:
            jobs.append(job)
    return jobs


def fetch_naukri() -> list[Job]:
    with Browser("naukri.com") as browser:
        def listing(query: str):
            def crawl():
                base = f"https://www.naukri.com/{_slug(query)}-jobs"
                urls = [base] + [f"{base}-{n}" for n in range(2, settings.INDIA_MAX_PAGES + 1)]
                return paginate(urls, lambda u: _parse_naukri(browser.html(u, NAUKRI_CARD)))
            return crawl
        return run_many([listing(q) for q in settings.INDIA_QUERIES])


# --- Foundit (JS-rendered) -------------------------------------------------------------
# During development foundit.in answered headless Chromium with "403 Access Denied"
# (bot protection), so this parser is based on the page's CSS class names and could not
# be verified end-to-end. It may start working from a different network.

FOUNDIT_CARD = ".srpResultCard, .cardContainer"


def _parse_foundit(html: str) -> list[Job]:
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    for card in soup.select(FOUNDIT_CARD):
        title = _text(card, ".jobTitle")
        link = card.select_one("a[href*='/job/']")
        job_id = card.get("id") or ""
        href = link.get("href") if link else (f"/job/{job_id}" if job_id.isdigit() else "")
        if not title or not href:
            continue
        details = card.get_text(" | ", strip=True)
        posted = re.search(r"(\d+\s+\w+\s+ago|today|just now)", details, re.I)
        location = _text(card, "[class*='location'], [class*='Location']")
        job = normalize(
            title=title,
            company=_text(card, ".companyName"),
            apply_link=urljoin("https://www.foundit.in/", href),
            source="Foundit",
            location=location,
            description=clean_text(details),
            posted=posted.group(1) if posted else None,
            remote=True if re.search(r"(?i)remote|work from home", location) else None,
        )
        if job:
            jobs.append(job)
    return jobs


def fetch_foundit() -> list[Job]:
    with Browser("foundit.in") as browser:
        def listing(query: str):
            def crawl():
                urls = [f"https://www.foundit.in/srp/results?query={quote(query)}"
                        + (f"&start={(n - 1) * 15}" if n > 1 else "")
                        for n in range(1, settings.INDIA_MAX_PAGES + 1)]
                return paginate(urls, lambda u: _parse_foundit(browser.html(u, FOUNDIT_CARD)))
            return crawl
        return run_many([listing(q) for q in settings.INDIA_QUERIES])


def feeds() -> list[Feed]:
    every = INDIA_FEED_INTERVAL_HOURS
    return [
        Feed("internshala:internships", "Internshala", "india", fetch_internshala_internships, min_interval_hours=every),
        Feed("internshala:jobs", "Internshala", "india", fetch_internshala_jobs, min_interval_hours=every),
        Feed("shine", "Shine", "india", fetch_shine, min_interval_hours=every),
        Feed("freshersworld", "Freshersworld", "india", fetch_freshersworld, min_interval_hours=every),
        Feed("naukri", "Naukri", "india", fetch_naukri, min_interval_hours=every),
        Feed("foundit", "Foundit", "india", fetch_foundit, min_interval_hours=every),
    ]
