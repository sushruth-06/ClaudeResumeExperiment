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
from jobsearch.text_utils import strip_stray_tags

MODEL = "claude-sonnet-5"

# Defensive caps applied in code, independent of prompt compliance — these
# are the actual one-page enforcement backstop, not just a suggestion to the model.
MAX_EXPERIENCE_ENTRIES = 3
MAX_BULLETS_PER_ENTRY = 3
MAX_SKILLS = 10

TAILOR_TOOL = {
    "name": "record_tailored_resume",
    "description": "Record the tailored resume content for this job application.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
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
                "description": "ONLY the experience entries that should appear on this one-page "
                "tailored resume, in order of relevance to this JD (most relevant first is fine; "
                "original resume order is also fine). Any entry from the original resume NOT "
                "listed here is dropped from the tailored resume entirely — use this to cut "
                "older/less relevant roles so the resume fits one page. Company/title must exactly "
                "match an entry from the input resume.",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "company": {"type": "string"},
                        "title": {"type": "string"},
                        "bullets": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "At most 3 rewritten bullets, each a single line (roughly "
                            "under 120 characters). Same underlying facts/achievements as the "
                            "original, but phrased with this JD's terminology and emphasis to "
                            "maximize callback likelihood. Never invent metrics or responsibilities "
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
job description's language and emphasis — while keeping the whole resume to exactly ONE printed page.

Hard rules:
- Never fabricate experience, employers, titles, dates, or metrics that aren't grounded in the
  candidate's original resume. You may rephrase, reorder, re-emphasize, and use the JD's terminology
  for real experience — you may not invent new achievements, projects, or data points that didn't
  happen. Truthful reframing only.
- One page, no exceptions. To hit this: include at most 2-3 experience entries (drop older/less
  relevant roles from experience_bullets entirely — they'll be cut from the resume), at most 3
  bullets per included entry, each bullet a single line (~100-120 characters), and a 2-sentence
  summary. Prioritize ruthlessly for relevance to this specific JD over completeness.
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
    """Returns a new Resume with summary/skills/experience tailored to `job`.

    Experience entries not selected by the model as relevant to this JD are
    dropped (not just left with stale bullets) to keep the resume to one page.
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
    result.summary = strip_stray_tags(tailored_data["summary"])
    result.skills = [strip_stray_tags(s) for s in tailored_data["skills"]][:MAX_SKILLS]

    bullets_by_key = {
        (b["company"], b["title"]): [strip_stray_tags(bullet) for bullet in b["bullets"]][
            :MAX_BULLETS_PER_ENTRY
        ]
        for b in tailored_data["experience_bullets"]
    }
    # Only keep entries the model explicitly selected for this one-page resume,
    # in their original order, capped as a backstop in case the model kept too many.
    result.experience = [
        entry for entry in result.experience if (entry.company, entry.title) in bullets_by_key
    ][:MAX_EXPERIENCE_ENTRIES]
    for entry in result.experience:
        entry.bullets = bullets_by_key[(entry.company, entry.title)]

    return result
