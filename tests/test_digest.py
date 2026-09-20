from __future__ import annotations

from jobsearch import db
from jobsearch.digest.build import build_digest_entries, render_digest_html
from jobsearch.digest.deliver import write_html_file
from jobsearch.models import RawJob


def seed(conn, source, external_id, title, company, fit_score):
    job = RawJob(
        source=source,
        external_id=external_id,
        company=company,
        title=title,
        location="Remote",
        url=f"https://example.com/{source}/{external_id}",
        description="desc",
    )
    job_id, _ = db.upsert_job(conn, job)
    db.save_score(
        conn,
        job_id,
        passed_deterministic=True,
        deterministic_reason="ok",
        llm_fit_score=fit_score,
        llm_reasoning=f"Great fit for {title}.",
        llm_seniority_assessment="Matches level.",
        llm_role_authenticity="Genuinely the role it claims to be.",
    )
    return job_id


def test_build_digest_entries_orders_by_score_desc(tmp_path):
    db_path = tmp_path / "t.db"
    db.init_db(db_path)
    with db.get_conn(db_path) as conn:
        seed(conn, "greenhouse", "1", "Backend Engineer", "Acme", 70)
        seed(conn, "lever", "2", "Staff Engineer", "Beta", 95)
        seed(conn, "greenhouse", "3", "Junior Engineer", "Gamma", 40)  # below threshold

        entries = build_digest_entries(conn, min_fit_score=65, limit=20)

    assert [e.company for e in entries] == ["Beta", "Acme"]
    assert entries[0].llm_fit_score == 95


def test_render_digest_html_real_template_and_write_file(tmp_path):
    db_path = tmp_path / "t.db"
    db.init_db(db_path)
    with db.get_conn(db_path) as conn:
        seed(conn, "greenhouse", "1", "Backend Engineer", "Acme", 88)
        entries = build_digest_entries(conn, min_fit_score=65, limit=20)

    html = render_digest_html(entries, run_date="2026-09-07")
    assert "Backend Engineer" in html
    assert "Acme" in html
    assert "88/100" in html
    assert "Great fit for Backend Engineer." in html
    assert "Genuinely the role it claims to be." in html
    assert "https://example.com/greenhouse/1" in html

    out = write_html_file(html, tmp_path / "digest.html")
    assert out.exists()
    assert "Backend Engineer" in out.read_text()


def test_render_digest_html_handles_empty_shortlist():
    html = render_digest_html([], run_date="2026-09-07")
    assert "No matches" in html


def test_digest_excludes_jobs_below_threshold_and_duplicates(tmp_path):
    db_path = tmp_path / "t.db"
    db.init_db(db_path)
    with db.get_conn(db_path) as conn:
        canonical_id = seed(conn, "greenhouse", "1", "Backend Engineer", "Acme", 90)
        dup_id = seed(conn, "lever", "2", "Backend Engineer", "Acme", 92)
        db.mark_duplicate(conn, dup_id, canonical_id)
        seed(conn, "greenhouse", "3", "Low Fit Role", "Acme", 30)

        entries = build_digest_entries(conn, min_fit_score=65, limit=20)

    assert len(entries) == 1
    assert entries[0].job_id == canonical_id
