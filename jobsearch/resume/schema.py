"""Structured resume data model.

The base resume is parsed once into this shape (see parser.py) and stored as
JSON so every later stage (LLM scoring, tailoring, PDF rendering) works
against reliable structured data instead of re-parsing raw resume text.
"""
from __future__ import annotations

from pydantic import BaseModel


class ContactInfo(BaseModel):
    name: str
    email: str = ""
    phone: str = ""
    location: str = ""
    linkedin: str = ""
    github: str = ""
    website: str = ""


class ExperienceEntry(BaseModel):
    company: str
    title: str
    location: str = ""
    start_date: str = ""  # free text, e.g. "Jan 2022"
    end_date: str = ""  # "" or "Present"
    bullets: list[str] = []


class EducationEntry(BaseModel):
    school: str
    degree: str = ""
    field: str = ""
    start_date: str = ""
    end_date: str = ""
    details: list[str] = []


class ProjectEntry(BaseModel):
    name: str
    description: str = ""
    bullets: list[str] = []
    url: str = ""


class Resume(BaseModel):
    contact: ContactInfo
    summary: str = ""
    skills: list[str] = []
    experience: list[ExperienceEntry] = []
    education: list[EducationEntry] = []
    projects: list[ProjectEntry] = []
    certifications: list[str] = []
