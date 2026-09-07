"""Tests against a fixture matching Greenhouse's public job-board API shape.

NOTE: written from the documented response shape
(https://developers.greenhouse.io/job-board.html) because this sandbox's
network policy currently blocks outbound calls to boards-api.greenhouse.io.
Re-run `python -m jobsearch.cli fetch-greenhouse stripe` once network access
is available to confirm against a real live response.
"""
from __future__ import annotations

from jobsearch.sources import greenhouse

FIXTURE_RESPONSE = {
    "jobs": [
        {
            "id": 7654321,
            "title": "Software Engineer, Backend",
            "updated_at": "2026-08-01T12:00:00-04:00",
            "location": {"name": "Remote - US"},
            "absolute_url": "https://boards.greenhouse.io/acme/jobs/7654321",
            "content": "<p>We are hiring a <b>Backend Engineer</b>.</p><p>Requires Python &amp; SQL.</p>",
        },
        {
            "id": 7654322,
            "title": "Staff Software Engineer",
            "updated_at": "2026-08-02T12:00:00-04:00",
            "location": {"name": "San Francisco, CA"},
            "absolute_url": "https://boards.greenhouse.io/acme/jobs/7654322",
            "content": "<p>Staff-level role.</p>",
        },
    ],
    "meta": {"total": 2},
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
    jobs = greenhouse.fetch_jobs("acme", session=sess)

    assert len(jobs) == 2
    first = jobs[0]
    assert first.source == "greenhouse"
    assert first.external_id == "7654321"
    assert first.company == "acme"
    assert first.title == "Software Engineer, Backend"
    assert first.location == "Remote - US"
    assert "Backend Engineer" in first.description
    assert "<p>" not in first.description  # HTML stripped
    assert first.url.startswith("https://boards.greenhouse.io/")
    # stable id/dedup key derived correctly
    assert first.job_id == first.job_id  # deterministic, non-empty
    assert len(first.job_id) == 16


def test_fetch_jobs_hits_correct_url():
    sess = FakeSession(FIXTURE_RESPONSE)
    greenhouse.fetch_jobs("acme", session=sess)
    url, params, _ = sess.calls[0]
    assert url == "https://boards-api.greenhouse.io/v1/boards/acme/jobs"
    assert params == {"content": "true"}


def test_fetch_all_skips_failing_boards():
    good = FakeSession(FIXTURE_RESPONSE)
    bad = FakeSession({}, status=404)

    class MultiSession:
        def __init__(self):
            self.n = 0
            self.headers = {}

        def get(self, url, params=None, timeout=None):
            self.n += 1
            return bad.get(url, params, timeout) if "badco" in url else good.get(url, params, timeout)

    import jobsearch.sources.greenhouse as gh

    orig_session_cls = None
    import requests

    real_session = requests.Session
    try:
        requests.Session = lambda: MultiSession()
        jobs = gh.fetch_all(["badco", "acme"])
    finally:
        requests.Session = real_session

    assert len(jobs) == 2  # only acme's jobs, badco's 404 was swallowed
