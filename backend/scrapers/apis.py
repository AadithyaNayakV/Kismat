"""Free job APIs, built on one reusable pattern: `ApiPuller`.

An ApiPuller needs three small functions:
  requests()  - a generator that yields request dicts ({url, params, method, json,
                headers}); after each yield it receives the parsed JSON response, so
                it can follow cursors / next links / stop early.
  items(data) - pulls the list of raw job dicts out of one response.
  mapper(raw) - turns one raw dict into a Job via `normalize(...)` (or None to skip).

Error handling is shared: if the first request fails, the feed fails. If a later page
fails, the jobs collected so far are kept and the run is flagged partial.

Sources: RemoteOK, Remotive, Himalayas, Jobicy, Arbeitnow, The Muse (no key), plus
Jooble, Adzuna, Findwork (free key/token, skipped when the env var is missing).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Callable, Generator, Optional

from config import settings
from db.models import Job
from scrapers.base import Feed, HttpClient, PartialResult
from scrapers.normalize import format_salary, normalize

log = logging.getLogger("scrapers.apis")

RequestGen = Generator[dict, Any, None]


@dataclass
class ApiPuller:
    name: str
    requests: Callable[[], RequestGen]
    items: Callable[[Any], list]
    mapper: Callable[[dict], Optional[Job]]
    delay_range: Optional[tuple[float, float]] = (0.5, 1.0)

    def fetch(self) -> list[Job]:
        client = HttpClient(delay_range=self.delay_range)
        jobs: list[Job] = []
        gen = self.requests()
        pages = 0
        try:
            req = next(gen)
        except StopIteration:
            return jobs
        while True:
            try:
                req = dict(req)
                method = req.pop("method", "GET")
                url = req.pop("url")
                if method == "POST":
                    data = client.post_json(url, req.pop("json", {}), **req)
                else:
                    data = client.get_json(url, **req)
            except Exception as exc:
                if pages == 0:
                    raise
                raise PartialResult(jobs, f"page {pages + 1} failed: {type(exc).__name__}: {exc}") from exc
            pages += 1
            raw_items = self.items(data) or []
            for raw in raw_items:
                try:
                    job = self.mapper(raw)
                except Exception as exc:  # one malformed record shouldn't kill the feed
                    log.debug("[%s] skipped malformed item: %s", self.name, exc)
                    continue
                if job:
                    jobs.append(job)
            try:
                req = gen.send(data)
            except StopIteration:
                break
        log.debug("[%s] %d pages, %d jobs", self.name, pages, len(jobs))
        return jobs


def single(url: str, **kwargs) -> Callable[[], RequestGen]:
    def gen():
        yield {"url": url, **kwargs}
    return gen


def _names(values) -> list[str]:
    """[{'name': 'X'}, 'Y'] -> ['X', 'Y']"""
    out = []
    for v in values or []:
        if isinstance(v, dict):
            v = v.get("name") or v.get("label")
        if v:
            out.append(str(v))
    return out


# --- RemoteOK -----------------------------------------------------------------------
# Terms: link back to the Remote OK page and name Remote OK as source.

def _map_remoteok(item: dict) -> Optional[Job]:
    if "position" not in item:
        return None  # first element is the legal notice
    return normalize(
        title=item.get("position"),
        company=item.get("company"),
        apply_link=item.get("url") or item.get("apply_url"),
        source="RemoteOK",
        location=item.get("location") or "Remote",
        description=item.get("description"),
        salary=format_salary(item.get("salary_min"), item.get("salary_max"), "USD", "year"),
        posted=item.get("date") or item.get("epoch"),
        tags=item.get("tags") or [],
        remote=True,
    )


remoteok = ApiPuller(
    "remoteok",
    single("https://remoteok.com/api"),
    lambda d: [x for x in d if isinstance(x, dict)],
    _map_remoteok,
)


# --- Remotive -----------------------------------------------------------------------
# Terms: link back + credit Remotive; poll at most ~4 times a day (throttled to 6h).

def _map_remotive(item: dict) -> Optional[Job]:
    return normalize(
        title=item.get("title"),
        company=item.get("company_name"),
        apply_link=item.get("url"),
        source="Remotive",
        location=item.get("candidate_required_location") or "Remote",
        description=item.get("description"),
        salary=item.get("salary") or "",
        posted=item.get("publication_date"),
        tags=[item.get("category"), *(item.get("tags") or [])],
        type_hints=item.get("job_type") or "",
        remote=True,
    )


remotive = ApiPuller(
    "remotive",
    single("https://remotive.com/api/remote-jobs"),
    lambda d: d.get("jobs", []),
    _map_remotive,
)


# --- Himalayas (cursor pagination, 20 per page) -------------------------------------

def _himalayas_requests() -> RequestGen:
    cursor = None
    for _ in range(settings.API_MAX_PAGES):
        params = {"limit": 20}
        if cursor:
            params["cursor"] = cursor
        data = yield {"url": "https://himalayas.app/jobs/api", "params": params}
        cursor = (data or {}).get("nextCursor")
        if not cursor or not data.get("jobs"):
            return


def _map_himalayas(item: dict) -> Optional[Job]:
    restrictions = item.get("locationRestrictions") or []
    location = "Remote" + (f" ({', '.join(restrictions[:4])})" if restrictions else "")
    return normalize(
        title=item.get("title"),
        company=item.get("companyName"),
        apply_link=item.get("applicationLink") or item.get("guid"),
        source="Himalayas",
        location=location,
        description=item.get("description") or item.get("excerpt"),
        salary=format_salary(item.get("minSalary"), item.get("maxSalary"),
                             item.get("currency") or "", item.get("salaryPeriod") or ""),
        posted=item.get("pubDate"),
        deadline=item.get("expiryDate"),
        tags=[*(item.get("parentCategories") or []), *(item.get("categories") or [])[:5]],
        type_hints=item.get("employmentType") or "",
        remote=True,
    )


himalayas = ApiPuller("himalayas", _himalayas_requests, lambda d: d.get("jobs", []), _map_himalayas)


# --- Jobicy ---------------------------------------------------------------------------
# Terms: credit Jobicy and send applicants to the job URL from the feed.

def _map_jobicy(item: dict) -> Optional[Job]:
    return normalize(
        title=item.get("jobTitle"),
        company=item.get("companyName"),
        apply_link=item.get("url"),
        source="Jobicy",
        location=f"Remote ({item['jobGeo']})" if item.get("jobGeo") else "Remote",
        description=item.get("jobDescription") or item.get("jobExcerpt"),
        salary=format_salary(item.get("salaryMin"), item.get("salaryMax"),
                             item.get("salaryCurrency") or "", item.get("salaryPeriod") or ""),
        posted=item.get("pubDate"),
        tags=_names(item.get("jobIndustry")),
        type_hints=" ".join(_names(item.get("jobType"))),
        remote=True,
    )


jobicy = ApiPuller(
    "jobicy",
    single("https://jobicy.com/api/v2/remote-jobs", params={"count": 100}),
    lambda d: d.get("jobs", []),
    _map_jobicy,
)


# --- Arbeitnow (page-number pagination, 250 per page, mostly Europe) ----------------

def _arbeitnow_requests() -> RequestGen:
    for page in range(1, 3):
        data = yield {"url": "https://www.arbeitnow.com/api/job-board-api", "params": {"page": page}}
        if not (data or {}).get("links", {}).get("next"):
            return


def _map_arbeitnow(item: dict) -> Optional[Job]:
    return normalize(
        title=item.get("title"),
        company=item.get("company_name"),
        apply_link=item.get("url"),
        source="Arbeitnow",
        location=item.get("location") or "",
        description=item.get("description"),
        posted=item.get("created_at"),
        tags=item.get("tags") or [],
        type_hints=" ".join(item.get("job_types") or []),
        remote=bool(item.get("remote")),
    )


arbeitnow = ApiPuller("arbeitnow", _arbeitnow_requests, lambda d: d.get("data", []), _map_arbeitnow)


# --- The Muse ---------------------------------------------------------------------------
# The public API does not sort by date, so we narrow to India + remote locations and
# rely on the pipeline's max-age filter to drop stale postings.

MUSE_LOCATIONS = ["India", "Flexible / Remote"]


def _muse_requests() -> RequestGen:
    key = os.environ.get("MUSE_API_KEY")  # optional, only raises the rate limit
    for page in range(settings.API_MAX_PAGES):
        params = [("page", page), ("descending", "true")] + [("location", loc) for loc in MUSE_LOCATIONS]
        if key:
            params.append(("api_key", key))
        data = yield {"url": "https://www.themuse.com/api/public/jobs", "params": params}
        if page + 1 >= (data or {}).get("page_count", 0):
            return


def _map_muse(item: dict) -> Optional[Job]:
    locations = _names(item.get("locations"))
    levels = _names(item.get("levels"))
    return normalize(
        title=item.get("name"),
        company=(item.get("company") or {}).get("name"),
        apply_link=(item.get("refs") or {}).get("landing_page"),
        source="The Muse",
        location=", ".join(locations[:3]),
        description=item.get("contents"),
        posted=item.get("publication_date"),
        tags=_names(item.get("categories")),
        type_hints=" ".join(levels),
        remote=any("remote" in loc.lower() for loc in locations) or None,
    )


muse = ApiPuller("themuse", _muse_requests, lambda d: d.get("results", []), _map_muse)


# --- Jooble (free key: https://jooble.org/api/about) -----------------------------------

def _jooble_requests() -> RequestGen:
    url = f"https://jooble.org/api/{os.environ.get('JOOBLE_KEY', '')}"
    for query in settings.SEARCH_QUERIES:
        for page in (1, 2):
            data = yield {"url": url, "method": "POST",
                          "json": {"keywords": query, "location": settings.JOOBLE_LOCATION, "page": str(page)}}
            if not (data or {}).get("jobs"):
                break


def _map_jooble(item: dict) -> Optional[Job]:
    return normalize(
        title=item.get("title"),
        company=item.get("company"),
        apply_link=item.get("link"),
        source="Jooble",
        location=item.get("location") or "",
        description=item.get("snippet"),
        salary=item.get("salary") or "",
        posted=item.get("updated"),
        type_hints=item.get("type") or "",
    )


jooble = ApiPuller("jooble", _jooble_requests, lambda d: d.get("jobs", []), _map_jooble)


# --- Adzuna (free app_id + app_key: https://developer.adzuna.com/) ----------------------

ADZUNA_CURRENCY = {"in": "INR", "gb": "GBP", "us": "USD", "au": "AUD", "ca": "CAD", "de": "EUR",
                   "fr": "EUR", "nl": "EUR", "sg": "SGD", "nz": "NZD", "za": "ZAR"}


def _adzuna_requests() -> RequestGen:
    country = settings.ADZUNA_COUNTRY
    base = {
        "app_id": os.environ.get("ADZUNA_APP_ID", ""),
        "app_key": os.environ.get("ADZUNA_APP_KEY", ""),
        "results_per_page": 50,
        "sort_by": "date",
        "max_days_old": 7,
        "content-type": "application/json",
    }
    for query in settings.SEARCH_QUERIES:
        for page in range(1, settings.ADZUNA_PAGES_PER_QUERY + 1):
            data = yield {"url": f"https://api.adzuna.com/v1/api/jobs/{country}/search/{page}",
                          "params": {**base, "what": query}}
            if len((data or {}).get("results", [])) < 50:
                break


def _map_adzuna(item: dict) -> Optional[Job]:
    currency = ADZUNA_CURRENCY.get(settings.ADZUNA_COUNTRY, "")
    return normalize(
        title=item.get("title"),
        company=(item.get("company") or {}).get("display_name"),
        apply_link=item.get("redirect_url"),
        source="Adzuna",
        location=(item.get("location") or {}).get("display_name", ""),
        description=item.get("description"),
        salary=format_salary(item.get("salary_min"), item.get("salary_max"), currency, "year"),
        posted=item.get("created"),
        tags=[(item.get("category") or {}).get("label", "")],
        type_hints=f"{item.get('contract_time') or ''} {item.get('contract_type') or ''}",
    )


adzuna = ApiPuller("adzuna", _adzuna_requests, lambda d: d.get("results", []), _map_adzuna)


# --- Findwork.dev (free token: https://findwork.dev/developers/) ------------------------

def _findwork_requests() -> RequestGen:
    headers = {"Authorization": f"Token {os.environ.get('FINDWORK_TOKEN', '')}"}
    url = "https://findwork.dev/api/jobs/"
    params = {"sort_by": "date"}
    for _ in range(settings.API_MAX_PAGES):
        data = yield {"url": url, "params": params, "headers": headers}
        url, params = (data or {}).get("next"), None
        if not url:
            return


def _map_findwork(item: dict) -> Optional[Job]:
    return normalize(
        title=item.get("role"),
        company=item.get("company_name"),
        apply_link=item.get("url"),
        source="Findwork",
        location=item.get("location") or "",
        description=item.get("text"),
        posted=item.get("date_posted"),
        tags=item.get("keywords") or [],
        type_hints=item.get("employment_type") or "",
        remote=bool(item.get("remote")) or None,
    )


findwork = ApiPuller("findwork", _findwork_requests, lambda d: d.get("results", []), _map_findwork)


def feeds() -> list[Feed]:
    return [
        Feed("remoteok", "RemoteOK", "api", remoteok.fetch),
        Feed("remotive", "Remotive", "api", remotive.fetch, min_interval_hours=6),
        Feed("himalayas", "Himalayas", "api", himalayas.fetch),
        Feed("jobicy", "Jobicy", "api", jobicy.fetch),
        Feed("arbeitnow", "Arbeitnow", "api", arbeitnow.fetch),
        Feed("themuse", "The Muse", "api", muse.fetch),
        Feed("jooble", "Jooble", "api", jooble.fetch, min_interval_hours=4, requires_env=("JOOBLE_KEY",)),
        Feed("adzuna", "Adzuna", "api", adzuna.fetch, min_interval_hours=6,
             requires_env=("ADZUNA_APP_ID", "ADZUNA_APP_KEY")),
        Feed("findwork", "Findwork", "api", findwork.fetch, requires_env=("FINDWORK_TOKEN",)),
    ]
