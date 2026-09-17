"""ATS company list. Each entry becomes its own isolated feed, e.g. "greenhouse:stripe".

How to find a company's slug: open its careers page and look at the job-board URL.
  Greenhouse       boards.greenhouse.io/<slug>  or job-boards.greenhouse.io/<slug>
  Lever            jobs.lever.co/<slug>
  Ashby            jobs.ashbyhq.com/<slug>
  SmartRecruiters  jobs.smartrecruiters.com/<Slug>   (case-sensitive)
  Breezy HR        <slug>.breezy.hr
  Teamtailor       <slug>.teamtailor.com   (use the full host for regional sites,
                                            e.g. "acme.na.teamtailor.com")

Check a new slug quickly:  python main.py --only greenhouse:<slug> --no-notify
A slug that 404s just shows up as a failed feed in the run summary; it doesn't
affect the others.

Every slug below returned open jobs when this list was built (Sept 2026).
Very large boards (thousands of postings) are left out to keep the committed
database small.
"""

COMPANIES: dict[str, list[str]] = {
    "greenhouse": [
        "stripe", "airbnb", "figma", "dropbox", "discord", "cloudflare", "gitlab",
        "reddit", "coinbase", "duolingo", "elastic", "mongodb", "datadog", "okta",
        "twilio", "anthropic", "samsara", "vercel",
        "groww", "druva",                      # India
    ],
    "lever": [
        "palantir", "spotify",
        "cred", "zeta", "paytm", "meesho", "hevodata", "mindtickle", "fampay",  # India
    ],
    "ashby": [
        "notion", "openai", "ramp", "linear", "replit", "supabase", "posthog",
        "cursor", "perplexity",
    ],
    "smartrecruiters": [
        "Freshworks", "Canva", "Wise", "ServiceNow", "Experian",
    ],
    "breezy": [
        "vetsez", "blenderbox", "strategic-systems-international", "seasats",
    ],
    "teamtailor": [
        "career",          # Teamtailor itself (career.teamtailor.com)
        "inforcer", "influencer", "corndel",
    ],
}
