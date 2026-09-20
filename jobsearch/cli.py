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


@main.command("fetch-aggregator")
@click.argument("queries", nargs=-1)
@click.option("--location", default="", help="Location filter, e.g. 'Remote' or 'New York'.")
def fetch_aggregator(queries: tuple[str, ...], location: str):
    """Fetch jobs from the configured aggregator API (JSearch or Adzuna).

    If no queries are given, uses data/criteria.yaml's target_titles.
    Requires JSEARCH_API_KEY or ADZUNA_APP_ID+ADZUNA_APP_KEY in .env.
    """
    from jobsearch.sources import aggregator

    qs = list(queries) or load_criteria().target_titles
    if not qs:
        click.echo("No queries configured (set data/criteria.yaml target_titles, or pass some).")
        return
    try:
        jobs = aggregator.fetch_all(qs, location=location)
    except aggregator.NotConfigured as e:
        raise click.ClickException(str(e))
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

    # Each job gets its own short-lived connection/transaction so a single
    # failure (bad network blip, one malformed LLM response) can't roll back
    # every already-completed - and already-paid-for - LLM call in the run.
    client = None
    passed_count = 0
    error_count = 0
    for row in pending:
        job = _row_to_raw_job(row)
        result = filters.evaluate(job, criteria)
        if not result.passed:
            with db.get_conn() as conn:
                db.save_score(conn, job.job_id, passed_deterministic=False, deterministic_reason=result.reason)
            continue

        if client is None:
            client = llm_score._client()
        try:
            llm_result = llm_score.score_job(job, resume.model_dump(), client=client)
        except Exception as e:
            error_count += 1
            click.echo(f"  ERROR scoring {job.company} — {job.title}: {e}")
            continue

        with db.get_conn() as conn:
            db.save_score(
                conn,
                job.job_id,
                passed_deterministic=True,
                deterministic_reason=result.reason,
                llm_fit_score=llm_result.fit_score,
                llm_reasoning=llm_result.reasoning,
                llm_seniority_assessment=llm_result.seniority_assessment,
                llm_role_authenticity=llm_result.role_authenticity,
            )
        passed_count += 1
        click.echo(f"  [{llm_result.fit_score:3d}] {job.company} — {job.title}")

    click.echo(
        f"Scored {len(pending)} jobs, {passed_count} passed deterministic filters, "
        f"{error_count} errored (left pending, will retry next run)."
    )


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
    from jobsearch.resume.render import render_pdf_one_page
    from jobsearch.resume.tailor import tailor_resume

    resume = _load_base_resume()
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if not row:
            raise click.ClickException(f"No job with id {job_id}")
        job = _row_to_raw_job(row)

        tailored = tailor_resume(resume, job)
        pdf_path = RESUME_OUTPUT_DIR / f"{job_id}_{job.company}.pdf".replace(" ", "_")
        render_pdf_one_page(tailored, pdf_path)
        db.save_resume(conn, job_id, str(pdf_path), tailored.model_dump())

    click.echo(f"Wrote tailored resume -> {pdf_path}")


