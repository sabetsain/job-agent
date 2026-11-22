"""Two-pass auditing package: Pass 1 deterministic gate and Pass 2 reasoning LLM auditor."""

from job_agent.auditing.deterministic import run_deterministic_audit
from job_agent.auditing.llm_auditor import build_llm_auditor_user_prompt, run_llm_audit
from job_agent.auditing.models import AuditResult, AuditViolation

__all__ = [
    "AuditResult",
    "AuditViolation",
    "build_llm_auditor_user_prompt",
    "run_deterministic_audit",
    "run_llm_audit",
]
