"""Intent-rooted integration tests for SQLite repository, ingestion pipeline, and CLI."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, TypeVar

import httpx
import pytest
import respx
from pydantic import BaseModel
from typer.testing import CliRunner

from job_agent.auditing import AuditResult
from job_agent.cli import app
from job_agent.graph import (
    DraftDocuments,
    IdeationResponse,
    TailoringPlan,
    ThreadIntentDecision,
)
from job_agent.llm.client import ModelTier
from job_agent.pipeline import run_ingestion, submit_manual_job
from job_agent.rendering.models import (
    CVBullet,
    CVEducation,
    CVExperience,
    CVProject,
    CVSkillCategory,
    TailoredCoverLetter,
    TailoredCV,
)
from job_agent.schemas import (
    ApplicationStatus,
    JobPosting,
    JobPreferences,
    SourcesConfig,
    WorkMode,
    load_job_preferences,
)
from job_agent.scoring.models import FitDecision, ScoringEvidence
from job_agent.sources.manual import ManualDropError
from job_agent.sources.runner import IngestionFetchResult, SourceFetchError
from job_agent.storage import JobRepository, StoredJob

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_PREFS_PATH = REPO_ROOT / "config" / "target_roles.example.yaml"
EXAMPLE_PROFILE_PATH = REPO_ROOT / "config" / "master_profile.example.yaml"
EXAMPLE_LLM_CONFIG_PATH = REPO_ROOT / "config" / "llm.example.yaml"
FIXED_NOW = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
T = TypeVar("T", bound=BaseModel)


def _make_posting(**overrides: object) -> JobPosting:
    """Create a valid normalized JobPosting with sensible Copenhagen defaults."""
    defaults: dict[str, object] = {
        "job_id": "1111222233334444",
        "source": "arbeitnow",
        "external_id": "ext-1",
        "title": "Junior Software Engineer",
        "company": "Nordic Cloud Labs",
        "location": "Copenhagen, Denmark",
        "work_mode": WorkMode.HYBRID,
        "apply_url": "https://example.com/jobs/1",
        "description": "Entry-level Python and SQL backend engineering role in Copenhagen.",
        "language": "en",
        "posted_at": FIXED_NOW - timedelta(days=2),
        "application_deadline": None,
        "ingested_at": FIXED_NOW,
    }
    defaults.update(overrides)
    return JobPosting(**defaults)  # type: ignore[arg-type]


def _default_prefs() -> JobPreferences:
    """Load the project's example target_roles preferences."""
    return load_job_preferences(EXAMPLE_PREFS_PATH)


# ---------------------------------------------------------------------------
# Schema & Repository tests
# ---------------------------------------------------------------------------


def test_sqlite_schema_matches_spec_and_has_no_google_drive_columns(tmp_path: Path) -> None:
    db_path = tmp_path / "nested" / "dir" / "job_agent.db"
    repo = JobRepository(db_path)
    assert db_path.exists()

    with sqlite3.connect(db_path) as conn:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()]

    expected_columns = [
        "job_id",
        "source",
        "external_id",
        "title",
        "company",
        "location",
        "work_mode",
        "language",
        "apply_url",
        "description",
        "status",
        "rejection_reason",
        "fit_score",
        "fit_breakdown_json",
        "cv_pdf_path",
        "cover_letter_pdf_path",
        "slack_thread_ts",
        "gmail_thread_id",
        "langgraph_thread_id",
        "posted_at",
        "application_deadline",
        "created_at",
        "updated_at",
    ]
    assert columns == expected_columns
    assert not any("drive" in col.lower() for col in columns)
    assert repo.list_jobs() == []


def test_repository_insert_get_and_filter_list(tmp_path: Path) -> None:
    repo = JobRepository(tmp_path / "jobs.db")
    en_job = _make_posting(job_id="aaaa1111bbbb2222", language="en")
    da_job = _make_posting(
        job_id="cccc3333dddd4444",
        language="da",
        title="Junior Udvikler",
        source="jobindex_rss",
        posted_at=FIXED_NOW - timedelta(days=1),
    )

    repo.insert_job(en_job, ApplicationStatus.PENDING_SCORING, created_at=FIXED_NOW)
    repo.insert_job(
        da_job,
        ApplicationStatus.PRE_FILTERED_OUT,
        rejection_reason="Excluded seniority title keyword matched: 'senior'",
        created_at=FIXED_NOW + timedelta(minutes=5),
    )

    fetched = repo.get_job("aaaa1111bbbb2222")
    assert isinstance(fetched, StoredJob)
    assert fetched.status == ApplicationStatus.PENDING_SCORING
    assert fetched.rejection_reason is None
    assert fetched.posted_at == en_job.posted_at
    assert repo.get_job("nonexistent") is None

    pending = repo.list_jobs(status=ApplicationStatus.PENDING_SCORING)
    assert [j.job_id for j in pending] == ["aaaa1111bbbb2222"]

    danish = repo.list_jobs(language="da")
    assert [j.job_id for j in danish] == ["cccc3333dddd4444"]


# ---------------------------------------------------------------------------
# Pipeline: persistence, stale discard, idempotency
# ---------------------------------------------------------------------------


def test_run_ingestion_persists_pending_and_prefiltered_and_discards_stale() -> None:
    repo = JobRepository(":memory:")
    prefs = _default_prefs()

    passing = _make_posting(
        job_id="pass000000000001",
        title="Junior Software Engineer",
        posted_at=FIXED_NOW - timedelta(days=3),
    )
    prefiltered = _make_posting(
        job_id="pref000000000002",
        title="Senior Platform Engineer",
        posted_at=FIXED_NOW - timedelta(days=2),
    )
    stale = _make_posting(
        job_id="stal000000000003",
        title="Junior Backend Developer",
        posted_at=FIXED_NOW - timedelta(days=25),
        application_deadline=None,
    )

    fetch_result = IngestionFetchResult(
        postings=[passing, prefiltered, stale],
        errors=[SourceFetchError(source="remotive", error="HTTP 503")],
    )
    summary = run_ingestion(
        prefs,
        SourcesConfig(),
        repo,
        fetch_result=fetch_result,
        now=FIXED_NOW,
    )

    assert summary.fetched == 3
    assert summary.skipped == 0
    assert summary.discarded_stale == 1
    assert summary.passed == 1
    assert summary.prefiltered_out == 1
    assert summary.pruned == 0
    assert len(summary.source_errors) == 1

    stored_pass = repo.get_job("pass000000000001")
    assert stored_pass is not None
    assert stored_pass.status == ApplicationStatus.PENDING_SCORING
    assert stored_pass.rejection_reason is None

    stored_pref = repo.get_job("pref000000000002")
    assert stored_pref is not None
    assert stored_pref.status == ApplicationStatus.PRE_FILTERED_OUT
    assert stored_pref.rejection_reason is not None
    assert "senior" in stored_pref.rejection_reason.lower()

    assert repo.get_job("stal000000000003") is None