@main.command("digest")
def digest_cmd():
    """Build the digest from the current shortlist, tailor a resume for each
    job that doesn't have one yet, render HTML, and deliver it.

    Delivery always writes a local HTML file; email/Slack fire additionally
    if their env vars are configured (see .env.example). Digested jobs are
    marked so they don't resurface tomorrow.
    """
    from datetime import date

    from pathlib import Path

    from jobsearch.digest.build import build_digest_entries, render_digest_html
    from jobsearch.digest.deliver import send_email, send_slack, write_html_file
    from jobsearch.resume.render import render_pdf_one_page
    from jobsearch.resume.tailor import tailor_resume
    from jobsearch.config import DIGEST_OUTPUT_DIR

    criteria = load_criteria()
    resume = _load_base_resume()
    run_date = date.today().isoformat()

    with db.get_conn() as conn:
        entries = build_digest_entries(
            conn, criteria.min_fit_score, criteria.digest_size, criteria.max_posting_age_hours
        )

    # Each job's tailoring gets its own short transaction so a failure on
    # one job (or later, on delivery) can't roll back already-completed -
    # and already-paid-for - tailoring work. Same pattern as score_cmd.
    for entry in entries:
        if entry.resume_pdf_path:
            continue
        with db.get_conn() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (entry.job_id,)).fetchone()
            job = _row_to_raw_job(row)
        try:
            tailored = tailor_resume(resume, job)
            pdf_path = RESUME_OUTPUT_DIR / f"{entry.job_id}_{job.company}.pdf".replace(" ", "_")
            render_pdf_one_page(tailored, pdf_path)
        except Exception as e:
            click.echo(f"  ERROR tailoring {job.company} — {job.title}: {e}")
            continue
        with db.get_conn() as conn:
            db.save_resume(conn, entry.job_id, str(pdf_path), tailored.model_dump())
        entry.resume_pdf_path = str(pdf_path)
        click.echo(f"  tailored resume -> {pdf_path}")

    html = render_digest_html(entries, run_date=run_date)
    out_path = write_html_file(html, DIGEST_OUTPUT_DIR / f"{run_date}.html")

    # Delivery failures must never block marking the digest done - the HTML
    # file above is already the guaranteed fallback delivery mechanism.
    attachments = [Path(e.resume_pdf_path) for e in entries if e.resume_pdf_path]
    email_status = "skipped (not configured)"
    try:
        email_status = "sent" if send_email(
            html,
            subject=f"Job Digest — {run_date} ({len(entries)} matches)",
            attachments=attachments,
        ) else "skipped (not configured)"
    except Exception as e:
        click.echo(f"  ERROR sending email: {e}")
        email_status = f"FAILED ({e})"

    slack_status = "skipped (not configured)"
    try:
        slack_status = "sent" if send_slack(entries, run_date) else "skipped (not configured)"
    except Exception as e:
        click.echo(f"  ERROR posting to Slack: {e}")
        slack_status = f"FAILED ({e})"

    with db.get_conn() as conn:
        db.record_digest_run(conn, run_date, [e.job_id for e in entries])
        for entry in entries:
            db.set_status(conn, entry.job_id, "digested")

    click.echo(f"Digest written to {out_path} ({len(entries)} jobs).")
    click.echo(f"Email: {email_status}")
    click.echo(f"Slack: {slack_status}")


@main.command("fetch-linkedin")
def fetch_linkedin():
    """Scrape LinkedIn job search results (feature-flagged; see criteria.yaml linkedin.enabled).

    Requires a one-time manual login into the persistent browser profile at
    data/.linkedin-profile — see jobsearch/sources/linkedin.py docstring.
    Off by default given LinkedIn ToS / account-restriction risk.
    """
    from jobsearch.sources import linkedin

    criteria = load_criteria()
    if not criteria.linkedin.enabled:
        click.echo("LinkedIn source is disabled (criteria.yaml linkedin.enabled: false). Skipping.")
        return
    if not criteria.linkedin.search_url:
        raise click.ClickException("criteria.yaml linkedin.search_url is empty.")

    jobs = linkedin.fetch_jobs(
        criteria.linkedin.search_url,
        max_results=criteria.linkedin.max_results_per_run,
        min_delay=criteria.linkedin.min_delay_seconds,
        max_delay=criteria.linkedin.max_delay_seconds,
    )
    _store_jobs(jobs)


@main.command("run-all")
@click.pass_context
def run_all(ctx):
    """Full daily pipeline: fetch all sources, score, tailor, and deliver the digest."""
    ctx.invoke(fetch_greenhouse, board_tokens=())
    ctx.invoke(fetch_lever, site_ids=())
    try:
        ctx.invoke(fetch_aggregator, queries=(), location="")
    except click.ClickException as e:
        click.echo(f"Skipping aggregator source: {e.message}")
    ctx.invoke(fetch_linkedin)
    ctx.invoke(score_cmd, limit=None)
    ctx.invoke(digest_cmd)


@main.command("stats")
def stats():
    """Print row counts for a quick sanity check."""
    with db.get_conn() as conn:
        for table in ("jobs", "scores", "resumes", "application_status"):
            n = conn.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"]
            click.echo(f"{table}: {n}")


if __name__ == "__main__":
    main()
