"""Pipeline entry point: scrape -> dedupe -> expire -> tag skills -> notify -> export.

Stages are wired in as each build step lands.
"""
from __future__ import annotations

import logging
import sys

from db.db import DB_PATH, connect, init_db

log = logging.getLogger("main")


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        stream=sys.stdout,
    )


def main() -> int:
    setup_logging()
    conn = connect()
    init_db(conn)
    log.info("DB ready at %s", DB_PATH)
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
