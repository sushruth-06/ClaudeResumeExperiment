from __future__ import annotations

from types import SimpleNamespace

from jobsearch.models import RawJob
from jobsearch.scoring import llm_score


class FakeToolUseBlock:
    type = "tool_use"
    name = "record_fit_assessment"

    def __init__(self, input_data):
        self.input = input_data


class FakeMessages:
    def __init__(self, tool_input):
        self.tool_input = tool_input
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return SimpleNamespace(content=[FakeToolUseBlock(self.tool_input)])


class FakeClient:
    def __init__(self, tool_input):
        self.messages = FakeMessages(tool_input)


def make_job() -> RawJob:
    return RawJob(
        source="greenhouse",
        external_id="1",
        company="acme",
        title="Backend Software Engineer",
        location="Remote",
        url="https://example.com/1",
        description="Build scalable backend systems in Python.",
    )


def test_score_job_parses_tool_response():
    fake = FakeClient(
        {
            "fit_score": 82,
            "seniority_assessment": "Matches mid-level.",
            "role_authenticity": "Genuinely a backend engineering role.",
            "reasoning": "Strong overlap in stack and responsibilities.",
        }
    )
    result = llm_score.score_job(make_job(), {"skills": ["python"]}, client=fake)

    assert result.fit_score == 82
    assert "mid-level" in result.seniority_assessment
    assert "backend" in result.role_authenticity
    assert "overlap" in result.reasoning


def test_score_job_forces_tool_choice():
    fake = FakeClient(
        {
            "fit_score": 50,
            "seniority_assessment": "x",
            "role_authenticity": "x",
            "reasoning": "x",
        }
    )
    llm_score.score_job(make_job(), {}, client=fake)
    kwargs = fake.messages.last_kwargs
    assert kwargs["tool_choice"] == {"type": "tool", "name": "record_fit_assessment"}
    assert kwargs["tools"][0]["name"] == "record_fit_assessment"
    assert "Backend Software Engineer" in kwargs["messages"][0]["content"]


def test_score_job_clamps_out_of_range_fit_score():
    fake = FakeClient(
        {
            "fit_score": 137,  # strict schemas can't enforce min/max on integers
            "seniority_assessment": "x",
            "role_authenticity": "x",
            "reasoning": "x",
        }
    )
    result = llm_score.score_job(make_job(), {}, client=fake)
    assert result.fit_score == 100

    fake_negative = FakeClient(
        {"fit_score": -12, "seniority_assessment": "x", "role_authenticity": "x", "reasoning": "x"}
    )
    result_negative = llm_score.score_job(make_job(), {}, client=fake_negative)
    assert result_negative.fit_score == 0


def test_score_job_raises_if_no_tool_call_returned():
    class EmptyClient:
        class messages:
            @staticmethod
            def create(**kwargs):
                return SimpleNamespace(content=[])

    import pytest

    with pytest.raises(RuntimeError):
        llm_score.score_job(make_job(), {}, client=EmptyClient())
