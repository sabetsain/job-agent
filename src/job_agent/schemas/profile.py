"""MasterProfile Pydantic v2 schema and YAML loader."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from job_agent.schemas._common import NonEmptyStr, load_yaml_mapping


class Identity(BaseModel):
    """Candidate identity, contact information, and profile links."""

    full_name: NonEmptyStr
    email: NonEmptyStr
    phone: str | None = None
    location: str | None = None
    linkedin_url: str | None = None
    github_url: str | None = None
    website_url: str | None = None


class ExperienceBullet(BaseModel):
    """Single verified accomplishment bullet under a work experience."""

    label: str | None = None
    text: NonEmptyStr
    metrics: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)


class ExperienceEntry(BaseModel):
    """Verified work experience entry."""

    company: NonEmptyStr
    title: NonEmptyStr
    start_date: NonEmptyStr
    end_date: str | None = None
    location: str | None = None
    bullets: list[ExperienceBullet] = Field(default_factory=list)


class ProjectEntry(BaseModel):
    """Verified project entry."""

    name: NonEmptyStr
    url: str | None = None
    description: str | None = None
    bullets: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)


class EducationEntry(BaseModel):
    """Verified education entry."""

    institution: NonEmptyStr
    degree: NonEmptyStr
    start_date: str | None = None
    end_date: str | None = None
    location: str | None = None
    highlights: list[str] = Field(default_factory=list)


class CertificationEntry(BaseModel):
    """Verified certification entry."""

    name: NonEmptyStr
    issuer: str | None = None
    date: str | None = None


class LanguageProficiency(BaseModel):
    """Spoken/written language proficiency (e.g., en, da)."""

    language: NonEmptyStr
    proficiency: NonEmptyStr


class SkillsCatalog(BaseModel):
    """Categorized technical skills inventory."""

    languages: list[str] = Field(default_factory=list)
    frameworks: list[str] = Field(default_factory=list)
    infrastructure: list[str] = Field(default_factory=list)
    databases: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    other: list[str] = Field(default_factory=list)


class MasterProfile(BaseModel):
    """Verified source-of-truth candidate profile loaded from YAML."""

    identity: Identity
    summary_seed: str = ""
    experiences: list[ExperienceEntry] = Field(default_factory=list)
    projects: list[ProjectEntry] = Field(default_factory=list)
    education: list[EducationEntry] = Field(default_factory=list)
    certifications: list[CertificationEntry] = Field(default_factory=list)
    languages: list[LanguageProficiency] = Field(default_factory=list)
    skills: SkillsCatalog = Field(default_factory=SkillsCatalog)


def load_master_profile(path: Path | str) -> MasterProfile:
    """Load and validate a MasterProfile from a YAML file."""
    data = load_yaml_mapping(path)
    return MasterProfile.model_validate(data)
