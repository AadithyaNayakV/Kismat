"""SQLite access: connection, schema setup, dedup upsert, last_seen_at tracking."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

from db.models import SCHEMA, STATUS_ACTIVE, Job, utc_now_iso

DB_PATH = Path(__file__).resolve().parent / "jobs.db"


def connect(path: Path | str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def upsert_job(conn: sqlite3.Connection, job: Job, seen_at: str | None = None) -> bool:
    """Insert a new job or refresh an existing one. Returns True if the job is new.

    Existing rows keep their notified flag and scraped_at; last_seen_at is bumped,
    and a job that reappears after being marked expired is reactivated unless its
    deadline has passed (the expiry checker handles that case).
    """
    now = seen_at or utc_now_iso()
    exists = conn.execute("SELECT 1 FROM jobs WHERE job_id = ?", (job.job_id,)).fetchone()
    if exists:
        conn.execute(
            """
            UPDATE jobs SET
                last_seen_at = ?,
                status       = ?,
                description  = COALESCE(NULLIF(?, ''), description),
                salary       = COALESCE(NULLIF(?, ''), salary),
                deadline     = COALESCE(?, deadline),
                location     = COALESCE(NULLIF(?, ''), location)
            WHERE job_id = ?
            """,
            (now, STATUS_ACTIVE, job.description, job.salary, job.deadline, job.location, job.job_id),
        )
        return False

    conn.execute(
        """
        INSERT INTO jobs (job_id, title, company, location, job_type, description,
                          skills_tags, salary, posted_date, deadline, apply_link,
                          source, status, notified, last_seen_at, scraped_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
        """,
        (
            job.job_id, job.title, job.company, job.location, job.job_type,
            job.description, job.skills_tags, job.salary, job.posted_date,
            job.deadline, job.apply_link, job.source, job.status, now, now,
        ),
    )
    return True


def upsert_jobs(conn: sqlite3.Connection, jobs: Iterable[Job], seen_at: str | None = None) -> int:
    """Upsert many jobs in one transaction. Returns the number of new jobs."""
    new_count = 0
    with conn:
        for job in jobs:
            if upsert_job(conn, job, seen_at):
                new_count += 1
    return new_count


def log_run(conn: sqlite3.Connection, run_id: str, source: str, started_at: str,
            jobs_found: int, jobs_new: int, error: str | None) -> None:
    with conn:
        conn.execute(
            """
            INSERT INTO scrape_runs (run_id, source, started_at, finished_at,
                                     jobs_found, jobs_new, error)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, source, started_at, utc_now_iso(), jobs_found, jobs_new, error),
        )
