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

## Step 3 — Remaining free API sources

**Built**
- `backend/scrapers/apis.py` rewritten around one reusable class, **`ApiPuller`**.
  A source is defined by three small functions: a *request generator* (yields
  request dicts and receives each JSON response, so it can follow cursors or next links
  or stop early), an *items extractor*, and a *mapper* that calls the shared normalizer.
  Paging, polite delays and error handling are shared.
- Sources: RemoteOK, **Remotive, Himalayas, Jobicy, Arbeitnow, The Muse** (no key),
  **Jooble, Adzuna, Findwork** (free key/token; the feed is skipped automatically
  when its env var is missing).
- Verified live: RemoteOK 99, Remotive 15, Himalayas 100, Jobicy 100, Arbeitnow 500,
  The Muse 62 jobs. The key-based mappers were checked against sample payloads
  (they can't be exercised until keys exist).

**Decisions not in the original plan**
- **Throttling per feed** (`Feed.min_interval_hours`): Remotive every 6 h (their
  terms ask for at most ~4 calls/day), Adzuna every 6 h (keeps well inside the free
  quota), Jooble every 4 h. The rest run every cycle.
- **Partial failures:** if page 1 fails, the feed fails. If a later page fails, the
  jobs already fetched are saved but the run is flagged `partial:` in `scrape_runs`,
  so expiry won't treat the missing jobs as removed.
- **Max job age** (`settings.MAX_JOB_AGE_DAYS = 60`): jobs with a `posted_date`
  older than this are dropped by the pipeline. Needed because The Muse returns
  years-old postings and does not sort by date. ATS feeds opt out (Step 4).
- **The Muse** is limited to `India` and `Flexible / Remote` locations
  (`MUSE_LOCATIONS`), 5 pages. `MUSE_API_KEY` is optional (only raises its rate limit).
- **Search terms** for keyword APIs (Adzuna, Jooble) are in
  `settings.SEARCH_QUERIES`. Adzuna country defaults to India (`ADZUNA_COUNTRY=in`,
  overridable by env var); Jooble location defaults to `India` (`JOOBLE_LOCATION`).
- **Arbeitnow** is fetched 2 pages (500 jobs). It is mostly European/German listings.
- **Himalayas** uses its new cursor pagination; its `expiryDate` is stored as the
  job's `deadline`.
- **Attribution:** Remotive, Jobicy and RemoteOK terms require linking to their job
  page and naming them. `apply_link` is the URL they provide, and the website shows
  the source name on every card.
- The plan's optional sources Reed, Careerjet and USAJobs were **not** built (the
  build prompt didn't list them). `ApiPuller` makes each one roughly a 30-line addition.

## Step 4 — ATS company loop

**Built**
- `backend/scrapers/ats.py` — **Greenhouse, Lever, Ashby, SmartRecruiters, Breezy HR,
  Teamtailor**. Each (platform, company) pair becomes its own feed named
  `platform:slug`, so one dead company only fails itself.
- `backend/config/companies.py` — a **starter list of 51 company slugs** (20 Greenhouse, 9 Lever,
  9 Ashby, 5 SmartRecruiters, 4 Breezy, 4 Teamtailor), including Indian employers
  (Groww, Druva, CRED, Zeta, Paytm, Meesho, Hevo, Mindtickle, FamPay, Freshworks).
  Every slug was checked live and returned jobs. The file explains how to find and test new slugs.
- Verified: all 51 feeds OK, **9,067 jobs** in one run (~2 minutes).

**Decisions not in the original plan**
- **Teamtailor uses the public `https://<company>.teamtailor.com/jobs.rss`** feed.
  The plan's `/api/v1/jobs` endpoint needs a per-company API key, so it can't be used
  for companies you don't control. Regional hosts (e.g. `acme.na.teamtailor.com`) can
  be listed as full hostnames.
- **SmartRecruiters** is paginated (100 per page, max 10 pages). A board larger than that
  is saved but flagged partial, so its jobs are not expired by disappearance.
  Its listing endpoint has no descriptions, so skill tags come from title +
  function/department only (fetching each job's detail would cost one request per job).
  The same applies to **Breezy**.
- **Greenhouse** is fetched with `?content=true` (full description for skill
  matching). Its `application_deadline` field becomes `deadline`.
- **ATS feeds are marked `complete=True`** (the board lists every open job), which is
  what makes disappearance-based expiry reliable for them (Step 6). They also opt out
  of the 60-day max-age filter, because ATS roles often stay open for months.
- **Very large boards were left out** (Databricks ~880, Bosch ~4,800 jobs). The LinkedIn
  careers board on SmartRecruiters was excluded to stay clear of anything LinkedIn.
- **Stored description cap lowered to 800 chars.** The website only shows a 220-char
  snippet and Telegram shows none, so the stored text is only used when tags are
  recomputed after you edit your skill list.
- **Git growth measured:** committing the updated DB after a full run added ~136 KB
  to the packed repo. At 12 runs/day that is roughly **0.6 GB/year**, which is fine for
  the 1–3 year horizon (GitHub recommends repos stay under a few GB).
  If it ever becomes a problem, the fix is to commit `jobs.db` to a separate
  single-commit `data` branch (force-pushed) instead of `main`. This is not done now
  because the plan asks for the DB to be committed alongside the code.
- `lever` and `ashby` responses don't include the company's display name, so the name
  is derived from the slug (`hevodata` → `Hevodata`).

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

### Free API keys (optional — each source is skipped until its key exists)
None of these ask for a credit card.
- **Adzuna** — sign up at <https://developer.adzuna.com/> → "Dashboard" shows an
  **Application ID** and **Application Key** → secrets `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`.
  Optional variable `ADZUNA_COUNTRY` (default `in`).
- **Jooble** — request a key at <https://jooble.org/api/about> (form; the key is
  emailed) → secret `JOOBLE_KEY`.
- **Findwork** — create an account at <https://findwork.dev/> and copy the API token
  from <https://findwork.dev/developers/> → secret `FINDWORK_TOKEN`.
- **The Muse** (optional, works without) — <https://www.themuse.com/developers/api/v2>
  → secret `MUSE_API_KEY`.
