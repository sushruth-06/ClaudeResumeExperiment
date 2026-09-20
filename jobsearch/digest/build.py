"""Assemble the morning digest: pull the shortlist from SQLite, attach each
job's tailored-resume path, and render to HTML.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import date, timezone, datetime

from jinja2 import Environment, FileSystemLoader

from jobsearch.config import TEMPLATE_DIR

_env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), autoescape=True)


@dataclass
class DigestEntry:
    job_id: str
    source: str
    company: str
    title: str
    location: str
    url: str
    llm_fit_score: int
    llm_reasoning: str
    llm_seniority_assessment: str
    llm_role_authenticity: str
    resume_pdf_path: str | None = None


def build_digest_entries(
    conn: sqlite3.Connection,
    min_fit_score: int,
    limit: int,
    max_posting_age_hours: int | None = None,
) -> list[DigestEntry]:
    from jobsearch import db

    rows = db.shortlisted_jobs(conn, min_fit_score, limit, max_posting_age_hours)
    entries = []
    for row in rows:
        resume_row = conn.execute(
            "SELECT pdf_path FROM resumes WHERE job_id = ?", (row["job_id"],)
        ).fetchone()
        entries.append(
            DigestEntry(
                job_id=row["job_id"],
                source=row["source"],
                company=row["company"],
                title=row["title"],
                location=row["location"] or "",
                url=row["url"],
                llm_fit_score=row["llm_fit_score"],
                llm_reasoning=row["llm_reasoning"] or "",
                llm_seniority_assessment=row["llm_seniority_assessment"] or "",
                llm_role_authenticity=row["llm_role_authenticity"] or "",
                resume_pdf_path=resume_row["pdf_path"] if resume_row else None,
            )
        )
    return entries


def render_digest_html(entries: list[DigestEntry], run_date: str | None = None) -> str:
    run_date = run_date or date.today().isoformat()
    template = _env.get_template("digest.html.jinja")
    return template.render(run_date=run_date, jobs=entries)
