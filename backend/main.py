"""Pipeline entry point. Run from the backend/ folder:

    python main.py                      # full run
    python main.py --list               # show all feeds
    python main.py --only remoteok      # just one source (prefix match: --only greenhouse)
    python main.py --skip-group india   # everything except the India scrapers
    python main.py --skip naukri,foundit
    python main.py --no-notify          # scrape + export, no Telegram
    python main.py --test-telegram      # send one test message and exit

Order: re-tag if skills changed -> scrape (each feed isolated) -> normalize -> tag skills -> upsert/dedupe
       -> expire -> notify -> export jobs.json
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from db.db import DB_PATH, connect, count_jobs, init_db, last_success_at, log_run, upsert_jobs
from db.models import utc_now_iso
from expiry import checker as expiry
from exporter import export_json
from filters import skill_matcher
from notifier import telegram
from scrapers.base import Feed, PartialResult
from scrapers.registry import all_feeds, select_feeds

log = logging.getLogger("main")
LOG_DIR = Path(__file__).resolve().parent / "logs"


def setup_logging() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows consoles
    LOG_DIR.mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for handler in (logging.StreamHandler(sys.stdout),
                    logging.FileHandler(LOG_DIR / "run.log", encoding="utf-8")):
        handler.setFormatter(fmt)
        root.addHandler(handler)
    for noisy in ("urllib3", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _hours_since(iso: str) -> float:
    return (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds() / 3600


def run_feed(conn, feed: Feed, run_id: str, ignore_throttle: bool) -> dict:
    """Run one feed in isolation. Never raises."""
    result = {"feed": feed.name, "found": 0, "new": 0, "error": None, "skipped": None}
    missing = [v for v in feed.requires_env if not os.environ.get(v)]
    if missing:
        result["skipped"] = f"missing env {', '.join(missing)}"
        log.info("[%s] skipped: %s", feed.name, result["skipped"])
        return result
    if feed.min_interval_hours and not ignore_throttle:
        last = last_success_at(conn, feed.name)
        if last and _hours_since(last) < feed.min_interval_hours:
            result["skipped"] = f"throttled (runs every {feed.min_interval_hours:g}h)"
            log.info("[%s] skipped: %s", feed.name, result["skipped"])
            return result

    started_at = utc_now_iso()
    t0 = time.monotonic()
    jobs, error = [], None
    try:
        jobs = feed.fetch()
    except PartialResult as partial:
        jobs, error = partial.jobs, f"partial: {partial}"
    except Exception as exc:  # isolation: one broken source never stops the run
        error = f"{type(exc).__name__}: {exc}"[:500]
        log.warning("[%s] failed: %s", feed.name, error, exc_info=log.isEnabledFor(logging.DEBUG))

    cutoff = None
    if feed.max_age_days:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=feed.max_age_days)).isoformat()
    unique = {}
    stale = 0
    for job in jobs:
        if cutoff and job.posted_date and job.posted_date < cutoff:
            stale += 1
            continue
        job.feed = feed.name
        skill_matcher.tag_job(job)
        unique[job.job_id] = job
    try:
        new = upsert_jobs(conn, unique.values(), seen_at=started_at)
    except Exception as exc:
        new, error = 0, f"DB error: {exc}"[:500]
        log.exception("[%s] DB write failed", feed.name)

    log_run(conn, run_id, feed.name, started_at, len(unique), new, error)
    result.update(found=len(unique), new=new, error=error)
    log.info("[%s] found=%d new=%d%s%s (%.1fs)", feed.name, len(unique), new,
             f" stale_dropped={stale}" if stale else "",
             f" error={error}" if error else "", time.monotonic() - t0)
    return result


def print_summary(results: list[dict]) -> None:
    ran = [r for r in results if not r["skipped"]]
    log.info("-" * 72)
    log.info("%-32s %7s %7s  %s", "feed", "found", "new", "status")
    for r in results:
        status = r["skipped"] and f"skipped ({r['skipped']})" or (r["error"] and f"ERROR {r['error'][:60]}") or "ok"
        log.info("%-32s %7s %7s  %s", r["feed"][:32], r["found"], r["new"], status)
    log.info("-" * 72)
    log.info("feeds run=%d ok=%d failed=%d skipped=%d | jobs found=%d new=%d",
             len(ran), sum(1 for r in ran if not r["error"]), sum(1 for r in ran if r["error"]),
             len(results) - len(ran), sum(r["found"] for r in ran), sum(r["new"] for r in ran))


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Job notifier pipeline")
    p.add_argument("--list", action="store_true", help="list feeds and exit")
    p.add_argument("--only", help="comma-separated feed names or prefixes")
    p.add_argument("--skip", help="comma-separated feed names or prefixes to leave out")
    p.add_argument("--group", help="comma-separated groups to run (api,ats,rss,india)")
    p.add_argument("--skip-group", help="comma-separated groups to skip")
    p.add_argument("--no-notify", action="store_true", help="don't send Telegram alerts")
    p.add_argument("--no-export", action="store_true", help="don't write frontend/jobs.json")
    p.add_argument("--ignore-throttle", action="store_true", help="run throttled feeds anyway")
    p.add_argument("--test-telegram", action="store_true", help="send a test message and exit")
    p.add_argument("--db", default=str(DB_PATH), help="path to the SQLite file")
    return p.parse_args(argv)


def _split(value):
    return [v.strip() for v in value.split(",") if v.strip()] if value else None


def main(argv=None) -> int:
    args = parse_args(argv)
    setup_logging()

    if args.test_telegram:
        if not telegram.is_configured():
            log.error("Set TELEGRAM_TOKEN and TELEGRAM_CHAT_ID first")
            return 1
        ok = telegram.send_message("✅ Test message from your job notifier.")
        log.info("Telegram test %s", "sent" if ok else "FAILED")
        return 0 if ok else 1

    feeds = select_feeds(all_feeds(), _split(args.only), _split(args.group), _split(args.skip_group),
                         _split(args.skip))
    if args.list:
        for f in feeds:
            extra = []
            if f.requires_env:
                extra.append(f"needs {','.join(f.requires_env)}")
            if f.min_interval_hours:
                extra.append(f"every {f.min_interval_hours:g}h")
            print(f"{f.group:6} {f.name:36} {f.source:18} {' '.join(extra)}")
        print(f"{len(feeds)} feeds")
        return 0

    conn = connect(args.db)
    init_db(conn)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    was_empty = count_jobs(conn) == 0
    log.info("Run %s starting: %d feeds, DB=%s", run_id, len(feeds), args.db)
    # Before scraping, so freshly scraped jobs keep tags computed from their full text.
    skill_matcher.retag_all(conn)

    results = [run_feed(conn, f, run_id, args.ignore_throttle) for f in feeds]
    print_summary(results)

    complete = {f.name for f in feeds if f.complete}
    succeeded = [r["feed"] for r in results
                 if r["feed"] in complete and not r["skipped"] and not r["error"] and r["found"] > 0]
    expiry.run(conn, succeeded)

    if was_empty and count_jobs(conn) > 0:
        # First ever run: load everything silently instead of sending thousands of alerts.
        n = telegram.mark_all_notified(conn)
        log.info("First run: marked %d jobs as already notified (no alerts)", n)
        if not args.no_notify:
            telegram.send_bootstrap_summary(n)
    elif not args.no_notify:
        telegram.notify_new_jobs(conn)

    if not args.no_export:
        try:
            export_json.export(conn)
        except Exception:
            log.exception("Export to jobs.json failed")

    conn.close()
    ran = [r for r in results if not r["skipped"]]
    if ran and all(r["error"] and not r["found"] for r in ran):
        log.error("Run %s finished, but every feed failed (network problem?)", run_id)
        return 1
    log.info("Run %s finished", run_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
