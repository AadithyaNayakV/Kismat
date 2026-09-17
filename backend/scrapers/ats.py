"""ATS company loop: Greenhouse, Lever, Ashby, SmartRecruiters, Breezy HR, Teamtailor.

Each (platform, company) pair in config/companies.py becomes its own Feed, so a
renamed or removed company only fails its own feed. These boards return *all* of a
company's open jobs in one go, so they are marked `complete=True`, and expiry can treat
a job that disappears as removed.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

import feedparser

from config import settings
from config.companies import COMPANIES
from db.models import Job
from scrapers.base import Feed, HttpClient, PartialResult
from scrapers.normalize import format_salary, normalize

log = logging.getLogger("scrapers.ats")

SMARTRECRUITERS_PAGE = 100
SMARTRECRUITERS_MAX_PAGES = 10


def _client() -> HttpClient:
    return HttpClient(delay_range=settings.ATS_DELAY_RANGE)


def _is_remote(*values) -> Optional[bool]:
    text = " ".join(str(v) for v in values if v).lower()
    return True if "remote" in text else None


# --- Greenhouse ---------------------------------------------------------------------

def greenhouse(slug: str) -> list[Job]:
    data = _client().get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
                              params={"content": "true"})
    jobs = []
    for item in data.get("jobs", []):
        location = (item.get("location") or {}).get("name", "")
        departments = [d.get("name", "") for d in item.get("departments") or []]
        job = normalize(
            title=item.get("title"),
            company=item.get("company_name") or slug,
            apply_link=item.get("absolute_url"),
            source="Greenhouse",
            location=location,
            description=item.get("content"),
            posted=item.get("first_published") or item.get("updated_at"),
            deadline=item.get("application_deadline"),
            tags=departments,
            remote=_is_remote(location),
        )
        if job:
            jobs.append(job)
    return jobs


# --- Lever ------------------------------------------------------------------------------

def lever(slug: str) -> list[Job]:
    data = _client().get_json(f"https://api.lever.co/v0/postings/{slug}", params={"mode": "json"})
    jobs = []
    for item in data if isinstance(data, list) else []:
        cats = item.get("categories") or {}
        lists = " ".join(f"{l.get('text', '')} {l.get('content', '')}" for l in item.get("lists") or [])
        salary = ""
        rng = item.get("salaryRange") or {}
        if rng.get("min") or rng.get("max"):
            salary = format_salary(rng.get("min"), rng.get("max"), rng.get("currency", ""),
                                   (rng.get("interval") or "").replace("per-", ""))
        location = cats.get("location") or ", ".join(cats.get("allLocations") or [])
        job = normalize(
            title=item.get("text"),
            company=slug.replace("-", " ").title(),
            apply_link=item.get("hostedUrl") or item.get("applyUrl"),
            source="Lever",
            location=location.title() if location.islower() else location,
            description=f"{item.get('descriptionPlain') or ''} {lists} {item.get('additionalPlain') or ''}",
            salary=salary,
            posted=item.get("createdAt"),
            tags=[cats.get("team"), cats.get("department")],
            type_hints=cats.get("commitment") or "",
            remote=True if (item.get("workplaceType") == "remote") else _is_remote(location),
        )
        if job:
            jobs.append(job)
    return jobs


# --- Ashby ------------------------------------------------------------------------------

def ashby(slug: str) -> list[Job]:
    data = _client().get_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}",
                              params={"includeCompensation": "true"})
    jobs = []
    for item in data.get("jobs", []):
        if item.get("isListed") is False:
            continue
        locations = [item.get("location") or ""] + [
            (l or {}).get("location", "") for l in item.get("secondaryLocations") or []]
        comp = (item.get("compensation") or {}).get("compensationTierSummary") or ""
        job = normalize(
            title=item.get("title"),
            company=slug.replace("-", " ").title(),
            apply_link=item.get("jobUrl") or item.get("applyUrl"),
            source="Ashby",
            location=", ".join(l for l in locations if l)[:200],
            description=item.get("descriptionPlain") or item.get("descriptionHtml"),
            salary=comp,
            posted=item.get("publishedAt"),
            tags=[item.get("department"), item.get("team")],
            type_hints=item.get("employmentType") or "",
            remote=True if item.get("isRemote") or item.get("workplaceType") == "Remote" else None,
        )
        if job:
            jobs.append(job)
    return jobs


# --- SmartRecruiters (paginated; listing has no description) ---------------------------

def smartrecruiters(slug: str) -> list[Job]:
    client = _client()
    jobs: list[Job] = []
    url = f"https://api.smartrecruiters.com/v1/companies/{slug}/postings"
    for page in range(SMARTRECRUITERS_MAX_PAGES):
        try:
            data = client.get_json(url, params={"limit": SMARTRECRUITERS_PAGE,
                                                "offset": page * SMARTRECRUITERS_PAGE})
        except Exception as exc:
            if page == 0:
                raise
            raise PartialResult(jobs, f"page {page + 1} failed: {exc}") from exc
        for item in data.get("content", []):
            loc = item.get("location") or {}
            company = item.get("company") or {}
            job = normalize(
                title=item.get("name"),
                company=company.get("name") or slug,
                apply_link=f"https://jobs.smartrecruiters.com/{company.get('identifier') or slug}/{item.get('id')}",
                source="SmartRecruiters",
                location=loc.get("fullLocation") or ", ".join(
                    x for x in (loc.get("city"), loc.get("country", "").upper()) if x),
                posted=item.get("releasedDate"),
                tags=[(item.get("function") or {}).get("label"), (item.get("department") or {}).get("label"),
                      (item.get("industry") or {}).get("label")],
                type_hints=f"{(item.get('typeOfEmployment') or {}).get('label', '')} "
                           f"{(item.get('experienceLevel') or {}).get('label', '')}",
                remote=True if loc.get("remote") else None,
            )
            if job:
                jobs.append(job)
        if (page + 1) * SMARTRECRUITERS_PAGE >= data.get("totalFound", 0):
            return jobs
    raise PartialResult(jobs, f"stopped at {SMARTRECRUITERS_MAX_PAGES} pages (board too large)")


# --- Breezy HR (listing has no description) ---------------------------------------------

def breezy(slug: str) -> list[Job]:
    data = _client().get_json(f"https://{slug}.breezy.hr/json")
    jobs = []
    for item in data if isinstance(data, list) else []:
        loc = item.get("location") or {}
        location = loc.get("name") or ", ".join(
            x for x in (loc.get("city"), (loc.get("state") or {}).get("name"),
                        (loc.get("country") or {}).get("name")) if x)
        salary = item.get("salary")
        job = normalize(
            title=item.get("name"),
            company=(item.get("company") or {}).get("name") or slug.replace("-", " ").title(),
            apply_link=item.get("url"),
            source="Breezy HR",
            location=location,
            salary=salary if isinstance(salary, str) else "",
            posted=item.get("published_date"),
            tags=[item.get("department")] if isinstance(item.get("department"), str) else [],
            type_hints=(item.get("type") or {}).get("name", ""),
            remote=True if loc.get("is_remote") else _is_remote(location, item.get("name")),
        )
        if job:
            jobs.append(job)
    return jobs


# --- Teamtailor (public career-site RSS; the JSON API needs a per-company key) ---------

def teamtailor(slug: str) -> list[Job]:
    host = slug if "." in slug else f"{slug}.teamtailor.com"
    resp = _client().get(f"https://{host}/jobs.rss")
    feed = feedparser.parse(resp.content)
    company = (feed.feed.get("title") or slug).strip()
    jobs = []
    for e in feed.entries:
        location = ", ".join(x for x in (e.get("tt_city"), e.get("tt_country")) if x) or e.get("tt_name", "")
        job = normalize(
            title=e.get("title"),
            company=company,
            apply_link=e.get("link"),
            source="Teamtailor",
            location=location,
            description=e.get("summary"),
            posted=e.get("published"),
            tags=[e.get("tt_department"), e.get("tt_role")],
            remote=True if (e.get("remotestatus") or "").lower() in ("fully", "remote") else None,
        )
        if job:
            jobs.append(job)
    return jobs


PLATFORMS: dict[str, tuple[str, Callable[[str], list[Job]]]] = {
    "greenhouse": ("Greenhouse", greenhouse),
    "lever": ("Lever", lever),
    "ashby": ("Ashby", ashby),
    "smartrecruiters": ("SmartRecruiters", smartrecruiters),
    "breezy": ("Breezy HR", breezy),
    "teamtailor": ("Teamtailor", teamtailor),
}


def _bind(fn: Callable[[str], list[Job]], slug: str) -> Callable[[], list[Job]]:
    return lambda: fn(slug)


def feeds() -> list[Feed]:
    out = []
    for platform, slugs in COMPANIES.items():
        if platform not in PLATFORMS:
            log.warning("Unknown ATS platform in config/companies.py: %s", platform)
            continue
        source, fn = PLATFORMS[platform]
        for slug in dict.fromkeys(slugs):  # de-duplicate, keep order
            out.append(Feed(f"{platform}:{slug}", source, "ats", _bind(fn, slug),
                            complete=True, max_age_days=None))
    return out
