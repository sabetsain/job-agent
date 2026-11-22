"""Pydantic v2 diagnostic models for two-pass CV and Cover Letter auditing."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class AuditViolation(BaseModel):
    """Single surgical violation emitted by the deterministic or LLM auditor."""

    document: Literal["cv", "cover_letter", "major_gaps"]
    location: str
    rule: str
    offending_snippet: str
    fix_instruction: str


class AuditResult(BaseModel):
    """Structured outcome of an audit pass with optional surgical violations."""

    passed: bool
    violations: list[AuditViolation] = Field(default_factory=list)
