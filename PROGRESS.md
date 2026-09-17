# Build Progress & Decisions Log

This file records what has been built, step by step, and **every decision that was
not spelled out in [job-notifier-project-plan.md](job-notifier-project-plan.md)**.
It is written so that someone with zero context (a person or another AI tool) can
pick the project up. The manual setup checklist is collected in one place at the
bottom.

Repo layout (see [README.md](README.md) for how to run things):

```
backend/    Python pipeline (scrapers, DB, filters, expiry, notifier, exporter, config, main.py)
frontend/   Static website (index.html, style.css, app.js, jobs.json written by the backend)
.github/workflows/   GitHub Actions automation
```

---

## Step 1 — Repo scaffold + DB schema

**Built**
- Folder structure from plan §10, later reorganised into `backend/` and `frontend/`
  (the user asked for a clean backend/frontend split; `docs/` from the plan became
  `frontend/`).
- `backend/db/models.py` — the `Job` dataclass (the one standard job schema every
  scraper produces) and the SQLite DDL. `backend/db/db.py` — connect, create tables,
  insert-or-update with dedup, run logging.
- `backend/db/jobs.db` — the SQLite file. It is committed to git on purpose (plan §9).
- `git init` on branch `main`, `.gitignore` (secrets, `.env`, `__pycache__`,
  `node_modules`, logs), `.gitattributes` marks `*.db` as binary.

**Decisions not in the original plan**
- **`job_id`** = first 32 hex chars of SHA-256 over `company|title|apply_link`, each
  lower-cased and trimmed, so small casing/whitespace differences don't create duplicates.
- **Re-seeing an existing job** updates `last_seen_at`, sets `status='active'`, and
  fills in description/salary/deadline/location if the new copy has them. It never
  resets `notified` or `scraped_at`.
- **Extra table `scrape_runs`** — one row per source per pipeline run (`run_id`,
  `source`, start/finish time, `jobs_found`, `jobs_new`, `error`). This is the
  "log every scrape run" requirement, and expiry logic also relies on it (Step 6).
- **Indexes** on `jobs.status`, `jobs.source`, `jobs.last_seen_at`.
- **Python 3.10+** compatible (local machine has 3.10; GitHub Actions uses 3.11).

<!-- NEXT-STEP -->

---

## Manual setup checklist (things only you can do)

_Kept up to date as steps are completed._
