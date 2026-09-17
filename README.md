# Job Radar — free, self-running job aggregator + Telegram alerts

Scrapes jobs from ~70 free sources every 2 hours, tags them with your skills, sends
Telegram alerts for new matches, flags expired postings, and publishes everything
to a filterable website. It runs entirely on GitHub Actions + GitHub Pages at zero cost.

- **Plan:** [job-notifier-project-plan.md](job-notifier-project-plan.md) (original design)
- **What was built and why:** [PROGRESS.md](PROGRESS.md) (step-by-step log of every
  decision, current status, known limitations, and the **manual setup checklist**)

```
GitHub Actions (every 2h) ──► backend/main.py
   scrape 69 feeds (APIs · ATS company boards · RSS · India job sites)
   → normalize → tag skills → dedupe into SQLite (backend/db/jobs.db)
   → expire (deadline / disappeared / stale) → Telegram alerts
   → export frontend/jobs.json → commit → deploy frontend/ to GitHub Pages
```

## Repository layout

```
backend/                     Python 3.10+ pipeline (run everything from this folder)
  main.py                    entry point / orchestrator (see --help)
  requirements.txt
  config/settings.py         all tunables (intervals, limits, search terms)
  config/companies.py        ATS company slugs (Greenhouse, Lever, Ashby, ...)
  filters/skills_config.py   ← YOUR SKILLS (MY_SKILLS)
  filters/skill_matcher.py   whole-word keyword matcher + auto re-tagging
  scrapers/base.py           HTTP client (retries, UA rotation, delays, robots.txt), Feed
  scrapers/normalize.py      the normalizer: raw fields → standard Job schema
  scrapers/robots.py         robots.txt parser with wildcard support
  scrapers/registry.py       collects feeds from all scraper modules
  scrapers/apis.py           RemoteOK, Remotive, Himalayas, Jobicy, Arbeitnow, The Muse,
                             Jooble, Adzuna, Findwork  (shared ApiPuller pattern)
  scrapers/ats.py            Greenhouse, Lever, Ashby, SmartRecruiters, Breezy, Teamtailor
  scrapers/rss.py            WeWorkRemotely, Jobspresso, Working Nomads
  scrapers/india_boards.py   Internshala, Shine, Freshersworld, Naukri*, Foundit*
  db/models.py, db/db.py     schema, Job dataclass, dedup upsert, run log
  db/jobs.db                 the database (committed on purpose)
  expiry/checker.py          deadline / disappearance / staleness rules
  notifier/telegram.py       Telegram alerts with spam guards
  exporter/export_json.py    writes frontend/jobs.json
frontend/                    static website (no build step)
  index.html, style.css, app.js, jobs.json (generated)
.github/workflows/
  scrape.yml                 every 2 hours: run pipeline, commit data, deploy site
  pages.yml                  deploy frontend/ to GitHub Pages
```
\* Naukri and Foundit use a headless browser and may be blocked by those sites' bot
protection. See PROGRESS.md, Step 7.

## Quick start (local)

```bash
cd backend
pip install -r requirements.txt
python -m playwright install chromium        # only needed for Naukri/Foundit

python main.py --list                        # show all feeds
python main.py --only remoteok --no-notify   # one source, no Telegram
python main.py --skip-group india            # everything except India HTML scrapers
python main.py                               # full run (≈6 min)
python main.py --test-telegram               # check your bot setup
```

Secrets are read from environment variables. For local runs you can copy
`.env.example` to `.env` (git-ignored) and fill it in.

Preview the website: `cd frontend && python -m http.server 8000` → open
<http://localhost:8000>. Opening `index.html` directly from disk doesn't work, because the
browser blocks loading `jobs.json` from a file.

## Everyday changes

| I want to… | Edit |
|---|---|
| change which skills trigger alerts | `backend/filters/skills_config.py` (`MY_SKILLS`, `SKILL_ALIASES`) |
| add/remove companies | `backend/config/companies.py` |
| change search keywords (Adzuna, Jooble, Shine, Naukri, Foundit) | `backend/config/settings.py` (`SEARCH_QUERIES`, `INDIA_QUERIES`) |
| change Internshala / Freshersworld categories | top of `backend/scrapers/india_boards.py` |
| change alert limits, expiry timing, export size | `backend/config/settings.py` |
| change the schedule | `cron` in `.github/workflows/scrape.yml` (keep `SCRAPE_INTERVAL_HOURS` in sync) |
| add a new JSON API source | add an `ApiPuller` in `backend/scrapers/apis.py` and list it in `feeds()` |

Push the change. The next scheduled run picks it up, or start a run yourself from the
Actions tab.

## Debugging

- **Per-run summary** (one line per feed: found / new / error) is in the Actions log,
  and `run.log` is attached to each run as an artifact.
- **Run history** is in the DB:
  ```bash
  cd backend
  python -c "import sqlite3;c=sqlite3.connect('db/jobs.db');[print(r) for r in c.execute('select started_at,source,jobs_found,jobs_new,error from scrape_runs order by id desc limit 30')]"
  ```
- The website's **Source status** panel (bottom of the page) shows each source's latest result.

## Rules this project follows

Free services only (no credit card anywhere) · robots.txt respected · 2–5 s randomized
delays on HTML scraping · each source isolated · no LinkedIn scraping · no attempts to get
around bot protection · jobs are never deleted, only marked expired.
