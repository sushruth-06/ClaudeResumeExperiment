"""Tests the DOM-extraction logic against a static local fixture page —
never touches linkedin.com. The fixture approximates LinkedIn's job-search
card/detail markup as of this writing; if real scraping ever returns zero
results, LinkedIn's DOM has likely changed and these selectors (in
jobsearch/sources/linkedin.py) are the first thing to update.
"""
from __future__ import annotations

from playwright.sync_api import sync_playwright

from jobsearch.resume.render import _PINNED_CHROMIUM
from jobsearch.sources.linkedin import parse_job_cards, parse_job_detail

SEARCH_RESULTS_FIXTURE = """
<html><body>
<ul>
  <li data-occludable-job-id="1111">
    <a class="job-card-list__title" href="https://www.linkedin.com/jobs/view/1111">
      <span class="job-card-list__title">Backend Software Engineer</span>
    </a>
    <div class="job-card-container__company-name">Acme Corp</div>
    <div class="job-card-container__metadata-item">Remote</div>
  </li>
  <li data-occludable-job-id="2222">
    <a class="job-card-list__title" href="https://www.linkedin.com/jobs/view/2222">
      <span class="job-card-list__title">Staff Engineer</span>
    </a>
    <div class="job-card-container__company-name">Beta Inc</div>
    <div class="job-card-container__metadata-item">New York, NY</div>
  </li>
</ul>
</body></html>
"""

JOB_DETAIL_FIXTURE = """
<html><body>
<div class="jobs-description__content">
  We are looking for a Backend Software Engineer to join our platform team.
  Requirements: 5+ years Python, distributed systems experience.
</div>
</body></html>
"""


def _page_with_content(browser, html: str):
    page = browser.new_page()
    page.set_content(html)
    return page


def test_parse_job_cards_extracts_all_fields():
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(_PINNED_CHROMIUM))
        page = _page_with_content(browser, SEARCH_RESULTS_FIXTURE)
        cards = parse_job_cards(page)
        browser.close()

    assert len(cards) == 2
    assert cards[0]["job_id"] == "1111"
    assert cards[0]["title"] == "Backend Software Engineer"
    assert cards[0]["company"] == "Acme Corp"
    assert cards[0]["location"] == "Remote"
    assert cards[0]["url"] == "https://www.linkedin.com/jobs/view/1111"

    assert cards[1]["title"] == "Staff Engineer"
    assert cards[1]["company"] == "Beta Inc"


def test_parse_job_cards_handles_missing_fields_gracefully():
    html = '<html><body><ul><li data-occludable-job-id="333"></li></ul></body></html>'
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(_PINNED_CHROMIUM))
        page = _page_with_content(browser, html)
        cards = parse_job_cards(page)
        browser.close()

    assert len(cards) == 1
    assert cards[0]["job_id"] == "333"
    assert cards[0]["title"] == ""
    assert cards[0]["url"] == ""


def test_parse_job_detail_extracts_description():
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(_PINNED_CHROMIUM))
        page = _page_with_content(browser, JOB_DETAIL_FIXTURE)
        description = parse_job_detail(page)
        browser.close()

    assert "Backend Software Engineer" in description
    assert "distributed systems" in description


def test_parse_job_detail_returns_empty_string_when_missing():
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(_PINNED_CHROMIUM))
        page = _page_with_content(browser, "<html><body>nothing here</body></html>")
        description = parse_job_detail(page)
        browser.close()

    assert description == ""
