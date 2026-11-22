"""LangGraph node implementations for Stage 2 tailoring, auditing, rendering, and HITL."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from langgraph.graph import END
from langgraph.types import Command, interrupt

from job_agent.auditing import AuditViolation, run_deterministic_audit, run_llm_audit
from job_agent.graph.state import (
    DraftDocuments,
    IdeationResponse,
    TailoringGraphState,
    TailoringPlan,
    ThreadIntentDecision,
)
from job_agent.llm.client import StructuredLLMClient
from job_agent.prompts import get_prompt
from job_agent.rendering.compiler import DocumentCompiler
from job_agent.rendering.models import TailoredCoverLetter, TailoredCV
from job_agent.schemas.jobs import ApplicationStatus
from job_agent.schemas.preferences import LayoutGuardrails
from job_agent.schemas.profile import MasterProfile
from job_agent.storage.repository import JobRepository

MAX_INTERNAL_RETRIES = 2
WORKSHOPPING_MESSAGE = "Workshopping now..."


def _dedupe_preserve_order(existing: list[str], incoming: list[str]) -> list[str]:
    """Merge non-empty strings while preserving original insertion order."""
    seen: set[str] = set()
    merged: list[str] = []
    for raw in [*existing, *incoming]:
        cleaned = raw.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        merged.append(cleaned)
    return merged


def _format_violation_warning(violation: AuditViolation) -> str:
    """Format an AuditViolation into a concise human-readable review warning."""
    return (
        f"[{violation.document}:{violation.location}] ({violation.rule}) "
        f"{violation.fix_instruction} [snippet: {violation.offending_snippet}]"
    )


def _dump_json(payload: dict[str, Any]) -> str:
    """Serialize node prompt context cleanly with UTF-8 preservation."""
    return json.dumps(payload, indent=2, ensure_ascii=False)


def _parse_review_input(
    user_input: Any,
) -> tuple[Literal["approve", "dismiss", "message"], str | None]:
    """Normalize CLI or Slack human review resume payload into action + optional text."""
    if isinstance(user_input, dict):
        action = str(user_input.get("action") or "").strip().lower()
        if action == "approve":
            return "approve", None
        if action == "dismiss":
            return "dismiss", None
        text = str(user_input.get("text") or user_input.get("message") or "").strip()
        return "message", text

    text = str(user_input or "").strip()
    lowered = text.lower()
    if lowered == "/approve":
        return "approve", None
    if lowered == "/dismiss":
        return "dismiss", None
    return "message", text


def _build_planner_user_prompt(
    state: TailoringGraphState,
    profile_json: dict[str, Any],
) -> str:
    payload = {
        "posting": state.get("posting") or {},
        "fit_breakdown": state.get("fit_breakdown") or {},
        "master_profile": profile_json,
        "ideation_notes": state.get("ideation_notes") or [],
        "session_verified_facts": state.get("session_verified_facts") or [],
        "previous_plan": state.get("plan"),
    }
    return (
        "Build a concrete TailoringPlan for the target job posting using verified "
        "MasterProfile and session_verified_facts.\n\n"
        f"{_dump_json(payload)}"
    )


def _build_writer_user_prompt(
    state: TailoringGraphState,
    profile_json: dict[str, Any],
) -> str:
    payload = {
        "posting": state.get("posting") or {},
        "plan": state.get("plan") or {},
        "master_profile": profile_json,
        "ideation_notes": state.get("ideation_notes") or [],
        "session_verified_facts": state.get("session_verified_facts") or [],
        "previous_cv": state.get("cv"),
        "previous_cover_letter": state.get("cover_letter"),
        "audit_violations": state.get("audit_violations") or [],
        "overflow_feedback": state.get("overflow_feedback") or [],
    }
    return (
        "Draft or surgically revise TailoredCV, TailoredCoverLetter, and major_gaps "
        "strictly adhering to the TailoringPlan, MasterProfile, session_verified_facts, "
        "and any audit_violations or overflow_feedback.\n\n"
        f"{_dump_json(payload)}"
    )


def _build_intent_router_user_prompt(state: TailoringGraphState) -> str:
    posting = state.get("posting") or {}
    payload = {
        "user_message": state.get("pending_user_message") or "",
        "posting_summary": {
            "title": posting.get("title", ""),
            "company": posting.get("company", ""),
            "language": posting.get("language", ""),
        },
        "major_gaps": state.get("major_gaps") or [],
        "recent_chat_history": (state.get("chat_history") or [])[-6:],
    }
    return (
        "Classify the user_message in this review thread as CHAT or REITERATE.\n\n"
        f"{_dump_json(payload)}"
    )


def _build_ideation_user_prompt(
    state: TailoringGraphState,
    profile_json: dict[str, Any],
) -> str:
    payload = {
        "classified_intent": state.get("classified_intent") or "CHAT",
        "user_message": state.get("pending_user_message") or "",
        "posting": state.get("posting") or {},
        "fit_breakdown": state.get("fit_breakdown") or {},
        "major_gaps": state.get("major_gaps") or [],
        "plan": state.get("plan"),
        "cv": state.get("cv"),
        "cover_letter": state.get("cover_letter"),
        "master_profile": profile_json,
        "ideation_notes": state.get("ideation_notes") or [],
        "session_verified_facts": state.get("session_verified_facts") or [],
        "chat_history": state.get("chat_history") or [],
    }
    return (
        "Respond to the user_message in this review thread, extract any profile "
        "additions/corrections and framing notes, and return IdeationResponse.\n\n"
        f"{_dump_json(payload)}"
    )


def build_tailoring_nodes(
    *,
    repository: JobRepository,
    profile: MasterProfile,
    llm_client: StructuredLLMClient,
    drafts_dir: Path | str,
    compiler: DocumentCompiler | None = None,
    layout_guardrails: LayoutGuardrails | None = None,
    status_callback: Callable[[str], None] | None = None,
) -> dict[str, Callable[[TailoringGraphState], Any]]:
    """Construct all dependency-injected LangGraph node callables."""
    resolved_drafts_dir = Path(drafts_dir)
    resolved_compiler = compiler or DocumentCompiler()
    resolved_guardrails = layout_guardrails or LayoutGuardrails()
    profile_json = profile.model_dump(mode="json")

    def emit_status(message: str) -> None:
        if status_callback is not None:
            status_callback(message)

    def _audit_failure_command(
        state: TailoringGraphState,
        violations: list[AuditViolation],
    ) -> Command[Literal["writer", "compiler"]]:
        retry_count = int(state.get("internal_retry_count") or 0)
        violations_dicts = [v.model_dump(mode="json") for v in violations]
        if retry_count < MAX_INTERNAL_RETRIES:
            return Command(
                update={
                    "internal_retry_count": retry_count + 1,
                    "audit_violations": violations_dicts,
                },
                goto="writer",
            )
        warning_lines = [_format_violation_warning(v) for v in violations]
        merged_warnings = _dedupe_preserve_order(
            list(state.get("remaining_warnings") or []),
            warning_lines,
        )
        return Command(
            update={
                "audit_violations": violations_dicts,
                "remaining_warnings": merged_warnings,
            },
            goto="compiler",
        )

    def planner(state: TailoringGraphState) -> Command[Literal["writer"]]:
        """Plan tailored framing, selected facts, section ordering, and major gaps."""
        if state.get("plan") is None and int(state.get("internal_retry_count") or 0) == 0:
            emit_status(WORKSHOPPING_MESSAGE)

        plan_model = llm_client.invoke_structured(
            tier="reasoning",
            system_prompt=get_prompt("planner"),
            user_prompt=_build_planner_user_prompt(state, profile_json),
            schema=TailoringPlan,
        )
        return Command(
            update={
                "plan": plan_model.model_dump(mode="json"),
                "major_gaps": list(plan_model.major_gaps),
            },
            goto="writer",
        )

    def writer(state: TailoringGraphState) -> Command[Literal["deterministic_auditor"]]:
        """Draft or surgically revise TailoredCV and TailoredCoverLetter."""
        draft = llm_client.invoke_structured(
            tier="reasoning",
            system_prompt=get_prompt("writer"),
            user_prompt=_build_writer_user_prompt(state, profile_json),
            schema=DraftDocuments,
        )
        return Command(
            update={
                "cv": draft.cv.model_dump(mode="json"),
                "cover_letter": draft.cover_letter.model_dump(mode="json"),
                "major_gaps": list(draft.major_gaps),
                "audit_violations": [],
                "overflow_feedback": [],
            },
            goto="deterministic_auditor",
        )

    def deterministic_auditor(
        state: TailoringGraphState,
    ) -> Command[Literal["llm_auditor", "writer", "compiler"]]:
        """Pass 1 deterministic Python gate (0 tokens) before LLM auditing."""
        cv = TailoredCV.model_validate(state["cv"])
        cover_letter = TailoredCoverLetter.model_validate(state["cover_letter"])
        result = run_deterministic_audit(
            cv=cv,
            cover_letter=cover_letter,
            profile=profile,
            session_verified_facts=list(state.get("session_verified_facts") or []),
        )
        if result.passed:
            return Command(update={"audit_violations": []}, goto="llm_auditor")
        return _audit_failure_command(state, result.violations)

    def llm_auditor(
        state: TailoringGraphState,
    ) -> Command[Literal["compiler", "writer"]]:
        """Pass 2 reasoning LLM auditor covering semantic truthfulness and humanizer checks."""
        cv = TailoredCV.model_validate(state["cv"])
        cover_letter = TailoredCoverLetter.model_validate(state["cover_letter"])
        result = run_llm_audit(
            cv=cv,
            cover_letter=cover_letter,
            major_gaps=list(state.get("major_gaps") or []),
            profile=profile,
            session_verified_facts=list(state.get("session_verified_facts") or []),
            llm_client=llm_client,
        )
        if result.passed:
            return Command(update={"audit_violations": []}, goto="compiler")
        return _audit_failure_command(state, result.violations)

    def compiler_node(
        state: TailoringGraphState,
    ) -> Command[Literal["writer", "human_review"]]:
        """Compile Typst PDFs, enforce page guardrails, and persist Pending_Review."""
        job_id = state["job_id"]
        cv = TailoredCV.model_validate(state["cv"])
        cover_letter = TailoredCoverLetter.model_validate(state["cover_letter"])
        compile_result = resolved_compiler.compile_application(
            cv=cv,
            cover_letter=cover_letter,
            output_dir=resolved_drafts_dir / job_id,
            guardrails=resolved_guardrails,
        )
        retry_count = int(state.get("internal_retry_count") or 0)
        if not compile_result.passed and retry_count < MAX_INTERNAL_RETRIES:
            return Command(
                update={
                    "internal_retry_count": retry_count + 1,
                    "overflow_feedback": list(compile_result.overflow_feedback),
                    "cv_pdf_path": compile_result.cv_pdf_path,
                    "cover_letter_pdf_path": compile_result.cover_letter_pdf_path,
                    "cv_pages": compile_result.cv_pages,
                    "cover_letter_pages": compile_result.cover_letter_pages,
                },
                goto="writer",
            )

        overflow_warnings = (
            list(compile_result.overflow_feedback) if not compile_result.passed else []
        )
        merged_warnings = _dedupe_preserve_order(
            list(state.get("remaining_warnings") or []),
            overflow_warnings,
        )
        repository.update_job(
            job_id,
            langgraph_thread_id=state["thread_id"],
            cv_pdf_path=compile_result.cv_pdf_path,
            cover_letter_pdf_path=compile_result.cover_letter_pdf_path,
            status=ApplicationStatus.PENDING_REVIEW,
        )
        return Command(
            update={
                "overflow_feedback": list(compile_result.overflow_feedback),
                "remaining_warnings": merged_warnings,
                "cv_pdf_path": compile_result.cv_pdf_path,
                "cover_letter_pdf_path": compile_result.cover_letter_pdf_path,
                "cv_pages": compile_result.cv_pages,
                "cover_letter_pages": compile_result.cover_letter_pages,
            },
            goto="human_review",
        )

    def human_review(
        state: TailoringGraphState,
    ) -> Command[Literal["finalize", "intent_router"]]:
        """Pause at HITL interrupt and route resumed user action or message."""
        posting = state.get("posting") or {}
        fit_breakdown = state.get("fit_breakdown") or {}
        payload: dict[str, Any] = {
            "job_id": state["job_id"],
            "title": posting.get("title", ""),
            "company": posting.get("company", ""),
            "location": posting.get("location", ""),
            "language": posting.get("language", ""),
            "apply_url": posting.get("apply_url", ""),
            "fit_score": fit_breakdown.get("fit_score"),
            "major_gaps": list(state.get("major_gaps") or []),
            "missing_posted_at": bool(state.get("missing_posted_at", False)),
            "cv_pdf_path": state.get("cv_pdf_path"),
            "cover_letter_pdf_path": state.get("cover_letter_pdf_path"),
            "remaining_warnings": list(state.get("remaining_warnings") or []),
            "last_ideation_reply": state.get("last_ideation_reply"),
        }
        user_input = interrupt(payload)
        action, text = _parse_review_input(user_input)
        if action == "approve":
            return Command(
                update={
                    "final_status": ApplicationStatus.READY_TO_SUBMIT.value,
                    "pending_user_message": None,
                },
                goto="finalize",
            )
        if action == "dismiss":
            return Command(
                update={
                    "final_status": ApplicationStatus.REJECTED.value,
                    "pending_user_message": None,
                },
                goto="finalize",
            )
        return Command(
            update={
                "pending_user_message": text or "",
                "final_status": None,
            },
            goto="intent_router",
        )

    def intent_router(state: TailoringGraphState) -> Command[Literal["ideation"]]:
        """Classify free-form review replies as CHAT or REITERATE via free scoring tier."""
        decision = llm_client.invoke_structured(
            tier="scoring",
            system_prompt=get_prompt("intent_router"),
            user_prompt=_build_intent_router_user_prompt(state),
            schema=ThreadIntentDecision,
        )
        return Command(
            update={"classified_intent": decision.intent},
            goto="ideation",
        )

    def ideation(
        state: TailoringGraphState,
    ) -> Command[Literal["human_review", "planner"]]:
        """Handle conversational ideation, capture facts/notes, and trigger REITERATE."""
        intent = state.get("classified_intent") or "CHAT"
        user_message = (state.get("pending_user_message") or "").strip()
        response = llm_client.invoke_structured(
            tier="reasoning",
            system_prompt=get_prompt("ideation"),
            user_prompt=_build_ideation_user_prompt(state, profile_json),
            schema=IdeationResponse,
        )

        incoming_notes: list[str] = []
        if response.captured_ideation_note and response.captured_ideation_note.strip():
            incoming_notes.append(response.captured_ideation_note.strip())
        elif intent == "REITERATE" and user_message:
            incoming_notes.append(user_message)
        updated_notes = _dedupe_preserve_order(
            list(state.get("ideation_notes") or []),
            incoming_notes,
        )

        suggestion_facts: list[str] = []
        for suggestion in response.detected_profile_suggestions:
            repository.add_profile_suggestion(
                job_id=state["job_id"],
                kind=suggestion.kind,
                fact_text=suggestion.fact_text,
                category=suggestion.category,
            )
            suggestion_facts.append(suggestion.fact_text)

        updated_facts = _dedupe_preserve_order(
            list(state.get("session_verified_facts") or []),
            [*response.new_session_verified_facts, *suggestion_facts],
        )

        updated_history = [
            *list(state.get("chat_history") or []),
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": response.reply},
        ]

        base_update: dict[str, Any] = {
            "ideation_notes": updated_notes,
            "session_verified_facts": updated_facts,
            "chat_history": updated_history,
            "last_ideation_reply": response.reply,
            "pending_user_message": None,
            "classified_intent": None,
        }

        if intent == "REITERATE":
            repository.update_job(state["job_id"], status=ApplicationStatus.REVISING)
            emit_status(WORKSHOPPING_MESSAGE)
            return Command(
                update={
                    **base_update,
                    "internal_retry_count": 0,
                    "audit_violations": [],
                    "overflow_feedback": [],
                    "remaining_warnings": [],
                },
                goto="planner",
            )

        return Command(update=base_update, goto="human_review")

    def finalize(state: TailoringGraphState) -> Command[Literal["__end__"]]:
        """Persist final approved or dismissed application status and terminate."""
        final_status = state["final_status"]
        if final_status is not None:
            repository.update_job(state["job_id"], status=ApplicationStatus(final_status))
        return Command(update={}, goto=END)

    return {
        "planner": planner,
        "writer": writer,
        "deterministic_auditor": deterministic_auditor,
        "llm_auditor": llm_auditor,
        "compiler": compiler_node,
        "human_review": human_review,
        "intent_router": intent_router,
        "ideation": ideation,
        "finalize": finalize,
    }
