"""Command-line entry points for the pipeline. Run `jobsearch --help`."""
from __future__ import annotations

import logging

import click

from jobsearch import db
from jobsearch.config import load_companies

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


@main.command("stats")
def stats():
    """Print row counts for a quick sanity check."""
    with db.get_conn() as conn:
        for table in ("jobs", "scores", "resumes", "application_status"):
            n = conn.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"]
            click.echo(f"{table}: {n}")


if __name__ == "__main__":
    main()
