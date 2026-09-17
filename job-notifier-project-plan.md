# Job Notifier & Aggregator — Complete Project Plan

> **Build status:** this plan is being implemented. See [PROGRESS.md](PROGRESS.md) for what has been built, every decision that differs from or extends this plan, and the manual setup checklist. The repo is split into `backend/` (Python) and `frontend/` (the static site that §10 calls `docs/`).

A fully free, self-running system that scrapes jobs from many sources, filters them by your skills, sends Telegram alerts, auto-removes expired listings, and shows everything (new + old) on a website with filters.

---

## 1. Goal

- Pull jobs from as many free sources as possible (APIs + scraping)
- Cover: tech, non-tech, internships, remote, India-focused, general
- Store full details with a direct apply link
- Auto-detect and remove/flag expired postings
- Filter by your skills
- Get Telegram notifications for new matching jobs
- Have a website showing all jobs (new + old) with filters and search
- Run every 2 hours, forever, at **zero cost**

---

## 2. High-Level Architecture

```
                    GitHub Actions (cron, every 2 hours, free forever)
                                    │
                                    ▼
                 ┌──────────────────────────────────┐
                 │           SCRAPERS LAYER          │
                 │  APIs + ATS loop + HTML scrapers  │
                 └──────────────────────────────────┘
                                    │
                                    ▼
                 ┌──────────────────────────────────┐
                 │            NORMALIZER             │
                 │  converts every source into one   │
                 │  standard job schema              │
                 └──────────────────────────────────┘
                                    │
                                    ▼
                 ┌──────────────────────────────────┐
                 │      SQLite DB (committed to repo)│
                 │  dedup by job_id, update          │
                 │  last_seen_at on every sighting   │
                 └──────────────────────────────────┘
                                    │
                                    ▼
                 ┌──────────────────────────────────┐
                 │         EXPIRY CHECKER            │
                 │  deadline passed OR missing       │
                 │  2+ scrape cycles → status=expired│
                 └──────────────────────────────────┘
                                    │
                                    ▼
                 ┌──────────────────────────────────┐
                 │        SKILL FILTER ENGINE        │
                 │  tags jobs against MY_SKILLS list │
                 └──────────────────────────────────┘
                          │                    │
                          ▼                    ▼
              ┌────────────────────┐  ┌────────────────────┐
              │   TELEGRAM BOT      │  │   jobs.json export  │
              │ sends new + match   │  │  powers the website  │
              └────────────────────┘  └────────────────────┘
                                                │
                                                ▼
                                   ┌────────────────────────┐
                                   │  Website (GitHub Pages) │
                                   │  new/old toggle, filters,│
                                   │  search, apply links     │
                                   └────────────────────────┘
```

Everything runs on GitHub's free infrastructure — no server, no paid database, no hosting bill.

---

## 3. Complete Source List

### 3.1 Free APIs (no scraping — start here, most reliable)

| Source | Access | Notes |
|---|---|---|
| Adzuna | `api.adzuna.com/v1/api/jobs/{country}/search` | Free API key, huge aggregator coverage |
| Jooble | `jooble.org/api/{key}` | Free API key, broad aggregator |
| Remotive | `remotive.com/api/remote-jobs` | No key needed, remote tech jobs |
| Himalayas | `himalayas.app/jobs/api` | No key needed, remote jobs |
| Jobicy | `jobicy.com/api/v2/remote-jobs` | No key needed, remote jobs |
| Findwork.dev | Free token (sign-up, no card) | Tech-focused |
| RemoteOK | `remoteok.com/api` | No key needed, remote tech |
| Arbeitnow | `arbeitnow.com/api/job-board-api` | No key needed, tech + general |
| The Muse | `themuse.com/api/public/jobs` | Free, general + tech |
| Reed (UK) | `reed.co.uk/developers` | Free key, useful if open to UK-remote |
| Careerjet | Free affiliate API | Broad international aggregator |
| USAJobs | `data.usajobs.gov` | Free key, US govt jobs |

### 3.2 ATS Platforms — "All Companies" Engine

Most companies use one of these hiring systems, each with a public JSON API per company slug. Maintain a growing list of slugs (search GitHub for existing open-source slug lists to jump-start this).

| ATS | Endpoint Pattern |
|---|---|
| Greenhouse | `boards-api.greenhouse.io/v1/boards/{company}/jobs` |
| Lever | `api.lever.co/v0/postings/{company}?mode=json` |
| Ashby | `api.ashbyhq.com/posting-api/job-board/{company}` |
| SmartRecruiters | `api.smartrecruiters.com/v1/companies/{company}/postings` |
| Workday | `{company}.wd1.myworkdayjobs.com/wday/cxs/{company}/{site}/jobs` |
| Recruitee | `{company}.recruitee.com/api/offers` |
| BambooHR | `{company}.bamboohr.com/jobs/embed2.php` |
| Breezy HR | `{company}.breezy.hr/json` |
| Teamtailor | `{company}.teamtailor.com/api/v1/jobs` |
| JazzHR | `{company}.applytojob.com` (some expose feeds) |