def test_run_ingestion_skips_existing_job_id_without_overwriting() -> None:
    repo = JobRepository(":memory:")
    prefs = _default_prefs()

    existing = _make_posting(
        job_id="applied000000001",
        title="Junior Software Engineer",
        posted_at=FIXED_NOW - timedelta(days=4),
    )
    repo.insert_job(existing, ApplicationStatus.APPLIED, created_at=FIXED_NOW - timedelta(days=1))
    repo.update_job(
        "applied000000001",
        cv_pdf_path="/tmp/cv.pdf",
        slack_thread_ts="1718452800.000100",
        fit_score=8.7,
        updated_at=FIXED_NOW - timedelta(hours=12),
    )

    reingested = _make_posting(
        job_id="applied000000001",
        title="Updated Title Should Be Ignored",
        posted_at=FIXED_NOW,
    )
    new_job = _make_posting(
        job_id="newjob0000000002",
        title="Associate Solutions Architect",
        posted_at=FIXED_NOW - timedelta(days=1),
    )

    summary = run_ingestion(
        prefs,
        SourcesConfig(),
        repo,
        fetch_result=IngestionFetchResult(postings=[reingested, new_job], errors=[]),
        now=FIXED_NOW,
    )

    assert summary.fetched == 2
    assert summary.skipped == 1
    assert summary.passed == 1

    untouched = repo.get_job("applied000000001")
    assert untouched is not None
    assert untouched.status == ApplicationStatus.APPLIED
    assert untouched.title == "Junior Software Engineer"
    assert untouched.cv_pdf_path == "/tmp/cv.pdf"
    assert untouched.slack_thread_ts == "1718452800.000100"
    assert untouched.fit_score == 8.7


# ---------------------------------------------------------------------------
# Priority candidate ordering & daily draft cap
# ---------------------------------------------------------------------------


def test_prioritized_candidates_prefers_7_day_and_future_deadline_over_older_eligible() -> None:
    repo = JobRepository(":memory:")

    three_days = _make_posting(
        job_id="age3_00000000001",
        posted_at=FIXED_NOW - timedelta(days=3),
        application_deadline=None,
    )
    fifteen_days = _make_posting(
        job_id="age15_0000000002",
        posted_at=FIXED_NOW - timedelta(days=15),
        application_deadline=None,
    )
    future_deadline = _make_posting(
        job_id="dead24_000000003",
        posted_at=FIXED_NOW - timedelta(days=24),
        application_deadline=FIXED_NOW + timedelta(days=5),
    )
    expired_deadline = _make_posting(
        job_id="exp10_0000000004",
        posted_at=FIXED_NOW - timedelta(days=10),
        application_deadline=FIXED_NOW - timedelta(days=1),
    )

    # Insert fallback postings in explicit FIFO order (exp10 queued before age15)
    repo.insert_job(expired_deadline, ApplicationStatus.QUEUED_FOR_DRAFTING, created_at=FIXED_NOW - timedelta(minutes=2))
    repo.insert_job(fifteen_days, ApplicationStatus.QUEUED_FOR_DRAFTING, created_at=FIXED_NOW - timedelta(minutes=1))
    repo.insert_job(future_deadline, ApplicationStatus.QUEUED_FOR_DRAFTING, created_at=FIXED_NOW)
    repo.insert_job(three_days, ApplicationStatus.QUEUED_FOR_DRAFTING, created_at=FIXED_NOW - timedelta(minutes=3))

    top_three = repo.list_prioritized_candidates(preferred_age_days=7, limit=3, now=FIXED_NOW)
    assert [job.job_id for job in top_three] == [
        "age3_00000000001",
        "dead24_000000003",
        "exp10_0000000004",
    ]

    all_four = repo.list_prioritized_candidates(preferred_age_days=7, limit=10, now=FIXED_NOW)
    assert [job.job_id for job in all_four] == [
        "age3_00000000001",
        "dead24_000000003",
        "exp10_0000000004",
        "age15_0000000002",
    ]


def test_prioritized_candidates_exact_preferred_age_boundary_and_fallback() -> None:
    repo = JobRepository(":memory:")

    exact_7_days = _make_posting(
        job_id="exact7_000000001",
        posted_at=FIXED_NOW - timedelta(days=7),
    )
    eight_days = _make_posting(
        job_id="age8_00000000002",
        posted_at=FIXED_NOW - timedelta(days=8),
    )
    twelve_days = _make_posting(
        job_id="age12_0000000003",
        posted_at=FIXED_NOW - timedelta(days=12),
    )
    drafted_recent = _make_posting(
        job_id="drafted_00000004",
        posted_at=FIXED_NOW - timedelta(days=1),
    )

    repo.insert_job(exact_7_days, ApplicationStatus.QUEUED_FOR_DRAFTING, created_at=FIXED_NOW)
    repo.insert_job(eight_days, ApplicationStatus.QUEUED_FOR_DRAFTING, created_at=FIXED_NOW - timedelta(minutes=2))
    repo.insert_job(twelve_days, ApplicationStatus.QUEUED_FOR_DRAFTING, created_at=FIXED_NOW - timedelta(minutes=1))
    repo.insert_job(drafted_recent, ApplicationStatus.QUEUED_FOR_DRAFTING, created_at=FIXED_NOW)
    repo.update_job("drafted_00000004", cv_pdf_path="/tmp/cv.pdf", updated_at=FIXED_NOW)

    # drafted_recent is excluded; exact_7_days stays ahead of 8- and 12-day postings
    candidates = repo.list_prioritized_candidates(preferred_age_days=7, limit=3, now=FIXED_NOW)
    assert [j.job_id for j in candidates] == [
        "exact7_000000001",
        "age8_00000000002",
        "age12_0000000003",
    ]

    # Once exact_7_days and age8 are applied/drafted, fallback returns remaining 12-day role
    repo.update_job("exact7_000000001", status=ApplicationStatus.APPLIED, updated_at=FIXED_NOW)
    repo.update_job(
        "age8_00000000002",
        cover_letter_pdf_path="/tmp/cl.pdf",
        updated_at=FIXED_NOW,
    )
    fallback = repo.list_prioritized_candidates(preferred_age_days=7, limit=3, now=FIXED_NOW)
    assert [j.job_id for j in fallback] == ["age12_0000000003"]


def test_prioritized_candidates_fifo_backlog_and_expiration_guard() -> None:
    repo = JobRepository(":memory:")

    # 3 jobs queued yesterday, 1 queued today (same preferred tier) -> yesterday drains first
    for idx in range(3):
        repo.insert_job(
            _make_posting(job_id=f"yest_{idx}", posted_at=FIXED_NOW - timedelta(days=2)),
            ApplicationStatus.QUEUED_FOR_DRAFTING,
            created_at=FIXED_NOW - timedelta(days=1, minutes=10 - idx),
        )
    repo.insert_job(
        _make_posting(job_id="today_0", posted_at=FIXED_NOW - timedelta(hours=2)),
        ApplicationStatus.QUEUED_FOR_DRAFTING,
        created_at=FIXED_NOW,
    )
    repo.update_job("today_0", fit_score=9.9)
    for idx in range(3):
        repo.update_job(f"yest_{idx}", fit_score=7.0)

    # Expired deadline and aged-out queued job + manual aged-out job
    repo.insert_job(
        _make_posting(
            job_id="expired_dl",
            posted_at=FIXED_NOW - timedelta(days=3),
            application_deadline=FIXED_NOW - timedelta(hours=1),
        ),
        ApplicationStatus.QUEUED_FOR_DRAFTING,
        created_at=FIXED_NOW - timedelta(days=2),
    )
    repo.insert_job(
        _make_posting(
            job_id="expired_age",
            posted_at=FIXED_NOW - timedelta(days=22),
            application_deadline=None,
        ),
        ApplicationStatus.QUEUED_FOR_DRAFTING,
        created_at=FIXED_NOW - timedelta(days=2),
    )
    repo.insert_job(
        _make_posting(
            job_id="manual_old",
            source="manual",
            posted_at=FIXED_NOW - timedelta(days=30),
            application_deadline=None,
        ),
        ApplicationStatus.QUEUED_FOR_DRAFTING,
        created_at=FIXED_NOW - timedelta(days=2),
    )

    assert repo.count_queued_jobs() == 7
    expired_count = repo.expire_stale_queued_jobs(max_age_days=21, now=FIXED_NOW)
    assert expired_count == 2
    assert repo.get_job("expired_dl").status == ApplicationStatus.EXPIRED
    assert repo.get_job("expired_age").status == ApplicationStatus.EXPIRED
    assert repo.get_job("manual_old").status == ApplicationStatus.QUEUED_FOR_DRAFTING
    assert repo.count_queued_jobs() == 5

    # Yesterday's 3 preferred jobs drain FIFO before today's higher-scoring job
    drained = repo.list_prioritized_candidates(preferred_age_days=7, limit=3, now=FIXED_NOW)
    assert [j.job_id for j in drained] == ["yest_0", "yest_1", "yest_2"]


