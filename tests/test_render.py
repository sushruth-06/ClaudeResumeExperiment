"""Exercises the real Jinja2 template and real Chromium (no mocking) since
PDF rendering is an output-fidelity concern, not a logic concern.
"""
from __future__ import annotations

from pypdf import PdfReader

from jobsearch.resume.render import _trim_for_one_page, render_html, render_pdf, render_pdf_one_page
from jobsearch.resume.schema import ContactInfo, EducationEntry, ExperienceEntry, ProjectEntry, Resume


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


def test_render_html_compact_mode_still_renders_all_content():
    html = render_html(make_resume(), compact=True)
    assert "Jordan Rivera" in html
    assert "Acme Corp" in html


def make_overflowing_resume() -> Resume:
    """A resume with enough content to reliably overflow one page."""
    long_bullet = (
        "Delivered a substantial cross-functional initiative involving multiple stakeholder "
        "teams, resulting in measurable improvements to process efficiency and reporting quality."
    )
    return Resume(
        contact=ContactInfo(
            name="Jordan Rivera", email="jordan@example.com", phone="555-0100",
            location="Remote", linkedin="linkedin.com/in/jordanrivera", github="github.com/jordanrivera",
        ),
        summary=long_bullet,
        skills=[f"Skill {i}" for i in range(15)],
        experience=[
            ExperienceEntry(
                company=f"Company {i}", title="Senior Analyst", location="Remote",
                start_date="Jan 2018", end_date="Dec 2020",
                bullets=[long_bullet, long_bullet, long_bullet, long_bullet],
            )
            for i in range(5)
        ],
        education=[EducationEntry(school="State University", degree="B.S.", field="Economics")],
    )


def test_render_pdf_one_page_fits_a_normal_resume_without_trimming(tmp_path):
    out = render_pdf_one_page(make_resume(), tmp_path / "resume.pdf")
    assert len(PdfReader(str(out)).pages) == 1


def test_render_pdf_one_page_actually_fits_overflowing_content(tmp_path):
    out = render_pdf_one_page(make_overflowing_resume(), tmp_path / "resume.pdf")
    assert len(PdfReader(str(out)).pages) == 1
    # confirm real trimming happened (4 bullets/entry doesn't fit one page
    # even in compact mode) rather than the page count just working out by luck
    text = "\n".join(page.extract_text() or "" for page in PdfReader(str(out)).pages)
    bullet_occurrences = text.count(
        "Delivered a substantial cross-functional initiative"
    )
    assert 0 < bullet_occurrences < 20  # started at 5 entries x 4 bullets = 20


def test_trim_for_one_page_shortens_longest_entry_bullets_first():
    resume = make_resume()
    resume.experience[0].bullets = ["b1", "b2", "b3", "b4"]
    trimmed = _trim_for_one_page(resume)
    assert trimmed is not None
    assert len(trimmed.experience[0].bullets) == 2


def test_trim_for_one_page_drops_last_experience_entry_next():
    resume = make_resume()
    resume.experience[0].bullets = ["b1", "b2"]  # already short
    resume.experience.append(
        ExperienceEntry(company="Old Co", title="Intern", bullets=["b1", "b2"])
    )
    trimmed = _trim_for_one_page(resume)
    assert trimmed is not None
    assert len(trimmed.experience) == 1
    assert trimmed.experience[0].company == "Acme Corp"


def test_trim_for_one_page_drops_projects_then_certifications():
    resume = make_resume()
    resume.experience[0].bullets = ["b1", "b2"]
    resume.projects = [ProjectEntry(name="Side Project", bullets=["p1"])]
    resume.certifications = ["AWS Certified"]

    trimmed = _trim_for_one_page(resume)
    assert trimmed.projects == []

    trimmed2 = _trim_for_one_page(trimmed)
    assert trimmed2.certifications == []


def test_trim_for_one_page_returns_none_when_nothing_left_to_cut():
    resume = make_resume()
    resume.experience[0].bullets = ["b1"]
    assert _trim_for_one_page(resume) is None
