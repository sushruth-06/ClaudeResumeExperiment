"""Render a Resume to PDF.

Uses Playwright + the pre-installed Chromium ("print to PDF") rather than a
separate PDF-rendering stack, since Playwright is already a dependency for
the LinkedIn scraper and Chromium is guaranteed present in this environment.
"""
from __future__ import annotations

import copy
import logging
import os
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright
from pypdf import PdfReader

from jobsearch.config import TEMPLATE_DIR
from jobsearch.resume.schema import Resume

logger = logging.getLogger(__name__)

# Pin to a pre-installed Chromium build when present (this repo's sandbox
# ships one that predates whatever revision the pip `playwright` package
# expects, so the default auto-download lookup fails). Falls back to
# Playwright's normal resolution elsewhere.
_PINNED_CHROMIUM = Path(os.environ.get("PLAYWRIGHT_CHROMIUM_PATH", "/opt/pw-browsers/chromium"))

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=True,  # template file is .html.jinja, not .html, so
    # select_autoescape's extension sniffing would silently miss it
)


def render_html(resume: Resume, compact: bool = False) -> str:
    template = _env.get_template("resume.html.jinja")
    return template.render(resume=resume, compact=compact)


def render_pdf(resume: Resume, output_path: Path, compact: bool = False) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    html = render_html(resume, compact=compact)

    launch_kwargs = {}
    if _PINNED_CHROMIUM.exists():
        launch_kwargs["executable_path"] = str(_PINNED_CHROMIUM)

    with sync_playwright() as p:
        browser = p.chromium.launch(**launch_kwargs)
        page = browser.new_page()
        page.set_content(html, wait_until="load")
        page.pdf(path=str(output_path), format="Letter", print_background=True)
        browser.close()

    return output_path


def _page_count(pdf_path: Path) -> int:
    return len(PdfReader(str(pdf_path)).pages)


def _trim_for_one_page(resume: Resume) -> Resume | None:
    """One trimming step: drop the least-relevant remaining content.

    Order: shorten the longest entry's bullets down to 2, then drop the
    last experience entry, then drop projects/certifications as a last
    resort. Returns None once there's nothing left to cut.
    """
    trimmed = copy.deepcopy(resume)

    over_length_entries = [e for e in trimmed.experience if len(e.bullets) > 2]
    if over_length_entries:
        over_length_entries[-1].bullets = over_length_entries[-1].bullets[:2]
        return trimmed

    if len(trimmed.experience) > 1:
        trimmed.experience = trimmed.experience[:-1]
        return trimmed

    if trimmed.projects:
        trimmed.projects = trimmed.projects[:-1]
        return trimmed

    if trimmed.certifications:
        trimmed.certifications = []
        return trimmed

    return None


def render_pdf_one_page(resume: Resume, output_path: Path, max_attempts: int = 6) -> Path:
    """Renders to PDF, verifying (not just hoping) the result is one page.

    Falls back through: trimming content -> compact CSS mode -> trimming
    again in compact mode. Accepts whatever fits after max_attempts and
    logs a warning if it never got there (e.g. an unusually long name/degree
    on an otherwise-empty resume) rather than failing the whole digest run.
    """
    current = resume
    compact = False
    for attempt in range(max_attempts):
        render_pdf(current, output_path, compact=compact)
        if _page_count(output_path) <= 1:
            return output_path

        if not compact:
            compact = True
            continue

        trimmed = _trim_for_one_page(current)
        if trimmed is None:
            logger.warning(
                "Could not fit resume to one page after %d attempts (job resume at %s); "
                "shipping the 2+ page version rather than failing the run.",
                attempt + 1,
                output_path,
            )
            return output_path
        current = trimmed

    logger.warning("Hit max_attempts=%d trying to fit resume to one page at %s", max_attempts, output_path)
    return output_path