def test_prioritized_candidates_limit_is_cap_not_quota() -> None:
    repo = JobRepository(":memory:")
    assert repo.list_prioritized_candidates(preferred_age_days=7, limit=3, now=FIXED_NOW) == []

    only_one = _make_posting(job_id="only1_0000000001")
    repo.insert_job(only_one, ApplicationStatus.QUEUED_FOR_DRAFTING, created_at=FIXED_NOW)

    result = repo.list_prioritized_candidates(preferred_age_days=7, limit=3, now=FIXED_NOW)
    assert len(result) == 1
    assert result[0].job_id == "only1_0000000001"
    assert repo.list_prioritized_candidates(preferred_age_days=7, limit=0, now=FIXED_NOW) == []


def test_prioritized_candidates_missing_posted_at_ranks_behind_preferred_tier() -> None:
    repo = JobRepository(":memory:")
    missing_posted_at = _make_posting(
        job_id="missing_posted_01",
        posted_at=None,
        application_deadline=None,
    )
    preferred_recent = _make_posting(
        job_id="recent_posted_002",
        posted_at=FIXED_NOW - timedelta(days=5),
        application_deadline=None,
    )
    repo.insert_job(
        missing_posted_at,
        ApplicationStatus.QUEUED_FOR_DRAFTING,
        created_at=FIXED_NOW,
    )
    repo.insert_job(
        preferred_recent,
        ApplicationStatus.QUEUED_FOR_DRAFTING,
        created_at=FIXED_NOW - timedelta(days=1),
    )

    ordered = repo.list_prioritized_candidates(preferred_age_days=7, limit=3, now=FIXED_NOW)
    assert [j.job_id for j in ordered] == ["recent_posted_002", "missing_posted_01"]


def test_profile_update_suggestions_weekly_cache() -> None:
    repo = JobRepository(":memory:")
    id1 = repo.add_profile_suggestion(
        job_id="job1",
        kind="addition",
        fact_text="Built Terraform module for GKE cluster",
        category="skills.infrastructure",
        created_at=FIXED_NOW,
    )
    id2 = repo.add_profile_suggestion(
        job_id="job2",
        kind="correction",
        fact_text="End date at Nordic Cloud Labs was 2025-06, not ongoing",
        category="experiences",
        created_at=FIXED_NOW + timedelta(hours=1),
    )

    unconsumed = repo.list_unconsumed_profile_suggestions()
    assert [(s.id, s.kind) for s in unconsumed] == [(id1, "addition"), (id2, "correction")]

    marked = repo.mark_profile_suggestions_consumed([id1], consumed_at=FIXED_NOW + timedelta(days=1))
    assert marked == 1
    remaining = repo.list_unconsumed_profile_suggestions()
    assert [s.id for s in remaining] == [id2]


# ---------------------------------------------------------------------------
# Six-month retention cleanup preserving Interviewing
# ---------------------------------------------------------------------------


def test_prune_old_jobs_deletes_older_than_180_days_and_preserves_interviewing() -> None:
    repo = JobRepository(":memory:")

    old_created = FIXED_NOW - timedelta(days=200)
    exact_180 = FIXED_NOW - timedelta(days=180)
    just_over_180 = FIXED_NOW - timedelta(days=180, seconds=1)

    repo.insert_job(
        _make_posting(job_id="old_rejected_001"),
        ApplicationStatus.REJECTED,
        created_at=old_created,
    )
    repo.insert_job(
        _make_posting(job_id="old_pending_0002"),
        ApplicationStatus.PENDING_SCORING,
        created_at=old_created,
    )
    repo.insert_job(
        _make_posting(job_id="old_interview_03"),
        ApplicationStatus.INTERVIEWING,
        created_at=old_created,
    )
    repo.insert_job(
        _make_posting(job_id="exact_180_000004"),
        ApplicationStatus.REJECTED,
        created_at=exact_180,
    )
    repo.insert_job(
        _make_posting(job_id="over_180_0000005"),
        ApplicationStatus.REJECTED,
        created_at=just_over_180,
    )

    deleted_count = repo.prune_old_jobs(retention_days=180, now=FIXED_NOW)
    assert deleted_count == 3

    assert repo.get_job("old_rejected_001") is None
    assert repo.get_job("old_pending_0002") is None
    assert repo.get_job("over_180_0000005") is None
    assert repo.get_job("old_interview_03") is not None
    assert repo.get_job("old_interview_03").status == ApplicationStatus.INTERVIEWING
    assert repo.get_job("exact_180_000004") is not None


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------


