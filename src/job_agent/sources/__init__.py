"""Job discovery source adapters, manual drop, and normalization."""

from job_agent.sources.arbeitnow import ArbeitnowSource
from job_agent.sources.base import JobSource, html_to_text, parse_timestamp
from job_agent.sources.himalayas import HimalayasSource
from job_agent.sources.jobicy import JobicySource
from job_agent.sources.jobindex import JobindexRssSource
from job_agent.sources.manual import ManualDropError, ingest_manual_text, ingest_manual_url
from job_agent.sources.normalize import (
    canonicalize_url,
    detect_language,
    generate_job_id,
    normalize_raw_job,
)
from job_agent.sources.remotive import RemotiveSource
from job_agent.sources.runner import (
    IngestionFetchResult,
    SourceFetchError,
    build_enabled_sources,
    fetch_all_sources,
)

__all__ = [
    "ArbeitnowSource",
    "HimalayasSource",
    "IngestionFetchResult",
    "JobSource",
    "JobicySource",
    "JobindexRssSource",
    "ManualDropError",
    "RemotiveSource",
    "SourceFetchError",
    "build_enabled_sources",
    "canonicalize_url",
    "detect_language",
    "fetch_all_sources",
    "generate_job_id",
    "html_to_text",
    "ingest_manual_text",
    "ingest_manual_url",
    "normalize_raw_job",
    "parse_timestamp",
]