### 3.3 India-Focused Sites (scraping required — check robots.txt, go slow)

| Source | Notes |
|---|---|
| Naukri | Biggest India general board; JS-heavy → needs Playwright |
| Indeed India | JS-heavy → Playwright; has bot detection, space out requests |
| Internshala | Internships + entry-level; server-rendered → BeautifulSoup works |
| Foundit (Monster India) | General jobs, HTML scraping |
| Shine.com | General jobs, India-focused |
| TimesJobs | General, older but active |
| Freshersworld | Great for freshers/entry-level |
| Hirist | Tech-specific, India |
| CutShort | Tech/startup jobs, India |
| Instahyre | Tech, India — verify if login is required before building |
| FreeJobAlert | Government jobs, simple HTML |
| Sarkari Result | Government jobs, simple HTML |

### 3.4 RSS Feeds (zero scraping effort)

| Source | Feed |
|---|---|
| WeWorkRemotely | `weworkremotely.com/remote-jobs.rss` |
| Jobspresso | RSS available on site |
| Working Nomads | RSS feed available |
| Naukri/Indeed saved searches | Some expose RSS — check manually |

---

## 4. Database Schema

```sql
CREATE TABLE jobs (
    job_id TEXT PRIMARY KEY,       -- hash of company+title+link, for dedup
    title TEXT,
    company TEXT,
    location TEXT,
    job_type TEXT,                 -- tech / non-tech / internship / remote
    description TEXT,              -- full text
    skills_tags TEXT,               -- comma-separated matched skills
    salary TEXT,
    posted_date TEXT,
    deadline TEXT,                  -- explicit deadline if stated, else NULL
    apply_link TEXT,
    source TEXT,                    -- which API/site
    status TEXT,                    -- active / expired
    notified INTEGER DEFAULT 0,     -- 0/1, avoid duplicate Telegram pings
    last_seen_at TEXT,              -- updated every scrape run it still appears
    scraped_at TEXT
);
```

Never hard-delete expired jobs — flag them as `expired` so the website can still show job history if you want to look back.

---

## 5. Expiry Logic (two methods, run both)

**A. Explicit deadline**
If a source states "Apply by [date]" — parse into `deadline`. Daily check:
```
if today > deadline: status = 'expired'
```

**B. Disappearance detection** (covers most sources with no stated deadline)
1. Every scrape run updates `last_seen_at` for jobs still found
2. After the run: any job whose `last_seen_at` is older than 2 scrape cycles → `status = 'expired'`
3. Expired jobs stop appearing in "active" views and Telegram, but stay in the DB for history

---

## 6. Skill Filtering

Maintain your own skill list in a config file (edit anytime, no redeploy needed):

```python
MY_SKILLS = ["python", "react", "sql", "django", "aws", "javascript", ...]
```

**v1 — keyword matching (build this first):**
Scan each job's description/title for these keywords (case-insensitive) → store matches in `skills_tags`. A job "matches" if it has 1+ overlapping skill.

**v2 — smarter matching (later upgrade, still free):**
Use `sentence-transformers` (runs locally, no API cost) to compute similarity between your resume text and job descriptions → ranked match %, instead of plain yes/no.

---

## 7. Telegram Bot

**Setup:**
1. Telegram → search `@BotFather` → `/newbot` → get bot token
2. Message your bot once → hit `https://api.telegram.org/bot<TOKEN>/getUpdates` → get your chat_id
3. Store both as GitHub Secrets (never hardcode)

**Notification logic:**
```python
new_matching_jobs = [
    j for j in new_jobs
    if skill_match(j) and j.status == "active" and not j.notified
]
for job in new_matching_jobs:
    send_telegram(job)
    mark_notified(job)
```

**Message format:**
```
🔔 {title} at {company}
📍 {location} | 🏷 {job_type} | Source: {source}
🛠 Skills: {skills_tags}
👉 Apply: {apply_link}
```

**Optional phase-2 bot commands:**
- `/latest` — shows last 10 jobs on demand
- `/skills python react` — temporary filter override

---

## 8. The Website (free forever, good UX)

**Hosting:** GitHub Pages — free forever for public repos, no backend server needed.

**Data flow:** After every scrape cycle, export the current DB state to `jobs.json` and commit it to the repo. The website is a static page that loads this JSON and does everything client-side in JavaScript — no server, no live DB queries, no cost.

**Website features:**
- **New vs All toggle** — "New" = last 24–48h, "All" = full history including expired (greyed out/marked)
- **Filters:**
  - Skill (multi-select checkboxes or dropdown)
  - Job type (tech / non-tech / internship / remote)
  - Location (search box)
  - Status (active only / include expired)
  - Source
