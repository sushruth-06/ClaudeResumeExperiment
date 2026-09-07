"""Render a Resume to PDF.

Uses Playwright + the pre-installed Chromium ("print to PDF") rather than a
separate PDF-rendering stack, since Playwright is already a dependency for
the LinkedIn scraper and Chromium is guaranteed present in this environment.
"""
from __future__ import annotations

import os
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright

from jobsearch.config import TEMPLATE_DIR
from jobsearch.resume.schema import Resume

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


def render_html(resume: Resume) -> str:
    template = _env.get_template("resume.html.jinja")
    return template.render(resume=resume)


def render_pdf(resume: Resume, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    html = render_html(resume)

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
