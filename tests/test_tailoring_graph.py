"""Integration tests for Stage 2 LangGraph tailoring, auditing, checkpointing, and HITL."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypeVar

import pypdf
from pydantic import BaseModel

from job_agent.auditing import AuditResult, AuditViolation
from job_agent.graph import (
    DraftDocuments,
    IdeationResponse,
    ProfileSuggestionDraft,
    TailoringPlan,
    TailoringWorkflowRunner,
    ThreadIntentDecision,
)
from job_agent.llm.client import ModelTier
from job_agent.rendering.compiler import DocumentCompiler
from job_agent.rendering.models import (
    CVBullet,
    CVEducation,
    CVExperience,
    CVProject,
    CVSkillCategory,
    CompileResult,
    TailoredCoverLetter,
    TailoredCV,
)
from job_agent.schemas.jobs import ApplicationStatus, JobPosting, WorkMode
from job_agent.schemas.preferences import LayoutGuardrails
from job_agent.schemas.profile import (
    EducationEntry,
    ExperienceBullet,
    ExperienceEntry,
    Identity,
    LanguageProficiency,
    MasterProfile,
    ProjectEntry,
    SkillsCatalog,
)
from job_agent.scoring.models import FitDecision, ScoringEvidence
from job_agent.storage.repository import JobRepository

T = TypeVar("T", bound=BaseModel)


def _sample_profile() -> MasterProfile:
    return MasterProfile(
        identity=Identity(
            full_name="Sebastian McConnell",
            email="sebastian@example.com",
            phone="+45 12 34 56 78",
            location="Copenhagen, Denmark",
            linkedin_url="https://linkedin.com/in/sebastian",
            github_url="https://github.com/sebastian",
            website_url="https://sebastian.dev",
        ),
        summary_seed=(
            "BSc in Computer Science & Data Science at University of Copenhagen "
            "with engineering experience at LEGO Group."
        ),
        experiences=[
            ExperienceEntry(
                company="LEGO Group",
                title="Student Developer",
                start_date="2024-06",
                end_date="2025-12",
                location="Copenhagen, Denmark",
                bullets=[
                    ExperienceBullet(
                        label="Developer Enablement",
                        text="Built internal Python CLI tooling and CI templates used by ~300 engineers.",
                        metrics=["~300 engineers"],
                        skills=["Python", "GitHub Actions", "Docker"],
                    ),
                    ExperienceBullet(
                        label="Observability",
                        text="Maintained OpenTelemetry ingestion pipelines handling ~1200 events per minute.",
                        metrics=["~1200 events/min"],
                        skills=["Python", "OpenTelemetry", "Pulumi"],
                    ),
                ],
            )
        ],
        projects=[
            ProjectEntry(
                name="Deterministic Graph Orchestrator",
                url="https://github.com/sebastian/graph-orch",
                bullets=[
                    "Implemented stateful Python workflow engine with SQLite checkpointing and strict Pydantic schemas."
                ],
                skills=["Python", "LangGraph", "SQLite", "Pydantic"],
            )
        ],
        education=[
            EducationEntry(
                institution="University of Copenhagen",
                degree="BSc in Computer Science & Data Science",
                start_date="2022-09",
                end_date="2025-06",
                location="Copenhagen, Denmark",
                highlights=[
                    "Bachelor thesis on deterministic evaluation harnesses for agentic pipelines."
                ],
            )
        ],
        languages=[
            LanguageProficiency(language="en", proficiency="Native"),
            LanguageProficiency(language="da", proficiency="Fluent"),
        ],
        skills=SkillsCatalog(
            languages=["Python", "TypeScript", "SQL"],
            frameworks=["FastAPI", "Pydantic", "LangGraph"],
            infrastructure=["Docker", "Pulumi", "GitHub Actions"],
            databases=["PostgreSQL", "SQLite"],
        ),
    )


def _clean_en_cv(
    *,
    section_order: list[str] | None = None,
    title: str = "Student Developer",
    start_date: str = "2024-06",
) -> TailoredCV:
    return TailoredCV(
        language="en",
        full_name="Sebastian McConnell",
        email="sebastian@example.com",
        phone="+45 12 34 56 78",
        location="Copenhagen, Denmark",
        linkedin_url="https://linkedin.com/in/sebastian",
        github_url="https://github.com/sebastian",
        website_url="https://sebastian.dev",
        profile_summary=(
            "Computer Science and Data Science graduate from the University of Copenhagen "
            "with backend and developer tooling experience at LEGO Group. I build reliable "
            "Python services, CI/CD automation, and deterministic data pipelines with strict schema checks."
        ),
        section_order=section_order or ["experience", "projects", "education", "skills"],  # type: ignore[arg-type]
        experiences=[
            CVExperience(
                company="LEGO Group",
                title=title,
                start_date=start_date,
                end_date="2025-12",
                location="Copenhagen, Denmark",
                bullets=[
                    CVBullet(
                        lead="Developer Enablement",
                        text="Built internal Python CLI tooling and GitHub Actions workflows adopted by ~300 engineers.",
                    ),
                    CVBullet(
                        lead="Observability Pipeline",
                        text="Maintained OpenTelemetry ingestion pipelines and Pulumi infrastructure handling ~1200 events per minute.",
                    ),
                ],
            )
        ],
        projects=[
            CVProject(
                name="Deterministic Graph Orchestrator",
                url="https://github.com/sebastian/graph-orch",
                bullets=[
                    CVBullet(
                        lead="Workflow Engine",
                        text="Implemented stateful Python orchestration with SQLite checkpointing and Pydantic v2 validation.",
                    )
                ],
            )
        ],
        education=[
            CVEducation(
                institution="University of Copenhagen",
                degree="BSc in Computer Science & Data Science",
                start_date="2022-09",
                end_date="2025-06",
                location="Copenhagen, Denmark",
                highlights=[
                    "Bachelor thesis on deterministic evaluation harnesses for agentic pipelines."
                ],
            )
        ],
        skills=[
            CVSkillCategory(category="Languages", items=["Python", "TypeScript", "SQL"]),
            CVSkillCategory(
                category="Backend & Infra",
                items=["FastAPI", "Pydantic", "Docker", "Pulumi"],
            ),
        ],
        languages_spoken=["English (Native)", "Danish (Fluent)"],
    )


def _clean_en_cover_letter() -> TailoredCoverLetter:
    return TailoredCoverLetter(
        language="en",
        full_name="Sebastian McConnell",
        email="sebastian@example.com",
        phone="+45 12 34 56 78",
        location="Copenhagen, Denmark",
        linkedin_url="https://linkedin.com/in/sebastian",
        recipient_company="Nordic Cloud Systems",
        role_title="Junior Backend Engineer",
        date_str="November 22, 2026",
        greeting="Dear Hiring Team at Nordic Cloud Systems,",
        paragraphs=[
            (
                "Building telemetry ingestion services that reject malformed payloads before they hit "
                "downstream storage matches the engineering problems I enjoy solving most. Your open "
                "Junior Backend Engineer role caught my attention because Nordic Cloud Systems runs "
                "strictly typed Python services at high throughput across European customer clusters. "
                "I recently completed my BSc in Computer Science and Data Science at the University "
                "of Copenhagen, following eighteen months of hands-on backend and developer tooling "
                "work inside LEGO Group."
            ),
            (
                "At LEGO Group, I worked as a Student Developer building internal Python CLI tools, "
                "reusable GitHub Actions workflows, and OpenTelemetry ingestion pipelines. Our tooling "
                "supported ~300 engineers across product squads, while the telemetry collectors "
                "processed ~1200 events per minute with strict schema validation. I also helped "
                "maintain cloud infrastructure defined in Pulumi and containerized local test setups "
                "with Docker so teams could reproduce production failures before merging pull requests. "
                "That daily feedback loop taught me to keep interfaces simple, write deterministic tests, "
                "and document failure modes clearly for other developers."
            ),
            (
                "During my bachelor thesis and personal engineering work, I deepened my focus on "
                "reliable Python orchestration and data modeling. For my thesis at the University of "
                "Copenhagen, I designed deterministic evaluation harnesses for stateful workflows, "
                "combining SQLite persistence with Pydantic v2 contracts to catch regressions early. "
                "When I do not know a specific hosted vendor tool yet, I learn its primitives quickly "
                "by mapping them to infrastructure and CI concepts I have already shipped in production."
            ),
            (
                "Nordic Cloud Systems stands out to me as a pragmatic engineering team that values "
                "clean architecture, fast feedback cycles, and measurable reliability over hype. I am "
                "confident that my foundation in Python backend services, schema validation, and "
                "developer enablement will let me contribute steadily from my first sprint. I am excited "
                "by the opportunity to further discuss how my background fits the role!"
            ),
        ],
        sign_off="Kind Regards,",
    )


def _sample_plan(
    section_order: list[str] | None = None,
    notes: str = "Emphasize Python backend and deterministic orchestration.",
) -> TailoringPlan:
    return TailoringPlan(
        angle_summary="Bridge LEGO Group backend enablement and KU thesis work to Nordic Cloud Systems.",
        selected_experiences=["LEGO Group - Student Developer"],
        selected_projects=["Deterministic Graph Orchestrator"],
        transferable_framings=["Frame Pulumi IaC as directly transferable to Terraform workflows."],
        major_gaps=["Go production experience"],
        section_order=section_order or ["experience", "projects", "education", "skills"],  # type: ignore[arg-type]
        notes=notes,
    )


def _seed_queued_job(
    repo: JobRepository,
    job_id: str = "job-001",
    *,
    apply_url: str = "https://nordiccloud.example.com/jobs/junior-backend",
    missing_posted_at: bool = True,
) -> str:
    posting = JobPosting(
        job_id=job_id,
        source="manual",
        title="Junior Backend Engineer",
        company="Nordic Cloud Systems",
        location="Copenhagen, Denmark",
        work_mode=WorkMode.HYBRID,
        language="en",
        apply_url=apply_url,
        description="Build reliable Python ingestion services and APIs. Go experience is a plus.",
        posted_at=None if missing_posted_at else datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc),
    )
    repo.insert_job(posting, status=ApplicationStatus.QUEUED_FOR_DRAFTING)
    decision = FitDecision(
        passed=True,
        status=ApplicationStatus.QUEUED_FOR_DRAFTING,
        fit_score=8.7,
        must_have_coverage=0.9,
        effective_tier="entry_level",
        tier_threshold=0.65,
        missing_posted_at=missing_posted_at,
        evidence=ScoringEvidence(
            seniority_tier="entry_level",
            must_have_skills=["Python", "SQL", "Docker"],
            direct_matches=["Python", "SQL", "Docker"],
            role_seniority_score=9.0,
            must_have_skills_score=9.0,
            domain_fit_score=8.5,
            nice_to_have_score=7.5,
            major_gaps=["Go production experience"],
            rationale="Strong Python backend match.",
        ),
    )
    repo.update_job(
        job_id,
        fit_score=decision.fit_score,
        fit_breakdown_json=decision.to_breakdown_json(),
    )
    return job_id


class ScriptedLLMClient:
    """Deterministic fake StructuredLLMClient recording every call by schema and tier."""

    def __init__(self, handlers: dict[type[BaseModel], Callable[[ModelTier, str, str], BaseModel]]) -> None:
        self._handlers = handlers
        self.calls: list[dict[str, Any]] = []

    def invoke_structured(
        self,
        tier: ModelTier,
        system_prompt: str,
        user_prompt: str,
        schema: type[T],
    ) -> T:
        self.calls.append(
            {
                "tier": tier,
                "schema": schema.__name__,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
            }
        )
        handler = self._handlers[schema]
        result = handler(tier, system_prompt, user_prompt)
        return result  # type: ignore[return-value]

    def calls_for(self, schema: type[BaseModel]) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["schema"] == schema.__name__]


class CountingCompiler(DocumentCompiler):
    """DocumentCompiler wrapper counting invocations and optionally forcing page overflow."""

    def __init__(self, *, fail_first_n: int = 0) -> None:
        super().__init__()
        self.compile_count = 0
        self.fail_first_n = fail_first_n

    def compile_application(
        self,
        cv: TailoredCV,
        cover_letter: TailoredCoverLetter,
        output_dir: Path | str,
        *,
        body_font_size_pt: float = 10.0,
        guardrails: LayoutGuardrails | None = None,
        cv_filename: str = "cv.pdf",
        cover_letter_filename: str = "cover_letter.pdf",
    ) -> CompileResult:
        self.compile_count += 1
        result = super().compile_application(
            cv=cv,
            cover_letter=cover_letter,
            output_dir=output_dir,
            body_font_size_pt=body_font_size_pt,
            guardrails=guardrails,
            cv_filename=cv_filename,
            cover_letter_filename=cover_letter_filename,
        )
        if self.compile_count <= self.fail_first_n:
            return CompileResult(
                passed=False,
                cv_pdf_path=result.cv_pdf_path,
                cover_letter_pdf_path=result.cover_letter_pdf_path,
                cv_pages=2,
                cover_letter_pages=1,
                overflow_feedback=[
                    "CV rendered to 2 pages, exceeding max_cv_pages=1. Shorten prose."
                ],
            )
        return result


def _default_handlers() -> dict[type[BaseModel], Callable[[ModelTier, str, str], BaseModel]]:
    return {
        TailoringPlan: lambda _tier, _sys, _usr: _sample_plan(),
        DraftDocuments: lambda _tier, _sys, _usr: DraftDocuments(
            cv=_clean_en_cv(),
            cover_letter=_clean_en_cover_letter(),
            major_gaps=["Go production experience"],
        ),
        AuditResult: lambda _tier, _sys, _usr: AuditResult(passed=True, violations=[]),
        ThreadIntentDecision: lambda _tier, _sys, _usr: ThreadIntentDecision(
            intent="CHAT", rationale="Conversational question."
        ),
        IdeationResponse: lambda _tier, _sys, _usr: IdeationResponse(
            reply="Let us emphasize your Python orchestration work.",
            captured_ideation_note=None,
            new_session_verified_facts=[],
            detected_profile_suggestions=[],
        ),
    }


def test_initial_draft_through_to_pending_review_and_apply_url(tmp_path: Path) -> None:
    repo = JobRepository(tmp_path / "jobs.db")
    job_id = _seed_queued_job(repo, apply_url="https://nordiccloud.example.com/apply/42")
    statuses: list[str] = []
    llm = ScriptedLLMClient(_default_handlers())
    compiler = CountingCompiler()

    with TailoringWorkflowRunner(
        repository=repo,
        profile=_sample_profile(),
        llm_client=llm,
        checkpoint_db_path=tmp_path / "checkpoints.db",
        drafts_dir=tmp_path / "drafts",
        compiler=compiler,
        status_callback=statuses.append,
    ) as runner:
        result = runner.draft_job(job_id)

    assert statuses == ["Workshopping now..."]
    assert result.interrupted is True
    assert result.interrupt_payload is not None
    assert result.interrupt_payload["apply_url"] == "https://nordiccloud.example.com/apply/42"
    assert result.interrupt_payload["job_id"] == job_id
    assert result.interrupt_payload["title"] == "Junior Backend Engineer"
    assert result.interrupt_payload["company"] == "Nordic Cloud Systems"
    assert result.interrupt_payload["fit_score"] == 8.7
    assert result.interrupt_payload["missing_posted_at"] is True
    assert result.interrupt_payload["major_gaps"] == ["Go production experience"]

    cv_pdf = Path(result.interrupt_payload["cv_pdf_path"])
    cl_pdf = Path(result.interrupt_payload["cover_letter_pdf_path"])
    assert cv_pdf.is_file()
    assert cl_pdf.is_file()
    assert len(pypdf.PdfReader(str(cv_pdf)).pages) == 1
    assert len(pypdf.PdfReader(str(cl_pdf)).pages) == 1

    stored = repo.get_job(job_id)
    assert stored is not None
    assert stored.status == ApplicationStatus.PENDING_REVIEW
    assert stored.langgraph_thread_id == result.thread_id
    assert stored.cv_pdf_path == str(cv_pdf)
    assert stored.cover_letter_pdf_path == str(cl_pdf)

    assert [c["tier"] for c in llm.calls_for(TailoringPlan)] == ["reasoning"]
    assert [c["tier"] for c in llm.calls_for(DraftDocuments)] == ["reasoning"]
    assert [c["tier"] for c in llm.calls_for(AuditResult)] == ["reasoning"]
    repo.close()


def test_checkpoint_resume_across_two_runner_instances(tmp_path: Path) -> None:
    repo = JobRepository(tmp_path / "jobs.db")
    job_id = _seed_queued_job(repo, job_id="job-resume")
    checkpoint_db = tmp_path / "checkpoints.db"
    drafts_dir = tmp_path / "drafts"
    llm1 = ScriptedLLMClient(_default_handlers())

    with TailoringWorkflowRunner(
        repository=repo,
        profile=_sample_profile(),
        llm_client=llm1,
        checkpoint_db_path=checkpoint_db,
        drafts_dir=drafts_dir,
    ) as runner1:
        first = runner1.draft_job(job_id)

    assert first.interrupted is True
    thread_id = first.thread_id

    llm2 = ScriptedLLMClient(_default_handlers())
    with TailoringWorkflowRunner(
        repository=repo,
        profile=_sample_profile(),
        llm_client=llm2,
        checkpoint_db_path=checkpoint_db,
        drafts_dir=drafts_dir,
    ) as runner2:
        snapshot = runner2.get_review_snapshot(thread_id)
        assert snapshot.interrupted is True
        assert snapshot.interrupt_payload is not None
        assert snapshot.interrupt_payload["apply_url"] == "https://nordiccloud.example.com/jobs/junior-backend"
        assert snapshot.state["job_id"] == job_id

        approved = runner2.resume_review(thread_id, "/approve")
        assert approved.interrupted is False
        assert approved.final_status == ApplicationStatus.READY_TO_SUBMIT.value

    stored = repo.get_job(job_id)
    assert stored is not None
    assert stored.status == ApplicationStatus.READY_TO_SUBMIT
    repo.close()


def test_pass1_deterministic_failure_routes_back_to_writer_without_llm_auditor(
    tmp_path: Path,
) -> None:
    repo = JobRepository(tmp_path / "jobs.db")
    job_id = _seed_queued_job(repo, job_id="job-pass1")

    writer_attempts = 0

    def draft_handler(_tier: ModelTier, _sys: str, user_prompt: str) -> DraftDocuments:
        nonlocal writer_attempts
        writer_attempts += 1
        if writer_attempts == 1:
            bad_cl = _clean_en_cover_letter()
            bad_cl.paragraphs[0] = bad_cl.paragraphs[0] + " I'm excited — truly."
            return DraftDocuments(
                cv=_clean_en_cv(),
                cover_letter=bad_cl,
                major_gaps=["Go production experience"],
            )
        payload = json.loads(user_prompt.split("\n\n", 1)[1])
        assert payload["audit_violations"], "Writer retry must receive surgical violations"
        return DraftDocuments(
            cv=_clean_en_cv(),
            cover_letter=_clean_en_cover_letter(),
            major_gaps=["Go production experience"],
        )

    handlers = _default_handlers()
    handlers[DraftDocuments] = draft_handler
    llm = ScriptedLLMClient(handlers)

    with TailoringWorkflowRunner(
        repository=repo,
        profile=_sample_profile(),
        llm_client=llm,
        checkpoint_db_path=tmp_path / "checkpoints.db",
        drafts_dir=tmp_path / "drafts",
    ) as runner:
        result = runner.draft_job(job_id)

    assert result.interrupted is True
    assert writer_attempts == 2
    assert len(llm.calls_for(AuditResult)) == 1
    assert result.state["internal_retry_count"] == 1
    assert result.interrupt_payload is not None
    assert result.interrupt_payload["remaining_warnings"] == []
    repo.close()


def test_max_two_internal_retries_on_repeated_audit_failures_still_compiles(
    tmp_path: Path,
) -> None:
    repo = JobRepository(tmp_path / "jobs.db")
    job_id = _seed_queued_job(repo, job_id="job-max-audit")

    def always_bad_cl(_tier: ModelTier, _sys: str, _usr: str) -> DraftDocuments:
        bad_cl = _clean_en_cover_letter()
        bad_cl.paragraphs[0] = bad_cl.paragraphs[0] + " — persistent em dash"
        return DraftDocuments(
            cv=_clean_en_cv(),
            cover_letter=bad_cl,
            major_gaps=[],
        )

    handlers = _default_handlers()
    handlers[DraftDocuments] = always_bad_cl
    llm = ScriptedLLMClient(handlers)
    compiler = CountingCompiler()

    with TailoringWorkflowRunner(
        repository=repo,
        profile=_sample_profile(),
        llm_client=llm,
        checkpoint_db_path=tmp_path / "checkpoints.db",
        drafts_dir=tmp_path / "drafts",
        compiler=compiler,
    ) as runner:
        result = runner.draft_job(job_id)

    assert result.interrupted is True
    assert len(llm.calls_for(DraftDocuments)) == 3
    assert len(llm.calls_for(AuditResult)) == 0
    assert compiler.compile_count == 1
    assert result.state["internal_retry_count"] == 2
    assert result.interrupt_payload is not None
    assert result.interrupt_payload["remaining_warnings"]
    assert any("em_dash" in w for w in result.interrupt_payload["remaining_warnings"])
    assert Path(result.interrupt_payload["cv_pdf_path"]).is_file()
    assert Path(result.interrupt_payload["cover_letter_pdf_path"]).is_file()
    repo.close()


def test_max_two_internal_retries_on_repeated_llm_audit_and_overflow_still_compiles(
    tmp_path: Path,
) -> None:
    repo = JobRepository(tmp_path / "jobs.db")
    job_id = _seed_queued_job(repo, job_id="job-max-overflow")
    handlers = _default_handlers()
    handlers[AuditResult] = lambda _t, _s, _u: AuditResult(
        passed=False,
        violations=[
            AuditViolation(
                document="cover_letter",
                location="cover_letter.paragraph_2",
                rule="humanizer_ing_trailer",
                offending_snippet="enabling teams to thrive",
                fix_instruction="Replace vague trailer with concrete impact.",
            )
        ],
    )
    llm = ScriptedLLMClient(handlers)
    compiler = CountingCompiler(fail_first_n=5)

    with TailoringWorkflowRunner(
        repository=repo,
        profile=_sample_profile(),
        llm_client=llm,
        checkpoint_db_path=tmp_path / "checkpoints.db",
        drafts_dir=tmp_path / "drafts",
        compiler=compiler,
    ) as runner:
        result = runner.draft_job(job_id)

    assert result.interrupted is True
    assert len(llm.calls_for(DraftDocuments)) == 3
    assert len(llm.calls_for(AuditResult)) == 3
    assert compiler.compile_count == 1
    assert result.interrupt_payload is not None
    assert len(result.interrupt_payload["remaining_warnings"]) >= 2

    repo2 = JobRepository(tmp_path / "jobs2.db")
    job_id2 = _seed_queued_job(repo2, job_id="job-overflow-only")
    llm2 = ScriptedLLMClient(_default_handlers())
    compiler2 = CountingCompiler(fail_first_n=5)
    with TailoringWorkflowRunner(
        repository=repo2,
        profile=_sample_profile(),
        llm_client=llm2,
        checkpoint_db_path=tmp_path / "checkpoints2.db",
        drafts_dir=tmp_path / "drafts2",
        compiler=compiler2,
    ) as runner2:
        result2 = runner2.draft_job(job_id2)

    assert result2.interrupted is True
    assert len(llm2.calls_for(DraftDocuments)) == 3
    assert compiler2.compile_count == 3
    assert result2.interrupt_payload is not None
    assert any("max_cv_pages=1" in w for w in result2.interrupt_payload["remaining_warnings"])
    repo.close()
    repo2.close()


def test_chat_ideation_does_not_recompile_and_uses_tiers(tmp_path: Path) -> None:
    repo = JobRepository(tmp_path / "jobs.db")
    job_id = _seed_queued_job(repo, job_id="job-chat")
    llm = ScriptedLLMClient(_default_handlers())
    compiler = CountingCompiler()

    with TailoringWorkflowRunner(
        repository=repo,
        profile=_sample_profile(),
        llm_client=llm,
        checkpoint_db_path=tmp_path / "checkpoints.db",
        drafts_dir=tmp_path / "drafts",
        compiler=compiler,
    ) as runner:
        initial = runner.draft_job(job_id)
        assert compiler.compile_count == 1

        chat_res = runner.resume_review(
            initial.thread_id,
            "Should we emphasize my Pulumi project more than the API work?",
        )

    assert chat_res.interrupted is True
    assert compiler.compile_count == 1
    assert [c["tier"] for c in llm.calls_for(ThreadIntentDecision)] == ["scoring"]
    assert [c["tier"] for c in llm.calls_for(IdeationResponse)] == ["reasoning"]
    assert chat_res.interrupt_payload is not None
    assert (
        chat_res.interrupt_payload["last_ideation_reply"]
        == "Let us emphasize your Python orchestration work."
    )
    assert len(chat_res.state["chat_history"]) == 2
    repo.close()


def test_one_shot_reiterate_and_multiple_unbounded_cycles(tmp_path: Path) -> None:
    repo = JobRepository(tmp_path / "jobs.db")
    job_id = _seed_queued_job(repo, job_id="job-reiterate")
    statuses: list[str] = []
    compiler = CountingCompiler()

    plan_calls = 0
    draft_calls = 0

    def plan_handler(_tier: ModelTier, _sys: str, user_prompt: str) -> TailoringPlan:
        nonlocal plan_calls
        plan_calls += 1
        if plan_calls > 1:
            mid_job = repo.get_job(job_id)
            assert mid_job is not None
            assert mid_job.status == ApplicationStatus.REVISING
        payload = json.loads(user_prompt.split("\n\n", 1)[1])
        notes = payload.get("ideation_notes") or []
        if any("education" in n.lower() for n in notes):
            return _sample_plan(section_order=["education", "experience", "projects", "skills"])
        return _sample_plan()

    def draft_handler(_tier: ModelTier, _sys: str, user_prompt: str) -> DraftDocuments:
        nonlocal draft_calls
        draft_calls += 1
        payload = json.loads(user_prompt.split("\n\n", 1)[1])
        order = payload["plan"]["section_order"]
        # Force one internal Pass 1 retry inside the second re-iteration to verify retry_count reset.
        if draft_calls == 3:
            bad_cl = _clean_en_cover_letter()
            bad_cl.paragraphs[0] = bad_cl.paragraphs[0] + " I'm checking retry reset."
            return DraftDocuments(
                cv=_clean_en_cv(section_order=order),
                cover_letter=bad_cl,
                major_gaps=["Go production experience"],
            )
        return DraftDocuments(
            cv=_clean_en_cv(section_order=order),
            cover_letter=_clean_en_cover_letter(),
            major_gaps=["Go production experience"],
        )

    def intent_handler(_tier: ModelTier, _sys: str, _usr: str) -> ThreadIntentDecision:
        return ThreadIntentDecision(intent="REITERATE", rationale="Explicit rewrite request.")

    def ideation_handler(_tier: ModelTier, _sys: str, user_prompt: str) -> IdeationResponse:
        payload = json.loads(user_prompt.split("\n\n", 1)[1])
        msg = payload["user_message"]
        return IdeationResponse(
            reply=f"Rebuilding now based on: {msg}",
            captured_ideation_note=msg,
        )

    llm = ScriptedLLMClient(
        {
            TailoringPlan: plan_handler,
            DraftDocuments: draft_handler,
            AuditResult: lambda _t, _s, _u: AuditResult(passed=True, violations=[]),
            ThreadIntentDecision: intent_handler,
            IdeationResponse: ideation_handler,
        }
    )

    with TailoringWorkflowRunner(
        repository=repo,
        profile=_sample_profile(),
        llm_client=llm,
        checkpoint_db_path=tmp_path / "checkpoints.db",
        drafts_dir=tmp_path / "drafts",
        compiler=compiler,
        status_callback=statuses.append,
    ) as runner:
        initial = runner.draft_job(job_id)
        assert initial.state["cv"]["section_order"] == [
            "experience",
            "projects",
            "education",
            "skills",
        ]

        re1 = runner.resume_review(
            initial.thread_id,
            "retry, swapping the education and work experience sections",
        )
        assert re1.interrupted is True
        assert re1.state["cv"]["section_order"] == [
            "education",
            "experience",
            "projects",
            "skills",
        ]
        assert compiler.compile_count == 2

        re2 = runner.resume_review(
            initial.thread_id,
            "regenerate again with a sharper opening hook",
        )
        assert re2.interrupted is True
        assert compiler.compile_count == 3
        assert re2.state["internal_retry_count"] == 1

    assert statuses == [
        "Workshopping now...",
        "Workshopping now...",
        "Workshopping now...",
    ]
    assert plan_calls == 3
    assert len(re2.state["ideation_notes"]) == 2
    stored = repo.get_job(job_id)
    assert stored is not None
    assert stored.status == ApplicationStatus.PENDING_REVIEW
    repo.close()


def test_profile_addition_and_correction_saved_without_mutating_master_profile(
    tmp_path: Path,
) -> None:
    repo = JobRepository(tmp_path / "jobs.db")
    job_id = _seed_queued_job(repo, job_id="job-facts")
    profile_yaml = tmp_path / "master_profile.yaml"
    original_yaml = "identity:\n  full_name: Sebastian McConnell\n"
    profile_yaml.write_text(original_yaml, encoding="utf-8")

    turn = 0

    def intent_handler(_tier: ModelTier, _sys: str, _usr: str) -> ThreadIntentDecision:
        nonlocal turn
        turn += 1
        if turn <= 2:
            return ThreadIntentDecision(intent="CHAT", rationale="Sharing new/corrected facts.")
        return ThreadIntentDecision(intent="REITERATE", rationale="User asked to rebuild.")

    def ideation_handler(_tier: ModelTier, _sys: str, _usr: str) -> IdeationResponse:
        if turn == 1:
            return IdeationResponse(
                reply="Noted your Kafka project for this application and weekly check-in.",
                new_session_verified_facts=[
                    "Built a Kafka stream processor handling 5k messages/sec."
                ],
                detected_profile_suggestions=[
                    ProfileSuggestionDraft(
                        kind="addition",
                        fact_text="Built a Kafka stream processor handling 5k messages/sec.",
                        category="projects",
                    )
                ],
            )
        if turn == 2:
            return IdeationResponse(
                reply="Updated your LEGO Group title and start date for this session.",
                new_session_verified_facts=[
                    "At LEGO Group, title was Junior Platform Engineer from 2024-05."
                ],
                detected_profile_suggestions=[
                    ProfileSuggestionDraft(
                        kind="correction",
                        fact_text="At LEGO Group, title was Junior Platform Engineer from 2024-05.",
                        category="experiences",
                    )
                ],
            )
        return IdeationResponse(
            reply="Rebuilding drafts with your corrected LEGO Group title.",
            captured_ideation_note="Use corrected LEGO Group title Junior Platform Engineer.",
        )

    def draft_handler(_tier: ModelTier, _sys: str, user_prompt: str) -> DraftDocuments:
        payload = json.loads(user_prompt.split("\n\n", 1)[1])
        facts = payload.get("session_verified_facts") or []
        if any("Junior Platform Engineer" in f for f in facts):
            return DraftDocuments(
                cv=_clean_en_cv(title="Junior Platform Engineer", start_date="2024-05"),
                cover_letter=_clean_en_cover_letter(),
                major_gaps=["Go production experience"],
            )
        return DraftDocuments(
            cv=_clean_en_cv(),
            cover_letter=_clean_en_cover_letter(),
            major_gaps=["Go production experience"],
        )

    llm = ScriptedLLMClient(
        {
            TailoringPlan: lambda _t, _s, _u: _sample_plan(),
            DraftDocuments: draft_handler,
            AuditResult: lambda _t, _s, _u: AuditResult(passed=True, violations=[]),
            ThreadIntentDecision: intent_handler,
            IdeationResponse: ideation_handler,
        }
    )

    with TailoringWorkflowRunner(
        repository=repo,
        profile=_sample_profile(),
        llm_client=llm,
        checkpoint_db_path=tmp_path / "checkpoints.db",
        drafts_dir=tmp_path / "drafts",
    ) as runner:
        initial = runner.draft_job(job_id)
        after_add = runner.resume_review(
            initial.thread_id,
            "I also built a Kafka stream processor handling 5k messages/sec.",
        )
        after_corr = runner.resume_review(
            initial.thread_id,
            "Actually my LEGO Group title was Junior Platform Engineer from 2024-05.",
        )
        rebuilt = runner.resume_review(
            initial.thread_id,
            "rewrite the CV using those updated facts",
        )

    assert after_add.interrupted is True
    assert after_corr.interrupted is True
    assert rebuilt.interrupted is True
    assert rebuilt.state["cv"]["experiences"][0]["title"] == "Junior Platform Engineer"
    assert rebuilt.state["cv"]["experiences"][0]["start_date"] == "2024-05"
    assert rebuilt.interrupt_payload is not None
    assert rebuilt.interrupt_payload["remaining_warnings"] == []

    suggestions = repo.list_unconsumed_profile_suggestions()
    assert [(s.kind, s.category) for s in suggestions] == [
        ("addition", "projects"),
        ("correction", "experiences"),
    ]
    assert all(s.consumed_at is None for s in suggestions)
    assert profile_yaml.read_text(encoding="utf-8") == original_yaml
    repo.close()


def test_approve_and_dismiss_conclude_workflow(tmp_path: Path) -> None:
    repo = JobRepository(tmp_path / "jobs.db")
    approve_id = _seed_queued_job(repo, job_id="job-approve")
    dismiss_id = _seed_queued_job(repo, job_id="job-dismiss")
    llm = ScriptedLLMClient(_default_handlers())

    with TailoringWorkflowRunner(
        repository=repo,
        profile=_sample_profile(),
        llm_client=llm,
        checkpoint_db_path=tmp_path / "checkpoints.db",
        drafts_dir=tmp_path / "drafts",
    ) as runner:
        r_app = runner.draft_job(approve_id)
        done_app = runner.resume_review(r_app.thread_id, "/approve")
        assert done_app.interrupted is False
        assert done_app.final_status == ApplicationStatus.READY_TO_SUBMIT.value

        r_dis = runner.draft_job(dismiss_id)
        done_dis = runner.resume_review(r_dis.thread_id, {"action": "dismiss"})
        assert done_dis.interrupted is False
        assert done_dis.final_status == ApplicationStatus.REJECTED.value

    assert repo.get_job(approve_id).status == ApplicationStatus.READY_TO_SUBMIT  # type: ignore[union-attr]
    assert repo.get_job(dismiss_id).status == ApplicationStatus.REJECTED  # type: ignore[union-attr]
    repo.close()
