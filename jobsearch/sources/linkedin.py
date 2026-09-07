"""LinkedIn job-search scraping via Playwright, using a persistent logged-in
browser profile.

THIS IS AGAINST LINKEDIN'S TOS AND CARRIES ACCOUNT-RESTRICTION RISK.
Treated as the most fragile/replaceable source, off by default
(criteria.yaml linkedin.enabled: false), and built conservatively:

- Uses a persistent browser profile (data/.linkedin-profile) so you log in
  manually ONE time, in a real (non-headless) browser window; the session
  cookie is then reused across runs instead of re-authenticating.
- Randomized delays between every navigation/scroll action
  (linkedin.min_delay_seconds..max_delay_seconds in criteria.yaml).
- Caps how many postings it will pull per run (linkedin.max_results_per_run).
- No parallelism, no headless-detection evasion, no automated login. If
  LinkedIn challenges the session (captcha, checkpoint), this bails out
  rather than trying to push through.

CSS selectors below are best-effort based on LinkedIn's current jobs-search
DOM structure as of this writing. LinkedIn changes its markup often without
notice — if this source silently returns zero results, the selectors are
the first thing to check (see `parse_job_cards`/`parse_job_detail`, which
are unit-testable in isolation against saved fixture HTML).
"""
from __future__ import annotations

import logging
import random
import time
from pathlib import Path

from playwright.sync_api import Page

from jobsearch.config import DATA_DIR
from jobsearch.models import RawJob

logger = logging.getLogger(__name__)

PROFILE_DIR = DATA_DIR / ".linkedin-profile"

_PINNED_CHROMIUM = "/opt/pw-browsers/chromium"


def _sleep(min_s: float, max_s: float) -> None:
    time.sleep(random.uniform(min_s, max_s))


def parse_job_cards(page: Page) -> list[dict]:
    """Extract (title, company, location, url) for each visible job card on
    a LinkedIn job-search results page. Pure DOM extraction, no navigation —
    testable against a static fixture page.
    """
    cards = []
    for card in page.query_selector_all("li[data-occludable-job-id]"):
        job_id = card.get_attribute("data-occludable-job-id") or ""
        title_el = card.query_selector(".job-card-list__title, .base-search-card__title")
        company_el = card.query_selector(".job-card-container__company-name, .base-search-card__subtitle")
        location_el = card.query_selector(".job-card-container__metadata-item, .job-search-card__location")
        link_el = card.query_selector("a.job-card-list__title, a.base-card__full-link")

        cards.append(
            {
                "job_id": job_id,
                "title": (title_el.inner_text().strip() if title_el else ""),
                "company": (company_el.inner_text().strip() if company_el else ""),
                "location": (location_el.inner_text().strip() if location_el else ""),
                "url": (link_el.get_attribute("href") if link_el else "") or "",
            }
        )
    return cards


def parse_job_detail(page: Page) -> str:
    """Extract the full job description from a job detail pane/page."""
    el = page.query_selector(".jobs-description__content, .description__text")
    return el.inner_text().strip() if el else ""


def fetch_jobs(search_url: str, max_results: int, min_delay: float, max_delay: float) -> list[RawJob]:
    """Navigate to `search_url` in a persistent logged-in profile and scrape
    up to `max_results` postings with human-scale randomized delays.

    Requires a one-time manual login: run
        python -m playwright ... (see README)
    or just call this once with headless disabled so the login prompt is
    visible, then subsequent runs reuse the saved session.
    """
    from playwright.sync_api import sync_playwright

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    jobs: list[RawJob] = []

    with sync_playwright() as p:
        launch_kwargs = {"headless": True, "user_data_dir": str(PROFILE_DIR)}
        if Path(_PINNED_CHROMIUM).exists():
            launch_kwargs["executable_path"] = _PINNED_CHROMIUM

        context = p.chromium.launch_persistent_context(**launch_kwargs)
        page = context.new_page()

        try:
            page.goto(search_url, wait_until="domcontentloaded")
            _sleep(min_delay, max_delay)

            if "login" in page.url or "checkpoint" in page.url:
                logger.error(
                    "LinkedIn redirected to login/checkpoint — session isn't logged in "
                    "or was challenged. Run with a visible browser once to log in manually."
                )
                return []

            cards = parse_job_cards(page)[:max_results]
            for card in cards:
                if not card["url"]:
                    continue
                _sleep(min_delay, max_delay)
                detail_page = context.new_page()
                try:
                    detail_page.goto(card["url"], wait_until="domcontentloaded")
                    _sleep(min_delay * 0.5, max_delay * 0.5)
                    description = parse_job_detail(detail_page)
                finally:
                    detail_page.close()

                jobs.append(
                    RawJob(
                        source="linkedin",
                        external_id=card["job_id"] or card["url"],
                        company=card["company"],
                        title=card["title"],
                        location=card["location"],
                        url=card["url"],
                        description=description,
                    )
                )
        finally:
            context.close()

    logger.info("linkedin: fetched %d jobs", len(jobs))
    return jobs
