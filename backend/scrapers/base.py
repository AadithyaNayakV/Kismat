"""Shared scraping plumbing: HTTP client (retries, rotating User-Agent, polite delays,
robots.txt checks), the Feed description every scraper registers, and PartialResult.
"""
from __future__ import annotations

import logging
import random
import time
import urllib.robotparser
from dataclasses import dataclass, field
from typing import Callable, Optional
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import settings
from db.models import Job

log = logging.getLogger("scrapers")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36 Edg/138.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:141.0) Gecko/20100101 Firefox/141.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.6; rv:141.0) Gecko/20100101 Firefox/141.0",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:141.0) Gecko/20100101 Firefox/141.0",
]


def random_user_agent() -> str:
    return random.choice(USER_AGENTS)


class PartialResult(Exception):
    """Raised by a scraper that collected some jobs but hit an error part-way.

    The jobs are still saved, but the run is recorded with an error so the expiry
    checker does not treat missing jobs as gone.
    """

    def __init__(self, jobs: list[Job], reason: str):
        super().__init__(reason)
        self.jobs = jobs


class RobotsDisallowed(Exception):
    pass


@dataclass
class Feed:
    """One independently-run scrape unit (one API, one ATS company, one RSS feed...)."""

    name: str                                # unique id, e.g. "remoteok", "greenhouse:stripe"
    source: str                              # value stored in jobs.source, e.g. "Greenhouse"
    group: str                               # api | ats | india | rss
    fetch: Callable[[], list[Job]]
    min_interval_hours: float = 0            # throttle sources that ask for infrequent polling
    requires_env: tuple[str, ...] = field(default_factory=tuple)


class HttpClient:
    """requests.Session wrapper. One instance per feed keeps scrapers isolated."""

    def __init__(self, delay_range: Optional[tuple[float, float]] = None, respect_robots: bool = False):
        self.delay_range = delay_range
        self.respect_robots = respect_robots
        self._last_request = 0.0
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}
        self.session = requests.Session()
        retry = Retry(
            total=3, backoff_factor=1.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET", "POST"),
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def _default_headers(self) -> dict:
        return {
            "User-Agent": random_user_agent(),
            "Accept-Language": "en-US,en;q=0.9",
        }

    def _wait(self) -> None:
        if not self.delay_range:
            return
        target = random.uniform(*self.delay_range)
        elapsed = time.monotonic() - self._last_request
        if self._last_request and elapsed < target:
            time.sleep(target - elapsed)

    def allowed(self, url: str) -> bool:
        """robots.txt check for the generic '*' agent. Unreachable robots.txt
        (network error / 5xx / 401 / 403) is treated as 'disallow' to stay safe;
        a 404 means no rules, so everything is allowed."""
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        rp = self._robots.get(base)
        if rp is None:
            rp = urllib.robotparser.RobotFileParser()
            try:
                resp = self.session.get(f"{base}/robots.txt", headers=self._default_headers(),
                                        timeout=settings.HTTP_TIMEOUT)
                if resp.status_code == 404:
                    rp.parse([])
                elif resp.ok:
                    rp.parse(resp.text.splitlines())
                else:
                    rp.disallow_all = True
            except requests.RequestException as exc:
                log.warning("robots.txt fetch failed for %s: %s", base, exc)
                rp.disallow_all = True
            self._robots[base] = rp
        return rp.can_fetch("*", url)

    def request(self, method: str, url: str, **kwargs) -> requests.Response:
        if self.respect_robots and not self.allowed(url):
            raise RobotsDisallowed(f"robots.txt disallows {url}")
        headers = self._default_headers()
        headers.update(kwargs.pop("headers", None) or {})
        kwargs.setdefault("timeout", settings.HTTP_TIMEOUT)
        self._wait()
        try:
            resp = self.session.request(method, url, headers=headers, **kwargs)
        finally:
            self._last_request = time.monotonic()
        resp.raise_for_status()
        return resp

    def get(self, url: str, **kwargs) -> requests.Response:
        return self.request("GET", url, **kwargs)

    def get_json(self, url: str, **kwargs):
        headers = {"Accept": "application/json", **(kwargs.pop("headers", None) or {})}
        return self.get(url, headers=headers, **kwargs).json()

    def post_json(self, url: str, payload: dict, **kwargs):
        headers = {"Accept": "application/json", **(kwargs.pop("headers", None) or {})}
        return self.request("POST", url, json=payload, headers=headers, **kwargs).json()
