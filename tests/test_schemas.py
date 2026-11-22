"""Intent-rooted unit tests for domain schemas and YAML loaders."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from job_agent.llm import DEFAULT_OPENCODE_BASE_URL, LLMConfig, load_llm_config
from job_agent.schemas import (
    ApplicationStatus,
    FreshnessPolicy,
    JobPosting,
    JobPreferences,
    LayoutGuardrails,
    MasterProfile,
    RawJob,
    SeniorityPolicy,
    SeniorityTier,
    SourcesConfig,
    WorkMode,
    load_job_preferences,
    load_master_profile,
    load_sources_config,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "config"


# ---------------------------------------------------------------------------
# MasterProfile tests
# ---------------------------------------------------------------------------


def test_load_valid_master_profile_example_yaml() -> None:
    profile = load_master_profile(CONFIG_DIR / "master_profile.example.yaml")

    assert isinstance(profile, MasterProfile)
    assert profile.identity.full_name == "Example Candidate"
    assert profile.identity.email == "candidate@example.com"
    assert len(profile.experiences) == 1
    assert profile.experiences[0].company == "Nordic Cloud Labs"
    assert profile.experiences[0].bullets[0].metrics == ["~1,200 daily requests", "99.9% uptime"]
    assert len(profile.projects) == 1
    assert len(profile.education) == 1
    assert len(profile.certifications) == 1
    assert [lang.language for lang in profile.languages] == ["en", "da"]
    assert "Python" in profile.skills.languages


@pytest.mark.parametrize("missing_field", ["full_name", "email"])
def test_reject_master_profile_missing_required_identity_fields(
    tmp_path: Path, missing_field: str
) -> None:
    identity = {"full_name": "Test Candidate", "email": "test@example.com"}
    del identity[missing_field]
    yaml_path = tmp_path / "profile.yaml"
    yaml_path.write_text(
        f"identity:\n" + "\n".join(f"  {k}: {v!r}" for k, v in identity.items()),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError) as exc_info:
        load_master_profile(yaml_path)

    error_locs = [err["loc"] for err in exc_info.value.errors()]
    assert ("identity", missing_field) in error_locs


@pytest.mark.parametrize("bad_value", ["", "   "])
def test_reject_master_profile_whitespace_identity_fields(bad_value: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        MasterProfile.model_validate(
            {"identity": {"full_name": bad_value, "email": "test@example.com"}}
        )
    assert any(err["loc"] == ("identity", "full_name") for err in exc_info.value.errors())


@pytest.mark.parametrize("missing_field", ["company", "title", "start_date"])
def test_reject_master_profile_experience_missing_required_field(
    tmp_path: Path, missing_field: str
) -> None:
    exp = {
        "company": "Nordic Cloud Labs",
        "title": "Junior Software Engineer",
        "start_date": "2024-02",
    }
    del exp[missing_field]
    yaml_path = tmp_path / "profile.yaml"
    yaml_lines = [
        "identity:",
        "  full_name: 'Test Candidate'",
        "  email: 'test@example.com'",
        "experiences:",
        "  - " + "\n    ".join(f"{k}: {v!r}" for k, v in exp.items()),
    ]
    yaml_path.write_text("\n".join(yaml_lines), encoding="utf-8")

    with pytest.raises(ValidationError) as exc_info:
        load_master_profile(yaml_path)

    error_locs = [err["loc"] for err in exc_info.value.errors()]
    assert ("experiences", 0, missing_field) in error_locs


# ---------------------------------------------------------------------------
# JobPreferences tests
# ---------------------------------------------------------------------------


def test_load_valid_job_preferences_example_yaml() -> None:
    prefs = load_job_preferences(CONFIG_DIR / "target_roles.example.yaml")

    assert isinstance(prefs, JobPreferences)
    assert "Junior Software Engineer" in prefs.target_roles.primary
    assert "Associate Solutions Architect" in prefs.target_roles.adjacent
    assert "Copenhagen" in prefs.locations.allowed_cities
    assert prefs.seniority_policy.max_years_experience == 2
    assert prefs.freshness_policy.max_age_days == 21
    assert prefs.freshness_policy.preferred_age_days == 7
    assert prefs.freshness_policy.daily_draft_limit == 3
    assert prefs.dealbreakers.excluded_companies == []
    assert prefs.layout_guardrails.min_font_size_pt == 10.0
    assert prefs.layout_guardrails.max_body_font_size_pt == 12.0
    assert prefs.layout_guardrails.preserve_whitespace_and_margins is True
    assert not hasattr(prefs, "voice_skill_path")
    assert not hasattr(prefs.scoring_rubric, "min_fit_score")


def test_seniority_policy_default_does_not_exclude_architect() -> None:
    policy = SeniorityPolicy()

    assert policy.max_years_experience == 2
    assert all("architect" not in kw.lower() for kw in policy.excluded_title_keywords)
    assert "senior" in policy.excluded_title_keywords


def test_layout_guardrails_body_font_size_bounds() -> None:
    allowed = LayoutGuardrails(min_font_size_pt=9.0, max_body_font_size_pt=12.0)
    assert allowed.min_font_size_pt == 9.0
    assert allowed.max_body_font_size_pt == 12.0

    with pytest.raises(ValidationError):
        LayoutGuardrails(min_font_size_pt=8.9)

    with pytest.raises(ValidationError):
        LayoutGuardrails(max_body_font_size_pt=12.1)

    with pytest.raises(ValidationError):
        LayoutGuardrails(min_font_size_pt=11.0, max_body_font_size_pt=10.5)


def test_seniority_tier_coverage_validation() -> None:
    equal_coverage = SeniorityPolicy(
        entry_level=SeniorityTier(max_years=1, min_must_have_coverage=0.80),
        stretch=SeniorityTier(max_years=2, min_must_have_coverage=0.80),
    )
    assert equal_coverage.stretch.min_must_have_coverage == 0.80

    with pytest.raises(ValidationError):
        SeniorityPolicy(
            entry_level=SeniorityTier(max_years=1, min_must_have_coverage=0.65),
            stretch=SeniorityTier(max_years=2, min_must_have_coverage=0.64),
        )


def test_freshness_policy_bounds() -> None:
    equal_age = FreshnessPolicy(max_age_days=21, preferred_age_days=21, daily_draft_limit=1)
    assert equal_age.preferred_age_days == 21
    assert equal_age.daily_draft_limit == 1

    with pytest.raises(ValidationError):
        FreshnessPolicy(max_age_days=21, preferred_age_days=22, daily_draft_limit=3)

    with pytest.raises(ValidationError):
        FreshnessPolicy(max_age_days=21, preferred_age_days=7, daily_draft_limit=0)

    with pytest.raises(ValidationError):
        FreshnessPolicy(max_age_days=0, preferred_age_days=0, daily_draft_limit=3)


def test_job_preferences_omits_removed_fields(tmp_path: Path) -> None:
    minimal_yaml = tmp_path / "target_roles.yaml"
    minimal_yaml.write_text("target_roles:\n  primary: ['Junior Software Engineer']\n", encoding="utf-8")

    prefs = load_job_preferences(minimal_yaml)
    assert prefs.seniority_policy.entry_level.min_must_have_coverage == 0.65
    assert prefs.seniority_policy.stretch.min_must_have_coverage == 0.95
    assert prefs.layout_guardrails.min_font_size_pt == 10.0
    assert prefs.layout_guardrails.max_body_font_size_pt == 12.0


def test_load_valid_llm_config_example_yaml() -> None:
    cfg = load_llm_config(CONFIG_DIR / "llm.example.yaml")

    assert isinstance(cfg, LLMConfig)
    assert cfg.base_url == DEFAULT_OPENCODE_BASE_URL
    assert cfg.api_key_env == "OPENCODE_API_KEY"
    assert cfg.scoring_model == "deepseek-v4.1-flash"
    assert cfg.reasoning_model == "deepseek-v4-pro"
    assert cfg.max_parse_retries == 2
    assert cfg.structured_output_method == "json_schema"


@pytest.mark.parametrize("bad_model", ["", "   "])
def test_llm_config_rejects_empty_models(bad_model: str) -> None:
    with pytest.raises(ValidationError):
        LLMConfig(scoring_model=bad_model, reasoning_model="deepseek-v4-pro")

    with pytest.raises(ValidationError):
        LLMConfig(scoring_model="deepseek-v4.1-flash", reasoning_model=bad_model)


# ---------------------------------------------------------------------------
# SourcesConfig, RawJob, JobPosting, and ApplicationStatus tests
# ---------------------------------------------------------------------------


def test_load_valid_sources_config_example_yaml() -> None:
    cfg = load_sources_config(CONFIG_DIR / "sources.example.yaml")

    assert isinstance(cfg, SourcesConfig)
    assert cfg.arbeitnow.enabled is True
    assert cfg.remotive.category == "software-dev"
    assert cfg.himalayas.limit == 50
    assert cfg.himalayas.api_key_env == "HIMALAYAS_API_KEY"
    assert cfg.jobicy.geo == "europe"
    assert cfg.jobicy.min_request_interval_seconds == 1.0
    assert cfg.jobindex_rss.enabled is False
    assert cfg.jobindex_rss.feed_urls == []


def test_application_status_enum_values() -> None:
    expected = {
        "Pending_Scoring",
        "PreFiltered_Out",
        "Scored_Out",
        "Queued_For_Drafting",
        "Expired",
        "Pending_Review",
        "Revising",
        "Ready_to_Submit",
        "Applied",
        "Interviewing",
        "Rejected",
    }
    assert {status.value for status in ApplicationStatus} == expected


@pytest.mark.parametrize("lang", ["da", "en"])
def test_job_posting_accepts_supported_languages(lang: str) -> None:
    posting = JobPosting(
        job_id="0123456789abcdef",
        source="jobindex_rss",
        title="Junior Software Engineer",
        company="Nordic Cloud Labs",
        location="Copenhagen, Denmark",
        work_mode=WorkMode.HYBRID,
        apply_url="https://example.com/jobs/1",
        description="Entry-level Python role in Copenhagen.",
        language=lang,  # type: ignore[arg-type]
    )
    assert posting.language == lang
    assert posting.ingested_at.tzinfo is not None


@pytest.mark.parametrize("invalid_lang", ["de", "sv", "fr", ""])
def test_job_posting_rejects_unsupported_language(invalid_lang: str) -> None:
    with pytest.raises(ValidationError):
        JobPosting(
            job_id="0123456789abcdef",
            source="arbeitnow",
            title="Junior Software Engineer",
            company="Example Co",
            description="Role description",
            language=invalid_lang,  # type: ignore[arg-type]
        )


def test_job_posting_preserves_and_normalizes_timestamps() -> None:
    posting = JobPosting(
        job_id="abcdef0123456789",
        source="jobindex_rss",
        title="Graduate Backend Developer",
        company="Copenhagen Tech",
        description="Vi søger en nyuddannet backend-udvikler.",
        language="da",
        posted_at="2026-05-01T09:30:00Z",  # type: ignore[arg-type]
        application_deadline="2026-05-25T23:59:00+02:00",  # type: ignore[arg-type]
        ingested_at=datetime(2026, 5, 2, 10, 0, 0),  # naive -> normalized to UTC
    )

    assert posting.posted_at is not None
    assert posting.posted_at.tzinfo is not None
    assert posting.posted_at.utcoffset() == timedelta(0)

    assert posting.application_deadline is not None
    assert posting.application_deadline.tzinfo is not None
    assert posting.application_deadline.utcoffset() == timedelta(hours=2)

    assert posting.ingested_at.tzinfo == timezone.utc


def test_raw_job_normalizes_naive_timestamps_to_utc() -> None:
    raw = RawJob(
        source="manual",
        title="Associate Solutions Architect",
        company="Cloud Co",
        posted_at=datetime(2026, 5, 1, 8, 0, 0),
        application_deadline=datetime(2026, 5, 20, 17, 0, 0),
    )

    assert raw.posted_at is not None and raw.posted_at.tzinfo == timezone.utc
    assert raw.application_deadline is not None and raw.application_deadline.tzinfo == timezone.utc
