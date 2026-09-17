I have a project plan document at ./job-notifier-project-plan.md in this repo. 
Read it fully first before doing anything.

Build a job notification and aggregation system based on that plan, with:
- Backend: Python (scrapers, DB, filtering, notifications, scheduling logic)
- Frontend: Plain JavaScript + HTML + CSS (static site, no framework needed) 
  hosted via GitHub Pages, reading a jobs.json file the backend generates
- Automation: GitHub Actions workflow to run the whole pipeline every 2 hours
- Notifications: Telegram bot
- Storage: SQLite committed to the repo (no external DB, no paid hosting)

Follow this exact build order, and after each step, show me the working result 
before moving to the next step:

STEP 1 — Repo scaffold
Create the folder structure exactly as described in the plan's "Repo Structure" 
section (scrapers/, db/, filters/, expiry/, notifier/, exporter/, docs/, config/, 
main.py, requirements.txt). Set up the DB schema from the plan's "Database Schema" 
section using SQLite.

STEP 2 — First working pipeline (proof of concept)
Implement ONE source end-to-end first: RemoteOK API. Build the scraper, the 
normalizer (standard job schema from the plan), insert into SQLite with dedup 
by job_id, and a Telegram notifier that sends a message for each new job. 
Give me instructions to create the Telegram bot and where to put the token 
(use environment variables / GitHub Secrets, never hardcode).

STEP 3 — Add remaining free API sources
Add Jooble, Remotive, Himalayas, Jobicy, Findwork, Arbeitnow, Adzuna, The Muse — 
using a shared reusable "API puller" pattern since their JSON structures are 
similar. Reuse the same normalizer.

STEP 4 — ATS company loop
Implement the Greenhouse and Lever pullers using a configurable list of company 
slugs (config/companies.py). Add Ashby, SmartRecruiters, Breezy, and Teamtailor 
too. Give me a starter list of 30-50 known company slugs across these platforms.

STEP 5 — Skill filtering
Build filters/skills_config.py with a MY_SKILLS list I can edit, and a keyword-based 
skill matcher that tags each job's matched skills into skills_tags. Only jobs 
with 1+ matching skill (or all jobs if MY_SKILLS is empty) should notify.

STEP 6 — Expiry logic
Implement both expiry methods from the plan: explicit deadline parsing, and 
disappearance detection (mark expired if last_seen_at is older than 2 scrape 
cycles). Never hard-delete — just flag status as expired.

STEP 7 — India-focused scraping sources
Add Naukri, Internshala, Foundit, Shine, and Freshersworld using BeautifulSoup 
where the page is server-rendered, and Playwright where it's JS-heavy (like 
Naukri). Respect robots.txt, add 2-5 second randomized delays between requests, 
and rotate a realistic User-Agent header. Handle pagination properly.

STEP 8 — RSS feeds
Add WeWorkRemotely, Jobspresso, and Working Nomads RSS parsing into the same 
normalized schema.

STEP 9 — jobs.json exporter
Build exporter/export_json.py that dumps the current DB state (active + expired, 
tagged with skills) into docs/jobs.json for the website to consume.

STEP 10 — Website (docs/index.html, style.css, app.js)
Build a clean, modern static website that:
- Loads jobs.json client-side (no backend calls)
- Shows a "New" (last 24-48h) vs "All" toggle
- Has filters: skill (multi-select), job_type, location search, status 
  (active/include expired), source
- Has a live search box for company/title
- Sorts newest first by default
- Displays jobs as clean cards (not a plain table) with title, company, 
  location, skills tags, posted date, deadline if present, and a clear 
  "Apply" button linking to apply_link
- Shows a job count badge at the top
- Is responsive and looks good on both desktop and mobile
- Make good design decisions on your own — modern, clean, minimal, easy to scan

STEP 11 — GitHub Actions automation
Create .github/workflows/scrape.yml exactly as described in the plan: runs 
main.py every 2 hours via cron, installs dependencies (including Playwright 
browsers), passes secrets as env vars, and commits + pushes the updated 
jobs.db and docs/jobs.json back to the repo after each run.

STEP 12 — Final review
Walk me through: how to set up all required GitHub Secrets (Telegram token/chat 
ID, Adzuna keys, Jooble key, etc.), how to enable GitHub Pages for the docs/ 
folder, and how to test the whole pipeline manually before relying on the 
schedule.

Important constraints throughout:
- Everything must be free forever — no paid tiers, no services requiring a 
  credit card, no trials
- Keep each source's scraper isolated so one breaking doesn't break others
- Log every scrape run (source name, jobs found, errors) to make debugging easy
- Do not build anything to scrape LinkedIn
- Ask me before moving to the next step if something is ambiguous