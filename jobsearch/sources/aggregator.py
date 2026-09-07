"""Aggregator job-search API for broader coverage beyond the direct
Greenhouse/Lever company list. Supports JSearch (via RapidAPI) and Adzuna —
whichever has credentials configured in the environment is used; JSearch
takes priority if both are set.

JSearch: https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch
Adzuna:  https://developer.adzuna.com/
"""
from __future__ import annotations

import logging
import os

import requests

from jobsearch.models import RawJob

logger = logging.getLogger(__name__)

TIMEOUT = 20


class NotConfigured(Exception):
    """Raised when no aggregator API credentials are available."""


def _fetch_jsearch(query: str, api_key: str, num_pages: int = 1) -> list[RawJob]:
    url = "https://jsearch.p.rapidapi.com/search"
    headers = {
        "X-RapidAPI-Key": api_key,
        "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
    }
    params = {"query": query, "page": "1", "num_pages": str(num_pages)}

    resp = requests.get(url, headers=headers, params=params, timeout=TIMEOUT)
    resp.raise_for_status()
    data = resp.json()

    jobs = []
    for item in data.get("data", []):
        location_parts = [
            p for p in (item.get("job_city"), item.get("job_state"), item.get("job_country")) if p
        ]
        location = ", ".join(location_parts)
        if item.get("job_is_remote"):
            location = f"Remote{' - ' + location if location else ''}"

        jobs.append(
            RawJob(
                source="aggregator",
                external_id=item.get("job_id", ""),
                company=item.get("employer_name", "") or "",
                title=item.get("job_title", "") or "",
                location=location,
                url=item.get("job_apply_link", "") or item.get("job_google_link", "") or "",
                description=item.get("job_description", "") or "",
                posted_at=item.get("job_posted_at_datetime_utc"),
                comp_min=item.get("job_min_salary"),
                comp_max=item.get("job_max_salary"),
                comp_currency=item.get("job_salary_currency"),
                raw=item,
            )
        )
    logger.info("aggregator(jsearch):%r fetched %d jobs", query, len(jobs))
    return jobs


def _fetch_adzuna(
    query: str, app_id: str, app_key: str, country: str = "us", location: str = ""
) -> list[RawJob]:
    url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/1"
    params = {
        "app_id": app_id,
        "app_key": app_key,
        "what": query,
        "content-type": "application/json",
    }
    if location:
        params["where"] = location

    resp = requests.get(url, params=params, timeout=TIMEOUT)
    resp.raise_for_status()
    data = resp.json()

    jobs = []
    for item in data.get("results", []):
        company = (item.get("company") or {}).get("display_name", "") or ""
        loc = (item.get("location") or {}).get("display_name", "") or ""
        jobs.append(
            RawJob(
                source="aggregator",
                external_id=str(item.get("id", "")),
                company=company,
                title=item.get("title", "") or "",
                location=loc,
                url=item.get("redirect_url", "") or "",
                description=item.get("description", "") or "",
                posted_at=item.get("created"),
                comp_min=item.get("salary_min"),
                comp_max=item.get("salary_max"),
                comp_currency="USD" if country == "us" else None,
                raw=item,
            )
        )
    logger.info("aggregator(adzuna):%r fetched %d jobs", query, len(jobs))
    return jobs


def fetch_jobs(query: str, location: str = "") -> list[RawJob]:
    """Fetch jobs matching `query` from whichever aggregator is configured.

    Raises NotConfigured if neither JSEARCH_API_KEY nor
    ADZUNA_APP_ID/ADZUNA_APP_KEY are set.
    """
    jsearch_key = os.environ.get("JSEARCH_API_KEY")
    adzuna_id = os.environ.get("ADZUNA_APP_ID")
    adzuna_key = os.environ.get("ADZUNA_APP_KEY")

    if jsearch_key:
        full_query = f"{query} in {location}" if location else query
        return _fetch_jsearch(full_query, jsearch_key)
    if adzuna_id and adzuna_key:
        return _fetch_adzuna(query, adzuna_id, adzuna_key, location=location)

    raise NotConfigured(
        "No aggregator API configured. Set JSEARCH_API_KEY or "
        "ADZUNA_APP_ID + ADZUNA_APP_KEY in .env."
    )


def fetch_all(queries: list[str], location: str = "") -> list[RawJob]:
    all_jobs: list[RawJob] = []
    for query in queries:
        try:
            all_jobs.extend(fetch_jobs(query, location=location))
        except NotConfigured:
            raise
        except requests.RequestException as e:
            logger.warning("aggregator query %r failed: %s", query, e)
    return all_jobs
