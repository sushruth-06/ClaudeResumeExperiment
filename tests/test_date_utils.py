from __future__ import annotations

from datetime import datetime, timezone

from jobsearch.date_utils import hours_since, parse_posted_at


def test_parses_iso8601_with_offset():
    # Greenhouse format
    dt = parse_posted_at("2026-08-01T12:00:00-04:00")
    assert dt == datetime(2026, 8, 1, 16, 0, 0, tzinfo=timezone.utc)


def test_parses_iso8601_zulu():
    # JSearch/Adzuna format
    dt = parse_posted_at("2026-08-01T00:00:00.000Z")
    assert dt.replace(microsecond=0) == datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def test_parses_epoch_millis_string():
    # Lever format
    dt = parse_posted_at("1735689600000")
    assert dt == datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def test_returns_none_for_empty_or_missing():
    assert parse_posted_at(None) is None
    assert parse_posted_at("") is None
    assert parse_posted_at("   ") is None


def test_returns_none_for_garbage():
    assert parse_posted_at("not a date") is None


def test_hours_since_fresh_posting():
    now = datetime(2026, 8, 1, 18, 0, 0, tzinfo=timezone.utc)
    hours = hours_since("2026-08-01T12:00:00-04:00", now=now)  # posted at 16:00 UTC
    assert hours == 2.0


def test_hours_since_stale_posting():
    now = datetime(2026, 8, 5, 0, 0, 0, tzinfo=timezone.utc)
    hours = hours_since("2026-08-01T00:00:00Z", now=now)
    assert hours == 96.0


def test_hours_since_none_for_unparseable():
    assert hours_since("garbage") is None
