"""Small text-cleanup helpers shared across LLM-output parsing.

Structured tool-call fields are meant to be plain prose, but models
occasionally leak a stray XML/HTML-like tag into them (e.g. a trailing
"</reasoning>" from internal formatting habits). These fields get rendered
directly into resume PDFs and digest HTML, so strip anything tag-shaped
before it reaches either.
"""
from __future__ import annotations

import re

_TAG_PATTERN = re.compile(r"</?[a-zA-Z][\w-]*\s*/?>")


def strip_stray_tags(text: str) -> str:
    return _TAG_PATTERN.sub("", text).strip()
