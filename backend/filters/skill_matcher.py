"""Skill matcher. Step 2 ships only the switch; keyword tagging lands in Step 5."""
from __future__ import annotations

from filters.skills_config import MY_SKILLS


def skills_filter_active() -> bool:
    """False when MY_SKILLS is empty, meaning every job should notify."""
    return bool(MY_SKILLS)


def tag_job(job) -> None:
    job.skills_tags = ""
