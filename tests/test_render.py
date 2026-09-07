"""Exercises the real Jinja2 template and real Chromium (no mocking) since
PDF rendering is an output-fidelity concern, not a logic concern.
"""
from __future__ import annotations

from jobsearch.resume.render import render_html, render_pdf
from jobsearch.resume.schema import ContactInfo, EducationEntry, ExperienceEntry, Resume


def make_resume() -> Resume:
    return Resume(
        contact=ContactInfo(name="Jordan Rivera", email="jordan@example.com"),
        summary="Backend engineer.",
        skills=["Python", "SQL"],
        experience=[
            ExperienceEntry(
                company="Acme Corp",
                title="Software Engineer",
                bullets=["Did a thing.", "Did another thing."],
            )
        ],
        education=[EducationEntry(school="State University", degree="B.S.")],
    )


def test_render_html_includes_all_sections():
    html = render_html(make_resume())
    assert "Jordan Rivera" in html
    assert "jordan@example.com" in html
    assert "Acme Corp" in html
    assert "Did a thing." in html
    assert "State University" in html


def test_render_html_escapes_content():
    resume = make_resume()
    resume.summary = "<script>alert(1)</script>"
    html = render_html(resume)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_render_pdf_produces_nonempty_file(tmp_path):
    out = render_pdf(make_resume(), tmp_path / "resume.pdf")
    assert out.exists()
    assert out.stat().st_size > 1000
    assert out.read_bytes().startswith(b"%PDF")
