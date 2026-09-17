"""Minimal robots.txt parser following RFC 9309 / Google's rules, including the `*`
and `$` wildcards that Python's urllib.robotparser ignores.

- The group whose User-agent token best matches our agent is used; otherwise `*`.
- Within a group, the longest matching rule wins; on a tie, Allow wins.
"""
from __future__ import annotations

import re
from urllib.parse import unquote, urlsplit


def _rule_regex(path: str) -> re.Pattern:
    path = unquote(path)
    anchored = path.endswith("$")
    if anchored:
        path = path[:-1]
    body = ".*".join(re.escape(part) for part in path.split("*"))
    return re.compile("^" + body + ("$" if anchored else ""))


class RobotsRules:
    def __init__(self, text: str = "", allow_all: bool = False, disallow_all: bool = False):
        self.allow_all = allow_all
        self.disallow_all = disallow_all
        self.groups: list[tuple[list[str], list[tuple[bool, str, re.Pattern]]]] = []
        if text:
            self._parse(text)

    def _parse(self, text: str) -> None:
        agents: list[str] = []
        rules: list = []
        last_was_agent = False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            key, value = (s.strip() for s in line.split(":", 1))
            key = key.lower()
            if key == "user-agent":
                if not last_was_agent and agents:
                    self.groups.append((agents, rules))
                    agents, rules = [], []
                agents.append(value.lower())
                last_was_agent = True
            elif key in ("allow", "disallow"):
                last_was_agent = False
                if agents and value:
                    rules.append((key == "allow", value, _rule_regex(value)))
            else:
                last_was_agent = False
        if agents:
            self.groups.append((agents, rules))

    def _rules_for(self, agent: str) -> list:
        agent = agent.lower()
        best, best_len = None, -1
        merged_star: list = []
        for agents, rules in self.groups:
            for a in agents:
                if a == "*":
                    merged_star.extend(rules)
                elif a in agent and len(a) > best_len:
                    best, best_len = rules, len(a)
        return best if best is not None else merged_star

    def can_fetch(self, agent: str, url: str) -> bool:
        if self.allow_all:
            return True
        if self.disallow_all:
            return False
        parts = urlsplit(url)
        target = unquote(parts.path or "/") + (f"?{unquote(parts.query)}" if parts.query else "")
        verdict, length = True, -1
        for allow, raw, rx in self._rules_for(agent):
            if rx.match(target):
                n = len(raw)
                if n > length or (n == length and allow):
                    verdict, length = allow, n
        return verdict
