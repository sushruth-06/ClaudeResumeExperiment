"""Lever public postings API.

No API key required. Docs: https://github.com/lever/postings-api
Endpoint: https://api.lever.co/v0/postings/{site_id}?mode=json
"""
from __future__ import annotations

import logging
import re

import requests

from jobsearch.models import RawJob

logger = logging.getLogger(__name__)

BASE_URL = "https://api.lever.co/v0/postings/{site_id}"
TIMEOUT = 15


def _strip_html(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html or "")
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def fetch_jobs(site_id: str, session: requests.Session | None = None) -> list[RawJob]:
    """Fetch all live postings for one Lever site id.

    Raises requests.HTTPError on non-200 — callers should catch per-company.
    """
    sess = session or requests
    url = BASE_URL.format(site_id=site_id)
    resp = sess.get(url, params={"mode": "json"}, timeout=TIMEOUT)
    resp.raise_for_status()
    data = resp.json()

    jobs: list[RawJob] = []
    for item in data:
        categories = item.get("categories", {}) or {}
        location = categories.get("location", "") or ""
        description_parts = [
            item.get("descriptionPlain", "") or _strip_html(item.get("description", "")),
        ]
        for list_section in item.get("lists", []) or []:
            description_parts.append(list_section.get("text", ""))
            content = list_section.get("content", "")
            description_parts.append(_strip_html(content))
        salary = item.get("salaryRange") or {}
        jobs.append(
            RawJob(
                source="lever",
                external_id=item.get("id", ""),
                company=site_id,
                title=item.get("text", ""),
                location=location,
                url=item.get("hostedUrl", ""),
                description="\n".join(p for p in description_parts if p),
                posted_at=str(item.get("createdAt", "")) or None,
                comp_min=salary.get("min"),
                comp_max=salary.get("max"),
                comp_currency=salary.get("currency"),
                raw=item,
            )
        )
    logger.info("lever:%s fetched %d jobs", site_id, len(jobs))
    return jobs


def fetch_all(site_ids: list[str]) -> list[RawJob]:
    session = requests.Session()
    session.headers.update({"User-Agent": "jobsearch-bot/0.1 (personal use)"})
    all_jobs: list[RawJob] = []
    for site_id in site_ids:
        try:
            all_jobs.extend(fetch_jobs(site_id, session=session))
        except requests.HTTPError as e:
            logger.warning("lever:%s failed: %s", site_id, e)
        except requests.RequestException as e:
            logger.warning("lever:%s network error: %s", site_id, e)
    return all_jobs
