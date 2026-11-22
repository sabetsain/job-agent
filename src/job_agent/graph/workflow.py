"""LangGraph workflow assembly, SQLite checkpointing, and HITL runner."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from job_agent.graph.nodes import build_tailoring_nodes
from job_agent.graph.state import TailoringGraphState, WorkflowRunResult
from job_agent.llm.client import StructuredLLMClient
from job_agent.rendering.compiler import DocumentCompiler
from job_agent.schemas.preferences import LayoutGuardrails
from job_agent.schemas.profile import MasterProfile
from job_agent.storage.repository import JobRepository, StoredJob


def build_tailoring_graph(
    *,
    repository: JobRepository,
    profile: MasterProfile,
    llm_client: StructuredLLMClient,
    drafts_dir: Path | str,
    checkpointer: BaseCheckpointSaver[Any],
    compiler: DocumentCompiler | None = None,
    layout_guardrails: LayoutGuardrails | None = None,
    status_callback: Callable[[str], None] | None = None,
) -> CompiledStateGraph[Any]:
    """Compile the Stage 2 tailoring and HITL ideation StateGraph."""
    nodes = build_tailoring_nodes(
        repository=repository,
        profile=profile,
        llm_client=llm_client,
        drafts_dir=drafts_dir,
        compiler=compiler,
        layout_guardrails=layout_guardrails,
        status_callback=status_callback,
    )

    builder = StateGraph(TailoringGraphState)
    for name, fn in nodes.items():
        builder.add_node(name, fn)

    builder.add_edge(START, "planner")
    return builder.compile(checkpointer=checkpointer)


def _stored_job_to_posting_dict(job: StoredJob) -> dict[str, Any]:
    """Serialize a StoredJob into the canonical posting dict expected by graph nodes."""
    return {
        "job_id": job.job_id,
        "source": job.source,
        "external_id": job.external_id,
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "work_mode": job.work_mode.value,
        "language": job.language,
        "apply_url": job.apply_url,
        "description": job.description,
        "posted_at": job.posted_at.isoformat() if job.posted_at else None,
        "application_deadline": (
            job.application_deadline.isoformat() if job.application_deadline else None
        ),
    }


def _snapshot_to_result(
    app: CompiledStateGraph[Any],
    thread_id: str,
) -> WorkflowRunResult:
    """Convert a LangGraph StateSnapshot into a normalized WorkflowRunResult."""
    snapshot = app.get_state({"configurable": {"thread_id": thread_id}})
    values = dict(snapshot.values) if isinstance(snapshot.values, dict) else {}
    interrupts = tuple(getattr(snapshot, "interrupts", ()) or ())
    if interrupts:
        payload = interrupts[0].value
        interrupt_payload = dict(payload) if isinstance(payload, dict) else {"value": payload}
        return WorkflowRunResult(
            thread_id=thread_id,
            interrupted=True,
            interrupt_payload=interrupt_payload,
            final_status=None,
            state=values,
        )

    return WorkflowRunResult(
        thread_id=thread_id,
        interrupted=False,
        interrupt_payload=None,
        final_status=values.get("final_status"),
        state=values,
    )


class TailoringWorkflowRunner:
    """Stateful SQLite-checkpointed runner for Stage 2 drafting and HITL review."""

    def __init__(
        self,
        *,
        repository: JobRepository,
        profile: MasterProfile,
        llm_client: StructuredLLMClient,
        checkpoint_db_path: Path | str,
        drafts_dir: Path | str,
        compiler: DocumentCompiler | None = None,
        layout_guardrails: LayoutGuardrails | None = None,
        status_callback: Callable[[str], None] | None = None,
    ) -> None:
        self._repository = repository
        self._profile = profile
        self._llm_client = llm_client
        self._drafts_dir = Path(drafts_dir)

        target = str(checkpoint_db_path)
        if target != ":memory:":
            Path(target).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(target, check_same_thread=False)
        self._checkpointer = SqliteSaver(self._conn)
        self._app = build_tailoring_graph(
            repository=repository,
            profile=profile,
            llm_client=llm_client,
            drafts_dir=self._drafts_dir,
            checkpointer=self._checkpointer,
            compiler=compiler,
            layout_guardrails=layout_guardrails,
            status_callback=status_callback,
        )

    def close(self) -> None:
        """Close the underlying SQLite checkpoint connection cleanly."""
        if getattr(self, "_conn", None) is not None:
            self._conn.close()
            self._conn = None  # type: ignore[assignment]

    def __enter__(self) -> TailoringWorkflowRunner:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def draft_job(self, job_id: str, thread_id: str | None = None) -> WorkflowRunResult:
        """Run Stage 2 drafting for a stored job through to the Human Review interrupt."""
        stored_job = self._repository.get_job(job_id)
        if stored_job is None:
            raise ValueError(f"Job not found in repository: {job_id!r}")

        resolved_thread_id = thread_id or stored_job.langgraph_thread_id or f"job-{job_id}"
        fit_breakdown = (
            json.loads(stored_job.fit_breakdown_json)
            if stored_job.fit_breakdown_json
            else {}
        )
        evidence = fit_breakdown.get("evidence") or {}
        missing_posted_at = bool(
            fit_breakdown.get("missing_posted_at", stored_job.posted_at is None)
        )

        initial_state: TailoringGraphState = {
            "job_id": stored_job.job_id,
            "thread_id": resolved_thread_id,
            "posting": _stored_job_to_posting_dict(stored_job),
            "fit_breakdown": fit_breakdown,
            "missing_posted_at": missing_posted_at,
            "plan": None,
            "cv": None,
            "cover_letter": None,
            "major_gaps": list(evidence.get("major_gaps") or []),
            "audit_violations": [],
            "overflow_feedback": [],
            "remaining_warnings": [],
            "cv_pdf_path": stored_job.cv_pdf_path,
            "cover_letter_pdf_path": stored_job.cover_letter_pdf_path,
            "cv_pages": 0,
            "cover_letter_pages": 0,
            "internal_retry_count": 0,
            "ideation_notes": [],
            "session_verified_facts": [],
            "chat_history": [],
            "last_ideation_reply": None,
            "pending_user_message": None,
            "classified_intent": None,
            "final_status": None,
        }

        self._app.invoke(
            initial_state,
            config={"configurable": {"thread_id": resolved_thread_id}},
        )
        return _snapshot_to_result(self._app, resolved_thread_id)

    def resume_review(
        self,
        thread_id: str,
        user_input: str | dict[str, Any],
    ) -> WorkflowRunResult:
        """Resume an interrupted review thread with a command or conversational reply."""
        self._app.invoke(
            Command(resume=user_input),
            config={"configurable": {"thread_id": thread_id}},
        )
        return _snapshot_to_result(self._app, thread_id)

    def get_review_snapshot(self, thread_id: str) -> WorkflowRunResult:
        """Read the latest persisted checkpoint state and interrupt payload for a thread."""
        return _snapshot_to_result(self._app, thread_id)


def draft_job(
    job_id: str,
    *,
    repository: JobRepository,
    profile: MasterProfile,
    llm_client: StructuredLLMClient,
    checkpoint_db_path: Path | str,
    drafts_dir: Path | str,
    thread_id: str | None = None,
    compiler: DocumentCompiler | None = None,
    layout_guardrails: LayoutGuardrails | None = None,
    status_callback: Callable[[str], None] | None = None,
) -> WorkflowRunResult:
    """One-shot helper to draft a job using a scoped TailoringWorkflowRunner."""
    with TailoringWorkflowRunner(
        repository=repository,
        profile=profile,
        llm_client=llm_client,
        checkpoint_db_path=checkpoint_db_path,
        drafts_dir=drafts_dir,
        compiler=compiler,
        layout_guardrails=layout_guardrails,
        status_callback=status_callback,
    ) as runner:
        return runner.draft_job(job_id=job_id, thread_id=thread_id)


def resume_review(
    thread_id: str,
    user_input: str | dict[str, Any],
    *,
    repository: JobRepository,
    profile: MasterProfile,
    llm_client: StructuredLLMClient,
    checkpoint_db_path: Path | str,
    drafts_dir: Path | str,
    compiler: DocumentCompiler | None = None,
    layout_guardrails: LayoutGuardrails | None = None,
    status_callback: Callable[[str], None] | None = None,
) -> WorkflowRunResult:
    """One-shot helper to resume a review thread using a scoped TailoringWorkflowRunner."""
    with TailoringWorkflowRunner(
        repository=repository,
        profile=profile,
        llm_client=llm_client,
        checkpoint_db_path=checkpoint_db_path,
        drafts_dir=drafts_dir,
        compiler=compiler,
        layout_guardrails=layout_guardrails,
        status_callback=status_callback,
    ) as runner:
        return runner.resume_review(thread_id=thread_id, user_input=user_input)


def get_review_snapshot(
    thread_id: str,
    *,
    repository: JobRepository,
    profile: MasterProfile,
    llm_client: StructuredLLMClient,
    checkpoint_db_path: Path | str,
    drafts_dir: Path | str,
    compiler: DocumentCompiler | None = None,
    layout_guardrails: LayoutGuardrails | None = None,
    status_callback: Callable[[str], None] | None = None,
) -> WorkflowRunResult:
    """One-shot helper to read a checkpointed review snapshot cleanly."""
    with TailoringWorkflowRunner(
        repository=repository,
        profile=profile,
        llm_client=llm_client,
        checkpoint_db_path=checkpoint_db_path,
        drafts_dir=drafts_dir,
        compiler=compiler,
        layout_guardrails=layout_guardrails,
        status_callback=status_callback,
    ) as runner:
        return runner.get_review_snapshot(thread_id=thread_id)
