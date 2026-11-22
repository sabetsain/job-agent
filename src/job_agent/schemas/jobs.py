"""Job posting, source configuration, and application lifecycle schemas."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from job_agent.schemas._common import AwareDatetime, NonEmptyStr, load_yaml_mapping


class WorkMode(StrEnum):
    """Normalized work mode for a job posting."""

    REMOTE = "remote"
    HYBRID = "hybrid"
    ONSITE = "onsite"
    UNKNOWN = "unknown"


class ApplicationStatus(StrEnum):
    """Lifecycle states for tracked job postings."""

    PENDING_SCORING = "Pending_Scoring"
    PRE_FILTERED_OUT = "PreFiltered_Out"
    SCORED_OUT = "Scored_Out"
    QUEUED_FOR_DRAFTING = "Queued_For_Drafting"
    EXPIRED = "Expired"
    PENDING_REVIEW = "Pending_Review"
    REVISING = "Revising"
    READY_TO_SUBMIT = "Ready_to_Submit"
    APPLIED = "Applied"
    INTERVIEWING = "Interviewing"
    REJECTED = "Rejected"


class ArbeitnowConfig(BaseModel):
    """Configuration for the Arbeitnow public JSON adapter."""

    enabled: bool = True
    endpoint: str = "https://www.arbeitnow.com/api/job-board-api"


class RemotiveConfig(BaseModel):
    """Configuration for the Remotive public JSON adapter."""

    enabled: bool = True
    endpoint: str = "https://remotive.com/api/remote-jobs"
    category: str | None = "software-dev"


class HimalayasConfig(BaseModel):
    """Configuration for the Himalayas JSON API adapter."""

    enabled: bool = True
    endpoint: str = "https://himalayas.app/jobs/api"
    limit: int = Field(default=50, ge=1)
    api_key_env: str | None = "HIMALAYAS_API_KEY"


class JobicyConfig(BaseModel):
    """Configuration for the Jobicy public JSON adapter."""

    enabled: bool = True
    endpoint: str = "https://jobicy.com/api/jobs"
    geo: str | None = "europe"
    count: int = Field(default=50, ge=1)
    industry: str | None = None
    tag: str | None = None
    min_request_interval_seconds: float = Field(default=1.0, ge=0.0)


class JobindexRssConfig(BaseModel):
    """Configuration for the Jobindex dynamic RSS feed adapter."""

    enabled: bool = False
    feed_urls: list[str] = Field(default_factory=list)


class SourcesConfig(BaseModel):
    """Whitelisted discovery adapter configuration."""

    arbeitnow: ArbeitnowConfig = Field(default_factory=ArbeitnowConfig)
    remotive: RemotiveConfig = Field(default_factory=RemotiveConfig)
    himalayas: HimalayasConfig = Field(default_factory=HimalayasConfig)
    jobicy: JobicyConfig = Field(default_factory=JobicyConfig)
    jobindex_rss: JobindexRssConfig = Field(default_factory=JobindexRssConfig)

    @model_validator(mode="before")
    @classmethod
    def _unwrap_sources_root(cls, data: Any) -> Any:
        """Accept both top-level `sources:` YAML wrapper and direct adapter fields."""
        if isinstance(data, dict) and set(data.keys()) == {"sources"}:
            inner = data["sources"]
            if inner is None:
                return {}
            if isinstance(inner, dict):
                return inner
        return data


class RawJob(BaseModel):
    """Pre-normalization job payload returned by discovery adapters."""

    source: NonEmptyStr
    title: NonEmptyStr
    company: str = ""
    location: str = ""
    work_mode: WorkMode = WorkMode.UNKNOWN
    apply_url: str = ""
    description: str = ""
    posted_at: AwareDatetime | None = None
    application_deadline: AwareDatetime | None = None
    external_id: str | None = None
    raw_metadata: dict[str, Any] = Field(default_factory=dict)


class JobPosting(BaseModel):
    """Canonical normalized job posting ready for filtering and persistence."""

    job_id: NonEmptyStr
    source: NonEmptyStr
    title: NonEmptyStr
    company: str = ""
    location: str = ""
    work_mode: WorkMode = WorkMode.UNKNOWN
    apply_url: str = ""
    description: str = ""
    language: Literal["da", "en"]
    posted_at: AwareDatetime | None = None
    application_deadline: AwareDatetime | None = None
    ingested_at: AwareDatetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    external_id: str | None = None
    raw_metadata: dict[str, Any] = Field(default_factory=dict)


def load_sources_config(path: Path | str) -> SourcesConfig:
    """Load and validate SourcesConfig from a YAML file."""
    data = load_yaml_mapping(path)
    return SourcesConfig.model_validate(data)
