from __future__ import annotations

from jobsearch.config import Criteria, Dealbreakers
from jobsearch.models import RawJob
from jobsearch.scoring import filters


def make_job(**overrides) -> RawJob:
    defaults = dict(
        source="greenhouse",
        external_id="1",
        company="acme",
        title="Backend Software Engineer",
        location="Remote - US",
        url="https://example.com/1",
        description="Build things with Python.",
    )
    defaults.update(overrides)
    return RawJob(**defaults)


def make_criteria(**overrides) -> Criteria:
    defaults = dict(
        target_titles=["software engineer", "backend engineer"],
        locations=["remote"],
        dealbreakers=Dealbreakers(),
    )
    defaults.update(overrides)
    return Criteria(**defaults)


def test_passes_when_everything_matches():
    result = filters.evaluate(make_job(), make_criteria())
    assert result.passed


def test_fails_on_title_mismatch():
    job = make_job(title="Product Manager")
    result = filters.evaluate(job, make_criteria())
    assert not result.passed
    assert "title" in result.reason


def test_fails_on_title_exclude_pattern():
    job = make_job(title="Staff Software Engineer III")
    criteria = make_criteria(
        dealbreakers=Dealbreakers(titles_exclude=["staff.*(iii|iv)"])
    )
    result = filters.evaluate(job, criteria)
    assert not result.passed
    assert "exclude pattern" in result.reason


def test_fails_on_location_mismatch():
    job = make_job(location="London, UK")
    result = filters.evaluate(job, make_criteria(locations=["remote", "New York"]))
    assert not result.passed
    assert "location" in result.reason


def test_location_matches_named_city():
    job = make_job(location="New York, NY")
    result = filters.evaluate(job, make_criteria(locations=["remote", "New York"]))
    assert result.passed


def test_empty_locations_means_anywhere():
    job = make_job(location="Antarctica")
    result = filters.evaluate(job, make_criteria(locations=[]))
    assert result.passed


def test_fails_on_excluded_keyword():
    job = make_job(description="This role requires being an unpaid intern first.")
    criteria = make_criteria(
        dealbreakers=Dealbreakers(keywords_exclude=["unpaid intern"])
    )
    result = filters.evaluate(job, criteria)
    assert not result.passed
    assert "keyword" in result.reason


def test_comp_floor_enforced_when_comp_known():
    job = make_job(comp_min=80000, comp_max=100000)
    criteria = make_criteria(dealbreakers=Dealbreakers(min_comp_usd=150000))
    result = filters.evaluate(job, criteria)
    assert not result.passed
    assert "comp" in result.reason


def test_comp_floor_passes_when_max_meets_it():
    job = make_job(comp_min=140000, comp_max=180000)
    criteria = make_criteria(dealbreakers=Dealbreakers(min_comp_usd=150000))
    result = filters.evaluate(job, criteria)
    assert result.passed


def test_comp_floor_ignored_when_no_comp_disclosed():
    job = make_job(comp_min=None, comp_max=None)
    criteria = make_criteria(dealbreakers=Dealbreakers(min_comp_usd=150000))
    result = filters.evaluate(job, criteria)
    assert result.passed


def test_default_criteria_is_permissive():
    job = make_job(title="Literally Anything", location="Nowhere")
    result = filters.evaluate(job, Criteria())
    assert result.passed