def test_cli_ingest_runs_sources_filters_stores_and_prunes(tmp_path: Path) -> None:
    runner = CliRunner()
    db_path = tmp_path / "state.db"
    prefs_path = tmp_path / "target_roles.yaml"
    prefs_path.write_text(EXAMPLE_PREFS_PATH.read_text(encoding="utf-8"), encoding="utf-8")

    sources_path = tmp_path / "sources.yaml"
    sources_path.write_text(
        """
sources:
  arbeitnow:
    enabled: true
    endpoint: "https://www.arbeitnow.com/api/job-board-api"
  remotive:
    enabled: true
    endpoint: "https://remotive.com/api/remote-jobs"
  himalayas:
    enabled: false
  jobicy:
    enabled: false
  jobindex_rss:
    enabled: false
""".strip(),
        encoding="utf-8",
    )

    repo = JobRepository(db_path)
    repo.insert_job(
        _make_posting(job_id="stale_old_row_01"),
        ApplicationStatus.REJECTED,
        created_at=datetime.now(timezone.utc) - timedelta(days=200),
    )

    now_ts = int(datetime.now(timezone.utc).timestamp())
    stale_ts = int((datetime.now(timezone.utc) - timedelta(days=30)).timestamp())

    with respx.mock(assert_all_called=True) as mock_router:
        mock_router.get("https://www.arbeitnow.com/api/job-board-api").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "slug": "junior-eng-cph",
                            "company_name": "Nordic Labs",
                            "title": "Junior Software Engineer",
                            "description": "<p>Python and SQL role in Copenhagen.</p>",
                            "remote": False,
                            "url": "https://arbeitnow.com/jobs/junior-eng-cph",
                            "location": "Copenhagen, Denmark",
                            "created_at": now_ts,
                        },
                        {
                            "slug": "senior-eng-cph",
                            "company_name": "Nordic Labs",
                            "title": "Senior Backend Engineer",
                            "description": "<p>Requires 6+ years experience.</p>",
                            "remote": False,
                            "url": "https://arbeitnow.com/jobs/senior-eng-cph",
                            "location": "Copenhagen, Denmark",
                            "created_at": now_ts,
                        },
                        {
                            "slug": "stale-eng-cph",
                            "company_name": "Nordic Labs",
                            "title": "Junior Platform Engineer",
                            "description": "<p>Old posting.</p>",
                            "remote": False,
                            "url": "https://arbeitnow.com/jobs/stale-eng-cph",
                            "location": "Copenhagen, Denmark",
                            "created_at": stale_ts,
                        },
                    ]
                },
            )
        )
        mock_router.get("https://remotive.com/api/remote-jobs").mock(
            return_value=httpx.Response(503, text="Service Unavailable")
        )

        result = runner.invoke(
            app,
            [
                "ingest",
                "--preferences",
                str(prefs_path),
                "--sources",
                str(sources_path),
                "--db",
                str(db_path),
            ],
        )

    assert result.exit_code == 0, result.output
    assert "fetched=3" in result.stdout
    assert "skipped=0" in result.stdout
    assert "discarded-stale=1" in result.stdout
    assert "passed=1" in result.stdout
    assert "pre-filtered=1" in result.stdout
    assert "pruned=1" in result.stdout
    assert "remotive" in result.stderr.lower()

    assert len(repo.list_jobs(status=ApplicationStatus.PENDING_SCORING)) == 1
    assert len(repo.list_jobs(status=ApplicationStatus.PRE_FILTERED_OUT)) == 1
    assert repo.get_job("stale_old_row_01") is None


def test_cli_list_filters_and_displays_expected_columns(tmp_path: Path) -> None:
    runner = CliRunner()
    db_path = tmp_path / "list.db"
    repo = JobRepository(db_path)

    pending = _make_posting(
        job_id="pend_job_00000001",
        company="Danske Tech",
        title="Junior Data Engineer",
        location="Copenhagen, Denmark",
        language="da",
        source="jobindex_rss",
        posted_at=FIXED_NOW - timedelta(days=2),
        application_deadline=FIXED_NOW + timedelta(days=10),
    )
    rejected = _make_posting(
        job_id="rej_job_000000002",
        company="Other Corp",
        title="Senior Architect",
        language="en",
        source="arbeitnow",
    )
    repo.insert_job(pending, ApplicationStatus.PENDING_SCORING, created_at=FIXED_NOW)
    repo.insert_job(rejected, ApplicationStatus.PRE_FILTERED_OUT, created_at=FIXED_NOW)

    result = runner.invoke(
        app,
        ["list", "--status", "Pending_Scoring", "--db", str(db_path)],
    )
    assert result.exit_code == 0, result.output
    assert "pend_job_00000001" in result.stdout
    assert "Danske Tech" in result.stdout
    assert "Junior Data Engineer" in result.stdout
    assert "Copenhagen, Denmark" in result.stdout
    assert "da" in result.stdout
    assert "2026-06-13T12:00:00+00:00" in result.stdout
    assert "2026-06-25T12:00:00+00:00" in result.stdout
    assert "jobindex_rss" in result.stdout
    assert "rej_job_000000002" not in result.stdout


def test_cli_add_raw_text_succeeds_and_is_idempotent(tmp_path: Path) -> None:
    runner = CliRunner()
    db_path = tmp_path / "manual.db"
    prefs_path = tmp_path / "target_roles.yaml"
    prefs_path.write_text(EXAMPLE_PREFS_PATH.read_text(encoding="utf-8"), encoding="utf-8")

    args = [
        "add",
        "--title",
        "Associate Solutions Architect",
        "--company",
        "CloudNord",
        "--location",
        "Copenhagen, Denmark",
        "--work-mode",
        "hybrid",
        "--text",
        "Entry-level Associate Solutions Architect working with Python and GCP.",
        "--preferences",
        str(prefs_path),
        "--db",
        str(db_path),
    ]
    first = runner.invoke(app, args)
    assert first.exit_code == 0, first.output
    assert "Pending_Scoring" in first.stdout

    repo = JobRepository(db_path)
    jobs = repo.list_jobs()
    assert len(jobs) == 1
    assert jobs[0].source == "manual"
    assert jobs[0].status == ApplicationStatus.PENDING_SCORING

    second = runner.invoke(app, args)
    assert second.exit_code == 0, second.output
    assert "Skipped existing job" in second.stdout
    assert len(repo.list_jobs()) == 1


