"""Pass 2 reasoning LLM auditor implementing blader/humanizer and semantic grounding."""

from __future__ import annotations

import json

from job_agent.auditing.models import AuditResult
from job_agent.llm.client import StructuredLLMClient
from job_agent.prompts import get_prompt
from job_agent.rendering.models import TailoredCoverLetter, TailoredCV
from job_agent.schemas.profile import MasterProfile


def build_llm_auditor_user_prompt(
    cv: TailoredCV,
    cover_letter: TailoredCoverLetter,
    major_gaps: list[str],
    profile: MasterProfile,
    session_verified_facts: list[str],
) -> str:
    """Serialize tailored drafts, major gaps, and verified profile facts for Pass 2."""
    payload = {
        "cv": cv.model_dump(mode="json"),
        "cover_letter": cover_letter.model_dump(mode="json"),
        "major_gaps": major_gaps,
        "master_profile": profile.model_dump(mode="json"),
        "session_verified_facts": session_verified_facts,
    }
    return (
        "Audit the following tailored CV, Cover Letter, and major_gaps list against "
        "master_profile and session_verified_facts.\n\n"
        f"{json.dumps(payload, indent=2, ensure_ascii=False)}"
    )


def run_llm_audit(
    cv: TailoredCV,
    cover_letter: TailoredCoverLetter,
    major_gaps: list[str],
    profile: MasterProfile,
    session_verified_facts: list[str],
    llm_client: StructuredLLMClient,
) -> AuditResult:
    """Invoke the reasoning-tier LLM auditor with prompts/auditor.md."""
    system_prompt = get_prompt("auditor")
    user_prompt = build_llm_auditor_user_prompt(
        cv=cv,
        cover_letter=cover_letter,
        major_gaps=major_gaps,
        profile=profile,
        session_verified_facts=session_verified_facts,
    )
    return llm_client.invoke_structured(
        tier="reasoning",
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        schema=AuditResult,
    )
