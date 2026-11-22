"""Intent-rooted unit tests for the deterministic pre-filter engine."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from job_agent.filters import PreFilterResult, evaluate_prefilter
from job_agent.schemas import (
    Dealbreakers,
    FreshnessPolicy,
    JobPosting,
    JobPreferences,
    LocationsConfig,
    SeniorityPolicy,
    WorkMode,
    load_job_preferences,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_PREFS_PATH = REPO_ROOT / "config" / "target_roles.example.yaml"
FIXED_NOW = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)


def _make_job(**overrides: object) -> JobPosting:
    """Build a valid entry-level Copenhagen JobPosting with sensible defaults."""
    defaults: dict[str, object] = {
        "job_id": "0123456789abcdef",
        "source": "arbeitnow",
        "title": "Junior Software Engineer",
        "company": "Nordic Cloud Labs",
        "location": "Copenhagen, Denmark",
        "work_mode": WorkMode.HYBRID,
        "apply_url": "https://example.com/jobs/1",
        "description": "Entry-level Python and SQL backend role in Copenhagen.",
        "language": "en",
        "posted_at": FIXED_NOW - timedelta(days=3),
        "application_deadline": None,
        "ingested_at": FIXED_NOW,
    }
    defaults.update(overrides)
    return JobPosting(**defaults)  # type: ignore[arg-type]


def _default_prefs(**overrides: object) -> JobPreferences:
    """Load example target_roles preferences and apply optional overrides."""
    prefs = load_job_preferences(EXAMPLE_PREFS_PATH)
    return prefs.model_copy(update=overrides)


# ---------------------------------------------------------------------------
# Seniority gate tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "expected_keyword"),
    [
        ("Senior Software Engineer", "senior"),
        ("Sr. Backend Developer", "sr."),
        ("Sr Software Engineer", "sr"),
        ("Staff Engineer", "staff"),
        ("Principal Cloud Engineer", "principal"),
        ("Lead Backend Developer", "lead"),
        ("Engineering Manager", "manager"),
        ("Director of Engineering", "director"),
        ("Head of Data", "head of"),
        ("VP of Engineering", "vp"),
        ("Chief Solutions Officer", "chief"),
        ("Seniorudvikler", "seniorudvikler"),
        ("IT-Chef", "chef"),
        ("Team Leder", "leder"),
    ],
)
def test_reject_excluded_seniority_titles(title: str, expected_keyword: str) -> None:
    prefs = _default_prefs()
    job = _make_job(title=title)

    result = evaluate_prefilter(job, prefs, now=FIXED_NOW)

    assert isinstance(result, PreFilterResult)
    assert result.passed is False
    assert result.discard_without_storing is False
    assert result.reason is not None
    assert expected_keyword in result.reason.lower()


@pytest.mark.parametrize(
    "title",
    [
        "Associate Solutions Architect",
        "Solutions Architect",
        "Junior Software Engineer",
        "Graduate Backend Developer",
        "Pleasant Software Developer",
    ],
)
def test_allow_entry_level_and_architect_titles(title: str) -> None:
    prefs = _default_prefs()
    job = _make_job(title=title)

    result = evaluate_prefilter(job, prefs, now=FIXED_NOW)

    assert result.passed is True
    assert result.reason is None
    assert result.discard_without_storing is False


@pytest.mark.parametrize(
    "description",
    [
        "Minimum 5+ years of experience in Python and distributed systems.",
        "Vi søger en udvikler med 3 års erfaring i Python.",
        "You have 3+ years experience building APIs.",
        "Mindst 4 års relevant erfaring med backend-udvikling.",
        "Requires at least 3 yrs of software engineering.",
        "3-5 years of hands-on experience with cloud platforms.",
    ],
)
def test_reject_explicit_years_above_max_years_experience(description: str) -> None:
    prefs = _default_prefs(seniority_policy=SeniorityPolicy(max_years_experience=2))
    job = _make_job(title="Backend Developer", description=description)

    result = evaluate_prefilter(job, prefs, now=FIXED_NOW)

    assert result.passed is False
    assert result.discard_without_storing is False
    assert result.reason is not None
    assert "max_years_experience=2" in result.reason


@pytest.mark.parametrize(
    "description",
    [
        "Ideal candidate has 2 years of experience with Python.",
        "Looking for 1-2 years of experience in backend development.",
        "Our company founded 10 years ago is growing rapidly in Copenhagen.",
        "Celebrating 15 years of innovation in Nordic fintech.",
    ],
)
def test_allow_years_at_or_below_ceiling_and_non_experience_numbers(description: str) -> None:
    prefs = _default_prefs(seniority_policy=SeniorityPolicy(max_years_experience=2))
    job = _make_job(title="Junior Software Engineer", description=description)

    result = evaluate_prefilter(job, prefs, now=FIXED_NOW)

    assert result.passed is True


# ---------------------------------------------------------------------------
# Posting freshness gate tests
# ---------------------------------------------------------------------------


def test_freshness_boundary_21_days_passes_and_22_days_discards() -> None:
    prefs = _default_prefs(freshness_policy=FreshnessPolicy(max_age_days=21))

    at_boundary = _make_job(posted_at=FIXED_NOW - timedelta(days=21), application_deadline=None)
    at_result = evaluate_prefilter(at_boundary, prefs, now=FIXED_NOW)
    assert at_result.passed is True
    assert at_result.discard_without_storing is False

    stale_job = _make_job(posted_at=FIXED_NOW - timedelta(days=22), application_deadline=None)
    stale_result = evaluate_prefilter(stale_job, prefs, now=FIXED_NOW)
    assert stale_result.passed is False
    assert stale_result.discard_without_storing is True
    assert stale_result.reason is not None
    assert "max_age_days=21" in stale_result.reason


def test_freshness_accepts_older_posting_with_future_deadline() -> None:
    prefs = _default_prefs(freshness_policy=FreshnessPolicy(max_age_days=21))
    job = _make_job(
        posted_at=FIXED_NOW - timedelta(days=25),
        application_deadline=FIXED_NOW + timedelta(days=5),
    )

    result = evaluate_prefilter(job, prefs, now=FIXED_NOW)

    assert result.passed is True
    assert result.discard_without_storing is False


def test_freshness_rejects_and_discards_older_posting_with_past_deadline() -> None:
    prefs = _default_prefs(freshness_policy=FreshnessPolicy(max_age_days=21))
    job = _make_job(
        posted_at=FIXED_NOW - timedelta(days=25),
        application_deadline=FIXED_NOW - timedelta(days=1),
    )

    result = evaluate_prefilter(job, prefs, now=FIXED_NOW)

    assert result.passed is False
    assert result.discard_without_storing is True


def test_freshness_passes_when_posted_at_is_missing() -> None:
    prefs = _default_prefs()
    job = _make_job(posted_at=None, application_deadline=None)

    result = evaluate_prefilter(job, prefs, now=FIXED_NOW)

    assert result.passed is True
    assert result.discard_without_storing is False


def test_freshness_manual_drop_bypasses_age_cutoff() -> None:
    prefs = _default_prefs(freshness_policy=FreshnessPolicy(max_age_days=21))
    job = _make_job(
        source="manual",
        posted_at=FIXED_NOW - timedelta(days=30),
        application_deadline=None,
    )

    result = evaluate_prefilter(job, prefs, now=FIXED_NOW)

    assert result.passed is True
    assert result.discard_without_storing is False

    senior_manual = _make_job(
        source="manual",
        title="Senior Software Engineer",
        posted_at=FIXED_NOW - timedelta(days=30),
    )
    senior_result = evaluate_prefilter(senior_manual, prefs, now=FIXED_NOW)
    assert senior_result.passed is False
    assert senior_result.discard_without_storing is False


def test_freshness_strict_second_past_max_age_and_exact_deadline_boundary() -> None:
    prefs = _default_prefs(freshness_policy=FreshnessPolicy(max_age_days=21))

    one_second_over = _make_job(
        posted_at=FIXED_NOW - timedelta(days=21, seconds=1),
        application_deadline=None,
    )
    over_res = evaluate_prefilter(one_second_over, prefs, now=FIXED_NOW)
    assert over_res.passed is False
    assert over_res.discard_without_storing is True

    exact_deadline = _make_job(
        posted_at=FIXED_NOW - timedelta(days=25),
        application_deadline=FIXED_NOW,
    )
    deadline_res = evaluate_prefilter(exact_deadline, prefs, now=FIXED_NOW)
    assert deadline_res.passed is False
    assert deadline_res.discard_without_storing is True


def test_freshness_normalizes_naive_now_and_offset_timestamps() -> None:
    prefs = _default_prefs(freshness_policy=FreshnessPolicy(max_age_days=21))
    naive_now = datetime(2026, 6, 15, 12, 0, 0)
    copenhagen_offset = timezone(timedelta(hours=2))
    posted_21d_local = datetime(2026, 5, 25, 14, 0, 0, tzinfo=copenhagen_offset)
    job = _make_job(posted_at=posted_21d_local, application_deadline=None)

    result = evaluate_prefilter(job, prefs, now=naive_now)

    assert result.passed is True


# ---------------------------------------------------------------------------
# Location and work-mode gate tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("location", "work_mode"),
    [
        ("Copenhagen, Denmark", WorkMode.ONSITE),
        ("Copenhagen, Denmark", WorkMode.HYBRID),
        ("København K", WorkMode.ONSITE),
        ("Frederiksberg, Danmark", WorkMode.HYBRID),
        ("Europe", WorkMode.REMOTE),
        ("Remote - EU", WorkMode.REMOTE),
        ("EMEA", WorkMode.REMOTE),
        ("Worldwide", WorkMode.REMOTE),
        ("Remote (CET)", WorkMode.UNKNOWN),
    ],
)
def test_accept_allowed_copenhagen_and_europe_remote_locations(
    location: str, work_mode: WorkMode
) -> None:
    prefs = _default_prefs()
    job = _make_job(location=location, work_mode=work_mode)

    result = evaluate_prefilter(job, prefs, now=FIXED_NOW)

    assert result.passed is True


@pytest.mark.parametrize(
    ("location", "work_mode"),
    [
        ("Remote (US Only)", WorkMode.REMOTE),
        ("Remote (US Only)", WorkMode.UNKNOWN),
        ("Remote - North America", WorkMode.REMOTE),
        ("On-site — San Francisco, CA", WorkMode.ONSITE),
        ("On-site — San Francisco, CA", WorkMode.UNKNOWN),
        ("New York, NY", WorkMode.HYBRID),
        ("Bellevue, WA", WorkMode.ONSITE),
    ],
)
def test_reject_us_only_remote_and_non_allowed_cities(
    location: str, work_mode: WorkMode
) -> None:
    prefs = _default_prefs()
    job = _make_job(location=location, work_mode=work_mode)

    result = evaluate_prefilter(job, prefs, now=FIXED_NOW)

    assert result.passed is False
    assert result.discard_without_storing is False
    assert result.reason is not None


def test_reject_disallowed_work_mode() -> None:
    prefs = _default_prefs(
        locations=LocationsConfig(
            allowed_cities=["Copenhagen"],
            allowed_countries=["Denmark"],
            allowed_work_modes=["remote", "hybrid"],
            remote_allowed_regions=["Denmark", "Europe"],
        )
    )
    job = _make_job(location="Copenhagen, Denmark", work_mode=WorkMode.ONSITE)

    result = evaluate_prefilter(job, prefs, now=FIXED_NOW)

    assert result.passed is False
    assert result.discard_without_storing is False
    assert result.reason is not None
    assert "onsite" in result.reason.lower()


def test_unknown_work_mode_remote_region_requires_remote_allowed() -> None:
    prefs = _default_prefs(
        locations=LocationsConfig(
            allowed_cities=["Copenhagen"],
            allowed_work_modes=["onsite", "hybrid"],
            remote_allowed_regions=["CET"],
        )
    )
    job = _make_job(location="CET", work_mode=WorkMode.UNKNOWN)

    result = evaluate_prefilter(job, prefs, now=FIXED_NOW)

    assert result.passed is False
    assert result.discard_without_storing is False


def test_empty_location_config_imposes_no_geo_restriction() -> None:
    prefs = _default_prefs(locations=LocationsConfig())
    job = _make_job(location="Berlin, Germany", work_mode=WorkMode.ONSITE)

    result = evaluate_prefilter(job, prefs, now=FIXED_NOW)

    assert result.passed is True


# ---------------------------------------------------------------------------
# Dealbreaker negative filter tests
# ---------------------------------------------------------------------------


def test_dealbreakers_empty_default_passes_cleanly() -> None:
    prefs = _default_prefs()
    assert prefs.dealbreakers == Dealbreakers()
    job = _make_job()

    result = evaluate_prefilter(job, prefs, now=FIXED_NOW)

    assert result.passed is True


def test_dealbreakers_reject_excluded_company_without_false_substring_match() -> None:
    prefs = _default_prefs(dealbreakers=Dealbreakers(excluded_companies=["Meta"]))

    rejected = evaluate_prefilter(_make_job(company="Meta Platforms"), prefs, now=FIXED_NOW)
    assert rejected.passed is False
    assert rejected.discard_without_storing is False
    assert rejected.reason is not None
    assert "excluded_companies" in rejected.reason
    assert "Meta" in rejected.reason

    allowed = evaluate_prefilter(_make_job(company="Metadata Labs"), prefs, now=FIXED_NOW)
    assert allowed.passed is True


def test_dealbreakers_reject_excluded_industry_contract_and_red_flags() -> None:
    prefs = _default_prefs(
        dealbreakers=Dealbreakers(
            excluded_industries=["Gambling"],
            excluded_contract_types=["Freelance"],
            red_flag_keywords=["unpaid", "commission only"],
        )
    )

    industry_job = _make_job(raw_metadata={"industry": "Online Gambling"})
    res_industry = evaluate_prefilter(industry_job, prefs, now=FIXED_NOW)
    assert res_industry.passed is False
    assert res_industry.discard_without_storing is False
    assert res_industry.reason is not None and "Gambling" in res_industry.reason

    contract_job = _make_job(raw_metadata={"contract_type": "Freelance"})
    res_contract = evaluate_prefilter(contract_job, prefs, now=FIXED_NOW)
    assert res_contract.passed is False
    assert res_contract.discard_without_storing is False
    assert res_contract.reason is not None and "Freelance" in res_contract.reason

    red_flag_job = _make_job(description="This is an unpaid internship opportunity.")
    res_flag = evaluate_prefilter(red_flag_job, prefs, now=FIXED_NOW)
    assert res_flag.passed is False
    assert res_flag.discard_without_storing is False
    assert res_flag.reason is not None and "unpaid" in res_flag.reason


def test_freshness_defaults_to_current_utc_when_now_omitted() -> None:
    prefs = _default_prefs()
    now = datetime.now(timezone.utc)

    fresh_job = _make_job(posted_at=now - timedelta(days=2))
    stale_job = _make_job(posted_at=now - timedelta(days=25))

    assert evaluate_prefilter(fresh_job, prefs).passed is True
    stale_res = evaluate_prefilter(stale_job, prefs)
    assert stale_res.passed is False
    assert stale_res.discard_without_storing is True
