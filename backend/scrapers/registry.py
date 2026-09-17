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
                 groups: list[str] | None = None, skip_groups: list[str] | None = None,
                 skip: list[str] | None = None) -> list[Feed]:
    """`only` / `skip` match a feed name exactly or by prefix before ':' (e.g. 'greenhouse')."""
    def matches(f: Feed, names: list[str]) -> bool:
        return any(f.name == n or f.name.split(":")[0] == n for n in names)

    out = []
    for f in feeds:
        if only and not matches(f, only):
            continue
        if skip and matches(f, skip):
            continue
        if groups and f.group not in groups:
            continue
        if skip_groups and f.group in skip_groups:
            continue
        out.append(f)
    return out
