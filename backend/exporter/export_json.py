"""Exports the DB to frontend/jobs.json for the static website.

File shape:
{
  "generated_at": "2026-09-17T12:00:00+00:00",
  "counts": {"active": 9800, "expired": 120, "exported": 9920},
  "my_skills": ["python", ...],          # so the site can pre-highlight your skills
  "all_skills": ["aws", "python", ...],   # every tag present in the export
  "sources": [ {"source": "Greenhouse", "feeds": 20, "ok": 20, "failed": 0,
                "last_run": "...", "jobs_active": 7000,
                "errors": ["greenhouse:x: HTTPError ..."]}, ... ],
  "jobs": [
    {"id", "title", "company", "location", "job_type": ["tech","remote"],
     "skills": ["python"], "salary", "posted", "deadline", "apply_link",
     "source", "status", "first_seen" (date), "last_seen" (date, expired jobs only),
     "snippet"},
    ...  (one job per line, newest first; empty fields omitted)
  ]
}

Included: all active jobs + expired jobs last seen within EXPORT_EXPIRED_DAYS.
The DB itself keeps everything forever.

One job per line keeps git diffs (and repo growth) small, since the file is
committed after every run.

Run standalone:  python -m exporter.export_json
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import settings
from db.models import utc_now_iso
from filters.skills_config import MY_SKILLS
from scrapers.normalize import truncate

log = logging.getLogger("exporter")

OUTPUT_PATH = Path(__file__).resolve().parents[2] / "frontend" / "jobs.json"


def _split(value: str | None) -> list[str]:
    return [v for v in (value or "").split(",") if v]


def _job_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=settings.EXPORT_EXPIRED_DAYS)).isoformat()
    return conn.execute(
        """
        SELECT job_id, title, company, location, job_type, skills_tags, salary,
               posted_date, deadline, apply_link, source, status, scraped_at,
               last_seen_at, description
        FROM jobs
        WHERE status = 'active' OR last_seen_at >= ?
        ORDER BY COALESCE(posted_date, scraped_at) DESC, job_id
        """,
        (cutoff,),
    ).fetchall()


def _job_dict(r: sqlite3.Row) -> dict:
    job = {
        "id": r["job_id"],
        "title": r["title"],
        "company": r["company"],
        "location": r["location"],
        "job_type": _split(r["job_type"]),
        "skills": _split(r["skills_tags"]),
        "salary": r["salary"],
        "posted": r["posted_date"],
        "deadline": r["deadline"],
        "apply_link": r["apply_link"],
        "source": r["source"],
        "status": r["status"],
        "first_seen": (r["scraped_at"] or "")[:10],
        "last_seen": (r["last_seen_at"] or "")[:10] if r["status"] != "active" else None,
        "snippet": truncate(r["description"] or "", settings.EXPORT_SNIPPET_CHARS),
    }
    return {k: v for k, v in job.items() if v not in (None, "", [])}


def _source_health(conn: sqlite3.Connection) -> list[dict]:
    """Latest run of every feed, grouped by source display name."""
    feed_source = dict(conn.execute("SELECT feed, source FROM jobs WHERE feed IS NOT NULL GROUP BY feed"))
    latest = conn.execute(
        """
        SELECT r.source AS feed, r.started_at, r.jobs_found, r.error
        FROM scrape_runs r
        JOIN (SELECT source, MAX(started_at) AS m FROM scrape_runs GROUP BY source) x
          ON x.source = r.source AND x.m = r.started_at
        """
    ).fetchall()
    active = dict(conn.execute("SELECT source, COUNT(*) FROM jobs WHERE status = 'active' GROUP BY source"))
    groups: dict[str, dict] = {}
    for row in latest:
        name = feed_source.get(row["feed"]) or row["feed"].split(":")[0].title()
        g = groups.setdefault(name, {"source": name, "feeds": 0, "ok": 0, "failed": 0,
                                     "last_run": "", "jobs_active": active.get(name, 0), "errors": []})
        g["feeds"] += 1
        g["last_run"] = max(g["last_run"], row["started_at"])
        if row["error"]:
            g["failed"] += 1
            g["errors"].append(f"{row['feed']}: {row['error'][:160]}")
        else:
            g["ok"] += 1
    for name, count in active.items():  # sources with jobs but no run history
        groups.setdefault(name, {"source": name, "feeds": 0, "ok": 0, "failed": 0,
                                 "last_run": "", "jobs_active": count, "errors": []})
    return sorted(groups.values(), key=lambda g: (-g["jobs_active"], g["source"]))


def export(conn: sqlite3.Connection, path: Path = OUTPUT_PATH) -> dict:
    rows = _job_rows(conn)
    jobs = [_job_dict(r) for r in rows]
    counts = {
        "active": conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'active'").fetchone()[0],
        "expired": conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'expired'").fetchone()[0],
        "exported": len(jobs),
    }
    header = {
        "generated_at": utc_now_iso(),
        "counts": counts,
        "my_skills": [s.lower() for s in MY_SKILLS],
        "all_skills": sorted({s for j in jobs for s in j.get("skills", [])}),
        "sources": _source_health(conn),
    }
    dumps = lambda o: json.dumps(o, ensure_ascii=False, separators=(",", ":"))
    head = json.dumps(header, ensure_ascii=False, indent=1)[:-2]  # drop closing "\n}"
    body = ",\n".join(dumps(j) for j in jobs)

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(head)
        f.write(',\n "jobs":[\n')
        f.write(body)
        f.write("\n]}\n")
    os.replace(tmp, path)  # atomic: the site never sees a half-written file
    size_kb = path.stat().st_size / 1024
    log.info("Exported %d jobs (%d active / %d expired in DB) to %s (%.0f KB)",
             len(jobs), counts["active"], counts["expired"], path, size_kb)
    return counts


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    from db.db import connect, init_db

    c = connect()
    init_db(c)
    export(c)
