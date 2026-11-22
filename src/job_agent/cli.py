"""CLI entrypoint for job-agent."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import typer

from job_agent.pipeline import run_ingestion, submit_manual_job
from job_agent.schemas.jobs import ApplicationStatus, WorkMode, load_sources_config
from job_agent.schemas.preferences import load_job_preferences
from job_agent.sources.manual import ManualDropError
from job_agent.storage.repository import JobRepository

app = typer.Typer(help="Autonomous job-hunting and application co-pilot.")

DEFAULT_PREFERENCES_PATH = Path("config/target_roles.yaml")
DEFAULT_SOURCES_PATH = Path("config/sources.yaml")
DEFAULT_DB_PATH = Path("data/job_agent.db")


def _fail(message: str) -> None:
    """Print an error message to stderr and exit non-zero."""
    typer.secho(f"Error: {message}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=1)


def _format_timestamp(dt: datetime | None) -> str:
    """Format an optional datetime compactly for CLI listing output."""
    if dt is None:
        return "-"
    return dt.isoformat(timespec="seconds")


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
