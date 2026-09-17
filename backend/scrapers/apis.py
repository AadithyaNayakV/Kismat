"""Free job APIs. Each source is one function returning list[Job]; `feeds()` registers them.

RemoteOK is the first source (Step 2). The others are added in Step 3.
"""
from __future__ import annotations

import logging

from scrapers.base import Feed, HttpClient
from scrapers.normalize import format_salary, normalize

log = logging.getLogger("scrapers.apis")


def fetch_remoteok() -> list:
    """https://remoteok.com/api — no key. Terms require linking back to the Remote OK
    page and naming Remote OK as the source, so apply_link is the Remote OK URL."""
    data = HttpClient().get_json("https://remoteok.com/api")
    jobs = []
    for item in data:
        if not isinstance(item, dict) or "position" not in item:
            continue  # first element is the legal notice
        job = normalize(
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
        if job:
            jobs.append(job)
    return jobs


def feeds() -> list[Feed]:
    return [
        Feed("remoteok", "RemoteOK", "api", fetch_remoteok),
    ]
