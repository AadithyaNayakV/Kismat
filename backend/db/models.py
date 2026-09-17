"""Standard job schema shared by every scraper, plus the SQLite DDL."""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional

STATUS_ACTIVE = "active"
STATUS_EXPIRED = "expired"

JOB_TYPES = ("tech", "non-tech", "internship", "remote")

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id       TEXT PRIMARY KEY,   -- hash of company+title+link, for dedup
    title        TEXT,
    company      TEXT,
    location     TEXT,
    job_type     TEXT,               -- tech / non-tech / internship / remote
    description  TEXT,               -- full text
    skills_tags  TEXT,               -- comma-separated matched skills
    salary       TEXT,
    posted_date  TEXT,
    deadline     TEXT,               -- explicit deadline if stated, else NULL
    apply_link   TEXT,
    source       TEXT,               -- which API/site
    status       TEXT,               -- active / expired
    notified     INTEGER DEFAULT 0,  -- 0/1, avoid duplicate Telegram pings
    last_seen_at TEXT,               -- updated every scrape run it still appears
    scraped_at   TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_status       ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_source       ON jobs(source);
CREATE INDEX IF NOT EXISTS idx_jobs_last_seen_at ON jobs(last_seen_at);

-- One row per source per pipeline run, for debugging.
CREATE TABLE IF NOT EXISTS scrape_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT,                -- groups all sources of one main.py run
    source      TEXT,
    started_at  TEXT,
    finished_at TEXT,
    jobs_found  INTEGER DEFAULT 0,
    jobs_new    INTEGER DEFAULT 0,
    error       TEXT
);

CREATE INDEX IF NOT EXISTS idx_runs_run_id ON scrape_runs(run_id);
"""


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
    job_id: str = field(default="")

    def __post_init__(self) -> None:
        if not self.job_id:
            self.job_id = make_job_id(self.company, self.title, self.apply_link)

    def to_dict(self) -> dict:
        return asdict(self)
