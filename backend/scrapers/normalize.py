"""The normalizer: turns raw fields from any source into the standard Job schema.

Every scraper calls `normalize(...)` so cleaning, date parsing, job_type
classification and truncation behave identically across sources.
"""
from __future__ import annotations

import html
import re
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Optional, Union

from bs4 import BeautifulSoup
from dateutil import parser as dateparser

from config import settings
from db.models import Job

_WS = re.compile(r"\s+")

TECH_KEYWORDS = [
    "engineer", "engineering", "developer", "software", "programmer", "devops", "sre",
    "site reliability", "data scientist", "data engineer", "data analyst", "analytics",
    "machine learning", "ml", "ai", "artificial intelligence", "deep learning", "llm",
    "frontend", "front-end", "front end", "backend", "back-end", "back end", "full stack",
    "full-stack", "fullstack", "web", "mobile", "android", "ios", "qa", "quality assurance",
    "test automation", "sdet", "tester", "cloud", "security", "cyber", "infrastructure",
    "network", "sysadmin", "system administrator", "database", "dba", "architect",
    "technical", "tech lead", "it support", "it", "networking", "platform", "embedded", "firmware",
    "blockchain", "python", "java", "javascript", "react", "node", "golang", "rust",
    ".net", "php", "salesforce", "sap", "erp", "bi developer", "power bi", "tableau",
    "cto", "programming", "coding", "computer", "hardware", "robotics", "game dev",
    "dev", "developers", "engineers", "c++", "c#", "sql", "typescript", "kotlin", "swift",
    "data science", "data", "software development", "information technology",
]
INTERN_KEYWORDS = ["intern", "internship", "trainee", "apprentice", "apprenticeship", "fresher"]
REMOTE_KEYWORDS = ["remote", "work from home", "wfh", "anywhere", "distributed"]


def clean_text(value: Optional[str]) -> str:
    """HTML (or escaped HTML) -> plain text with collapsed whitespace."""
    if not value:
        return ""
    text = html.unescape(str(value))
    if "<" in text and ">" in text:
        text = BeautifulSoup(text, "html.parser").get_text(" ")
    return _WS.sub(" ", text).strip()


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut + "…"


_RELATIVE = re.compile(r"(\d+)\s*\+?\s*(minute|min|hour|hr|day|week|month|year)s?\s+ago", re.I)


