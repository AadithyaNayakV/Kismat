"""Telegram notifier. Needs env vars TELEGRAM_TOKEN and TELEGRAM_CHAT_ID.

Rules (plan §7): only jobs that are new (notified=0), active, and match MY_SKILLS
(or everything when MY_SKILLS is empty). Extra guards against spam:
- only jobs posted within settings.NOTIFY_MAX_AGE_DAYS (or with unknown date),
- at most settings.MAX_NOTIFICATIONS_PER_RUN individual messages; the rest are
  summarised in one message and still marked notified.
"""
from __future__ import annotations

import html
import logging
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone

import requests

from config import settings
from filters.skill_matcher import skills_filter_active

log = logging.getLogger("notifier.telegram")

API = "https://api.telegram.org/bot{token}/{method}"
SEND_INTERVAL = 1.1  # seconds; Telegram allows ~1 msg/sec per chat


def is_configured() -> bool:
    return bool(os.environ.get("TELEGRAM_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"))


def send_message(text: str) -> bool:
    token = os.environ.get("TELEGRAM_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    for attempt in range(4):
        try:
            resp = requests.post(API.format(token=token, method="sendMessage"), json=payload, timeout=20)
        except requests.RequestException as exc:
            log.warning("Telegram send failed (attempt %d): %s", attempt + 1, exc)
            time.sleep(2 * (attempt + 1))
            continue
        if resp.status_code == 429:
            wait = resp.json().get("parameters", {}).get("retry_after", 5)
            log.warning("Telegram rate limit, sleeping %ss", wait)
            time.sleep(wait + 1)
            continue
        if not resp.ok:
            # Never log the token: the URL is not logged, only Telegram's description.
            log.error("Telegram error %s: %s", resp.status_code, resp.json().get("description"))
            return False
        return True
    return False


def _e(value) -> str:
    return html.escape(str(value or ""), quote=False)


def format_job(row: sqlite3.Row) -> str:
    skills = row["skills_tags"] or "—"
    lines = [
        f"🔔 <b>{_e(row['title'])}</b> at <b>{_e(row['company'])}</b>",
        f"📍 {_e(row['location'] or 'N/A')} | 🏷 {_e(row['job_type'])} | Source: {_e(row['source'])}",
        f"🛠 Skills: {_e(skills)}",
    ]
    if row["salary"]:
        lines.append(f"💰 {_e(row['salary'])}")
    if row["deadline"]:
        lines.append(f"⏳ Apply by: {_e(row['deadline'])}")
    lines.append(f'👉 <a href="{html.escape(row["apply_link"], quote=True)}">Apply</a>')
    return "\n".join(lines)


def _candidates(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=settings.NOTIFY_MAX_AGE_DAYS)).isoformat()
    sql = """
        SELECT * FROM jobs
        WHERE notified = 0 AND status = 'active'
          AND (posted_date IS NULL OR posted_date >= ?)
    """
    if skills_filter_active():
        sql += " AND COALESCE(skills_tags, '') != ''"
    sql += " ORDER BY COALESCE(posted_date, scraped_at) DESC"
    return conn.execute(sql, (cutoff,)).fetchall()


def _mark_notified(conn: sqlite3.Connection, job_ids: list[str]) -> None:
    with conn:
        conn.executemany("UPDATE jobs SET notified = 1 WHERE job_id = ?", [(j,) for j in job_ids])


def notify_new_jobs(conn: sqlite3.Connection) -> int:
    """Send alerts for new matching jobs. Returns the number of jobs covered."""
    rows = _candidates(conn)
    if not rows:
        log.info("Telegram: no new matching jobs")
        return 0
    if not is_configured():
        log.warning("Telegram: TELEGRAM_TOKEN / TELEGRAM_CHAT_ID not set — %d alerts not sent "
                    "(they will be sent on a later run once configured)", len(rows))
        return 0

    individual, overflow = rows[: settings.MAX_NOTIFICATIONS_PER_RUN], rows[settings.MAX_NOTIFICATIONS_PER_RUN:]
    sent_ids = []
    for row in individual:
        if send_message(format_job(row)):
            sent_ids.append(row["job_id"])
        time.sleep(SEND_INTERVAL)

    if overflow:
        text = f"➕ <b>{len(overflow)} more</b> new matching jobs this run."
        if settings.SITE_URL:
            text += f'\n🌐 <a href="{html.escape(settings.SITE_URL, quote=True)}">See them all on the website</a>'
        if send_message(text):
            sent_ids.extend(r["job_id"] for r in overflow)

    _mark_notified(conn, sent_ids)
    log.info("Telegram: sent %d individual alerts, %d in summary", min(len(sent_ids), len(individual)), len(overflow))
    return len(sent_ids)


def mark_all_notified(conn: sqlite3.Connection) -> int:
    """Used on the very first run so an empty DB doesn't trigger thousands of alerts."""
    with conn:
        cur = conn.execute("UPDATE jobs SET notified = 1 WHERE notified = 0")
    return cur.rowcount


def send_bootstrap_summary(total: int) -> None:
    if not is_configured():
        return
    text = (f"✅ Job notifier is set up. Loaded <b>{total}</b> existing jobs into the database "
            "without alerting. From now on you'll get alerts for new matching jobs.")
    if settings.SITE_URL:
        text += f'\n🌐 <a href="{html.escape(settings.SITE_URL, quote=True)}">Open the job board</a>'
    send_message(text)
