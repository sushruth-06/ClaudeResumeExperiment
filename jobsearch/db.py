"""SQLite storage: jobs seen, scores, generated resumes, application status.

Deliberately raw sqlite3 (no ORM) — the schema is small and stable, and this
keeps the dependency footprint minimal.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from jobsearch.config import DB_PATH
from jobsearch.models import RawJob

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    dedup_key TEXT NOT NULL,
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    company TEXT NOT NULL,
    title TEXT NOT NULL,
    location TEXT,
    url TEXT NOT NULL,
    description TEXT,
    posted_at TEXT,
    comp_min INTEGER,
    comp_max INTEGER,
    comp_currency TEXT,
    raw_json TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    is_duplicate_of TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_dedup_key ON jobs(dedup_key);

CREATE TABLE IF NOT EXISTS scores (
    job_id TEXT PRIMARY KEY REFERENCES jobs(job_id),
    passed_deterministic INTEGER NOT NULL,
    deterministic_reason TEXT,
    llm_fit_score INTEGER,
    llm_reasoning TEXT,
    llm_seniority_assessment TEXT,
    llm_role_authenticity TEXT,
    scored_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS resumes (
    job_id TEXT PRIMARY KEY REFERENCES jobs(job_id),
    pdf_path TEXT NOT NULL,
    bullets_json TEXT,
    generated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS application_status (
    job_id TEXT PRIMARY KEY REFERENCES jobs(job_id),
    status TEXT NOT NULL DEFAULT 'new',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS digest_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date TEXT NOT NULL,
    job_ids_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_conn(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    path = db_path or DB_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: Path | None = None) -> None:
    with get_conn(db_path) as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)


def _migrate(conn: sqlite3.Connection) -> None:
    """Idempotent ALTER TABLEs for columns added after a table already existed.

    CREATE TABLE IF NOT EXISTS in SCHEMA only handles brand-new databases;
    an existing one needs its own column added explicitly.
    """
    existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(scores)")}
    if "llm_role_authenticity" not in existing_cols:
        conn.execute("ALTER TABLE scores ADD COLUMN llm_role_authenticity TEXT")


def upsert_job(conn: sqlite3.Connection, job: RawJob) -> tuple[str, bool]:
    """Insert a job if new, or bump last_seen_at if already known.

    Returns (job_id, is_new).
    """
    now = _now()
    existing = conn.execute(
        "SELECT job_id FROM jobs WHERE job_id = ?", (job.job_id,)
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE jobs SET last_seen_at = ? WHERE job_id = ?", (now, job.job_id)
        )
        return job.job_id, False

    conn.execute(
        """
        INSERT INTO jobs (
            job_id, dedup_key, source, external_id, company, title, location,
            url, description, posted_at, comp_min, comp_max, comp_currency,
            raw_json, first_seen_at, last_seen_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job.job_id,
            job.dedup_key,
            job.source,
            job.external_id,
            job.company,
            job.title,
            job.location,
            job.url,
            job.description,
            job.posted_at,
            job.comp_min,
            job.comp_max,
            job.comp_currency,
            json.dumps(job.raw),
            now,
            now,
        ),
    )
    conn.execute(
        "INSERT INTO application_status (job_id, status, updated_at) VALUES (?, 'new', ?)",
        (job.job_id, now),
    )
    return job.job_id, True


def mark_duplicate(conn: sqlite3.Connection, job_id: str, canonical_job_id: str) -> None:
    conn.execute(
        "UPDATE jobs SET is_duplicate_of = ? WHERE job_id = ?",
        (canonical_job_id, job_id),
    )


def find_by_dedup_key(conn: sqlite3.Connection, dedup_key: str, exclude_job_id: str) -> Optional[str]:
    row = conn.execute(
        "SELECT job_id FROM jobs WHERE dedup_key = ? AND job_id != ? AND is_duplicate_of IS NULL",
        (dedup_key, exclude_job_id),
    ).fetchone()
    return row["job_id"] if row else None


def save_score(
    conn: sqlite3.Connection,
    job_id: str,
    passed_deterministic: bool,
    deterministic_reason: str,
    llm_fit_score: Optional[int] = None,
    llm_reasoning: Optional[str] = None,
    llm_seniority_assessment: Optional[str] = None,
    llm_role_authenticity: Optional[str] = None,
) -> None:
    conn.execute(
        """
        INSERT INTO scores (job_id, passed_deterministic, deterministic_reason,
            llm_fit_score, llm_reasoning, llm_seniority_assessment,
            llm_role_authenticity, scored_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(job_id) DO UPDATE SET
            passed_deterministic=excluded.passed_deterministic,
            deterministic_reason=excluded.deterministic_reason,
            llm_fit_score=excluded.llm_fit_score,
            llm_reasoning=excluded.llm_reasoning,
            llm_seniority_assessment=excluded.llm_seniority_assessment,
            llm_role_authenticity=excluded.llm_role_authenticity,
            scored_at=excluded.scored_at
        """,
        (
            job_id,
            int(passed_deterministic),
            deterministic_reason,
            llm_fit_score,
            llm_reasoning,
            llm_seniority_assessment,
            llm_role_authenticity,
            _now(),
        ),
    )


def save_resume(conn: sqlite3.Connection, job_id: str, pdf_path: str, bullets: dict) -> None:
    conn.execute(
        """
        INSERT INTO resumes (job_id, pdf_path, bullets_json, generated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(job_id) DO UPDATE SET
            pdf_path=excluded.pdf_path, bullets_json=excluded.bullets_json,
            generated_at=excluded.generated_at
        """,
        (job_id, pdf_path, json.dumps(bullets), _now()),
    )


def set_status(conn: sqlite3.Connection, job_id: str, status: str) -> None:
    conn.execute(
        """
        INSERT INTO application_status (job_id, status, updated_at) VALUES (?, ?, ?)
        ON CONFLICT(job_id) DO UPDATE SET status=excluded.status, updated_at=excluded.updated_at
        """,
        (job_id, status, _now()),
    )


def record_digest_run(conn: sqlite3.Connection, run_date: str, job_ids: list[str]) -> None:
    conn.execute(
        "INSERT INTO digest_runs (run_date, job_ids_json, created_at) VALUES (?, ?, ?)",
        (run_date, json.dumps(job_ids), _now()),
    )


def jobs_pending_score(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT j.* FROM jobs j
        LEFT JOIN scores s ON j.job_id = s.job_id
        WHERE s.job_id IS NULL AND j.is_duplicate_of IS NULL
        """
    ).fetchall()


def shortlisted_jobs(conn: sqlite3.Connection, min_fit_score: int, limit: int) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT j.*, s.llm_fit_score, s.llm_reasoning, s.llm_seniority_assessment,
            s.llm_role_authenticity
        FROM jobs j
        JOIN scores s ON j.job_id = s.job_id
        LEFT JOIN application_status a ON j.job_id = a.job_id
        WHERE s.passed_deterministic = 1
          AND s.llm_fit_score >= ?
          AND j.is_duplicate_of IS NULL
          AND (a.status IS NULL OR a.status NOT IN ('digested', 'applied', 'rejected', 'skipped'))
        ORDER BY s.llm_fit_score DESC
        LIMIT ?
        """,
        (min_fit_score, limit),
    ).fetchall()
