"""Loads .env, criteria.yaml, and companies.yaml into typed config objects."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "jobsearch.db"
RESUME_OUTPUT_DIR = DATA_DIR / "output" / "resumes"
DIGEST_OUTPUT_DIR = DATA_DIR / "output" / "digests"

load_dotenv(ROOT / ".env")


class Dealbreakers(BaseModel):
    titles_exclude: list[str] = []
    keywords_exclude: list[str] = []
    min_comp_usd: Optional[int] = None


class LinkedInConfig(BaseModel):
    enabled: bool = False
    search_url: str = ""
    max_results_per_run: int = 25
    min_delay_seconds: float = 4
    max_delay_seconds: float = 11


class Criteria(BaseModel):
    target_titles: list[str] = []
    seniority: str = "any"
    locations: list[str] = []
    dealbreakers: Dealbreakers = Dealbreakers()
    watchlist_companies: list[str] = []
    digest_size: int = 18
    min_fit_score: int = 65
    linkedin: LinkedInConfig = LinkedInConfig()


class Companies(BaseModel):
    greenhouse: list[str] = []
    lever: list[str] = []


def load_criteria(path: Path | None = None) -> Criteria:
    path = path or (DATA_DIR / "criteria.yaml")
    if not path.exists():
        return Criteria()
    with open(path) as f:
        raw = yaml.safe_load(f) or {}
    return Criteria(**raw)


def load_companies(path: Path | None = None) -> Companies:
    path = path or (DATA_DIR / "companies.yaml")
    if not path.exists():
        return Companies()
    with open(path) as f:
        raw = yaml.safe_load(f) or {}
    return Companies(**raw)


class Secrets:
    """Thin accessor over env vars so call sites fail with a clear message."""

    @staticmethod
    def get(name: str, required: bool = False) -> str | None:
        val = os.environ.get(name)
        if required and not val:
            raise RuntimeError(
                f"Missing required environment variable {name!r}. "
                f"Copy .env.example to .env and fill it in."
            )
        return val


for d in (DATA_DIR, RESUME_OUTPUT_DIR, DIGEST_OUTPUT_DIR):
    d.mkdir(parents=True, exist_ok=True)
