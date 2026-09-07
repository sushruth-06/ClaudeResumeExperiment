# jobsearch

Agentic daily job-search pipeline: source postings from Greenhouse, Lever, an
aggregator API, and (optionally) LinkedIn; score and dedupe them against your
resume; tailor a resume PDF for each strong match; deliver a morning digest.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # then fill in the keys you have
```

Playwright is used for PDF rendering and (optionally) LinkedIn scraping. If
your machine doesn't already have a Chromium build Playwright can find, run
`python -m playwright install chromium`.

## One-time setup

1. **Base resume** — convert it to structured JSON once:
   ```bash
   jobsearch parse-resume /path/to/your_resume.pdf
   ```
   Requires `ANTHROPIC_API_KEY` in `.env`. Output goes to
   `data/resume/base_resume.json`; edit it by hand any time if the LLM
   parse needs a correction — every later step reads from that file, not
   your original resume.

2. **Criteria** — edit `data/criteria.yaml`: target titles, seniority,
   locations, dealbreakers, min fit score, digest size.

3. **Companies** (for the Greenhouse/Lever direct source) — edit
   `data/companies.yaml` with your target company list. Not every company
   uses Greenhouse or Lever; check their `/jobs` page URL. The aggregator
   source below is meant to catch everything else.

4. **Aggregator API** (optional, broader coverage) — set either
   `JSEARCH_API_KEY` (RapidAPI) or `ADZUNA_APP_ID`+`ADZUNA_APP_KEY` in
   `.env`.

5. **LinkedIn** (optional, off by default — see risk note below) — set
   `linkedin.enabled: true` and `linkedin.search_url` in `criteria.yaml`,
   then run `jobsearch fetch-linkedin` once with a visible (non-headless)
   browser to log in manually; the session persists in
   `data/.linkedin-profile` after that.

6. **Delivery** (optional beyond the local HTML file, which always
   happens) — set `SMTP_*`/`DIGEST_EMAIL_*` for email, or
   `SLACK_WEBHOOK_URL` for Slack, in `.env`.

## Running

```bash
jobsearch run-all      # fetch all sources -> score -> tailor -> digest
jobsearch stats        # row counts, quick sanity check
```

Or run stages individually — useful for debugging one source/step:

```bash
jobsearch fetch-greenhouse [board_token ...]   # defaults to companies.yaml
jobsearch fetch-lever [site_id ...]
jobsearch fetch-aggregator [query ...] [--location ...]
jobsearch fetch-linkedin
jobsearch score [--limit N]
jobsearch tailor <job_id>
jobsearch digest
```

## Scheduling (runs every morning, unattended)

```bash
./jobsearch/scheduler/install_cron.sh
```

Installs a cron entry for 7:00am local time that runs
`jobsearch/scheduler/run_daily.sh` (activates the venv, runs `run-all`,
logs to `data/logs/`). On macOS, `launchd` is more reliable across
sleep/wake than cron — see
`jobsearch/scheduler/com.jobsearch.dailyrun.plist.example`.

## Architecture

```
jobsearch/
  sources/       greenhouse.py, lever.py, aggregator.py, linkedin.py
  scoring/       filters.py (deterministic), llm_score.py (LLM judgment)
  resume/        schema.py, parser.py, tailor.py, render.py
  digest/        build.py, deliver.py
  scheduler/     run_daily.sh, install_cron.sh, launchd plist
  db.py          SQLite: jobs, scores, resumes, application_status, digest_runs
  cli.py         entry points (see `jobsearch --help`)
data/
  criteria.yaml, companies.yaml, resume/base_resume.json, jobsearch.db (gitignored)
  output/resumes/*.pdf, output/digests/*.html (gitignored)
templates/
  resume.html.jinja, digest.html.jinja
```

Every job is deduped across sources by a normalized `(company, title)` key
(see `jobsearch/models.py::RawJob.dedup_key`), and jobs already digested are
excluded from future shortlists so the same posting doesn't resurface daily.

## LinkedIn scraping — risk note

`jobsearch/sources/linkedin.py` scrapes LinkedIn's job-search results using
your own logged-in session. **This is against LinkedIn's Terms of Service**
and carries a real risk of account restriction. It's disabled by default,
built conservatively (randomized delays, no automated login, small per-run
caps, bails out on any login/checkpoint challenge), and is the one source
not verified against the live site in development — its CSS selectors are
best-effort and may need adjusting after your first real login. Treat it as
optional and easily disabled if it becomes unreliable.

## Tests

```bash
pytest tests/ -v
```

Fixtures for Greenhouse/Lever/JSearch/Adzuna are built from each provider's
documented response shape (this development sandbox's network policy blocks
outbound calls to those hosts) — re-run the corresponding `jobsearch fetch-*`
command against real data once you have network access and API keys to
confirm parsing still matches.
