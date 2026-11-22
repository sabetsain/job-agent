"""Ingestion and manual submission pipelines connecting sources, pre-filter, and storage."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
from pydantic import BaseModel, Field

from job_agent.filters.prefilter import PreFilterResult, evaluate_prefilter
from job_agent.schemas.jobs import ApplicationStatus, JobPosting, SourcesConfig, WorkMode
from job_agent.schemas.preferences import JobPreferences
from job_agent.sources.manual import ManualDropError, ingest_manual_text, ingest_manual_url
from job_agent.sources.runner import IngestionFetchResult, SourceFetchError, fetch_all_sources
from job_agent.storage.repository import JobRepository


def _to_utc(dt: datetime) -> datetime:
    """Normalize a naive or timezone-aware datetime to UTC."""
    if dt.tzinfo is None or dt.utcoffset() is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class IngestionSummary(BaseModel):
    """Counts and per-source errors produced by a single ingestion pass."""

    fetched: int = 0
    skipped: int = 0
    discarded_stale: int = 0
    passed: int = 0
    prefiltered_out: int = 0
    pruned: int = 0
    source_errors: list[SourceFetchError] = Field(default_factory=list)


def run_ingestion(
    preferences: JobPreferences,
    sources_config: SourcesConfig,
    repository: JobRepository,
    fetch_result: IngestionFetchResult | None = None,
    now: datetime | None = None,
) -> IngestionSummary:
    """Run one discovery pass, skip known job_ids, pre-filter, persist, and prune old rows."""
    current_time = _to_utc(now) if now is not None else datetime.now(timezone.utc)
    result = fetch_result if fetch_result is not None else fetch_all_sources(sources_config)

    skipped = 0
    discarded_stale = 0
    passed = 0
    prefiltered_out = 0

    for posting in result.postings:
        if repository.exists(posting.job_id):
            skipped += 1
            continue

        prefilter = evaluate_prefilter(posting, preferences, now=current_time)
        if not prefilter.passed and prefilter.discard_without_storing:
            discarded_stale += 1
            continue

        if not prefilter.passed:
            repository.insert_job(
                posting,
                status=ApplicationStatus.PRE_FILTERED_OUT,
                rejection_reason=prefilter.reason,
                created_at=current_time,
            )
            prefiltered_out += 1
        else:
            repository.insert_job(
                posting,
                status=ApplicationStatus.PENDING_SCORING,
                rejection_reason=None,
                created_at=current_time,
            )
            passed += 1

    pruned = repository.prune_old_jobs(retention_days=180, now=current_time)

    return IngestionSummary(
        fetched=len(result.postings),
        skipped=skipped,
        discarded_stale=discarded_stale,
        passed=passed,
        prefiltered_out=prefiltered_out,
        pruned=pruned,
        source_errors=list(result.errors),
    )


def submit_manual_job(
    preferences: JobPreferences,
    repository: JobRepository,
    *,
    url: str | None = None,
    text: str | None = None,
    title: str = "",
    company: str = "",
    location: str = "",
    work_mode: WorkMode = WorkMode.UNKNOWN,
    apply_url: str = "",
    posted_at: datetime | None = None,
    application_deadline: datetime | None = None,
    client: httpx.Client | None = None,
    now: datetime | None = None,
) -> tuple[JobPosting, PreFilterResult | None, bool]:
    """Submit a manual job posting via raw text or direct URL and persist if new."""
    if text is not None and text.strip():
        posting = ingest_manual_text(
            title=title,
            company=company,
            apply_url=apply_url or (url or ""),
            description=text,
            location=location,
            work_mode=work_mode,
            posted_at=posted_at,
            application_deadline=application_deadline,
        )
    elif url is not None and url.strip():
        posting = ingest_manual_url(
            url=url,
            title=title,
            company=company,
            location=location,
            work_mode=work_mode,
            client=client,
        )
    else:
        raise ManualDropError(
            reason="No job URL or job description text provided",
            hint="Provide --url or --text / --file (or pipe job description text via stdin).",
        )

    if repository.exists(posting.job_id):
        return posting, None, True

    current_time = _to_utc(now) if now is not None else datetime.now(timezone.utc)
    prefilter = evaluate_prefilter(posting, preferences, now=current_time)
    status = (
        ApplicationStatus.PENDING_SCORING
        if prefilter.passed
        else ApplicationStatus.PRE_FILTERED_OUT
    )
    rejection_reason = None if prefilter.passed else prefilter.reason

    repository.insert_job(
        posting,
        status=status,
        rejection_reason=rejection_reason,
        created_at=current_time,
    )
    return posting, prefilter, False
