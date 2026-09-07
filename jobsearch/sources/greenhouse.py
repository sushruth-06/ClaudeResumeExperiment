"""Greenhouse public job board API.

No API key required. Docs: https://developers.greenhouse.io/job-board.html
Endpoint: https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true
"""
from __future__ import annotations

import logging
import re

import requests

from jobsearch.models import RawJob

logger = logging.getLogger(__name__)

BASE_URL = "https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs"
TIMEOUT = 15


def _strip_html(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html or "")
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def fetch_jobs(board_token: str, session: requests.Session | None = None) -> list[RawJob]:
    """Fetch all live postings for one Greenhouse board token.

    Raises requests.HTTPError on non-200 (e.g. board_token doesn't exist / no
    longer uses Greenhouse) — callers should catch per-company so one bad
    token doesn't kill the whole run.
    """
    sess = session or requests
    url = BASE_URL.format(board_token=board_token)
    resp = sess.get(url, params={"content": "true"}, timeout=TIMEOUT)
    resp.raise_for_status()
    data = resp.json()

    jobs: list[RawJob] = []
    for item in data.get("jobs", []):
        location = (item.get("location") or {}).get("name", "") or ""
        jobs.append(
            RawJob(
                source="greenhouse",
                external_id=str(item["id"]),
                company=board_token,
                title=item.get("title", ""),
                location=location,
                url=item.get("absolute_url", ""),
                description=_strip_html(item.get("content", "")),
                posted_at=item.get("updated_at"),
                raw=item,
            )
        )
    logger.info("greenhouse:%s fetched %d jobs", board_token, len(jobs))
    return jobs


def fetch_all(board_tokens: list[str]) -> list[RawJob]:
    session = requests.Session()
    session.headers.update({"User-Agent": "jobsearch-bot/0.1 (personal use)"})
    all_jobs: list[RawJob] = []
    for token in board_tokens:
        try:
            all_jobs.extend(fetch_jobs(token, session=session))
        except requests.HTTPError as e:
            logger.warning("greenhouse:%s failed: %s", token, e)
        except requests.RequestException as e:
            logger.warning("greenhouse:%s network error: %s", token, e)
    return all_jobs
