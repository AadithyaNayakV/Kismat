"""Expiry checker (plan §5). Jobs are never deleted, only flagged status='expired'.

Three rules, run after every scrape:

A. Explicit deadline: deadline (YYYY-MM-DD) is before today (UTC).

B. Disappearance, for "complete" feeds (ATS boards list every open job): a job that
   was missing from the last EXPIRY_MISSED_RUNS *successful* runs of its own feed.
   Implementation: when feed X succeeds this run, take the start time of X's
   N-th most recent successful run. Any active job of X with last_seen_at earlier than
   that was absent from all of those N runs. Failed or partial runs never count,
   so an outage can't wipe out a feed's jobs, and GitHub cron delays don't matter.

C. Staleness, for everything else: "latest N jobs" APIs, RSS and search pages only show
   a window of recent postings, so falling out of the window doesn't mean the job
   closed. These jobs expire when not seen for WINDOW_FEED_STALE_DAYS. The same rule
   is a fallback for complete feeds that stop working or are removed from the config.

A job that reappears later is automatically reactivated by the upsert (unless its
deadline has passed, in which case rule A expires it again on the same run).
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Iterable

from config import settings

log = logging.getLogger("expiry")


def expire_by_deadline(conn: sqlite3.Connection, today: str | None = None) -> int:
    today = today or datetime.now(timezone.utc).date().isoformat()
    with conn:
        cur = conn.execute(
            "UPDATE jobs SET status = 'expired' "
            "WHERE status = 'active' AND deadline IS NOT NULL AND deadline != '' AND deadline < ?",
            (today,),
        )
    return cur.rowcount


def _nth_last_success(conn: sqlite3.Connection, feed: str, n: int) -> str | None:
    row = conn.execute(
        """
        SELECT started_at FROM scrape_runs
        WHERE source = ? AND error IS NULL AND jobs_found > 0
        ORDER BY started_at DESC LIMIT 1 OFFSET ?
        """,
        (feed, n - 1),
    ).fetchone()
    return row[0] if row else None


def expire_missing(conn: sqlite3.Connection, successful_complete_feeds: Iterable[str],
                   missed_runs: int = settings.EXPIRY_MISSED_RUNS) -> int:
    total = 0
    for feed in successful_complete_feeds:
        threshold = _nth_last_success(conn, feed, missed_runs)
        if not threshold:
            continue  # not enough history yet
        with conn:
            cur = conn.execute(
                "UPDATE jobs SET status = 'expired' "
                "WHERE status = 'active' AND feed = ? AND last_seen_at < ?",
                (feed, threshold),
            )
        if cur.rowcount:
            log.info("[%s] %d jobs disappeared -> expired", feed, cur.rowcount)
        total += cur.rowcount
    return total


def expire_stale(conn: sqlite3.Connection, days: int = settings.WINDOW_FEED_STALE_DAYS) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).replace(microsecond=0).isoformat()
    with conn:
        cur = conn.execute(
            "UPDATE jobs SET status = 'expired' WHERE status = 'active' AND last_seen_at < ?",
            (cutoff,),
        )
    return cur.rowcount


def run(conn: sqlite3.Connection, successful_complete_feeds: Iterable[str]) -> dict:
    counts = {
        "deadline": expire_by_deadline(conn),
        "disappeared": expire_missing(conn, successful_complete_feeds),
        "stale": expire_stale(conn),
    }
    active = conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'active'").fetchone()[0]
    expired = conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'expired'").fetchone()[0]
    log.info("Expiry: %d by deadline, %d disappeared, %d stale | now %d active, %d expired",
             counts["deadline"], counts["disappeared"], counts["stale"], active, expired)
    return counts
