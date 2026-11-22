"""Pydantic v2 structured output schemas and LangGraph state definition for tailoring."""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field

from job_agent.rendering.models import CVSectionKey, TailoredCoverLetter, TailoredCV


class TailoringPlan(BaseModel):
    """Structured tailoring plan emitted by the Planner node before drafting."""

    angle_summary: str
    selected_experiences: list[str]
    selected_projects: list[str]
    transferable_framings: list[str]
    major_gaps: list[str]
    section_order: list[CVSectionKey]
    notes: str


class DraftDocuments(BaseModel):
    """Structured CV, Cover Letter, and major-gap output from the Writer node."""

    cv: TailoredCV
    cover_letter: TailoredCoverLetter
    major_gaps: list[str]


class ThreadIntentDecision(BaseModel):
    """Free scoring-model classification of a review thread user reply."""

    intent: Literal["CHAT", "REITERATE"]
    rationale: str


class ProfileSuggestionDraft(BaseModel):
    """Detected profile addition or correction for the weekly MasterProfile cache."""

    kind: Literal["addition", "correction"]
    fact_text: str
    category: str


class IdeationResponse(BaseModel):
    """Structured output from the Ideation co-pilot node."""

    reply: str
    captured_ideation_note: str | None = None
    new_session_verified_facts: list[str] = Field(default_factory=list)
    detected_profile_suggestions: list[ProfileSuggestionDraft] = Field(default_factory=list)


class WorkflowRunResult(BaseModel):
    """Normalized return value from drafting, resuming, or inspecting a graph thread."""

    thread_id: str
    interrupted: bool
    interrupt_payload: dict[str, Any] | None = None
    final_status: str | None = None
    state: dict[str, Any] = Field(default_factory=dict)


class TailoringGraphState(TypedDict, total=False):
    """Checkpointed LangGraph state for Stage 2 tailoring and HITL ideation."""

    job_id: str
    thread_id: str
    posting: dict[str, Any]
    fit_breakdown: dict[str, Any]
    missing_posted_at: bool
    plan: dict[str, Any] | None
    cv: dict[str, Any] | None
    cover_letter: dict[str, Any] | None
    major_gaps: list[str]
    audit_violations: list[dict[str, Any]]
    overflow_feedback: list[str]
    remaining_warnings: list[str]
    cv_pdf_path: str | None
    cover_letter_pdf_path: str | None
    cv_pages: int
    cover_letter_pages: int
    internal_retry_count: int
    ideation_notes: list[str]
    session_verified_facts: list[str]
    chat_history: list[dict[str, str]]
    last_ideation_reply: str | None
    pending_user_message: str | None
    classified_intent: Literal["CHAT", "REITERATE"] | None
    final_status: str | None
