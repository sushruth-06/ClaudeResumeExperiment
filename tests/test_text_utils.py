from __future__ import annotations

from jobsearch.text_utils import strip_stray_tags


def test_strips_trailing_closing_tag():
    # real artifact observed from a live LLM response
    raw = (
        "Candidate's background is in business/data analytics, not corporate "
        "finance. This is a poor fit despite shared reporting themes.</reasoning>\n"
    )
    assert strip_stray_tags(raw) == (
        "Candidate's background is in business/data analytics, not corporate "
        "finance. This is a poor fit despite shared reporting themes."
    )


def test_strips_opening_and_self_closing_tags():
    assert strip_stray_tags("<reasoning>Some text</reasoning>") == "Some text"
    assert strip_stray_tags("Some text<br/>") == "Some text"


def test_leaves_plain_text_untouched():
    text = "Strong fit: 5 years Python, distributed systems, and AWS."
    assert strip_stray_tags(text) == text


def test_does_not_mangle_comparison_operators():
    # a bare "<" or ">" without a tag-like word after it is not a tag
    text = "Requires 5+ years, salary < $150k is a dealbreaker"
    assert strip_stray_tags(text) == text
