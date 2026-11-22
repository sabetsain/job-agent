"""CLI entrypoint for job-agent."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any, NoReturn

import typer

from job_agent.graph.state import WorkflowRunResult
from job_agent.graph.workflow import TailoringWorkflowRunner
from job_agent.llm.client import (
    LLMConfigurationError,
    OpenCodeLLMClient,
    StructuredLLMClient,
    StructuredOutputError,
)
from job_agent.llm.config import load_llm_config
from job_agent.pipeline import run_ingestion, submit_manual_job
from job_agent.schemas.jobs import ApplicationStatus, WorkMode, load_sources_config
from job_agent.schemas.preferences import JobPreferences, load_job_preferences
from job_agent.schemas.profile import MasterProfile, load_master_profile
from job_agent.scoring.scorer import score_pending_jobs
from job_agent.sources.manual import ManualDropError
from job_agent.storage.repository import JobRepository, StoredJob

app = typer.Typer(help="Autonomous job-hunting and application co-pilot.")

DEFAULT_PREFERENCES_PATH = Path("config/target_roles.yaml")
DEFAULT_SOURCES_PATH = Path("config/sources.yaml")
DEFAULT_DB_PATH = Path("data/job_agent.db")
DEFAULT_PROFILE_PATH = Path("config/master_profile.yaml")
DEFAULT_LLM_CONFIG_PATH = Path("config/llm.yaml")
DEFAULT_CHECKPOINT_DB_PATH = Path("data/checkpoints.db")
DEFAULT_DRAFTS_DIR = Path("data/drafts")


def _fail(message: str) -> NoReturn:
    """Print an error message to stderr and exit non-zero."""
    typer.secho(f"Error: {message}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=1)


def _format_timestamp(dt: datetime | None) -> str:
    """Format an optional datetime compactly for CLI listing output."""
    if dt is None:
        return "-"
    return dt.isoformat(timespec="seconds")


def _default_llm_client_factory(llm_config_path: Path) -> StructuredLLMClient:
    """Load LLMConfig from YAML and return the default OpenCode Go client."""
    cfg = load_llm_config(llm_config_path)
    return OpenCodeLLMClient(cfg)


def _load_stage_deps_or_fail(
    *,
    preferences: Path,
    profile: Path,
    llm_config: Path,
) -> tuple[JobPreferences, MasterProfile, StructuredLLMClient]:
    """Load preferences, master profile, and LLM client or fail loudly."""
    try:
        prefs = load_job_preferences(preferences)
        profile_obj = load_master_profile(profile)
        llm_client = _default_llm_client_factory(llm_config)
    except (OSError, ValueError, LLMConfigurationError) as exc:
        _fail(f"Failed to load configuration: {exc}")
    return prefs, profile_obj, llm_client


def _extract_review_fields(
    result: WorkflowRunResult,
    fallback_job: StoredJob | None = None,
) -> dict[str, Any]:
    """Normalize interrupt payload, graph state, and StoredJob fields for CLI display."""
    payload = result.interrupt_payload or {}
    state = result.state or {}
    posting = state.get("posting") or {}
    fit_breakdown = state.get("fit_breakdown") or {}

    job_id = str(
        payload.get("job_id")
        or state.get("job_id")
        or (fallback_job.job_id if fallback_job else "")
    )
    title = str(
        payload.get("title")
        or posting.get("title")
        or (fallback_job.title if fallback_job else "")
    )
    company = str(
        payload.get("company")
        or posting.get("company")
        or (fallback_job.company if fallback_job else "")
        or "-"
    )
    location = str(
        payload.get("location")
        or posting.get("location")
        or (fallback_job.location if fallback_job else "")
        or "-"
    )
    language = str(
        payload.get("language")
        or posting.get("language")
        or (fallback_job.language if fallback_job else "")
        or "-"
    )
    apply_url = str(
        payload.get("apply_url")
        or posting.get("apply_url")
        or (fallback_job.apply_url if fallback_job else "")
    )
    fit_score = payload.get(
        "fit_score",
        fit_breakdown.get("fit_score", fallback_job.fit_score if fallback_job else None),
    )
    major_gaps = [
        str(item)
        for item in (payload.get("major_gaps") or state.get("major_gaps") or [])
    ]
    missing_posted_at = bool(
        payload.get(
            "missing_posted_at",
            state.get(
                "missing_posted_at",
                fallback_job.posted_at is None if fallback_job else False,
            ),
        )
    )
    cv_pdf_path = payload.get(
        "cv_pdf_path",
        state.get("cv_pdf_path", fallback_job.cv_pdf_path if fallback_job else None),
    )
    cover_letter_pdf_path = payload.get(
        "cover_letter_pdf_path",
        state.get(
            "cover_letter_pdf_path",
            fallback_job.cover_letter_pdf_path if fallback_job else None,
        ),
    )
    remaining_warnings = [
        str(item)
        for item in (
            payload.get("remaining_warnings") or state.get("remaining_warnings") or []
        )
    ]
    last_ideation_reply = payload.get(
        "last_ideation_reply",
        state.get("last_ideation_reply"),
    )

    return {
        "job_id": job_id,
        "title": title,
        "company": company,
        "location": location,
        "language": language,
        "apply_url": apply_url,
        "fit_score": fit_score,
        "major_gaps": major_gaps,
        "missing_posted_at": missing_posted_at,
        "cv_pdf_path": cv_pdf_path,
        "cover_letter_pdf_path": cover_letter_pdf_path,
        "remaining_warnings": remaining_warnings,
        "last_ideation_reply": last_ideation_reply,
    }


def _echo_draft_details(fields: dict[str, Any], *, include_brief_meta: bool = False) -> None:
    """Print job brief or drafted output lines including Apply URL, PDFs, gaps, and warnings."""
    fit_score = fields["fit_score"]
    fit_str = f"{float(fit_score):.2f}/10" if fit_score is not None else "-"

    if include_brief_meta:
        typer.echo(f"Job: {fields['title']} at {fields['company']} ({fields['job_id']})")
        typer.echo(f"Location: {fields['location']} | Language: {fields['language']} | Fit Score: {fit_str}")
    else:
        typer.echo(f"[{fields['job_id']}] {fields['company']} | {fields['title']} | fit={fit_str}")

    typer.echo(f"Apply URL: {fields['apply_url']}")
    typer.echo(f"CV PDF: {fields['cv_pdf_path'] or '-'}")
    typer.echo(f"Cover Letter PDF: {fields['cover_letter_pdf_path'] or '-'}")
    major_gaps = fields["major_gaps"]
    typer.echo(f"Major gaps: {', '.join(major_gaps) if major_gaps else 'None'}")
    if fields["missing_posted_at"]:
        typer.echo("Warning: posted_at is missing (freshness unverified).")
    for warning in fields["remaining_warnings"]:
        typer.echo(f"Warning: {warning}")


@app.command("ingest")
def ingest_command(
    preferences: Path = typer.Option(
        DEFAULT_PREFERENCES_PATH,
        "--preferences",
        help="Path to target_roles YAML configuration.",
    ),
    sources: Path = typer.Option(
        DEFAULT_SOURCES_PATH,
        "--sources",
        help="Path to sources YAML configuration.",
    ),
    db: Path = typer.Option(
        DEFAULT_DB_PATH,
        "--db",
        help="Path to local SQLite database.",
    ),
) -> None:
    """Run once-daily discovery, pre-filtering, persistence, and 6-month retention cleanup."""
    try:
        prefs = load_job_preferences(preferences)
        sources_cfg = load_sources_config(sources)
    except (OSError, ValueError) as exc:
        _fail(f"Failed to load configuration: {exc}")
        return

    repo = JobRepository(db)
    summary = run_ingestion(prefs, sources_cfg, repo)

    typer.echo(
        "Ingestion complete: "
        f"fetched={summary.fetched}, "
        f"skipped={summary.skipped}, "
        f"discarded-stale={summary.discarded_stale}, "
        f"passed={summary.passed}, "
        f"pre-filtered={summary.prefiltered_out}, "
        f"pruned={summary.pruned}"
    )

    for err in summary.source_errors:
        typer.secho(
            f"Warning: source '{err.source}' failed: {err.error}",
            fg=typer.colors.YELLOW,
            err=True,
        )


@app.command("add")
def add_command(
    url: str | None = typer.Option(None, "--url", help="Direct URL of the job posting."),
    text: str | None = typer.Option(None, "--text", help="Raw job description text."),
    file: Path | None = typer.Option(
        None,
        "--file",
        help="Path to a text file containing the raw job description.",
    ),
    title: str = typer.Option(
        "",
        "--title",
        help="Job title (required for raw text; optional override for URL).",
    ),
    company: str = typer.Option("", "--company", help="Company name."),
    location: str = typer.Option("", "--location", help="Job location."),
    work_mode: WorkMode = typer.Option(
        WorkMode.UNKNOWN,
        "--work-mode",
        help="Work mode: remote, hybrid, onsite, or unknown.",
    ),
    preferences: Path = typer.Option(
        DEFAULT_PREFERENCES_PATH,
        "--preferences",
        help="Path to target_roles YAML configuration.",
    ),
    db: Path = typer.Option(
        DEFAULT_DB_PATH,
        "--db",
        help="Path to local SQLite database.",
    ),
) -> None:
    """Manually submit a job posting via raw text or direct URL."""
    if text is not None and file is not None:
        _fail("Provide either --text or --file, not both.")
        return

    raw_text = text
    if file is not None:
        try:
            raw_text = file.read_text(encoding="utf-8")
        except OSError as exc:
            _fail(f"Could not read --file '{file}': {exc}")
            return
    elif raw_text is None and not sys.stdin.isatty():
        stdin_content = sys.stdin.read()
        if stdin_content.strip():
            raw_text = stdin_content

    try:
        prefs = load_job_preferences(preferences)
    except (OSError, ValueError) as exc:
        _fail(f"Failed to load preferences: {exc}")
        return

    repo = JobRepository(db)
    try:
        posting, prefilter, already_existed = submit_manual_job(
            prefs,
            repo,
            url=url,
            text=raw_text,
            title=title,
            company=company,
            location=location,
            work_mode=work_mode,
        )
    except ManualDropError as exc:
        _fail(str(exc))
        return

    if already_existed:
        typer.echo(
            f"Skipped existing job {posting.job_id} ({posting.title} at {posting.company or '-'})"
        )
        return

    if prefilter is not None and prefilter.passed:
        typer.echo(
            f"Added job {posting.job_id} ({posting.title} at {posting.company or '-'}) "
            f"with status {ApplicationStatus.PENDING_SCORING.value}"
        )
    else:
        reason = prefilter.reason if prefilter is not None else "Pre-filtered"
        typer.echo(
            f"Added job {posting.job_id} ({posting.title} at {posting.company or '-'}) "
            f"with status {ApplicationStatus.PRE_FILTERED_OUT.value}: {reason}"
        )


@app.command("list")
def list_command(
    status: ApplicationStatus | None = typer.Option(
        None,
        "--status",
        help="Filter jobs by application status.",
    ),
    language: str | None = typer.Option(
        None,
        "--language",
        help="Filter jobs by language (da or en).",
    ),
    db: Path = typer.Option(
        DEFAULT_DB_PATH,
        "--db",
        help="Path to local SQLite database.",
    ),
) -> None:
    """List stored jobs from SQLite, optionally filtered by status or language."""
    repo = JobRepository(db)
    jobs = repo.list_jobs(status=status, language=language)

    if not jobs:
        typer.echo("No jobs found.")
        return

    typer.echo(
        "job_id | company | title | location | language | posted_at | application_deadline | source | status"
    )
    for job in jobs:
        typer.echo(
            f"{job.job_id} | "
            f"{job.company or '-'} | "
            f"{job.title} | "
            f"{job.location or '-'} | "
            f"{job.language} | "
            f"{_format_timestamp(job.posted_at)} | "
            f"{_format_timestamp(job.application_deadline)} | "
            f"{job.source} | "
            f"{job.status.value}"
        )


@app.command("score")
def score_command(
    preferences: Path = typer.Option(
        DEFAULT_PREFERENCES_PATH,
        "--preferences",
        help="Path to target_roles YAML configuration.",
    ),
    profile: Path = typer.Option(
        DEFAULT_PROFILE_PATH,
        "--profile",
        help="Path to master_profile YAML configuration.",
    ),
    llm_config: Path = typer.Option(
        DEFAULT_LLM_CONFIG_PATH,
        "--llm-config",
        help="Path to LLM YAML configuration.",
    ),
    db: Path = typer.Option(
        DEFAULT_DB_PATH,
        "--db",
        help="Path to local SQLite database.",
    ),
) -> None:
    """Evaluate Pending_Scoring jobs into Queued_For_Drafting or Scored_Out."""
    prefs, profile_obj, llm_client = _load_stage_deps_or_fail(
        preferences=preferences,
        profile=profile,
        llm_config=llm_config,
    )
    repo = JobRepository(db)
    try:
        summary = score_pending_jobs(repo, profile_obj, prefs, llm_client)
    except (LLMConfigurationError, StructuredOutputError) as exc:
        _fail(str(exc))

    typer.echo(
        "Scoring complete: "
        f"evaluated={summary.evaluated}, "
        f"queued={summary.queued_for_drafting}, "
        f"scored-out={summary.scored_out}, "
        f"missing-posted-at={summary.missing_posted_at_count}"
    )


@app.command("queue")
def queue_command(
    preferences: Path = typer.Option(
        DEFAULT_PREFERENCES_PATH,
        "--preferences",
        help="Path to target_roles YAML configuration.",
    ),
    db: Path = typer.Option(
        DEFAULT_DB_PATH,
        "--db",
        help="Path to local SQLite database.",
    ),
) -> None:
    """Show total queued count and jobs waiting in Queued_For_Drafting."""
    if preferences != DEFAULT_PREFERENCES_PATH or preferences.exists():
        try:
            load_job_preferences(preferences)
        except (OSError, ValueError) as exc:
            _fail(f"Failed to load preferences: {exc}")

    repo = JobRepository(db)
    queued_count = repo.count_queued_jobs()
    queued_jobs = repo.list_jobs(status=ApplicationStatus.QUEUED_FOR_DRAFTING)
    typer.echo(f"Queued for drafting: {queued_count}")
    if not queued_jobs:
        return

    typer.echo(
        "job_id | company | title | fit_score | posted_at | application_deadline | apply_url"
    )
    for job in queued_jobs:
        fit_str = f"{job.fit_score:.2f}" if job.fit_score is not None else "-"
        typer.echo(
            f"{job.job_id} | "
            f"{job.company or '-'} | "
            f"{job.title} | "
            f"{fit_str} | "
            f"{_format_timestamp(job.posted_at)} | "
            f"{_format_timestamp(job.application_deadline)} | "
            f"{job.apply_url}"
        )


@app.command("draft")
def draft_command(
    preferences: Path = typer.Option(
        DEFAULT_PREFERENCES_PATH,
        "--preferences",
        help="Path to target_roles YAML configuration.",
    ),
    profile: Path = typer.Option(
        DEFAULT_PROFILE_PATH,
        "--profile",
        help="Path to master_profile YAML configuration.",
    ),
    llm_config: Path = typer.Option(
        DEFAULT_LLM_CONFIG_PATH,
        "--llm-config",
        help="Path to LLM YAML configuration.",
    ),
    db: Path = typer.Option(
        DEFAULT_DB_PATH,
        "--db",
        help="Path to local SQLite database.",
    ),
    checkpoints: Path = typer.Option(
        DEFAULT_CHECKPOINT_DB_PATH,
        "--checkpoints",
        help="Path to LangGraph SQLite checkpoint database.",
    ),
    drafts_dir: Path = typer.Option(
        DEFAULT_DRAFTS_DIR,
        "--drafts-dir",
        help="Directory where drafted PDFs are saved.",
    ),
) -> None:
    """Expire stale queued jobs and draft up to daily_draft_limit prioritized candidates."""
    prefs, profile_obj, llm_client = _load_stage_deps_or_fail(
        preferences=preferences,
        profile=profile,
        llm_config=llm_config,
    )
    repo = JobRepository(db)
    expired = repo.expire_stale_queued_jobs(max_age_days=prefs.freshness_policy.max_age_days)
    candidates = repo.list_prioritized_candidates(
        preferred_age_days=prefs.freshness_policy.preferred_age_days,
        limit=prefs.freshness_policy.daily_draft_limit,
    )
    if not candidates:
        typer.echo(f"No queued jobs to draft (expired={expired}).")
        return

    with TailoringWorkflowRunner(
        repository=repo,
        profile=profile_obj,
        llm_client=llm_client,
        checkpoint_db_path=checkpoints,
        drafts_dir=drafts_dir,
        layout_guardrails=prefs.layout_guardrails,
        status_callback=lambda msg: typer.echo(msg),
    ) as runner:
        for candidate in candidates:
            try:
                result = runner.draft_job(candidate.job_id)
            except (LLMConfigurationError, StructuredOutputError) as exc:
                _fail(str(exc))
            fields = _extract_review_fields(result, candidate)
            _echo_draft_details(fields, include_brief_meta=False)

    typer.echo(f"Drafting complete: drafted={len(candidates)}, expired={expired}")


@app.command("review")
def review_command(
    job_id: str = typer.Argument(..., help="Job ID to review interactively."),
    preferences: Path = typer.Option(
        DEFAULT_PREFERENCES_PATH,
        "--preferences",
        help="Path to target_roles YAML configuration.",
    ),
    profile: Path = typer.Option(
        DEFAULT_PROFILE_PATH,
        "--profile",
        help="Path to master_profile YAML configuration.",
    ),
    llm_config: Path = typer.Option(
        DEFAULT_LLM_CONFIG_PATH,
        "--llm-config",
        help="Path to LLM YAML configuration.",
    ),
    db: Path = typer.Option(
        DEFAULT_DB_PATH,
        "--db",
        help="Path to local SQLite database.",
    ),
    checkpoints: Path = typer.Option(
        DEFAULT_CHECKPOINT_DB_PATH,
        "--checkpoints",
        help="Path to LangGraph SQLite checkpoint database.",
    ),
    drafts_dir: Path = typer.Option(
        DEFAULT_DRAFTS_DIR,
        "--drafts-dir",
        help="Directory where drafted PDFs are saved.",
    ),
) -> None:
    """Interactively review, ideate, revise, approve, or dismiss a drafted job."""
    prefs, profile_obj, llm_client = _load_stage_deps_or_fail(
        preferences=preferences,
        profile=profile,
        llm_config=llm_config,
    )
    repo = JobRepository(db)
    stored_job = repo.get_job(job_id)
    if stored_job is None:
        _fail(f"Job not found: {job_id}")

    thread_id = stored_job.langgraph_thread_id or f"job-{job_id}"
    reiterate_triggered = False

    def _on_status(msg: str) -> None:
        nonlocal reiterate_triggered
        reiterate_triggered = True
        typer.echo(msg)

    with TailoringWorkflowRunner(
        repository=repo,
        profile=profile_obj,
        llm_client=llm_client,
        checkpoint_db_path=checkpoints,
        drafts_dir=drafts_dir,
        layout_guardrails=prefs.layout_guardrails,
        status_callback=_on_status,
    ) as runner:
        snapshot = runner.get_review_snapshot(thread_id)
        if not snapshot.state and not snapshot.interrupted:
            if stored_job.status == ApplicationStatus.QUEUED_FOR_DRAFTING:
                try:
                    snapshot = runner.draft_job(job_id, thread_id=thread_id)
                except (LLMConfigurationError, StructuredOutputError) as exc:
                    _fail(str(exc))
            else:
                _fail(
                    f"Job '{job_id}' has no active review checkpoint "
                    f"(status={stored_job.status.value})."
                )

        current_fields = _extract_review_fields(snapshot, stored_job)
        _echo_draft_details(current_fields, include_brief_meta=True)

        if not snapshot.interrupted and snapshot.final_status is not None:
            typer.echo(f"Review already finalized: {snapshot.final_status}")
            return

        while True:
            try:
                raw_input = input("Review> ")
            except (EOFError, KeyboardInterrupt):
                break

            stripped = raw_input.strip()
            if not stripped or stripped.lower() in {"/exit", "/quit"}:
                break

            if stripped.lower() == "/approve":
                try:
                    runner.resume_review(thread_id, "/approve")
                except (LLMConfigurationError, StructuredOutputError) as exc:
                    _fail(str(exc))
                typer.echo("Approved! Status: Ready_to_Submit")
                break

            if stripped.lower() == "/dismiss":
                try:
                    runner.resume_review(thread_id, "/dismiss")
                except (LLMConfigurationError, StructuredOutputError) as exc:
                    _fail(str(exc))
                typer.echo("Dismissed. Status: Rejected")
                break

            reiterate_triggered = False
            prev_cv_pdf = current_fields["cv_pdf_path"]
            prev_cl_pdf = current_fields["cover_letter_pdf_path"]
            try:
                updated_snapshot = runner.resume_review(thread_id, stripped)
            except (LLMConfigurationError, StructuredOutputError) as exc:
                _fail(str(exc))

            updated_fields = _extract_review_fields(updated_snapshot, stored_job)
            reply_text = updated_fields["last_ideation_reply"]
            pdfs_updated = (
                updated_fields["cv_pdf_path"] != prev_cv_pdf
                or updated_fields["cover_letter_pdf_path"] != prev_cl_pdf
            )
            if reiterate_triggered or not reply_text or pdfs_updated:
                typer.echo(f"CV PDF: {updated_fields['cv_pdf_path'] or '-'}")
                typer.echo(f"Cover Letter PDF: {updated_fields['cover_letter_pdf_path'] or '-'}")
                typer.echo(f"Apply URL: {updated_fields['apply_url']}")
                for warning in updated_fields["remaining_warnings"]:
                    typer.echo(f"Warning: {warning}")
            else:
                typer.echo(f"Co-Pilot: {reply_text}")

            current_fields = updated_fields
