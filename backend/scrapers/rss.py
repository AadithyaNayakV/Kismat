"""Feed-style sources: WeWorkRemotely (RSS), Jobspresso (RSS), Working Nomads (JSON feed).

All three are "latest N jobs" windows, so they use the staleness expiry rule.
"""
from __future__ import annotations

import html
import re
from typing import Optional

import feedparser

from db.models import Job
from scrapers.base import Feed, HttpClient
from scrapers.normalize import normalize


def _parse_feed(url: str, delay: Optional[tuple[float, float]] = None) -> feedparser.FeedParserDict:
    resp = HttpClient(delay_range=delay, respect_robots=True).get(
        url, headers={"Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8"})
    feed = feedparser.parse(resp.content)
    if feed.bozo and not feed.entries:
        raise ValueError(f"Could not parse feed {url}: {feed.bozo_exception}")
    return feed


# --- WeWorkRemotely -----------------------------------------------------------------
# Titles look like "Company: Job title". Entries carry region, skills, type, expires_at.

def fetch_weworkremotely() -> list[Job]:
    feed = _parse_feed("https://weworkremotely.com/remote-jobs.rss")
    jobs = []
    for e in feed.entries:
        raw_title = e.get("title", "")
        company, _, title = raw_title.partition(": ")
        if not title:
            company, title = "", raw_title
        region = e.get("region") or "Anywhere"
        job = normalize(
            title=title,
            company=company,
            apply_link=e.get("link"),
            source="WeWorkRemotely",
            location=f"Remote ({region})",
            description=e.get("summary"),
            posted=e.get("published"),
            deadline=e.get("expires_at"),
            tags=[t.get("term") for t in e.get("tags", [])] + (e.get("skills") or "").split(","),
            type_hints=e.get("type") or "",
            remote=True,
        )
        if job:
            jobs.append(job)
    return jobs


# --- Jobspresso (WordPress job feed) --------------------------------------------------
# robots.txt disallows any URL with "?", so the query-string feed can't be used;
# /jobs/feed/ is allowed. The <author> field holds "Company<br>⚲ Location".

def fetch_jobspresso() -> list[Job]:
    feed = _parse_feed("https://jobspresso.co/jobs/feed/", delay=(3.0, 4.0))  # Crawl-delay: 3
    jobs = []
    for e in feed.entries:
        author = html.unescape(e.get("author", ""))
        company, location = (re.split(r"<br\s*/?>", author, maxsplit=1) + [""])[:2]
        location = location.replace("⚲", "").strip()
        content = (e.get("content") or [{}])[0].get("value") or e.get("summary")
        job = normalize(
            title=e.get("title"),
            company=company,
            apply_link=e.get("link"),
            source="Jobspresso",
            location=f"Remote ({location})" if location else "Remote",
            description=content,
            posted=e.get("published"),
            tags=[t.get("term") for t in e.get("tags", [])],
            remote=True,
        )
        if job:
            jobs.append(job)
    return jobs


# --- Working Nomads -------------------------------------------------------------------
# The site no longer publishes RSS; the syndication feed its pages link to is JSON.

def fetch_workingnomads() -> list[Job]:
    data = HttpClient(respect_robots=True).get_json("https://www.workingnomads.com/api/exposed_jobs/")
    jobs = []
    for item in data if isinstance(data, list) else []:
        job = normalize(
            title=item.get("title"),
            company=item.get("company_name"),
            apply_link=item.get("url"),
            source="Working Nomads",
            location=f"Remote ({item['location']})" if item.get("location") else "Remote",
            description=item.get("description"),
            posted=item.get("pub_date"),
            tags=[item.get("category_name"), *(item.get("tags") or "").split(",")],
            remote=True,
        )
        if job:
            jobs.append(job)
    return jobs


def feeds() -> list[Feed]:
    return [
        Feed("weworkremotely", "WeWorkRemotely", "rss", fetch_weworkremotely),
        Feed("jobspresso", "Jobspresso", "rss", fetch_jobspresso),
        Feed("workingnomads", "Working Nomads", "rss", fetch_workingnomads),
    ]
