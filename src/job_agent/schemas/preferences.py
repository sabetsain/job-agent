"""JobPreferences Pydantic v2 schema and YAML loader."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from job_agent.schemas._common import NonEmptyStr, load_yaml_mapping

DEFAULT_EXCLUDED_TITLE_KEYWORDS: tuple[str, ...] = (
    "senior",
    "sr.",
    "sr ",
    "staff",
    "principal",
    "lead",
    "manager",
    "director",
    "head of",
    "vp",
    "chief",
    "seniorudvikler",
    "chef",
    "leder",
)

DEFAULT_VOICE_SKILL_PATH = ".agent/skills/application-voice"


class TargetRoles(BaseModel):
    """Primary and adjacent target job titles."""

    primary: list[str] = Field(default_factory=list)
    adjacent: list[str] = Field(default_factory=list)


class LocationsConfig(BaseModel):
    """Geographic and work-mode eligibility rules."""

    allowed_cities: list[str] = Field(default_factory=list)
    allowed_countries: list[str] = Field(default_factory=list)
    allowed_regions: list[str] = Field(default_factory=list)
    allowed_work_modes: list[Literal["remote", "hybrid", "onsite"]] = Field(
        default_factory=lambda: ["onsite", "hybrid", "remote"]
    )
    remote_allowed_regions: list[str] = Field(default_factory=list)


class SeniorityTier(BaseModel):
    """Experience ceiling and must-have coverage requirement for a seniority tier."""

    max_years: int = Field(ge=0)
    min_must_have_coverage: float = Field(ge=0.0, le=1.0)


class SeniorityPolicy(BaseModel):
    """Tiered seniority rules keeping entry-level primary and Architect roles eligible."""

    excluded_title_keywords: list[str] = Field(
        default_factory=lambda: list(DEFAULT_EXCLUDED_TITLE_KEYWORDS)
    )
    max_years_experience: int = Field(default=2, ge=0)
    entry_level: SeniorityTier = Field(
        default_factory=lambda: SeniorityTier(max_years=1, min_must_have_coverage=0.65)
    )
    stretch: SeniorityTier = Field(
        default_factory=lambda: SeniorityTier(max_years=2, min_must_have_coverage=0.95)
    )

    @model_validator(mode="after")
    def _validate_tier_coverage(self) -> SeniorityPolicy:
        if self.stretch.min_must_have_coverage < self.entry_level.min_must_have_coverage:
            raise ValueError(
                "stretch.min_must_have_coverage must be greater than or equal to "
                "entry_level.min_must_have_coverage"
            )
        return self


class FreshnessPolicy(BaseModel):
    """Posting age bounds and daily drafting upper cap (never a quota)."""

    max_age_days: int = Field(default=21, ge=1)
    preferred_age_days: int = Field(default=7, ge=0)
    daily_draft_limit: int = Field(default=3, ge=1)

    @model_validator(mode="after")
    def _validate_bounds(self) -> FreshnessPolicy:
        if self.max_age_days < 1:
            raise ValueError("max_age_days must be at least 1")
        if self.daily_draft_limit < 1:
            raise ValueError("daily_draft_limit must be at least 1")
        if self.preferred_age_days > self.max_age_days:
            raise ValueError("preferred_age_days must be less than or equal to max_age_days")
        return self


class SkillsPreferences(BaseModel):
    """Required and bonus skill signals."""

    must_have: list[str] = Field(default_factory=list)
    nice_to_have: list[str] = Field(default_factory=list)


class Dealbreakers(BaseModel):
    """Hard negative filters; empty lists by default."""

    excluded_companies: list[str] = Field(default_factory=list)
    excluded_industries: list[str] = Field(default_factory=list)
    excluded_contract_types: list[str] = Field(default_factory=list)
    red_flag_keywords: list[str] = Field(default_factory=list)


class ScoringRubric(BaseModel):
    """Weighted fit scoring configuration (no compensation floor)."""

    role_seniority_weight: float = Field(default=0.30, ge=0.0, le=1.0)
    must_have_skills_weight: float = Field(default=0.35, ge=0.0, le=1.0)
    domain_fit_weight: float = Field(default=0.20, ge=0.0, le=1.0)
    nice_to_have_weight: float = Field(default=0.15, ge=0.0, le=1.0)
    min_fit_score: float = Field(default=7.5, ge=0.0, le=10.0)


class LayoutGuardrails(BaseModel):
    """Document readability and formatting invariants."""

    max_cv_pages: int = Field(default=1, ge=1)
    max_cover_letter_pages: int = Field(default=1, ge=1)
    min_font_size_pt: float = Field(default=10.0, ge=9.0)
    preserve_whitespace_and_margins: bool = True


class JobPreferences(BaseModel):
    """Target roles, filtering policies, scoring rubric, layout guardrails, and voice skill."""

    target_roles: TargetRoles = Field(default_factory=TargetRoles)
    locations: LocationsConfig = Field(default_factory=LocationsConfig)
    seniority_policy: SeniorityPolicy = Field(default_factory=SeniorityPolicy)
    freshness_policy: FreshnessPolicy = Field(default_factory=FreshnessPolicy)
    skills: SkillsPreferences = Field(default_factory=SkillsPreferences)
    dealbreakers: Dealbreakers = Field(default_factory=Dealbreakers)
    scoring_rubric: ScoringRubric = Field(default_factory=ScoringRubric)
    layout_guardrails: LayoutGuardrails = Field(default_factory=LayoutGuardrails)
    voice_skill_path: NonEmptyStr = DEFAULT_VOICE_SKILL_PATH


def load_job_preferences(path: Path | str) -> JobPreferences:
    """Load and validate JobPreferences from a YAML file."""
    data = load_yaml_mapping(path)
    return JobPreferences.model_validate(data)