- **Search bar** — company or title, live-filter as you type
- **Sort** — newest first by default, option to sort by deadline
- **Each job card shows:** title, company, location, skills tags, posted date, deadline (if any), and a clear **Apply** button linking to `apply_link`
- **Clean card/grid layout** rather than a plain table — easier to scan on mobile too
- **Job count badge** — "1,204 active jobs" so you get a sense of volume at a glance

**Tech for the site:** Plain HTML + CSS + vanilla JS (or lightweight framework if you prefer) reading `jobs.json` — keeps it fast, free, and simple to maintain for 1-3 years without dependency headaches.

---

## 9. Automation — GitHub Actions Workflow

```yaml
# .github/workflows/scrape.yml
name: Job Scraper
on:
  schedule:
    - cron: '0 */2 * * *'     # every 2 hours
  workflow_dispatch:           # manual trigger option

jobs:
  scrape:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt
      - run: playwright install chromium   # only if using Playwright sources
      - run: python main.py                 # scrape → dedupe → expire → filter → notify → export
        env:
          TELEGRAM_TOKEN: ${{ secrets.TELEGRAM_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
          ADZUNA_APP_ID: ${{ secrets.ADZUNA_APP_ID }}
          ADZUNA_APP_KEY: ${{ secrets.ADZUNA_APP_KEY }}
          JOOBLE_KEY: ${{ secrets.JOOBLE_KEY }}
      - name: Commit updated data
        run: |
          git config user.name "job-bot"
          git config user.email "bot@users.noreply.github.com"
          git add db/jobs.db docs/jobs.json
          git commit -m "Auto-update jobs $(date)" || echo "No changes"
          git push
```

`main.py` runs the full pipeline end to end: scrape all sources → normalize → dedupe/update DB → run expiry checker → tag skills → send Telegram alerts for new matches → export `jobs.json` for the website.

---

## 10. Repo Structure

```
job-notifier/
├── .github/workflows/scrape.yml
├── scrapers/
│   ├── apis.py          # Adzuna, Jooble, Remotive, Himalayas, Jobicy, Findwork, RemoteOK, Arbeitnow
│   ├── ats.py            # Greenhouse, Lever, Ashby, Breezy, SmartRecruiters, Teamtailor loop
│   ├── india_boards.py   # Naukri, Internshala, Foundit, Shine, Freshersworld
│   └── rss.py            # WeWorkRemotely, Jobspresso, Working Nomads
├── db/
│   ├── models.py
│   ├── db.py             # dedup, insert/update, last_seen_at logic
│   └── jobs.db
├── filters/
│   ├── skills_config.py  # MY_SKILLS list
│   └── skill_matcher.py
├── expiry/
│   └── checker.py
├── notifier/
│   └── telegram.py
├── exporter/
│   └── export_json.py    # builds docs/jobs.json for the website
├── docs/                  # GitHub Pages source
│   ├── index.html
│   ├── style.css
│   ├── app.js
│   └── jobs.json
├── config/
│   └── companies.py       # ATS slug list
├── main.py                 # orchestrates the full pipeline
└── requirements.txt
```

---

## 11. Build Order (Roadmap)

1. Repo scaffold + DB schema (all fields from day one)
2. Free API scrapers — Adzuna, Jooble, Remotive, Himalayas, Jobicy, Findwork, RemoteOK, Arbeitnow (shared reusable pattern)
3. ATS company loop — Greenhouse, Lever, Ashby, Breezy, SmartRecruiters, Teamtailor with starter slug list
4. Skill tagging function (keyword match v1)
5. Expiry checker (deadline + disappearance based)
6. Telegram notifier — new + matching + active only
7. jobs.json exporter
8. Website v1 (GitHub Pages) — list view, new/old toggle, basic filters
9. India scraping batch — Naukri, Internshala, Foundit, Shine, Freshersworld (added after core is stable)
10. GitHub Actions workflow — wires everything to run every 2 hours automatically
11. Website polish — search, sort, better cards, job count badge
12. Phase 2 (optional): resume-matching via sentence-transformers, Telegram bot commands, trend analytics

---

## 12. Why This Stays Free for 1–3 Years

| Component | Why it's free forever, not a trial |
|---|---|
| GitHub Actions | Permanent free tier (unlimited on public repos) |
| GitHub Pages | Free forever for public repos |
| Telegram Bot API | No paid tier for basic messaging, ever |
| SQLite in repo | No external DB hosting, no expiry |
| All listed APIs | Free tiers, no credit card required |
| Website | Static, client-side filtering — no server cost |

No credit card is entered anywhere in this stack, so there is zero risk of an accidental charge when a "trial" ends — because none of these are trials.

---

## 13. Notes / Good Practices

- Always check `robots.txt` before scraping a site
- Add random delays (2–5 sec) between scraping requests
- Never scrape LinkedIn directly — against ToS and heavily blocked
- Log every scrape run (source, jobs found, errors) for easy debugging
- Keep scraper logic separate per source — one breaking doesn't break the rest
- Start with Tier 1 (APIs) + Tier 2 (ATS) fully working before adding harder scraping sources
