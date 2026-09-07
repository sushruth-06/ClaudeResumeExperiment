"""Tests against fixtures matching JSearch's and Adzuna's documented
response shapes. Live verification needs a real JSEARCH_API_KEY or
ADZUNA_APP_ID/ADZUNA_APP_KEY, which this sandbox doesn't currently have
(and network egress to these hosts is also blocked by policy here).
"""
from __future__ import annotations

import pytest

from jobsearch.sources import aggregator

JSEARCH_FIXTURE = {
    "status": "OK",
    "data": [
        {
            "job_id": "abc123",
            "employer_name": "Acme Corp",
            "job_title": "Backend Software Engineer",
            "job_description": "Build backend systems in Python.",
            "job_apply_link": "https://acme.example.com/jobs/abc123",
            "job_city": "Austin",
            "job_state": "TX",
            "job_country": "US",
            "job_is_remote": False,
            "job_posted_at_datetime_utc": "2026-08-01T00:00:00.000Z",
            "job_min_salary": 130000,
            "job_max_salary": 170000,
            "job_salary_currency": "USD",
        },
        {
            "job_id": "def456",
            "employer_name": "Remote Co",
            "job_title": "Senior Engineer",
            "job_description": "Remote role.",
            "job_apply_link": "https://remoteco.example.com/jobs/def456",
            "job_is_remote": True,
        },
    ],
}

ADZUNA_FIXTURE = {
    "results": [
        {
            "id": "999",
            "title": "Platform Engineer",
            "company": {"display_name": "Beta Inc"},
            "location": {"display_name": "New York, NY"},
            "redirect_url": "https://adzuna.example.com/jobs/999",
            "description": "Work on our platform team.",
            "created": "2026-08-02T00:00:00Z",
            "salary_min": 140000,
            "salary_max": 180000,
        }
    ]
}


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"status {self.status_code}")

    def json(self):
        return self._payload


def test_fetch_jsearch_parses_fixture(monkeypatch):
    def fake_get(url, headers=None, params=None, timeout=None):
        assert url == "https://jsearch.p.rapidapi.com/search"
        assert headers["X-RapidAPI-Key"] == "test-key"
        return FakeResponse(JSEARCH_FIXTURE)

    monkeypatch.setattr("jobsearch.sources.aggregator.requests.get", fake_get)
    jobs = aggregator._fetch_jsearch("backend engineer", "test-key")

    assert len(jobs) == 2
    first = jobs[0]
    assert first.source == "aggregator"
    assert first.company == "Acme Corp"
    assert first.title == "Backend Software Engineer"
    assert first.location == "Austin, TX, US"
    assert first.comp_min == 130000
    assert first.comp_currency == "USD"

    remote_job = jobs[1]
    assert remote_job.location.startswith("Remote")


def test_fetch_adzuna_parses_fixture(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        assert "adzuna.com" in url
        assert params["app_id"] == "id123"
        return FakeResponse(ADZUNA_FIXTURE)

    monkeypatch.setattr("jobsearch.sources.aggregator.requests.get", fake_get)
    jobs = aggregator._fetch_adzuna("platform engineer", "id123", "key456")

    assert len(jobs) == 1
    job = jobs[0]
    assert job.company == "Beta Inc"
    assert job.title == "Platform Engineer"
    assert job.location == "New York, NY"
    assert job.comp_min == 140000


def test_fetch_jobs_prefers_jsearch_when_both_configured(monkeypatch):
    monkeypatch.setenv("JSEARCH_API_KEY", "jkey")
    monkeypatch.setenv("ADZUNA_APP_ID", "aid")
    monkeypatch.setenv("ADZUNA_APP_KEY", "akey")

    calls = []

    def fake_jsearch(query, api_key, num_pages=1):
        calls.append(("jsearch", query))
        return []

    def fake_adzuna(*args, **kwargs):
        calls.append(("adzuna",))
        return []

    monkeypatch.setattr(aggregator, "_fetch_jsearch", fake_jsearch)
    monkeypatch.setattr(aggregator, "_fetch_adzuna", fake_adzuna)

    aggregator.fetch_jobs("backend engineer")
    assert calls == [("jsearch", "backend engineer")]


def test_fetch_jobs_falls_back_to_adzuna(monkeypatch):
    monkeypatch.delenv("JSEARCH_API_KEY", raising=False)
    monkeypatch.setenv("ADZUNA_APP_ID", "aid")
    monkeypatch.setenv("ADZUNA_APP_KEY", "akey")

    calls = []
    monkeypatch.setattr(aggregator, "_fetch_adzuna", lambda *a, **k: calls.append("adzuna") or [])

    aggregator.fetch_jobs("backend engineer")
    assert calls == ["adzuna"]


def test_fetch_jobs_raises_not_configured(monkeypatch):
    monkeypatch.delenv("JSEARCH_API_KEY", raising=False)
    monkeypatch.delenv("ADZUNA_APP_ID", raising=False)
    monkeypatch.delenv("ADZUNA_APP_KEY", raising=False)

    with pytest.raises(aggregator.NotConfigured):
        aggregator.fetch_jobs("backend engineer")
