"""Keyword skill matcher (plan §6, v1).

tag_job(job)      -> sets job.skills_tags from the job's full text (before truncation)
match_skills(txt) -> list of matched skills, in MY_SKILLS order
retag_all(conn)   -> recomputes skills_tags for every stored job when MY_SKILLS changed
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3

from filters.skills_config import MY_SKILLS, SKILL_ALIASES

log = logging.getLogger("filters.skills")

META_KEY = "skills_fingerprint"


def _pattern(term: str) -> str:
    # Whole-word match that still works for terms starting/ending with symbols.
    # Spaces/hyphens inside a term match any run of spaces or hyphens.
    parts = [re.escape(p) for p in re.split(r"[\s\-]+", term.strip().lower()) if p]
    return r"(?<![a-z0-9])" + r"[\s\-]+".join(parts) + r"(?![a-z0-9])"


def _compile(skills: list[str], aliases: dict[str, list[str]]) -> list[tuple[str, re.Pattern]]:
    compiled = []
    seen = set()
    for skill in skills:
        key = skill.strip()
        if not key or key.lower() in seen:
            continue
        seen.add(key.lower())
        terms = [key] + aliases.get(key, []) + aliases.get(key.lower(), [])
        # Very short aliases ("js", "ts", "ml") are only trusted as whole words, which
        # _pattern already enforces.
        regex = "|".join(_pattern(t) for t in sorted(set(terms), key=len, reverse=True))
        compiled.append((key.lower(), re.compile(regex, re.I)))
    return compiled


_MATCHERS = _compile(MY_SKILLS, SKILL_ALIASES)


def skills_filter_active() -> bool:
    """False when MY_SKILLS is empty, meaning every job should notify."""
    return bool(_MATCHERS)


def match_skills(text: str) -> list[str]:
    if not text:
        return []
    return [skill for skill, rx in _MATCHERS if rx.search(text)]


def tag_job(job) -> None:
    text = job.match_text or f"{job.title} {job.description}"
    job.skills_tags = ",".join(match_skills(text))


def is_match(skills_tags: str) -> bool:
    return not skills_filter_active() or bool(skills_tags)


def fingerprint() -> str:
    payload = json.dumps([MY_SKILLS, SKILL_ALIASES], sort_keys=True)
    return hashlib.sha1(payload.encode()).hexdigest()


def retag_all(conn: sqlite3.Connection, force: bool = False) -> int:
    """Re-tag stored jobs when the skill config changed since the last run.

    Uses the stored (truncated) title + job_type + description, so tags can be
    slightly less complete than tags computed at scrape time. Active jobs are
    re-tagged from full text anyway the next time they are scraped.

    Jobs that were never notified and now match are *not* alerted retroactively
    unless they are recent — the notifier's max-age rule handles that.
    """
    from db.db import get_meta, set_meta

    fp = fingerprint()
    if not force and get_meta(conn, META_KEY) == fp:
        return 0
    rows = conn.execute("SELECT job_id, title, job_type, description, skills_tags FROM jobs").fetchall()
    updates = []
    for r in rows:
        tags = ",".join(match_skills(f"{r['title']} {r['job_type']} {r['description']}"))
        if tags != (r["skills_tags"] or ""):
            updates.append((tags, r["job_id"]))
    with conn:
        conn.executemany("UPDATE jobs SET skills_tags = ? WHERE job_id = ?", updates)
    set_meta(conn, META_KEY, fp)
    log.info("Skill config changed: re-tagged %d of %d jobs", len(updates), len(rows))
    return len(updates)
