"""Command-line entry points for the pipeline. Run `jobsearch --help`."""
from __future__ import annotations

import logging

import click

from jobsearch import db
from jobsearch.config import BASE_RESUME_JSON_PATH, RESUME_OUTPUT_DIR, load_companies, load_criteria

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@click.group()
def main():
    """Agentic job-search pipeline."""
    db.init_db()


@main.command("fetch-greenhouse")
@click.argument("board_tokens", nargs=-1)
def fetch_greenhouse(board_tokens: tuple[str, ...]):
    """Fetch jobs from Greenhouse boards and upsert into the DB.

    If no board_tokens are given, uses data/companies.yaml's greenhouse list.
    """
    from jobsearch.sources import greenhouse

    tokens = list(board_tokens) or load_companies().greenhouse
    if not tokens:
        click.echo("No Greenhouse board tokens configured.")
        return
    jobs = greenhouse.fetch_all(tokens)
    _store_jobs(jobs)


@main.command("fetch-lever")
@click.argument("site_ids", nargs=-1)
def fetch_lever(site_ids: tuple[str, ...]):
    """Fetch jobs from Lever boards and upsert into the DB.

    If no site_ids are given, uses data/companies.yaml's lever list.
    """
    from jobsearch.sources import lever

    ids = list(site_ids) or load_companies().lever
    if not ids:
        click.echo("No Lever site ids configured.")
        return
    jobs = lever.fetch_all(ids)
    _store_jobs(jobs)


def _store_jobs(jobs) -> None:
    new_count = 0
    with db.get_conn() as conn:
        for job in jobs:
            canonical = db.find_by_dedup_key(conn, job.dedup_key, job.job_id)
            job_id, is_new = db.upsert_job(conn, job)
            if is_new:
                new_count += 1
            if canonical:
                db.mark_duplicate(conn, job_id, canonical)
    click.echo(f"Fetched {len(jobs)} jobs, {new_count} new.")


@main.command("parse-resume")
@click.argument("resume_path", type=click.Path(exists=True, dir_okay=False))
def parse_resume_cmd(resume_path: str):
    """Convert a base resume (PDF/DOCX/txt/md) into structured JSON.

    Saved to data/resume/base_resume.json for reuse by scoring/tailoring.
    """
    from pathlib import Path

    from jobsearch.resume.parser import parse_resume_file

    resume = parse_resume_file(Path(resume_path), BASE_RESUME_JSON_PATH)
    click.echo(f"Parsed resume for {resume.contact.name!r} -> {BASE_RESUME_JSON_PATH}")


def _load_base_resume():
    from jobsearch.resume.schema import Resume

    if not BASE_RESUME_JSON_PATH.exists():
        raise click.ClickException(
            f"No parsed base resume at {BASE_RESUME_JSON_PATH}. "
            f"Run `jobsearch parse-resume <path>` first."
        )
    return Resume.model_validate_json(BASE_RESUME_JSON_PATH.read_text())


@main.command("score")
@click.option("--limit", default=None, type=int, help="Max number of jobs to LLM-score this run.")
def score_cmd(limit: int | None):
    """Run deterministic filters, then LLM fit-scoring, on all unscored jobs."""
    from jobsearch.scoring import filters, llm_score

    criteria = load_criteria()
    resume = _load_base_resume()

    with db.get_conn() as conn:
        pending = db.jobs_pending_score(conn)
        if limit:
            pending = pending[:limit]
        click.echo(f"{len(pending)} jobs pending score.")

        client = None
        passed_count = 0
        for row in pending:
            job = _row_to_raw_job(row)
            result = filters.evaluate(job, criteria)
            if not result.passed:
                db.save_score(conn, job.job_id, passed_deterministic=False, deterministic_reason=result.reason)
                continue

            if client is None:
                client = llm_score._client()
            llm_result = llm_score.score_job(job, resume.model_dump(), client=client)
            db.save_score(
                conn,
                job.job_id,
                passed_deterministic=True,
                deterministic_reason=result.reason,
                llm_fit_score=llm_result.fit_score,
                llm_reasoning=llm_result.reasoning,
                llm_seniority_assessment=llm_result.seniority_assessment,
            )
            passed_count += 1
            click.echo(f"  [{llm_result.fit_score:3d}] {job.company} — {job.title}")

    click.echo(f"Scored {len(pending)} jobs, {passed_count} passed deterministic filters.")


def _row_to_raw_job(row):
    from jobsearch.models import RawJob

    return RawJob(
        source=row["source"],
        external_id=row["external_id"],
        company=row["company"],
        title=row["title"],
        location=row["location"] or "",
        url=row["url"],
        description=row["description"] or "",
        posted_at=row["posted_at"],
        comp_min=row["comp_min"],
        comp_max=row["comp_max"],
        comp_currency=row["comp_currency"],
    )


@main.command("tailor")
@click.argument("job_id")
def tailor_cmd(job_id: str):
    """Generate a tailored resume PDF for one job_id (see `jobsearch stats`/DB for ids)."""
    from jobsearch.resume.render import render_pdf
    from jobsearch.resume.tailor import tailor_resume

    resume = _load_base_resume()
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if not row:
            raise click.ClickException(f"No job with id {job_id}")
        job = _row_to_raw_job(row)

        tailored = tailor_resume(resume, job)
        pdf_path = RESUME_OUTPUT_DIR / f"{job_id}_{job.company}.pdf".replace(" ", "_")
        render_pdf(tailored, pdf_path)
        db.save_resume(conn, job_id, str(pdf_path), tailored.model_dump())

    click.echo(f"Wrote tailored resume -> {pdf_path}")


@main.command("stats")
def stats():
    """Print row counts for a quick sanity check."""
    with db.get_conn() as conn:
        for table in ("jobs", "scores", "resumes", "application_status"):
            n = conn.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"]
            click.echo(f"{table}: {n}")


if __name__ == "__main__":
    main()
