from __future__ import annotations

from types import SimpleNamespace

from jobsearch.models import RawJob
from jobsearch.resume.schema import ContactInfo, ExperienceEntry, Resume
from jobsearch.resume.tailor import tailor_resume


class FakeToolUseBlock:
    type = "tool_use"
    name = "record_tailored_resume"

    def __init__(self, input_data):
        self.input = input_data


class FakeClient:
    def __init__(self, tool_input):
        self.tool_input = tool_input
        self.last_kwargs = None
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.last_kwargs = kwargs
        return SimpleNamespace(content=[FakeToolUseBlock(self.tool_input)])


def make_resume() -> Resume:
    return Resume(
        contact=ContactInfo(name="Jordan Rivera", email="jordan@example.com"),
        summary="Generic backend engineer.",
        skills=["Python", "SQL"],
        experience=[
            ExperienceEntry(
                company="Acme Corp",
                title="Software Engineer",
                bullets=["Built a payments service handling $2M/day."],
            )
        ],
    )


def make_job() -> RawJob:
    return RawJob(
        source="greenhouse",
        external_id="1",
        company="Fintech Co",
        title="Backend Engineer, Payments",
        location="Remote",
        url="https://example.com/1",
        description="We need someone who knows distributed ledgers and idempotent payment APIs.",
    )


def test_tailor_resume_applies_new_summary_skills_and_bullets():
    fake = FakeClient(
        {
            "summary": "Backend engineer specializing in idempotent payment APIs.",
            "skills": ["Python", "Distributed Systems", "SQL"],
            "experience_bullets": [
                {
                    "company": "Acme Corp",
                    "title": "Software Engineer",
                    "bullets": [
                        "Built an idempotent payments API processing $2M/day in distributed ledger transactions."
                    ],
                }
            ],
        }
    )
    original = make_resume()
    tailored = tailor_resume(original, make_job(), client=fake)

    assert tailored.summary == "Backend engineer specializing in idempotent payment APIs."
    assert tailored.skills == ["Python", "Distributed Systems", "SQL"]
    assert "idempotent payments API" in tailored.experience[0].bullets[0]
    # original untouched
    assert original.summary == "Generic backend engineer."
    assert original.experience[0].bullets[0] == "Built a payments service handling $2M/day."
    # contact info carried over unchanged
    assert tailored.contact.name == "Jordan Rivera"


def test_tailor_resume_sends_job_and_resume_context():
    fake = FakeClient(
        {"summary": "s", "skills": [], "experience_bullets": []}
    )
    tailor_resume(make_resume(), make_job(), client=fake)
    content = fake.last_kwargs["messages"][0]["content"]
    assert "Fintech Co" in content
    assert "Backend Engineer, Payments" in content
    assert "Jordan Rivera" in content


def test_tailor_resume_leaves_unmentioned_experience_untouched():
    resume = make_resume()
    resume.experience.append(
        ExperienceEntry(company="Other Co", title="Intern", bullets=["Did intern things."])
    )
    fake = FakeClient(
        {
            "summary": "s",
            "skills": [],
            "experience_bullets": [
                {"company": "Acme Corp", "title": "Software Engineer", "bullets": ["New bullet."]}
            ],
        }
    )
    tailored = tailor_resume(resume, make_job(), client=fake)
    assert tailored.experience[1].bullets == ["Did intern things."]
