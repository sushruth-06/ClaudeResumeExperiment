"""End-to-end dedup test: the same posting seen from two different sources
(Greenhouse + Lever, say) should collapse to one canonical job."""
from __future__ import annotations

from jobsearch import db
from jobsearch.models import RawJob


def make_job(source: str, external_id: str, title="Backend Engineer", company="Acme") -> RawJob:
    return RawJob(
        source=source,
        external_id=external_id,
        company=company,
        title=title,
        location="Remote",
        url=f"https://example.com/{source}/{external_id}",
        description="desc",
    )


def ingest(conn, job: RawJob) -> str:
    canonical = db.find_by_dedup_key(conn, job.dedup_key, job.job_id)
    job_id, _ = db.upsert_job(conn, job)
    if canonical:
        db.mark_duplicate(conn, job_id, canonical)
    return job_id


def test_same_posting_across_sources_is_deduped(tmp_path):
    db_path = tmp_path / "test.db"
    db.init_db(db_path)

    with db.get_conn(db_path) as conn:
        gh_job = make_job("greenhouse", "111")
        lever_job = make_job("lever", "222")  # same company/title, different source+id

        gh_id = ingest(conn, gh_job)
        lever_id = ingest(conn, lever_job)

        assert gh_id != lever_id  # distinct rows...

        gh_row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (gh_id,)).fetchone()
        lever_row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (lever_id,)).fetchone()

        # ...but the second one seen is marked as a duplicate of the first
        assert gh_row["is_duplicate_of"] is None
        assert lever_row["is_duplicate_of"] == gh_id


def test_different_postings_are_not_deduped(tmp_path):
    db_path = tmp_path / "test.db"
    db.init_db(db_path)

    with db.get_conn(db_path) as conn:
        job_a = make_job("greenhouse", "111", title="Backend Engineer", company="Acme")
        job_b = make_job("greenhouse", "222", title="Frontend Engineer", company="Acme")

        id_a = ingest(conn, job_a)
        id_b = ingest(conn, job_b)

        row_a = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (id_a,)).fetchone()
        row_b = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (id_b,)).fetchone()
        assert row_a["is_duplicate_of"] is None
        assert row_b["is_duplicate_of"] is None


def test_refetching_same_source_job_updates_last_seen_not_duplicate(tmp_path):
    db_path = tmp_path / "test.db"
    db.init_db(db_path)

    with db.get_conn(db_path) as conn:
        job = make_job("greenhouse", "111")
        id1 = ingest(conn, job)
        id2 = ingest(conn, job)  # same source+external_id -> same job_id, not a dup
        assert id1 == id2
        row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (id1,)).fetchone()
        assert row["is_duplicate_of"] is None


def test_shortlisted_jobs_excludes_duplicates(tmp_path):
    db_path = tmp_path / "test.db"
    db.init_db(db_path)

    with db.get_conn(db_path) as conn:
        gh_job = make_job("greenhouse", "111")
        lever_job = make_job("lever", "222")
        gh_id = ingest(conn, gh_job)
        lever_id = ingest(conn, lever_job)

        db.save_score(conn, gh_id, passed_deterministic=True, deterministic_reason="ok", llm_fit_score=90)
        db.save_score(conn, lever_id, passed_deterministic=True, deterministic_reason="ok", llm_fit_score=95)

        shortlisted = db.shortlisted_jobs(conn, min_fit_score=50, limit=10)
        ids = [r["job_id"] for r in shortlisted]
        assert gh_id in ids
        assert lever_id not in ids  # excluded as a duplicate despite a higher score
