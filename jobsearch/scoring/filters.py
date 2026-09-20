"""Deterministic pass: cheap regex/keyword/comp checks that run before any LLM call.

Purpose is twofold: cut LLM spend by dropping obvious non-matches, and give a
human-readable reason for every rejection so the digest/debugging story is clear.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from jobsearch.config import Criteria
from jobsearch.date_utils import hours_since
from jobsearch.models import RawJob

REMOTE_LOCATION_PATTERN = re.compile(r"\bremote\b", re.IGNORECASE)


@dataclass
class FilterResult:
    passed: bool
    reason: str


def _title_matches(title: str, patterns: list[str]) -> bool:
    if not patterns:
        return True
    return any(re.search(p, title, re.IGNORECASE) for p in patterns)


def _title_excluded(title: str, patterns: list[str]) -> str | None:
    for p in patterns:
        if re.search(p, title, re.IGNORECASE):
            return p
    return None


def _location_matches(location: str, wanted: list[str]) -> bool:
    if not wanted:
        return True
    location_lower = (location or "").lower()
    for w in wanted:
        if w.lower() == "remote":
            if REMOTE_LOCATION_PATTERN.search(location_lower):
                return True
        elif w.lower() in location_lower:
            return True
    return False


def _keyword_excluded(description: str, keywords: list[str]) -> str | None:
    desc_lower = (description or "").lower()
    for kw in keywords:
        if kw.lower() in desc_lower:
            return kw
    return None


def _is_fresh_enough(job: RawJob, max_age_hours: int | None) -> tuple[bool, str]:
    if max_age_hours is None:
        return True, ""
    age = hours_since(job.posted_at)
    if age is None:
        # Can't confirm freshness -> fail closed rather than risk surfacing
        # a stale repost when the whole point is "only today's new postings".
        return False, "posted_at missing/unparseable, can't confirm freshness"
    if age > max_age_hours:
        return False, f"posted {age:.1f}h ago, exceeds max_posting_age_hours={max_age_hours}"
    return True, ""


def _comp_floor_met(job: RawJob, min_comp_usd: int | None) -> bool:
    if min_comp_usd is None:
        return True
    if job.comp_max is not None:
        return job.comp_max >= min_comp_usd
    if job.comp_min is not None:
        return job.comp_min >= min_comp_usd
    # No comp data posted at all -> don't penalize; let it through to the LLM
    # pass rather than silently dropping postings that just don't disclose comp.
    return True


def evaluate(job: RawJob, criteria: Criteria) -> FilterResult:
    """Run all deterministic checks. Short-circuits on the first failure."""
    excluded_pattern = _title_excluded(job.title, criteria.dealbreakers.titles_exclude)
    if excluded_pattern:
        return FilterResult(False, f"title matched exclude pattern: {excluded_pattern!r}")

    if not _title_matches(job.title, criteria.target_titles):
        return FilterResult(False, "title did not match any target_titles pattern")

    if not _location_matches(job.location, criteria.locations):
        return FilterResult(False, f"location {job.location!r} not in allowed locations")

    excluded_kw = _keyword_excluded(job.description, criteria.dealbreakers.keywords_exclude)
    if excluded_kw:
        return FilterResult(False, f"description contains excluded keyword: {excluded_kw!r}")

    if not _comp_floor_met(job, criteria.dealbreakers.min_comp_usd):
        return FilterResult(False, f"comp below floor of {criteria.dealbreakers.min_comp_usd}")

    fresh, fresh_reason = _is_fresh_enough(job, criteria.max_posting_age_hours)
    if not fresh:
        return FilterResult(False, fresh_reason)

    return FilterResult(True, "passed all deterministic checks")