def parse_datetime(value: Union[str, int, float, datetime, date, None]) -> Optional[datetime]:
    """Accepts ISO strings, free-form dates, epoch seconds/milliseconds, and
    relative strings like '3 days ago', 'today', 'just now'. Returns aware UTC."""
    if value is None or value == "":
        return None
    try:
        if isinstance(value, datetime):
            dt = value
        elif isinstance(value, date):
            dt = datetime(value.year, value.month, value.day)
        elif isinstance(value, (int, float)) or (isinstance(value, str) and value.strip().isdigit()):
            num = float(value)
            if num > 1e12:          # milliseconds
                num /= 1000
            dt = datetime.fromtimestamp(num, tz=timezone.utc)
        else:
            s = value.strip()
            low = s.lower()
            now = datetime.now(timezone.utc)
            if low in ("today", "just now", "few hours ago", "an hour ago", "new", "now"):
                return now
            if low == "yesterday":
                return now - timedelta(days=1)
            m = _RELATIVE.search(low)
            if m:
                n, unit = int(m.group(1)), m.group(2).lower()
                delta = {
                    "minute": timedelta(minutes=n), "min": timedelta(minutes=n),
                    "hour": timedelta(hours=n), "hr": timedelta(hours=n),
                    "day": timedelta(days=n), "week": timedelta(weeks=n),
                    "month": timedelta(days=30 * n), "year": timedelta(days=365 * n),
                }[unit]
                return now - delta
            dt = dateparser.parse(s, dayfirst=False, fuzzy=True)
    except (ValueError, OverflowError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_iso(value) -> Optional[str]:
    dt = parse_datetime(value)
    return dt.replace(microsecond=0).isoformat() if dt else None


def parse_deadline(value, dayfirst: bool = False) -> Optional[str]:
    """Explicit deadline -> 'YYYY-MM-DD' (or None). `dayfirst` for Indian-style dates."""
    if value is None or value == "":
        return None
    if isinstance(value, str):
        s = re.sub(r"(?i)\b(apply\s*by|last\s*date(\s*to\s*apply)?|deadline|closing\s*date)\b[:\s-]*", "", value).strip()
        if not s:
            return None
        try:
            if s.isdigit():
                dt = parse_datetime(s)
            else:
                dt = dateparser.parse(s, dayfirst=dayfirst, fuzzy=True)
        except (ValueError, OverflowError):
            return None
        return dt.date().isoformat() if dt else None
    dt = parse_datetime(value)
    return dt.date().isoformat() if dt else None


def format_salary(min_value=None, max_value=None, currency: str = "", period: str = "") -> str:
    def fmt(v):
        try:
            v = float(v)
        except (TypeError, ValueError):
            return None
        if v <= 0:
            return None
        return f"{v:,.0f}"

    lo, hi = fmt(min_value), fmt(max_value)
    if not lo and not hi:
        return ""
    amount = f"{lo} – {hi}" if lo and hi and lo != hi else (lo or hi)
    parts = [currency.strip() if currency else "", amount, f"/ {period}" if period else ""]
    return " ".join(p for p in parts if p)


def keyword_pattern(keywords: Iterable[str]) -> re.Pattern:
    """Case-insensitive whole-word matcher that also works for 'c++', '.net', 'node.js'."""
    alts = sorted({re.escape(k.strip().lower()) for k in keywords if k.strip()}, key=len, reverse=True)
    return re.compile(r"(?<![a-z0-9])(" + "|".join(alts) + r")(?![a-z0-9])", re.I)


_TECH_RE = keyword_pattern(TECH_KEYWORDS)
_INTERN_RE = keyword_pattern(INTERN_KEYWORDS)
_REMOTE_RE = keyword_pattern(REMOTE_KEYWORDS)


def classify_job_type(title: str, hints: str = "", remote: Optional[bool] = None, location: str = "") -> str:
    """Returns a comma-separated set of tags: 'tech' or 'non-tech', plus 'internship'
    and/or 'remote' when they apply. Example: 'tech,remote'."""
    tags = ["tech" if _TECH_RE.search(f"{title} {hints}") else "non-tech"]
    if _INTERN_RE.search(f"{title} {hints}"):
        tags.append("internship")
    if remote is True or (remote is None and _REMOTE_RE.search(f"{location} {hints}")):
        tags.append("remote")
    return ",".join(tags)


def normalize(
    *,
    title: str,
    company: str,
    apply_link: str,
    source: str,
    location: str = "",
    description: str = "",
    salary: str = "",
    posted=None,
    deadline=None,
    tags: Iterable[str] = (),
    type_hints: str = "",
    remote: Optional[bool] = None,
    job_type: Optional[str] = None,
) -> Optional[Job]:
    """Build a Job. Returns None when the record is unusable (no title or link)."""
    title = clean_text(title)
    apply_link = (apply_link or "").strip()
    if not title or not apply_link.startswith(("http://", "https://")):
        return None
    company = clean_text(company) or "Unknown"
    location = clean_text(location)
    if remote and not location:
        location = "Remote"
    full_description = clean_text(description)
    tag_text = " ".join(clean_text(t) for t in tags if t)
    hints = f"{type_hints} {tag_text}".strip()

    job = Job(
        title=title,
        company=company,
        apply_link=apply_link,
        source=source,
        location=location,
        job_type=job_type or classify_job_type(title, hints, remote, location),
        description=truncate(full_description, settings.DESCRIPTION_MAX_CHARS),
        salary=clean_text(salary),
        posted_date=to_iso(posted),
        deadline=parse_deadline(deadline),
    )
    # Full text (not stored) used by the skill matcher.
    job.match_text = f"{title} {hints} {full_description}"
    return job
