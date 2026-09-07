"""Core dataclasses passed between pipeline stages (sourcing -> scoring -> tailoring -> digest)."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RawJob:
    """A job posting as fetched from a source, before dedup/scoring."""

    source: str  # "greenhouse" | "lever" | "aggregator" | "linkedin"
    external_id: str  # id/slug as given by the source
    company: str
    title: str
    location: str
    url: str
    description: str
    posted_at: Optional[str] = None  # ISO date string if known
    comp_min: Optional[int] = None
    comp_max: Optional[int] = None
    comp_currency: Optional[str] = None
    raw: dict = field(default_factory=dict)

    @property
    def job_id(self) -> str:
        """Stable id for this posting, used as the SQLite primary key."""
        h = hashlib.sha256(f"{self.source}:{self.external_id}".encode()).hexdigest()
        return h[:16]

    @property
    def dedup_key(self) -> str:
        """Coarser key used to catch the same posting across sources."""
        norm_title = "".join(c.lower() for c in self.title if c.isalnum())
        norm_company = "".join(c.lower() for c in self.company if c.isalnum())
        return f"{norm_company}:{norm_title}"
