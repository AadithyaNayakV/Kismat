"""SQLite access: connection, schema setup, dedup upsert, last_seen_at tracking."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable, Optional

from db.models import CREATE_FEED_INDEX, MIGRATIONS, SCHEMA, STATUS_ACTIVE, Job, utc_now_iso

DB_PATH = Path(__file__).resolve().parent / "jobs.db"


def connect(path: Path | str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    for table, column, col_type in MIGRATIONS:
        existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
    conn.execute(CREATE_FEED_INDEX)
    conn.commit()


def count_jobs(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]


def upsert_job(conn: sqlite3.Connection, job: Job, seen_at: Optional[str] = None) -> bool:
    """Insert a new job or refresh an existing one. Returns True if the job is new.

    Existing rows keep notified, scraped_at and posted_date; last_seen_at is bumped,
    the row is (re)activated, and skills/description/etc. are refreshed. A reactivated
    job whose deadline has passed is expired again by the expiry checker.
    """
    now = seen_at or utc_now_iso()
    exists = conn.execute("SELECT 1 FROM jobs WHERE job_id = ?", (job.job_id,)).fetchone()
    if exists:
        conn.execute(
            """
            UPDATE jobs SET
                last_seen_at = ?,
                status       = ?,
                feed         = ?,
                skills_tags  = ?,
                description  = COALESCE(NULLIF(?, ''), description),
                salary       = COALESCE(NULLIF(?, ''), salary),
                deadline     = COALESCE(?, deadline),
                location     = COALESCE(NULLIF(?, ''), location),
                posted_date  = COALESCE(posted_date, ?)
            WHERE job_id = ?
            """,
            (now, STATUS_ACTIVE, job.feed, job.skills_tags, job.description, job.salary,
             job.deadline, job.location, job.posted_date, job.job_id),
        )
        return False

    conn.execute(
        """
        INSERT INTO jobs (job_id, title, company, location, job_type, description,
                          skills_tags, salary, posted_date, deadline, apply_link,
                          source, status, notified, last_seen_at, scraped_at, feed)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
        """,
        (
            job.job_id, job.title, job.company, job.location, job.job_type,
            job.description, job.skills_tags, job.salary, job.posted_date,
            job.deadline, job.apply_link, job.source, job.status, now, now, job.feed,
        ),
    )
    return True


def upsert_jobs(conn: sqlite3.Connection, jobs: Iterable[Job], seen_at: Optional[str] = None) -> int:
    """Upsert many jobs in one transaction. Returns the number of new jobs."""
    new_count = 0
    with conn:
        for job in jobs:
            if upsert_job(conn, job, seen_at):
                new_count += 1
    return new_count


def log_run(conn: sqlite3.Connection, run_id: str, feed: str, started_at: str,
            jobs_found: int, jobs_new: int, error: Optional[str]) -> None:
    with conn:
        conn.execute(
            """
            INSERT INTO scrape_runs (run_id, source, started_at, finished_at,
                                     jobs_found, jobs_new, error)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, feed, started_at, utc_now_iso(), jobs_found, jobs_new, error),
        )


def last_success_at(conn: sqlite3.Connection, feed: str) -> Optional[str]:
    row = conn.execute(
        "SELECT MAX(started_at) FROM scrape_runs WHERE source = ? AND error IS NULL", (feed,)
    ).fetchone()
    return row[0] if row else None


def get_meta(conn: sqlite3.Connection, key: str) -> Optional[str]:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    with conn:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
