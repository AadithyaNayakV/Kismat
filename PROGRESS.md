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

## Step 2 — First working pipeline (RemoteOK → SQLite → Telegram)

**Built**
- `backend/scrapers/base.py` — shared plumbing: an `HttpClient` (automatic retries
  on 429/5xx, a random realistic User-Agent on every request, optional polite delay,
  optional robots.txt check), the `Feed` record every scraper registers, and
  `PartialResult`.
- `backend/scrapers/normalize.py` — **the normalizer**. Every source calls
  `normalize(...)`, which strips HTML, parses dates (ISO, epoch, "3 days ago"),
  parses deadlines, formats salary, classifies `job_type`, and truncates the description.
- `backend/scrapers/apis.py` — `fetch_remoteok()`.
- `backend/scrapers/registry.py` — collects all feeds from all scraper modules;
  `--only/--group/--skip-group` select a subset.
- `backend/notifier/telegram.py` — sends one HTML-formatted message per new
  matching job (format from plan §7, plus salary/deadline lines when known).
- `backend/main.py` — the pipeline with a command-line interface (`--list`, `--only`, `--no-notify`,
  `--test-telegram`, ...). Prints a per-feed summary table and also writes
  `backend/logs/run.log` (git-ignored).
- Verified: first run stored 99 RemoteOK jobs; second run found 99 / new 0 (dedup
  works); notifier output checked with a fake sender.

**Decisions not in the original plan**
- **"Feed" = one isolated scrape unit** (one API, one ATS company, one RSS feed).
  Each feed runs inside its own try/except, so a crash only affects that feed. Every feed
  run is written to `scrape_runs`.
- **New column `jobs.feed`** stores the feed that found the job (e.g. `greenhouse:stripe`),
  while `jobs.source` keeps the display name (`Greenhouse`). Expiry needs this
  per-feed granularity (Step 6). `init_db` adds missing columns automatically, so
  older DB files upgrade in place.
- **`job_type` holds several tags separated by commas**: always `tech` or `non-tech`, plus
  `internship` and/or `remote` when they apply (e.g. `tech,remote`). The plan's
  four values overlap (a remote tech internship is all three), so one value could not
  represent them. The classification is a keyword match on title + source category/tags.
- **Description stored truncated** to 1,500 characters (`settings.DESCRIPTION_MAX_CHARS`),
  because the DB is committed to git every 2 hours and would otherwise grow fast.
  Skill matching runs on the *full* text before truncation.
- **RemoteOK apply link** points to the Remote OK job page (not the employer's
  page), because RemoteOK's API terms require linking back to them.
- **No alert flood on the first run:** if the DB was empty before the run, every job
  is marked as already notified and one "set up complete" message is sent.
- **Spam guards:** at most 25 individual alerts per run (`MAX_NOTIFICATIONS_PER_RUN`);
  the rest go in a single "N more" message. Jobs posted more than 7 days ago are not
  alerted. Messages are spaced 1.1 s apart, and Telegram rate-limit (429) replies are retried.
- **If Telegram isn't configured**, alerts are skipped (with a warning) and the jobs stay
  un-notified, so they are sent once the secrets exist (still capped as above).
- **All tunables** live in `backend/config/settings.py`. Secrets only come from
  environment variables.
- The console output is forced to UTF-8 so emoji don't crash on Windows terminals.

<!-- NEXT-STEP -->

---

## Manual setup checklist (things only you can do)

_Kept up to date as steps are completed._

### Telegram bot (required for alerts)
1. In Telegram, open **@BotFather** → send `/newbot` → pick a name and a username
   ending in `bot`. BotFather replies with a **token** like `123456:ABC-...`.
2. Open a chat with your new bot and send it any message (e.g. "hi").
3. In a browser open `https://api.telegram.org/bot<TOKEN>/getUpdates` (paste your
   token after `bot`). Find `"chat":{"id": 123456789 ...}` — that number is your
   **chat ID**. (For a group: add the bot to the group, send a message, and the ID will be
   negative, e.g. `-100...`.)
4. Add both as GitHub Secrets (see "GitHub Secrets" below): `TELEGRAM_TOKEN`,
   `TELEGRAM_CHAT_ID`.
5. To test locally (PowerShell, from `backend/`):
   ```powershell
   $env:TELEGRAM_TOKEN = "123456:ABC-..."
   $env:TELEGRAM_CHAT_ID = "123456789"
   python main.py --test-telegram
   ```
   Never commit the token. `.env` files are git-ignored if you prefer to keep them in one.
