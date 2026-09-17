"""Standard job schema shared by every scraper, plus the SQLite DDL."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

STATUS_ACTIVE = "active"
STATUS_EXPIRED = "expired"

# jobs.job_type holds a comma-separated subset, e.g. "tech,remote" or "non-tech,internship".
JOB_TYPES = ("tech", "non-tech", "internship", "remote")

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id       TEXT PRIMARY KEY,   -- hash of company+title+link, for dedup
    title        TEXT,
    company      TEXT,
    location     TEXT,
    job_type     TEXT,               -- comma-separated: tech|non-tech [,internship] [,remote]
    description  TEXT,               -- plain text, truncated to settings.DESCRIPTION_MAX_CHARS
    skills_tags  TEXT,               -- comma-separated matched skills
    salary       TEXT,
    posted_date  TEXT,               -- ISO-8601 UTC
    deadline     TEXT,               -- YYYY-MM-DD if explicitly stated, else NULL
    apply_link   TEXT,
    source       TEXT,               -- which API/site (display name)
    status       TEXT,               -- active / expired
    notified     INTEGER DEFAULT 0,  -- 0/1, avoid duplicate Telegram pings
    last_seen_at TEXT,               -- updated every scrape run it still appears
    scraped_at   TEXT,               -- first time we saw it
    feed         TEXT                -- scrape unit that found it, e.g. "greenhouse:stripe" (used by expiry)
);

CREATE INDEX IF NOT EXISTS idx_jobs_status       ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_source       ON jobs(source);
CREATE INDEX IF NOT EXISTS idx_jobs_last_seen_at ON jobs(last_seen_at);

-- One row per feed per pipeline run, for debugging and for expiry.
CREATE TABLE IF NOT EXISTS scrape_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT,                -- groups all feeds of one main.py run
    source      TEXT,                -- the feed name, e.g. "remoteok", "greenhouse:stripe"
    started_at  TEXT,
    finished_at TEXT,
    jobs_found  INTEGER DEFAULT 0,
    jobs_new    INTEGER DEFAULT 0,
    error       TEXT                 -- NULL = full success
);

CREATE INDEX IF NOT EXISTS idx_runs_run_id ON scrape_runs(run_id);
CREATE INDEX IF NOT EXISTS idx_runs_source ON scrape_runs(source, started_at);

-- Small key/value store (e.g. fingerprint of MY_SKILLS to know when to re-tag).
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

# Columns added after the first schema version: (table, column, type). init_db adds
# any that are missing, so older jobs.db files upgrade in place.
MIGRATIONS = [
    ("jobs", "feed", "TEXT"),
]
CREATE_FEED_INDEX = "CREATE INDEX IF NOT EXISTS idx_jobs_feed ON jobs(feed, last_seen_at);"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def make_job_id(company: str, title: str, apply_link: str) -> str:
    key = "|".join(s.strip().lower() for s in (company or "", title or "", apply_link or ""))
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


@dataclass
class Job:
    title: str
    company: str
    apply_link: str
    source: str
    location: str = ""
    job_type: str = ""
    description: str = ""
    skills_tags: str = ""
    salary: str = ""
    posted_date: Optional[str] = None
    deadline: Optional[str] = None
    status: str = STATUS_ACTIVE
    job_id: str = ""
    feed: str = ""
    # Not stored: full untruncated text used for skill matching.
    match_text: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        if not self.job_id:
            self.job_id = make_job_id(self.company, self.title, self.apply_link)
