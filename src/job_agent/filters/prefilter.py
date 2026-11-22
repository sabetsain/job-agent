"""Deterministic pre-filtering rules applied before LLM scoring."""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel

from job_agent.schemas.jobs import JobPosting, WorkMode
from job_agent.schemas.preferences import (
    Dealbreakers,
    FreshnessPolicy,
    JobPreferences,
    LocationsConfig,
    SeniorityPolicy,
)

_YEARS_EXPERIENCE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(\d+)\+?\s*(?:to\s+\d+\s+|-\s*\d+\s+)?"
        r"(?:years?|yrs?|år|års)(?:\s+of)?(?:\s+[\w-]+){0,2}\s+"
        r"(?:experience|erfaring)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:minimum|min\.?|at\s+least|mindst)\s+(\d+)\+?\s*"
        r"(?:years?|yrs?|år|års)\b",
        re.IGNORECASE,
    ),
)

_MENTIONS_REMOTE_RE = re.compile(r"(?<!\w)remote(?!\w)", re.IGNORECASE)
_MENTIONS_HYBRID_RE = re.compile(r"(?<!\w)hybrid(?!\w)", re.IGNORECASE)
_MENTIONS_ONSITE_RE = re.compile(r"(?<!\w)on-?site(?!\w)", re.IGNORECASE)
_DISALLOWED_REMOTE_ONLY_RE = re.compile(
    r"(?<!\w)(?:us|u\.s\.|usa|united\s+states|north\s+america)\s+only(?!\w)",
    re.IGNORECASE,
)


class PreFilterResult(BaseModel):
    """Outcome of deterministic pre-filter evaluation for a job posting."""

    passed: bool
    reason: str | None = None
    discard_without_storing: bool = False


def _to_utc(dt: datetime) -> datetime:
    """Normalize a naive or timezone-aware datetime to UTC."""
    if dt.tzinfo is None or dt.utcoffset() is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _compile_keyword_pattern(keyword: str) -> re.Pattern[str] | None:
    """Build a case-insensitive boundary-aware regex for a keyword or phrase."""
    cleaned = keyword.strip()
    if not cleaned:
        return None
    parts = [re.escape(part) for part in cleaned.split()]
    body = r"\s+".join(parts)
    prefix = r"(?<!\w)" if (cleaned[0].isalnum() or cleaned[0] == "_") else ""
    suffix = r"(?!\w)" if (cleaned[-1].isalnum() or cleaned[-1] == "_") else ""
    return re.compile(f"{prefix}{body}{suffix}", re.IGNORECASE)


def _find_matching_keyword(texts: Iterable[str], keywords: Iterable[str]) -> str | None:
    """Return the first keyword matching any non-empty text, or None."""
    haystack = [text for text in texts if text]
    if not haystack:
        return None
    for raw_kw in keywords:
        pattern = _compile_keyword_pattern(raw_kw)
        if pattern is None:
            continue
        if any(pattern.search(text) for text in haystack):
            return raw_kw.strip()
    return None


def _extract_metadata_strings(raw_metadata: dict[str, Any], keys: tuple[str, ...]) -> list[str]:
    """Extract string or list-of-string values for selected metadata keys."""
    values: list[str] = []
    for key in keys:
        val = raw_metadata.get(key)
        if isinstance(val, str) and val.strip():
            values.append(val)
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, str) and item.strip():
                    values.append(item)
    return values


def check_freshness(
    job: JobPosting,
    policy: FreshnessPolicy,
    now: datetime | None = None,
) -> PreFilterResult:
    """Enforce posting age cutoff with manual-drop, missing-timestamp, and deadline rules."""
    if job.source.strip().lower() == "manual":
        return PreFilterResult(passed=True)

    if job.posted_at is None:
        return PreFilterResult(passed=True)

    current_time = _to_utc(now) if now is not None else datetime.now(timezone.utc)

    if job.application_deadline is not None:
        if _to_utc(job.application_deadline) > current_time:
            return PreFilterResult(passed=True)

    age = current_time - _to_utc(job.posted_at)
    if age > timedelta(days=policy.max_age_days):
        return PreFilterResult(
            passed=False,
            reason=(
                f"Posting age ({age.days} days) exceeds max_age_days={policy.max_age_days} "
                "with no future application deadline"
            ),
            discard_without_storing=True,
        )

    return PreFilterResult(passed=True)


def check_seniority(job: JobPosting, policy: SeniorityPolicy) -> PreFilterResult:
    """Reject Senior+ titles and descriptions demanding more than max_years_experience."""
    matched_title_kw = _find_matching_keyword([job.title], policy.excluded_title_keywords)
    if matched_title_kw is not None:
        return PreFilterResult(
            passed=False,
            reason=f"Excluded seniority title keyword matched: '{matched_title_kw}'",
            discard_without_storing=False,
        )

    for pattern in _YEARS_EXPERIENCE_PATTERNS:
        for match in pattern.finditer(job.description):
            years = int(match.group(1))
            if years > policy.max_years_experience:
                return PreFilterResult(
                    passed=False,
                    reason=(
                        f"Requires minimum {years} years of experience "
                        f"(exceeds max_years_experience={policy.max_years_experience})"
                    ),
                    discard_without_storing=False,
                )

    return PreFilterResult(passed=True)


