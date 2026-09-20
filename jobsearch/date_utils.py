"""Parsing helpers for the inconsistent posted_at formats across sources.

Greenhouse/JSearch/Adzuna give ISO8601 strings; Lever gives epoch
milliseconds as a string. Both need to resolve to the same thing so the
freshness filter can compare them uniformly.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


def parse_posted_at(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    value = value.strip()
    if not value:
        return None

    if value.isdigit():
        try:
            return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            return None

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def hours_since(value: Optional[str], now: Optional[datetime] = None) -> Optional[float]:
    dt = parse_posted_at(value)
    if dt is None:
        return None
    now = now or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (now - dt).total_seconds() / 3600
