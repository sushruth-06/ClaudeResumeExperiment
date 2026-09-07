"""Tests against a fixture matching Lever's public postings API shape.

NOTE: written from the documented response shape
(https://github.com/lever/postings-api) because this sandbox's network
policy currently blocks outbound calls to api.lever.co. Re-run
`python -m jobsearch.cli fetch-lever netflix` once network access is
available to confirm against a real live response.
"""
from __future__ import annotations

from jobsearch.sources import lever

FIXTURE_RESPONSE = [
    {
        "id": "abcd-1234-efgh",
        "text": "Senior Backend Engineer",
        "categories": {
            "commitment": "Full-time",
            "department": "Engineering",
            "location": "Remote - US",
            "team": "Platform",
        },
        "createdAt": 1735689600000,
        "hostedUrl": "https://jobs.lever.co/acme/abcd-1234-efgh",
        "descriptionPlain": "Build our platform backend.",
        "lists": [
            {"text": "Requirements", "content": "<ul><li>5+ years Python</li></ul>"}
        ],
        "salaryRange": {"min": 160000, "max": 210000, "currency": "USD"},
    }
]


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


class FakeSession:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params, timeout))
        return FakeResponse(self.payload, self.status)


def test_fetch_jobs_parses_fixture():
    sess = FakeSession(FIXTURE_RESPONSE)
    jobs = lever.fetch_jobs("acme", session=sess)

    assert len(jobs) == 1
    job = jobs[0]
    assert job.source == "lever"
    assert job.external_id == "abcd-1234-efgh"
    assert job.company == "acme"
    assert job.title == "Senior Backend Engineer"
    assert job.location == "Remote - US"
    assert "Build our platform backend" in job.description
    assert "5+ years Python" in job.description
    assert job.comp_min == 160000
    assert job.comp_max == 210000
    assert job.comp_currency == "USD"


def test_fetch_jobs_hits_correct_url():
    sess = FakeSession(FIXTURE_RESPONSE)
    lever.fetch_jobs("acme", session=sess)
    url, params, _ = sess.calls[0]
    assert url == "https://api.lever.co/v0/postings/acme"
    assert params == {"mode": "json"}
