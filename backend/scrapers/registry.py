"""Collects every Feed from every scraper module.

A module that fails to import (e.g. an optional dependency missing) is logged and
skipped, so one broken scraper module never stops the others.
"""
from __future__ import annotations

import importlib
import logging

from scrapers.base import Feed

log = logging.getLogger("scrapers.registry")

MODULES = ["scrapers.apis", "scrapers.ats", "scrapers.rss", "scrapers.india_boards"]


def all_feeds() -> list[Feed]:
    feeds: list[Feed] = []
    for module_name in MODULES:
        try:
            module = importlib.import_module(module_name)
            if hasattr(module, "feeds"):
                feeds.extend(module.feeds())
        except Exception:
            log.exception("Could not load feeds from %s — skipping that module", module_name)
    names = [f.name for f in feeds]
    dupes = {n for n in names if names.count(n) > 1}
    if dupes:
        raise ValueError(f"Duplicate feed names: {sorted(dupes)}")
    return feeds


def select_feeds(feeds: list[Feed], only: list[str] | None = None,
                 groups: list[str] | None = None, skip_groups: list[str] | None = None) -> list[Feed]:
    """`only` matches a feed name exactly or by prefix before ':' (e.g. 'greenhouse')."""
    out = []
    for f in feeds:
        if only and not any(f.name == o or f.name.split(":")[0] == o for o in only):
            continue
        if groups and f.group not in groups:
            continue
        if skip_groups and f.group in skip_groups:
            continue
        out.append(f)
    return out
