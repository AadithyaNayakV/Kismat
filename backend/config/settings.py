"""Tunable settings for the whole pipeline. Secrets never live here — they come from
environment variables (GitHub Secrets in CI, a local .env / shell exports when testing).
"""
from __future__ import annotations

import os

# --- Scheduling / expiry -----------------------------------------------------------
SCRAPE_INTERVAL_HOURS = 2          # must match the cron in .github/workflows/scrape.yml
EXPIRY_MISSED_RUNS = 2             # a job missing from this many successful runs of its feed -> expired

# --- Freshness ---------------------------------------------------------------------------
MAX_JOB_AGE_DAYS = 60              # jobs whose posted_date is older are ignored (per-feed override)
WINDOW_FEED_STALE_DAYS = 21        # "latest N" feeds: expire when not seen for this many days

# --- Storage size control (the DB and jobs.json are committed to git) --------------
DESCRIPTION_MAX_CHARS = 800        # stored description is cut to this; skill matching uses the full text
EXPORT_SNIPPET_CHARS = 220         # description snippet written to jobs.json
EXPORT_EXPIRED_DAYS = 60           # expired jobs older than this (by last_seen_at) are left out of jobs.json

# --- Telegram -------------------------------------------------------------------------
MAX_NOTIFICATIONS_PER_RUN = 25     # extra matches are rolled into one summary message
NOTIFY_MAX_AGE_DAYS = 7            # don't ping for jobs whose posted_date is older than this
SITE_URL = os.environ.get("SITE_URL", "")  # optional, linked in summary messages

# --- Search terms for keyword-based sources (Adzuna, Jooble, India boards) ----------
# Each term costs API calls / page loads per run, so keep these lists short.
SEARCH_QUERIES = ["software developer", "python developer", "data analyst"]
INDIA_QUERIES = ["python", "software developer", "data analyst"]

ADZUNA_COUNTRY = os.environ.get("ADZUNA_COUNTRY", "in")   # in, gb, us, ...
ADZUNA_PAGES_PER_QUERY = 2
JOOBLE_LOCATION = os.environ.get("JOOBLE_LOCATION", "India")

# Pages fetched per paginated source per run.
API_MAX_PAGES = 5
INDIA_MAX_PAGES = 2

# --- Politeness -------------------------------------------------------------------------
SCRAPE_DELAY_RANGE = (2.0, 5.0)    # seconds between HTML-scraping requests (India boards)
ATS_DELAY_RANGE = (0.3, 0.8)       # seconds between ATS company requests (JSON APIs)
HTTP_TIMEOUT = 30
