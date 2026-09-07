"""LLM-driven resume tailoring: pick/rewrite bullets to mirror a specific JD's
language, optimizing for callback likelihood without fabricating experience.
"""
from __future__ import annotations

import copy
import os
from typing import Optional

import anthropic

from jobsearch.models import RawJob
from jobsearch.resume.schema import Resume

MODEL = "claude-sonnet-5"

TAILOR_TOOL = {
    "name": "record_tailored_resume",
    "description": "Record the tailored resume content for this job application.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "A 2-3 sentence professional summary rewritten to mirror this JD's "
                "language and highlight the candidate's most relevant experience for it.",
            },
            "skills": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Reordered/filtered skills list: the candidate's real skills most "
                "relevant to this JD first. Do not add skills the candidate doesn't have.",
            },
            "experience_bullets": {
                "type": "array",
                "description": "For each experience entry (same order/company/title as the input "
                "resume), the tailored bullet points to use.",
                "items": {
                    "type": "object",
                    "properties": {
                        "company": {"type": "string"},
                        "title": {"type": "string"},
                        "bullets": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Rewritten bullets: same underlying facts/achievements "
                            "as the original, but phrased with this JD's terminology and emphasis "
                            "to maximize callback likelihood. Never invent metrics or responsibilities "
                            "that aren't grounded in the original bullets.",
                        },
                    },
                    "required": ["company", "title", "bullets"],
                },
            },
        },
        "required": ["summary", "skills", "experience_bullets"],
    },
}

SYSTEM_PROMPT = """You are an expert resume writer helping a candidate tailor their resume for a
specific job posting. Your goal is to maximize the chance of a callback/interview by mirroring the
job description's language and emphasis.

Hard rules:
- Never fabricate experience, employers, titles, dates, or metrics that aren't grounded in the
  candidate's original resume. You may rephrase, reorder, re-emphasize, and use the JD's terminology
  for real experience — you may not invent new achievements.
- Keep bullets truthful but make them count: lead with impact, mirror keywords the JD uses (for ATS
  matching), and cut irrelevant detail.
- Use the record_tailored_resume tool to respond, and nothing else."""


def _client(api_key: Optional[str] = None) -> anthropic.Anthropic:
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key."
        )
    return anthropic.Anthropic(api_key=key)


def tailor_resume(resume: Resume, job: RawJob, client: anthropic.Anthropic | None = None) -> Resume:
    """Returns a new Resume with summary/skills/experience bullets tailored to `job`.

    Contact info, education, projects, and certifications are carried over unchanged.
    """
    client = client or _client()

    user_content = (
        f"CANDIDATE RESUME (structured):\n{resume.model_dump_json(indent=2)}\n\n"
        f"TARGET JOB POSTING:\n"
        f"Company: {job.company}\n"
        f"Title: {job.title}\n"
        f"Description:\n{job.description[:8000]}"
    )

    resp = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        tools=[TAILOR_TOOL],
        tool_choice={"type": "tool", "name": "record_tailored_resume"},
        messages=[{"role": "user", "content": user_content}],
    )

    tailored_data = None
    for block in resp.content:
        if block.type == "tool_use" and block.name == "record_tailored_resume":
            tailored_data = block.input
            break
    if tailored_data is None:
        raise RuntimeError(f"Model did not return a record_tailored_resume tool call: {resp}")

    result = copy.deepcopy(resume)
    result.summary = tailored_data["summary"]
    result.skills = tailored_data["skills"]

    bullets_by_key = {
        (b["company"], b["title"]): b["bullets"] for b in tailored_data["experience_bullets"]
    }
    for entry in result.experience:
        key = (entry.company, entry.title)
        if key in bullets_by_key:
            entry.bullets = bullets_by_key[key]

    return result
