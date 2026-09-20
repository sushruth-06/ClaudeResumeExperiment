from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from jobsearch import db
from jobsearch.models import RawJob


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(db.SCHEMA)
    return conn


def add_scored_job(conn: sqlite3.Connection, external_id: str, posted_at: str, fit_score: int) -> str:
    job = RawJob(
        source="greenhouse",
        external_id=external_id,
        company="Acme",
        title="Data Analyst",
        location="Remote",
        url=f"https://example.com/{external_id}",
        description="desc",
        posted_at=posted_at,
    )
    job_id, _ = db.upsert_job(conn, job)
    db.save_score(conn, job_id, True, "ok", llm_fit_score=fit_score)
    return job_id


def test_shortlisted_jobs_excludes_stale_rows_when_freshness_set():
    conn = make_conn()
    now = datetime.now(timezone.utc)
    fresh_id = add_scored_job(conn, "fresh", (now - timedelta(hours=2)).isoformat(), 80)
    stale_id = add_scored_job(conn, "stale", (now - timedelta(days=10)).isoformat(), 90)

    rows = db.shortlisted_jobs(conn, min_fit_score=0, limit=10, max_posting_age_hours=24)

    ids = [r["job_id"] for r in rows]
    assert fresh_id in ids
    assert stale_id not in ids


def test_shortlisted_jobs_includes_stale_rows_when_no_freshness_filter():
    conn = make_conn()
    now = datetime.now(timezone.utc)
    stale_id = add_scored_job(conn, "stale", (now - timedelta(days=10)).isoformat(), 90)

    rows = db.shortlisted_jobs(conn, min_fit_score=0, limit=10, max_posting_age_hours=None)

    assert stale_id in [r["job_id"] for r in rows]


def test_shortlisted_jobs_excludes_unparseable_posted_at_when_freshness_set():
    conn = make_conn()
    unparseable_id = add_scored_job(conn, "bad-date", "not-a-date", 90)

    rows = db.shortlisted_jobs(conn, min_fit_score=0, limit=10, max_posting_age_hours=24)

    assert unparseable_id not in [r["job_id"] for r in rows]


def test_shortlisted_jobs_respects_limit_after_freshness_filtering():
    conn = make_conn()
    now = datetime.now(timezone.utc)
    for i in range(3):
        add_scored_job(conn, f"fresh-{i}", (now - timedelta(hours=1)).isoformat(), 80 + i)

    rows = db.shortlisted_jobs(conn, min_fit_score=0, limit=2, max_posting_age_hours=24)

    assert len(rows) == 2
    # highest fit score first
    assert rows[0]["llm_fit_score"] == 82
