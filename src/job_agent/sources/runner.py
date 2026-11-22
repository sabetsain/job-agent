"""Once-daily ingestion orchestrator across enabled JobSource adapters."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from job_agent.schemas.jobs import JobPosting, SourcesConfig
from job_agent.sources.arbeitnow import ArbeitnowSource
from job_agent.sources.base import JobSource
from job_agent.sources.himalayas import HimalayasSource
from job_agent.sources.jobicy import JobicySource
from job_agent.sources.jobindex import JobindexRssSource
from job_agent.sources.normalize import normalize_raw_job
from job_agent.sources.remotive import RemotiveSource

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SourceFetchError:
    """Structured error recorded when an individual JobSource adapter fails."""

    source: str
    error: str


@dataclass(frozen=True)
class IngestionFetchResult:
    """Aggregated result of a single once-daily ingestion fetch pass."""

    postings: list[JobPosting]
    errors: list[SourceFetchError]


def build_enabled_sources(
    config: SourcesConfig,
    client: httpx.Client | None = None,
) -> list[JobSource]:
    """Instantiate all enabled discovery adapters from SourcesConfig."""
    sources: list[JobSource] = []

    if config.arbeitnow.enabled:
        sources.append(ArbeitnowSource(config=config.arbeitnow, client=client))
    if config.remotive.enabled:
        sources.append(RemotiveSource(config=config.remotive, client=client))
    if config.himalayas.enabled:
        sources.append(HimalayasSource(config=config.himalayas, client=client))
    if config.jobicy.enabled:
        sources.append(JobicySource(config=config.jobicy, client=client))
    if config.jobindex_rss.enabled:
        sources.append(JobindexRssSource(config=config.jobindex_rss, client=client))

    return sources


def fetch_all_sources(
    config: SourcesConfig,
    sources: list[JobSource] | None = None,
) -> IngestionFetchResult:
    """Invoke each enabled adapter once, isolate per-source errors, and normalize postings."""
    active_sources = sources if sources is not None else build_enabled_sources(config)
    postings: list[JobPosting] = []
    errors: list[SourceFetchError] = []

    for source in active_sources:
        try:
            raw_jobs = source.fetch()
        except Exception as exc:
            logger.warning("Job source %r failed during ingestion: %s", source.name, exc)
            errors.append(SourceFetchError(source=source.name, error=str(exc)))
            continue

        for raw_job in raw_jobs:
            postings.append(normalize_raw_job(raw_job))

    return IngestionFetchResult(postings=postings, errors=errors)
