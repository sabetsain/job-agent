"""Pydantic v2 models for Stage 1 fit scoring evidence and deterministic decisions."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from job_agent.schemas.jobs import ApplicationStatus


class TransferableMatch(BaseModel):
    """Mapping between a requested skill and a candidate's adjacent verified skill."""

    requested_skill: str
    candidate_skill: str
    rationale: str


class ScoringEvidence(BaseModel):
    """Structured evidence extracted by the free scoring model via LangChain."""

    is_technical: bool = True
    inferred_min_years: int | None = Field(default=None, ge=0)
    seniority_tier: Literal["entry_level", "stretch", "senior_plus"]
    seniority_signals: list[str] = Field(default_factory=list)
    must_have_skills: list[str] = Field(default_factory=list)
    direct_matches: list[str] = Field(default_factory=list)
    transferable_matches: list[TransferableMatch] = Field(default_factory=list)
    missing_must_haves: list[str] = Field(default_factory=list)
    role_seniority_score: float = Field(ge=0.0, le=10.0)
    must_have_skills_score: float = Field(ge=0.0, le=10.0)
    domain_fit_score: float = Field(ge=0.0, le=10.0)
    nice_to_have_score: float = Field(ge=0.0, le=10.0)
    major_gaps: list[str] = Field(default_factory=list)
    rationale: str


class FitDecision(BaseModel):
    """Deterministic Python gating result persisted on the job row."""

    passed: bool
    status: ApplicationStatus
    fit_score: float = Field(ge=0.0, le=10.0)
    must_have_coverage: float = Field(ge=0.0, le=1.0)
    effective_tier: Literal["entry_level", "stretch", "senior_plus"]
    tier_threshold: float = Field(ge=0.0, le=1.0)
    missing_posted_at: bool
    rejection_reason: str | None = None
    evidence: ScoringEvidence

    def to_breakdown_json(self) -> str:
        """Serialize the full deterministic decision and LLM evidence to JSON."""
        return self.model_dump_json()


class ScoringRunSummary(BaseModel):
    """Counts produced by scoring all Pending_Scoring postings."""

    evaluated: int = 0
    queued_for_drafting: int = 0
    scored_out: int = 0
    missing_posted_at_count: int = 0
