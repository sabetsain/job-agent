"""Pydantic v2 output models for Typst CV and Cover Letter rendering."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from job_agent.schemas._common import NonEmptyStr

CVSectionKey = Literal["experience", "projects", "education", "skills"]


class CVBullet(BaseModel):
    """Single CV bullet point with an optional bold lead-in phrase."""

    lead: str | None = None
    text: NonEmptyStr


class CVExperience(BaseModel):
    """Tailored work experience entry for CV rendering."""

    company: NonEmptyStr
    title: NonEmptyStr
    start_date: NonEmptyStr
    end_date: str | None = None
    location: str | None = None
    bullets: list[CVBullet] = Field(default_factory=list)


class CVProject(BaseModel):
    """Tailored project entry for CV rendering."""

    name: NonEmptyStr
    url: str | None = None
    bullets: list[CVBullet] = Field(default_factory=list)


class CVEducation(BaseModel):
    """Tailored education entry for CV rendering."""

    institution: NonEmptyStr
    degree: NonEmptyStr
    start_date: str | None = None
    end_date: str | None = None
    location: str | None = None
    highlights: list[str] = Field(default_factory=list)


class CVSkillCategory(BaseModel):
    """Categorized skill line for CV rendering."""

    category: NonEmptyStr
    items: list[str] = Field(default_factory=list)


class TailoredCV(BaseModel):
    """Complete structured CV payload passed to the Typst CV template."""

    language: Literal["da", "en"]
    full_name: NonEmptyStr
    email: NonEmptyStr
    phone: str | None = None
    location: str | None = None
    linkedin_url: str | None = None
    github_url: str | None = None
    website_url: str | None = None
    profile_summary: NonEmptyStr
    section_order: list[CVSectionKey] = Field(
        default_factory=lambda: ["experience", "projects", "education", "skills"]
    )
    experiences: list[CVExperience] = Field(default_factory=list)
    projects: list[CVProject] = Field(default_factory=list)
    education: list[CVEducation] = Field(default_factory=list)
    skills: list[CVSkillCategory] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    languages_spoken: list[str] = Field(default_factory=list)


class TailoredCoverLetter(BaseModel):
    """Complete structured Cover Letter payload passed to the Typst Cover Letter template."""

    language: Literal["da", "en"]
    full_name: NonEmptyStr
    email: NonEmptyStr
    phone: str | None = None
    location: str | None = None
    linkedin_url: str | None = None
    github_url: str | None = None
    website_url: str | None = None
    recipient_company: NonEmptyStr
    role_title: NonEmptyStr
    date_str: NonEmptyStr
    greeting: NonEmptyStr
    paragraphs: list[NonEmptyStr] = Field(min_length=3, max_length=5)
    sign_off: NonEmptyStr


class CompileResult(BaseModel):
    """Deterministic Typst compilation and page-budget validation result."""

    passed: bool
    cv_pdf_path: str
    cover_letter_pdf_path: str
    cv_pages: int
    cover_letter_pages: int
    overflow_feedback: list[str] = Field(default_factory=list)