def _infer_work_mode(job: JobPosting) -> tuple[WorkMode, bool]:
    """Return effective work mode and whether remote was signaled in location."""
    if job.work_mode != WorkMode.UNKNOWN:
        return job.work_mode, job.work_mode == WorkMode.REMOTE

    location_text = job.location.strip()
    if _MENTIONS_REMOTE_RE.search(location_text):
        return WorkMode.REMOTE, True
    if _MENTIONS_HYBRID_RE.search(location_text):
        return WorkMode.HYBRID, False
    if _MENTIONS_ONSITE_RE.search(location_text):
        return WorkMode.ONSITE, False
    return WorkMode.UNKNOWN, False


def check_location_and_work_mode(
    job: JobPosting,
    locations: LocationsConfig,
) -> PreFilterResult:
    """Verify work mode and geographic eligibility against configured location rules."""
    effective_mode, is_remote = _infer_work_mode(job)

    if effective_mode != WorkMode.UNKNOWN and effective_mode.value not in locations.allowed_work_modes:
        return PreFilterResult(
            passed=False,
            reason=f"Work mode '{effective_mode.value}' is not in allowed_work_modes",
            discard_without_storing=False,
        )

    has_geo_constraints = bool(
        locations.allowed_cities
        or locations.allowed_countries
        or locations.allowed_regions
        or locations.remote_allowed_regions
    )
    if not has_geo_constraints:
        return PreFilterResult(passed=True)

    location_text = job.location.strip()

    if is_remote:
        remote_regions = locations.remote_allowed_regions or [
            *locations.allowed_regions,
            *locations.allowed_countries,
            *locations.allowed_cities,
        ]
        if _DISALLOWED_REMOTE_ONLY_RE.search(location_text) and _find_matching_keyword(
            ["us", "usa", "u.s.", "united states", "north america"],
            remote_regions,
        ) is None:
            return PreFilterResult(
                passed=False,
                reason=f"Remote location '{job.location}' is restricted to a non-allowed region",
                discard_without_storing=False,
            )
        if _find_matching_keyword([location_text], remote_regions) is None:
            return PreFilterResult(
                passed=False,
                reason=f"Remote location '{job.location}' does not match allowed remote regions",
                discard_without_storing=False,
            )
        return PreFilterResult(passed=True)

    allowed_geo = [
        *locations.allowed_cities,
        *locations.allowed_countries,
        *locations.allowed_regions,
    ]
    if job.work_mode == WorkMode.UNKNOWN and "remote" in locations.allowed_work_modes:
        allowed_geo = [*allowed_geo, *locations.remote_allowed_regions]

    if not allowed_geo or _find_matching_keyword([location_text], allowed_geo) is None:
        return PreFilterResult(
            passed=False,
            reason=(
                f"Location '{job.location}' does not match allowed cities, countries, or regions"
            ),
            discard_without_storing=False,
        )

    return PreFilterResult(passed=True)


def check_dealbreakers(job: JobPosting, dealbreakers: Dealbreakers) -> PreFilterResult:
    """Reject postings matching configured companies, industries, contract types, or red flags."""
    matched_company = _find_matching_keyword([job.company], dealbreakers.excluded_companies)
    if matched_company is not None:
        return PreFilterResult(
            passed=False,
            reason=f"Dealbreaker (excluded_companies): '{matched_company}'",
            discard_without_storing=False,
        )

    industry_texts = [
        job.title,
        job.description,
        *_extract_metadata_strings(
            job.raw_metadata, ("industry", "industries", "category", "categories", "tags")
        ),
    ]
    matched_industry = _find_matching_keyword(industry_texts, dealbreakers.excluded_industries)
    if matched_industry is not None:
        return PreFilterResult(
            passed=False,
            reason=f"Dealbreaker (excluded_industries): '{matched_industry}'",
            discard_without_storing=False,
        )

    contract_texts = [
        job.title,
        job.description,
        *_extract_metadata_strings(
            job.raw_metadata,
            ("contract_type", "job_type", "employment_type", "job_types", "tags"),
        ),
    ]
    matched_contract = _find_matching_keyword(contract_texts, dealbreakers.excluded_contract_types)
    if matched_contract is not None:
        return PreFilterResult(
            passed=False,
            reason=f"Dealbreaker (excluded_contract_types): '{matched_contract}'",
            discard_without_storing=False,
        )

    red_flag_texts = [job.company, job.title, job.description]
    matched_red_flag = _find_matching_keyword(red_flag_texts, dealbreakers.red_flag_keywords)
    if matched_red_flag is not None:
        return PreFilterResult(
            passed=False,
            reason=f"Dealbreaker (red_flag_keywords): '{matched_red_flag}'",
            discard_without_storing=False,
        )

    return PreFilterResult(passed=True)


def evaluate_prefilter(
    job: JobPosting,
    preferences: JobPreferences,
    now: datetime | None = None,
) -> PreFilterResult:
    """Run all deterministic pre-filter gates in sequence on a normalized JobPosting."""
    current_time = _to_utc(now) if now is not None else datetime.now(timezone.utc)

    for result in (
        check_freshness(job, preferences.freshness_policy, now=current_time),
        check_seniority(job, preferences.seniority_policy),
        check_location_and_work_mode(job, preferences.locations),
        check_dealbreakers(job, preferences.dealbreakers),
    ):
        if not result.passed:
            return result

    return PreFilterResult(passed=True)
