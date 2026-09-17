# Setup Guide (one-time, ~20 minutes)

Everything here is free and needs no credit card. Do the sections in order.
A short checkbox version is at the bottom of [PROGRESS.md](PROGRESS.md).

---

## 1. Put the code on GitHub

1. Create a **public** repository on GitHub, e.g. `job-radar`, with no README,
   .gitignore, or license (the repo already has them).
   - Keep it public: GitHub Actions minutes are unlimited for public repos, and a full run
     every 2 hours (~2,200 min/month) would exceed the 2,000 free minutes of a private
     repo. GitHub Pages is also free only for public repos on the Free plan.
   - Nothing secret is committed: tokens live in GitHub Secrets. The job database and
     `jobs.json` only contain public job postings.
2. Push the local repo (from the project folder):
   ```powershell
   git remote add origin https://github.com/<your-username>/job-radar.git
   git push -u origin main
   ```

## 2. Create the Telegram bot

1. In Telegram, open **@BotFather** → send `/newbot` → choose a display name and a
   username ending in `bot`. BotFather replies with a **token** like
   `7123456789:AAH...`. Keep it private.
2. Open a chat with your new bot and send it any message (e.g. `hi`). Bots can't message you
   until you've messaged them first.
3. In a browser, open `https://api.telegram.org/bot<TOKEN>/getUpdates` (put your token right
   after `bot`, no `<>`). Find `"chat":{"id":123456789,...` — that number is your
   **chat ID**.
   - Empty result (`"result":[]`)? Send the bot another message and reload.
   - Want alerts in a group? Add the bot to the group, send a message there, reload.
     Group IDs are negative (e.g. `-1001234567890`).

## 3. Get the optional free API keys

Each of these sources is simply skipped until its key exists, so you can add them later.

| Source | Where | Secret name(s) |
|---|---|---|
| Adzuna | <https://developer.adzuna.com/> → sign up → Dashboard → *Application ID* and *Application Key* | `ADZUNA_APP_ID`, `ADZUNA_APP_KEY` |
| Jooble | <https://jooble.org/api/about> → fill in the form → key arrives by e-mail | `JOOBLE_KEY` |
| Findwork | <https://findwork.dev/> → sign up → <https://findwork.dev/developers/> → copy the token | `FINDWORK_TOKEN` |
| The Muse (optional, works without) | <https://www.themuse.com/developers/api/v2> → register an app | `MUSE_API_KEY` |

## 4. Add GitHub Secrets

Repository → **Settings** → **Secrets and variables** → **Actions** → **Secrets** tab →
**New repository secret**. Add each one separately (name must match exactly):

| Name | Required? | Value |
|---|---|---|
| `TELEGRAM_TOKEN` | for alerts | bot token from step 2 |
| `TELEGRAM_CHAT_ID` | for alerts | chat ID from step 2 |
| `ADZUNA_APP_ID` | optional | from step 3 |
| `ADZUNA_APP_KEY` | optional | from step 3 |
| `JOOBLE_KEY` | optional | from step 3 |
| `FINDWORK_TOKEN` | optional | from step 3 |
| `MUSE_API_KEY` | optional | from step 3 |

Optional **Variables** (same page → **Variables** tab; these aren't secret):

| Name | Default | Meaning |
|---|---|---|
| `SITE_URL` | – | your Pages URL (step 5), linked in Telegram summary messages |
| `ADZUNA_COUNTRY` | `in` | Adzuna country code (`in`, `gb`, `us`, `au`, …) |
| `JOOBLE_LOCATION` | `India` | location sent with Jooble searches |

## 5. Enable GitHub Pages

The website lives in `frontend/` and is deployed by a workflow, not from a branch.

1. Repository → **Settings** → **Pages**.
2. **Build and deployment → Source:** choose **GitHub Actions**. Nothing else to set.
3. Repository → **Settings** → **Actions** → **General** → **Workflow permissions:**
   select **Read and write permissions** → Save. The scraper needs this to commit the
   updated data.
4. Your site will be at `https://<your-username>.github.io/<repo-name>/` after the first
   deploy (step 6). Put that URL in the `SITE_URL` variable if you like.

## 6. Test everything manually before trusting the schedule

1. **Deploy the site once:** Actions tab → **Deploy website** → **Run workflow**. When it's
   green, open your Pages URL. You should see the jobs committed in the repo.
2. **Quick pipeline test:** Actions → **Job Scraper** → **Run workflow**
   - *Only these feeds:* `remoteok`
   - *Send Telegram alerts:* ✔
   - Expect: green run. The log shows `[remoteok] found=… new=…` and a summary table,
     followed by a commit named `Auto-update jobs …` and a website deploy.
     You'll get a Telegram message only if RemoteOK had a *new* job that matches your skills.
3. **Telegram check:** if you want to confirm the bot works right now, run it locally:
   ```powershell
   cd backend
   $env:TELEGRAM_TOKEN = "<token>"; $env:TELEGRAM_CHAT_ID = "<chat id>"
   python main.py --test-telegram
   ```
4. **Full run:** Actions → **Job Scraper** → **Run workflow** with *Only these feeds*
   empty. It takes ~6–8 minutes. In the log's summary table, check that:
   - most feeds say `ok`,
   - `adzuna` / `jooble` / `findwork` say `skipped (missing env …)` until you add keys,
   - **`naukri`**: `ok` or an error. It can't be tested before this point (see PROGRESS.md
     Step 7). If it fails every time, add `naukri` to the `--skip` list or just ignore the line,
   - `foundit` is expected to show `SiteBlocked` (bot protection).
5. **Check the website:** reload your Pages URL. The badge, "Updated … ago", and the
   **Source status** panel at the bottom should reflect the run.
6. **Leave it running:** the schedule starts automatically (every 2 hours, UTC).
   Check the Actions tab after a few hours to confirm scheduled runs are green.

## 7. Personalise

- Edit `backend/filters/skills_config.py` → `MY_SKILLS` (the starter list is only an
  example: python, javascript, react, sql, django, aws). Commit and push; the next run re-tags
  every job automatically.
- Add companies in `backend/config/companies.py`. Test one with
  `python main.py --only greenhouse:<slug> --no-notify`.
- Search keywords: `backend/config/settings.py` → `SEARCH_QUERIES`, `INDIA_QUERIES`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Run fails at "Commit updated data" with 403 | Step 5.3: set workflow permissions to *Read and write* |
| "Deploy website" fails with "Pages not enabled"/404 | Step 5.2: Pages source must be *GitHub Actions* |
| No Telegram messages | Run `--test-telegram` locally; check secret names; make sure you messaged the bot first. Alerts only go out for *new* jobs matching `MY_SKILLS` that were posted in the last 7 days, max 25 per run. |
| First run sent only one "set up" message | Expected: the first run loads all existing jobs silently. |
| Website says "Could not load jobs.json" | Opened from disk. Use the Pages URL or `python -m http.server` inside `frontend/`. |
| Scheduled runs stopped | GitHub pauses schedules after 60 days without repo activity; re-enable in the Actions tab. |
| A company feed keeps failing (HTTP 404) | The company changed or left that ATS; remove or fix its slug in `companies.py`. |
| A site scraper returns 0 jobs or fails | The site's layout changed. Update the selectors in `scrapers/india_boards.py` (each parser is a small function). |