@pytest.mark.parametrize(
    ("status_code", "html_body", "expected_snippet"),
    [
        (403, "<html><body>Forbidden - Sign in required</body></html>", "403"),
        (200, "<html><body><p>Loading...</p></body></html>", "extract"),
    ],
)
def test_cli_add_url_fails_loudly_without_inserting_row(
    tmp_path: Path,
    status_code: int,
    html_body: str,
    expected_snippet: str,
) -> None:
    runner = CliRunner()
    db_path = tmp_path / "manual_fail.db"
    prefs_path = tmp_path / "target_roles.yaml"
    prefs_path.write_text(EXAMPLE_PREFS_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    target_url = "https://careers.example.com/jobs/blocked"

    with respx.mock(assert_all_called=True) as mock_router:
        mock_router.get(target_url).mock(
            return_value=httpx.Response(status_code, text=html_body)
        )
        result = runner.invoke(
            app,
            [
                "add",
                "--url",
                target_url,
                "--preferences",
                str(prefs_path),
                "--db",
                str(db_path),
            ],
        )

    assert result.exit_code != 0
    assert expected_snippet in result.stderr.lower()
    assert "--text" in result.stderr or "raw job description" in result.stderr.lower()

    repo = JobRepository(db_path)
    assert repo.list_jobs() == []


def test_submit_manual_job_raises_without_inserting_on_invalid_input() -> None:
    repo = JobRepository(":memory:")
    prefs = _default_prefs()

    with pytest.raises(ManualDropError):
        submit_manual_job(prefs, repo, url=None, text=None)

    assert repo.list_jobs() == []


def test_cli_add_url_succeeds_for_clean_html_and_list_filters_by_language(tmp_path: Path) -> None:
    runner = CliRunner()
    db_path = tmp_path / "manual_url_ok.db"
    prefs_path = tmp_path / "target_roles.yaml"
    prefs_path.write_text(EXAMPLE_PREFS_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    target_url = "https://careers.example.com/jobs/junior-dev"

    html_body = (
        "<html><body><main>"
        "<h1>Junior Backend Developer</h1>"
        "<p>Join our Copenhagen engineering team building Python and SQL microservices.</p>"
        "</main></body></html>"
    )
    with respx.mock(assert_all_called=True) as mock_router:
        mock_router.get(target_url).mock(return_value=httpx.Response(200, text=html_body))
        add_result = runner.invoke(
            app,
            [
                "add",
                "--url",
                target_url,
                "--company",
                "Kbh Cloud",
                "--location",
                "Copenhagen, Denmark",
                "--work-mode",
                "onsite",
                "--preferences",
                str(prefs_path),
                "--db",
                str(db_path),
            ],
        )

    assert add_result.exit_code == 0, add_result.output
    assert "Pending_Scoring" in add_result.stdout

    en_list = runner.invoke(app, ["list", "--language", "en", "--db", str(db_path)])
    assert en_list.exit_code == 0
    assert "Junior Backend Developer" in en_list.stdout

    da_list = runner.invoke(app, ["list", "--language", "da", "--db", str(db_path)])
    assert da_list.exit_code == 0
    assert "No jobs found." in da_list.stdout


def test_repository_prioritized_candidates_defaults_and_nonpositive_limit() -> None:
    repo = JobRepository(":memory:")
    now = datetime.now(timezone.utc)

    repo.insert_job(
        _make_posting(job_id="d_7d12h", title="7.5d", posted_at=now - timedelta(days=7, hours=12)),
        ApplicationStatus.QUEUED_FOR_DRAFTING,
        created_at=now - timedelta(minutes=4),
    )
    repo.insert_job(
        _make_posting(
            job_id="d_deadline",
            title="Deadline",
            posted_at=now - timedelta(days=24),
            application_deadline=now + timedelta(days=3),
        ),
        ApplicationStatus.QUEUED_FOR_DRAFTING,
        created_at=now - timedelta(minutes=1),
    )
    repo.insert_job(
        _make_posting(job_id="d_recent_0", title="Recent 0", posted_at=now - timedelta(days=1)),
        ApplicationStatus.QUEUED_FOR_DRAFTING,
        created_at=now - timedelta(minutes=3),
    )
    repo.insert_job(
        _make_posting(job_id="d_recent_1", title="Recent 1", posted_at=now - timedelta(days=2)),
        ApplicationStatus.QUEUED_FOR_DRAFTING,
        created_at=now - timedelta(minutes=2),
    )

    default_results = repo.list_prioritized_candidates()
    assert len(default_results) == 3
    assert [j.job_id for j in default_results] == ["d_recent_0", "d_recent_1", "d_deadline"]
    assert repo.list_prioritized_candidates(limit=0, now=now) == []
    repo.close()
    assert repo._memory_conn is None


def test_repository_prune_old_jobs_defaults() -> None:
    repo = JobRepository(":memory:")
    now = datetime.now(timezone.utc)

    repo.insert_job(
        _make_posting(job_id="old_180d12h", title="Old"),
        ApplicationStatus.REJECTED,
        created_at=now - timedelta(days=180, hours=12),
    )
    repo.insert_job(
        _make_posting(job_id="fresh_179d", title="Keep"),
        ApplicationStatus.REJECTED,
        created_at=now - timedelta(days=179),
    )

    pruned = repo.prune_old_jobs()
    assert pruned == 1
    assert repo.get_job("old_180d12h") is None
    assert repo.get_job("fresh_179d") is not None
    repo.close()


def test_repository_update_job_lifecycle_fields_and_missing_id() -> None:
    repo = JobRepository(":memory:")
    now = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
    posting = _make_posting(job_id="upd1", title="Junior Developer", posted_at=now)
    repo.insert_job(posting, ApplicationStatus.PENDING_SCORING, created_at=now)

    assert repo.update_job("upd1") is False
    assert repo.update_job("nonexistent", status=ApplicationStatus.APPLIED) is False

    updated = repo.update_job(
        "upd1",
        status=ApplicationStatus.INTERVIEWING,
        rejection_reason=None,
        fit_score=8.7,
        fit_breakdown_json='{"total": 8.7}',
        cv_pdf_path="output/cv.pdf",
        cover_letter_pdf_path="output/cl.pdf",
        slack_thread_ts="1732270000.1234",
        gmail_thread_id="gmail-abc",
        langgraph_thread_id="lg-xyz",
        updated_at=now + timedelta(hours=2),
    )
    assert updated is True

    stored = repo.get_job("upd1")
    assert stored is not None
    assert stored.status == ApplicationStatus.INTERVIEWING
    assert stored.rejection_reason is None
    assert stored.fit_score == 8.7
    assert stored.fit_breakdown_json == '{"total": 8.7}'
    assert stored.cv_pdf_path == "output/cv.pdf"
    assert stored.cover_letter_pdf_path == "output/cl.pdf"
    assert stored.slack_thread_ts == "1732270000.1234"
    assert stored.gmail_thread_id == "gmail-abc"
    assert stored.langgraph_thread_id == "lg-xyz"
    assert stored.updated_at == now + timedelta(hours=2)
    repo.close()


# ---------------------------------------------------------------------------
# Stage 1 & Stage 2 CLI harness tests (score, queue, draft, review)
# ---------------------------------------------------------------------------


class _FakeCliLLMClient:
    """Deterministic fake StructuredLLMClient for CLI score/draft/review tests."""

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
        result = self._handlers[schema](tier, system_prompt, user_prompt)
        return result  # type: ignore[return-value]


def _grounded_example_cv(*, summary_note: str = "") -> TailoredCV:
    """Build a TailoredCV strictly grounded in config/master_profile.example.yaml."""
    extra = f" {summary_note}" if summary_note else ""
    return TailoredCV(
        language="en",
        full_name="Example Candidate",
        email="candidate@example.com",
        phone="+45 12 34 56 78",
        location="Copenhagen, Denmark",
        linkedin_url="https://linkedin.com/in/example",
        github_url="https://github.com/example",
        website_url="https://example.dev",
        profile_summary=(
            "Software engineer based in Copenhagen building Python FastAPI microservices, "
            f"automated data pipelines, and Pulumi GCP deployments.{extra}"
        ),
        section_order=["experience", "projects", "education", "skills"],
        experiences=[
            CVExperience(
                company="Nordic Cloud Labs",
                title="Junior Software Engineer",
                start_date="2024-02",
                end_date="present",
                location="Copenhagen, Denmark",
                bullets=[
                    CVBullet(
                        lead="Backend APIs",
                        text="Built FastAPI microservices handling ~1,200 daily requests with 99.9% uptime.",
                    ),
                    CVBullet(
                        lead="Infrastructure Automation",
                        text="Provisioned GCP Cloud Run services and Cloud SQL instances using Pulumi IaC.",
                    ),
                ],
            )
        ],
        projects=[
            CVProject(
                name="OpenTelemetry Log Router",
                url="https://github.com/example/otel-router",
                bullets=[
                    CVBullet(
                        lead="Log Filtering",
                        text="Reduced log ingestion overhead by 35% via deterministic pre-filtering.",
                    )
                ],
            )
        ],
        education=[
            CVEducation(
                institution="University of Copenhagen",
                degree="B.Sc. in Computer Science",
                start_date="2020-09",
                end_date="2023-06",
                location="Copenhagen, Denmark",
                highlights=["Thesis on distributed systems consensus protocols."],
            )
        ],
        skills=[
            CVSkillCategory(category="Languages", items=["Python", "SQL", "TypeScript"]),
            CVSkillCategory(
                category="Backend & Cloud",
                items=["FastAPI", "Pulumi", "GCP", "Docker", "PostgreSQL"],
            ),
        ],
        languages_spoken=["English (Native / Fluent)", "Danish (Fluent)"],
    )


def _grounded_example_cover_letter() -> TailoredCoverLetter:
    """Build a TailoredCoverLetter strictly grounded in config/master_profile.example.yaml."""
    return TailoredCoverLetter(
        language="en",
        full_name="Example Candidate",
        email="candidate@example.com",
        phone="+45 12 34 56 78",
        location="Copenhagen, Denmark",
        linkedin_url="https://linkedin.com/in/example",
        recipient_company="CloudNord ApS",
        role_title="Junior Backend Engineer",
        date_str="November 22, 2026",
        greeting="Dear Hiring Team at CloudNord ApS,",
        paragraphs=[
            (
                "Designing reliable backend APIs in Python and FastAPI that validate payloads before "
                "hitting production storage matches the engineering work I enjoy most. Your Junior "
                "Backend Engineer opening at CloudNord ApS stood out because the team runs cloud-native "
                "Python services and PostgreSQL workloads in Copenhagen. With my B.Sc. in Computer "
                "Science from the University of Copenhagen and production experience at Nordic Cloud "
                "Labs, I bring practical backend and cloud delivery skills."
            ),
            (
                "At Nordic Cloud Labs, I built FastAPI microservices handling ~1,200 daily requests "
                "with 99.9% uptime and provisioned GCP Cloud Run services alongside Cloud SQL instances "
                "using Pulumi IaC. Working across both application code and Docker-based infrastructure "
                "taught me how small schema mismatches become production incidents and how clear tests "
                "keep services dependable under load."
            ),
            (
                "In my OpenTelemetry Log Router project, I also reduced log ingestion overhead by 35% "
                "via deterministic pre-filtering in Python. While I have not yet operated Go services "
                "in production, my foundation in strictly typed Python services and cloud tooling "
                "translates cleanly to learning new backend stacks quickly."
            ),
            (
                "CloudNord ApS looks like an engineering team focused on pragmatic architecture and "
                "steady delivery. I would welcome the chance to discuss how my FastAPI, PostgreSQL, "
                "and GCP background can support your backend squad."
            ),
        ],
        sign_off="Kind Regards,",
    )


def _build_stage2_fake_client() -> _FakeCliLLMClient:
    """Create a deterministic fake LLM client supporting full Stage 2 draft + review flows."""
    intent_turn = 0
    reiterate_done = False

    def _plan_handler(_tier: ModelTier, _sys: str, user_prompt: str) -> TailoringPlan:
        note_suffix = "Emphasize FastAPI reliability." if "emphasize" in user_prompt.lower() else ""
        return TailoringPlan(
            angle_summary="Bridge Nordic Cloud Labs FastAPI and Pulumi work to CloudNord ApS.",
            selected_experiences=["Nordic Cloud Labs - Junior Software Engineer"],
            selected_projects=["OpenTelemetry Log Router"],
            transferable_framings=["Map Pulumi GCP IaC to cloud deployment pipelines."],
            major_gaps=["Go production experience"],
            section_order=["experience", "projects", "education", "skills"],
            notes=note_suffix or "Standard tailored draft.",
        )

    def _writer_handler(_tier: ModelTier, _sys: str, _user: str) -> DraftDocuments:
        summary_note = "Focused on deterministic Python services." if reiterate_done else ""
        return DraftDocuments(
            cv=_grounded_example_cv(summary_note=summary_note),
            cover_letter=_grounded_example_cover_letter(),
            major_gaps=["Go production experience"],
        )

    def _audit_handler(_tier: ModelTier, _sys: str, _user: str) -> AuditResult:
        return AuditResult(passed=True, violations=[])

    def _intent_handler(_tier: ModelTier, _sys: str, _user: str) -> ThreadIntentDecision:
        nonlocal intent_turn
        intent_turn += 1
        if intent_turn == 1:
            return ThreadIntentDecision(intent="CHAT", rationale="User asked a question.")
        return ThreadIntentDecision(intent="REITERATE", rationale="User requested CV emphasis update.")

    def _ideation_handler(_tier: ModelTier, _sys: str, _user: str) -> IdeationResponse:
        nonlocal reiterate_done
        if intent_turn == 1:
            return IdeationResponse(
                reply="We left Go out because only verified Python and GCP facts appear in your profile.",
                captured_ideation_note="Keep Python and GCP framing central.",
            )
        reiterate_done = True
        return IdeationResponse(
            reply="Updating the CV and cover letter now.",
            captured_ideation_note="Emphasize deterministic Python services in summary.",
        )

    return _FakeCliLLMClient(
        {
            TailoringPlan: _plan_handler,
            DraftDocuments: _writer_handler,
            AuditResult: _audit_handler,
            ThreadIntentDecision: _intent_handler,
            IdeationResponse: _ideation_handler,
        }
    )


def _seed_cli_queued_job(
    repo: JobRepository,
    job_id: str,
    *,
    company: str = "CloudNord ApS",
    title: str = "Junior Backend Engineer",
    apply_url: str = "https://cloudnord.example.com/jobs/junior-backend",
    posted_at: datetime | None = None,
    application_deadline: datetime | None = None,
    source: str = "arbeitnow",
    fit_score: float = 8.6,
    created_at: datetime | None = None,
    missing_posted_at: bool | None = None,
) -> None:
    """Insert a Queued_For_Drafting job with persisted FitDecision breakdown."""
    posting = _make_posting(
        job_id=job_id,
        source=source,
        company=company,
        title=title,
        apply_url=apply_url,
        posted_at=posted_at,
        application_deadline=application_deadline,
    )
    repo.insert_job(posting, ApplicationStatus.QUEUED_FOR_DRAFTING, created_at=created_at)
    is_missing_posted_at = (posted_at is None) if missing_posted_at is None else missing_posted_at
    decision = FitDecision(
        passed=True,
        status=ApplicationStatus.QUEUED_FOR_DRAFTING,
        fit_score=fit_score,
        must_have_coverage=0.9,
        effective_tier="entry_level",
        tier_threshold=0.65,
        missing_posted_at=is_missing_posted_at,
        evidence=ScoringEvidence(
            seniority_tier="entry_level",
            must_have_skills=["Python", "FastAPI", "PostgreSQL"],
            direct_matches=["Python", "FastAPI", "PostgreSQL"],
            role_seniority_score=9.0,
            must_have_skills_score=9.0,
            domain_fit_score=8.5,
            nice_to_have_score=7.5,
            major_gaps=["Go production experience"],
            rationale="Strong entry-level Python backend match.",
        ),
    )
    repo.update_job(
        job_id,
        fit_score=decision.fit_score,
        fit_breakdown_json=decision.to_breakdown_json(),
    )


def test_cli_score_evaluates_pending_and_fails_loudly_without_api_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = CliRunner()
    db_path = tmp_path / "score.db"
    prefs_path = tmp_path / "target_roles.yaml"
    profile_path = tmp_path / "master_profile.yaml"
    llm_path = tmp_path / "llm.yaml"
    prefs_path.write_text(EXAMPLE_PREFS_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    profile_path.write_text(EXAMPLE_PROFILE_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    llm_path.write_text(EXAMPLE_LLM_CONFIG_PATH.read_text(encoding="utf-8"), encoding="utf-8")

    repo = JobRepository(db_path)
    repo.insert_job(
        _make_posting(job_id="pend_pass_0001", title="Junior Python Engineer", posted_at=None),
        ApplicationStatus.PENDING_SCORING,
        created_at=FIXED_NOW,
    )
    repo.insert_job(
        _make_posting(job_id="pend_fail_0002", title="Lead Architect", posted_at=FIXED_NOW),
        ApplicationStatus.PENDING_SCORING,
        created_at=FIXED_NOW + timedelta(minutes=1),
    )

    # Without OPENCODE_API_KEY, default OpenCodeLLMClient fails loudly
    monkeypatch.delenv("OPENCODE_API_KEY", raising=False)
    missing_key_result = runner.invoke(
        app,
        [
            "score",
            "--preferences",
            str(prefs_path),
            "--profile",
            str(profile_path),
            "--llm-config",
            str(llm_path),
            "--db",
            str(db_path),
        ],
    )
    assert missing_key_result.exit_code != 0
    assert "OPENCODE_API_KEY" in missing_key_result.stderr

    # With fake client factory, evaluates all pending into Queued_For_Drafting / Scored_Out
    def _scoring_handler(_tier: ModelTier, _sys: str, user_prompt: str) -> ScoringEvidence:
        payload = json.loads(user_prompt)
        if payload["job"]["job_id"] == "pend_pass_0001":
            return ScoringEvidence(
                seniority_tier="entry_level",
                must_have_skills=["Python", "SQL"],
                direct_matches=["Python", "SQL"],
                role_seniority_score=9.0,
                must_have_skills_score=9.0,
                domain_fit_score=8.5,
                nice_to_have_score=8.0,
                major_gaps=[],
                rationale="Strong entry-level match.",
            )
        return ScoringEvidence(
            seniority_tier="senior_plus",
            inferred_min_years=7,
            seniority_signals=["Lead Architect", "7+ years"],
            must_have_skills=["Architecture"],
            missing_must_haves=["Architecture"],
            role_seniority_score=3.0,
            must_have_skills_score=3.0,
            domain_fit_score=5.0,
            nice_to_have_score=4.0,
            major_gaps=["7+ years experience"],
            rationale="Too senior.",
        )

    fake_client = _FakeCliLLMClient({ScoringEvidence: _scoring_handler})
    monkeypatch.setattr("job_agent.cli._default_llm_client_factory", lambda _path: fake_client)

    result = runner.invoke(
        app,
        [
            "score",
            "--preferences",
            str(prefs_path),
            "--profile",
            str(profile_path),
            "--llm-config",
            str(llm_path),
            "--db",
            str(db_path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "evaluated=2" in result.stdout
    assert "queued=1" in result.stdout
    assert "scored-out=1" in result.stdout
    assert "missing-posted-at=1" in result.stdout

    assert repo.get_job("pend_pass_0001").status == ApplicationStatus.QUEUED_FOR_DRAFTING
    assert repo.get_job("pend_fail_0002").status == ApplicationStatus.SCORED_OUT


def test_cli_queue_prints_count_and_queued_rows(tmp_path: Path) -> None:
    runner = CliRunner()
    db_path = tmp_path / "queue.db"
    prefs_path = tmp_path / "target_roles.yaml"
    prefs_path.write_text(EXAMPLE_PREFS_PATH.read_text(encoding="utf-8"), encoding="utf-8")

    empty_res = runner.invoke(app, ["queue", "--preferences", str(prefs_path), "--db", str(db_path)])
    assert empty_res.exit_code == 0, empty_res.output
    assert "Queued for drafting: 0" in empty_res.stdout

    repo = JobRepository(db_path)
    _seed_cli_queued_job(
        repo,
        "q_job_0001",
        company="Nordic Cloud Labs",
        title="Junior Python Developer",
        apply_url="https://nordic.example.com/jobs/1",
        posted_at=FIXED_NOW - timedelta(days=1),
        application_deadline=FIXED_NOW + timedelta(days=7),
        fit_score=8.75,
        created_at=FIXED_NOW,
    )
    _seed_cli_queued_job(
        repo,
        "q_job_0002",
        company="Copenhagen Data",
        title="Associate Data Engineer",
        apply_url="https://cphdata.example.com/jobs/2",
        posted_at=None,
        fit_score=8.1,
        created_at=FIXED_NOW + timedelta(minutes=1),
    )
    repo.insert_job(
        _make_posting(job_id="other_pending"),
        ApplicationStatus.PENDING_SCORING,
        created_at=FIXED_NOW,
    )

    res = runner.invoke(app, ["queue", "--preferences", str(prefs_path), "--db", str(db_path)])
    assert res.exit_code == 0, res.output
    assert "Queued for drafting: 2" in res.stdout
    assert "q_job_0001" in res.stdout
    assert "Nordic Cloud Labs" in res.stdout
    assert "https://nordic.example.com/jobs/1" in res.stdout
    assert "8.75" in res.stdout
    assert "q_job_0002" in res.stdout
    assert "https://cphdata.example.com/jobs/2" in res.stdout
    assert "other_pending" not in res.stdout


def test_cli_draft_expires_stale_and_respects_daily_draft_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = CliRunner()
    db_path = tmp_path / "draft.db"
    checkpoints_path = tmp_path / "checkpoints.db"
    drafts_dir = tmp_path / "drafts"
    prefs_path = tmp_path / "target_roles.yaml"
    profile_path = tmp_path / "master_profile.yaml"
    llm_path = tmp_path / "llm.yaml"
    prefs_path.write_text(EXAMPLE_PREFS_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    profile_path.write_text(EXAMPLE_PROFILE_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    llm_path.write_text(EXAMPLE_LLM_CONFIG_PATH.read_text(encoding="utf-8"), encoding="utf-8")

    fake_client = _build_stage2_fake_client()
    monkeypatch.setattr("job_agent.cli._default_llm_client_factory", lambda _path: fake_client)

    # Empty queue exits 0 cleanly (cap, never a quota)
    empty_res = runner.invoke(
        app,
        [
            "draft",
            "--preferences",
            str(prefs_path),
            "--profile",
            str(profile_path),
            "--llm-config",
            str(llm_path),
            "--db",
            str(db_path),
            "--checkpoints",
            str(checkpoints_path),
            "--drafts-dir",
            str(drafts_dir),
        ],
    )
    assert empty_res.exit_code == 0, empty_res.output
    assert "No queued jobs to draft (expired=0)." in empty_res.stdout

    repo = JobRepository(db_path)
    now = datetime.now(timezone.utc)
    # 1 stale job (should expire before drafting) + 4 fresh queued jobs (daily_draft_limit = 3)
    _seed_cli_queued_job(
        repo,
        "stale_queued_0",
        company="OldCo",
        title="Old Junior Role",
        apply_url="https://oldco.example.com/jobs/0",
        posted_at=now - timedelta(days=30),
        created_at=now - timedelta(days=5),
    )
    for idx in range(1, 5):
        _seed_cli_queued_job(
            repo,
            f"fresh_queued_{idx}",
            company="CloudNord ApS",
            title=f"Junior Backend Engineer {idx}",
            apply_url=f"https://cloudnord.example.com/jobs/{idx}",
            posted_at=now - timedelta(days=1),
            created_at=now - timedelta(minutes=10 - idx),
        )

    result = runner.invoke(
        app,
        [
            "draft",
            "--preferences",
            str(prefs_path),
            "--profile",
            str(profile_path),
            "--llm-config",
            str(llm_path),
            "--db",
            str(db_path),
            "--checkpoints",
            str(checkpoints_path),
            "--drafts-dir",
            str(drafts_dir),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Workshopping now..." in result.stdout
    assert "Apply URL: https://cloudnord.example.com/jobs/1" in result.stdout
    assert "Apply URL: https://cloudnord.example.com/jobs/2" in result.stdout
    assert "Apply URL: https://cloudnord.example.com/jobs/3" in result.stdout
    assert "Apply URL: https://cloudnord.example.com/jobs/4" not in result.stdout
    assert "CV PDF:" in result.stdout
    assert "Cover Letter PDF:" in result.stdout
    assert "drafted=3, expired=1" in result.stdout

    assert repo.get_job("stale_queued_0").status == ApplicationStatus.EXPIRED
    for idx in range(1, 4):
        stored = repo.get_job(f"fresh_queued_{idx}")
        assert stored.status == ApplicationStatus.PENDING_REVIEW
        assert stored.cv_pdf_path is not None and Path(stored.cv_pdf_path).is_file()
        assert stored.cover_letter_pdf_path is not None and Path(stored.cover_letter_pdf_path).is_file()
    assert repo.get_job("fresh_queued_4").status == ApplicationStatus.QUEUED_FOR_DRAFTING


def test_cli_review_chat_reiterate_and_approve_flow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = CliRunner()
    db_path = tmp_path / "review.db"
    checkpoints_path = tmp_path / "checkpoints.db"
    drafts_dir = tmp_path / "drafts"
    prefs_path = tmp_path / "target_roles.yaml"
    profile_path = tmp_path / "master_profile.yaml"
    llm_path = tmp_path / "llm.yaml"
    prefs_path.write_text(EXAMPLE_PREFS_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    profile_path.write_text(EXAMPLE_PROFILE_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    llm_path.write_text(EXAMPLE_LLM_CONFIG_PATH.read_text(encoding="utf-8"), encoding="utf-8")

    fake_client = _build_stage2_fake_client()
    monkeypatch.setattr("job_agent.cli._default_llm_client_factory", lambda _path: fake_client)

    repo = JobRepository(db_path)
    _seed_cli_queued_job(
        repo,
        "rev_job_001",
        company="CloudNord ApS",
        title="Junior Backend Engineer",
        apply_url="https://cloudnord.example.com/jobs/review-me",
        posted_at=None,
        created_at=FIXED_NOW,
        missing_posted_at=True,
    )

    # First draft via CLI so review attaches to existing Pending_Review checkpoint
    draft_res = runner.invoke(
        app,
        [
            "draft",
            "--preferences",
            str(prefs_path),
            "--profile",
            str(profile_path),
            "--llm-config",
            str(llm_path),
            "--db",
            str(db_path),
            "--checkpoints",
            str(checkpoints_path),
            "--drafts-dir",
            str(drafts_dir),
        ],
    )
    assert draft_res.exit_code == 0, draft_res.output
    assert repo.get_job("rev_job_001").status == ApplicationStatus.PENDING_REVIEW

    # Interactive review: CHAT -> REITERATE -> /approve
    review_res = runner.invoke(
        app,
        [
            "review",
            "rev_job_001",
            "--preferences",
            str(prefs_path),
            "--profile",
            str(profile_path),
            "--llm-config",
            str(llm_path),
            "--db",
            str(db_path),
            "--checkpoints",
            str(checkpoints_path),
            "--drafts-dir",
            str(drafts_dir),
        ],
        input=(
            "Why is Go missing from the draft?\n"
            "Please emphasize deterministic Python services and regenerate.\n"
            "/approve\n"
        ),
    )
    assert review_res.exit_code == 0, review_res.output
    assert "Apply URL: https://cloudnord.example.com/jobs/review-me" in review_res.stdout
    assert "Warning: posted_at is missing" in review_res.stdout
    assert "Major gaps: Go production experience" in review_res.stdout
    assert (
        "Co-Pilot: We left Go out because only verified Python and GCP facts appear in your profile."
        in review_res.stdout
    )
    assert "Workshopping now..." in review_res.stdout
    assert "Approved! Status: Ready_to_Submit" in review_res.stdout

    final_job = repo.get_job("rev_job_001")
    assert final_job is not None
    assert final_job.status == ApplicationStatus.READY_TO_SUBMIT
    assert final_job.cv_pdf_path is not None and Path(final_job.cv_pdf_path).is_file()
    assert final_job.cover_letter_pdf_path is not None and Path(final_job.cover_letter_pdf_path).is_file()


def test_cli_review_empty_exit_and_dismiss_flows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = CliRunner()
    db_path = tmp_path / "review_dismiss.db"
    checkpoints_path = tmp_path / "checkpoints.db"
    drafts_dir = tmp_path / "drafts"
    prefs_path = tmp_path / "target_roles.yaml"
    profile_path = tmp_path / "master_profile.yaml"
    llm_path = tmp_path / "llm.yaml"
    prefs_path.write_text(EXAMPLE_PREFS_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    profile_path.write_text(EXAMPLE_PROFILE_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    llm_path.write_text(EXAMPLE_LLM_CONFIG_PATH.read_text(encoding="utf-8"), encoding="utf-8")

    fake_client = _build_stage2_fake_client()
    monkeypatch.setattr("job_agent.cli._default_llm_client_factory", lambda _path: fake_client)

    repo = JobRepository(db_path)
    _seed_cli_queued_job(
        repo,
        "rev_dismiss_002",
        apply_url="https://cloudnord.example.com/jobs/dismiss-me",
        posted_at=datetime.now(timezone.utc) - timedelta(days=1),
        created_at=FIXED_NOW,
    )

    # Opening review directly on a Queued_For_Drafting job drafts it first; /exit leaves Pending_Review
    exit_res = runner.invoke(
        app,
        [
            "review",
            "rev_dismiss_002",
            "--preferences",
            str(prefs_path),
            "--profile",
            str(profile_path),
            "--llm-config",
            str(llm_path),
            "--db",
            str(db_path),
            "--checkpoints",
            str(checkpoints_path),
            "--drafts-dir",
            str(drafts_dir),
        ],
        input="/exit\n",
    )
    assert exit_res.exit_code == 0, exit_res.output
    assert "Workshopping now..." in exit_res.stdout
    assert repo.get_job("rev_dismiss_002").status == ApplicationStatus.PENDING_REVIEW

    # Empty input / EOF also exits cleanly without changing status
    eof_res = runner.invoke(
        app,
        [
            "review",
            "rev_dismiss_002",
            "--preferences",
            str(prefs_path),
            "--profile",
            str(profile_path),
            "--llm-config",
            str(llm_path),
            "--db",
            str(db_path),
            "--checkpoints",
            str(checkpoints_path),
            "--drafts-dir",
            str(drafts_dir),
        ],
        input="",
    )
    assert eof_res.exit_code == 0, eof_res.output
    assert repo.get_job("rev_dismiss_002").status == ApplicationStatus.PENDING_REVIEW

    # /dismiss transitions to Rejected
    dismiss_res = runner.invoke(
        app,
        [
            "review",
            "rev_dismiss_002",
            "--preferences",
            str(prefs_path),
            "--profile",
            str(profile_path),
            "--llm-config",
            str(llm_path),
            "--db",
            str(db_path),
            "--checkpoints",
            str(checkpoints_path),
            "--drafts-dir",
            str(drafts_dir),
        ],
        input="/dismiss\n",
    )
    assert dismiss_res.exit_code == 0, dismiss_res.output
    assert "Dismissed. Status: Rejected" in dismiss_res.stdout
    assert repo.get_job("rev_dismiss_002").status == ApplicationStatus.REJECTED
