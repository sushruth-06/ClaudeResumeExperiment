"""LLM judgment pass: seniority fit, "is this really the role it claims to be",
and an overall fit score + reasoning against the candidate's resume.

Runs only on postings that already passed the deterministic filters, to keep
API spend down. One call per job, structured output via tool-use so scores
are always parseable.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

import anthropic

from jobsearch.models import RawJob

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-5"

SCORE_TOOL = {
    "name": "record_fit_assessment",
    "description": "Record a structured assessment of how well this job posting fits the candidate.",
    "input_schema": {
        "type": "object",
        "properties": {
            "fit_score": {
                "type": "integer",
                "minimum": 0,
                "maximum": 100,
                "description": "Overall fit score: how strong a match this role is for the candidate, "
                "weighing seniority alignment, skill/experience overlap, and role authenticity.",
            },
            "seniority_assessment": {
                "type": "string",
                "description": "One sentence on whether the posting's actual seniority (based on "
                "responsibilities described, not just the title) matches the candidate's level.",
            },
            "role_authenticity": {
                "type": "string",
                "description": "One sentence on whether this posting is really the role its title "
                "claims to be (e.g. a 'Software Engineer' posting that's actually a sales/customer-support "
                "role), or a red flag if so.",
            },
            "reasoning": {
                "type": "string",
                "description": "2-4 sentences of overall reasoning for the fit_score, written for a "
                "human skimming a digest of ~20 jobs.",
            },
        },
        "required": ["fit_score", "seniority_assessment", "role_authenticity", "reasoning"],
    },
}

SYSTEM_PROMPT = """You are an expert technical recruiter helping a candidate triage job postings.
You will be given the candidate's resume (as structured JSON) and one job posting.
Judge fit honestly and critically — the candidate would rather skip a mediocre match than waste
time tailoring a resume for it. Use the record_fit_assessment tool to respond, and nothing else."""


@dataclass
class LLMScore:
    fit_score: int
    seniority_assessment: str
    role_authenticity: str
    reasoning: str


def _client(api_key: Optional[str] = None) -> anthropic.Anthropic:
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key "
            "(https://console.anthropic.com/settings/keys)."
        )
    return anthropic.Anthropic(api_key=key)


def score_job(job: RawJob, resume_json: dict, client: anthropic.Anthropic | None = None) -> LLMScore:
    client = client or _client()

    user_content = (
        f"CANDIDATE RESUME (structured):\n{resume_json}\n\n"
        f"JOB POSTING:\n"
        f"Company: {job.company}\n"
        f"Title: {job.title}\n"
        f"Location: {job.location}\n"
        f"Description:\n{job.description[:8000]}"
    )

    resp = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        tools=[SCORE_TOOL],
        tool_choice={"type": "tool", "name": "record_fit_assessment"},
        messages=[{"role": "user", "content": user_content}],
    )

    for block in resp.content:
        if block.type == "tool_use" and block.name == "record_fit_assessment":
            data = block.input
            return LLMScore(
                fit_score=int(data["fit_score"]),
                seniority_assessment=data["seniority_assessment"],
                role_authenticity=data["role_authenticity"],
                reasoning=data["reasoning"],
            )

    raise RuntimeError(f"Model did not return a record_fit_assessment tool call: {resp}")
