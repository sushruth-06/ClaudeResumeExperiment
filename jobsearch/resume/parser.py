"""Convert a base resume (PDF/DOCX/txt/md) into structured Resume JSON.

Run once (or whenever the base resume changes) via:
    jobsearch parse-resume path/to/resume.pdf
The result is saved to data/resume/base_resume.json and reused by every
later stage instead of re-parsing raw text each run.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

import anthropic

from jobsearch.resume.schema import Resume

MODEL = "claude-sonnet-5"

RESUME_TOOL = {
    "name": "record_resume",
    "description": "Record the candidate's resume as structured data.",
    "input_schema": Resume.model_json_schema(),
}

SYSTEM_PROMPT = """You convert raw resume text into structured data with perfect fidelity.
Do not invent, embellish, or drop any content — preserve every bullet point, date, and
detail exactly as written (fixing only obvious OCR/extraction artifacts like stray
whitespace). Use the record_resume tool to respond, and nothing else."""


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in (".txt", ".md"):
        return path.read_text()
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    if suffix == ".docx":
        import docx

        doc = docx.Document(str(path))
        return "\n".join(p.text for p in doc.paragraphs)
    raise ValueError(f"Unsupported resume file type: {suffix}")


def _client(api_key: Optional[str] = None) -> anthropic.Anthropic:
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key."
        )
    return anthropic.Anthropic(api_key=key)


def parse_resume(raw_text: str, client: anthropic.Anthropic | None = None) -> Resume:
    client = client or _client()
    resp = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        tools=[RESUME_TOOL],
        tool_choice={"type": "tool", "name": "record_resume"},
        messages=[{"role": "user", "content": f"RAW RESUME TEXT:\n\n{raw_text}"}],
    )
    for block in resp.content:
        if block.type == "tool_use" and block.name == "record_resume":
            return Resume(**block.input)
    raise RuntimeError(f"Model did not return a record_resume tool call: {resp}")


def parse_resume_file(path: Path, output_path: Path) -> Resume:
    raw_text = extract_text(path)
    resume = parse_resume(raw_text)
    output_path.write_text(resume.model_dump_json(indent=2))
    return resume
