"""Intent-rooted integration tests for SQLite repository, ingestion pipeline, and CLI."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
import respx
from typer.testing import CliRunner

from job_agent.cli import app
from job_agent.pipeline import run_ingestion, submit_manual_job
from job_agent.schemas import (
    ApplicationStatus,
    JobPosting,
    JobPreferences,
    SourcesConfig,
    WorkMode,
    load_job_preferences,
)
from job_agent.sources.manual import ManualDropError
from job_agent.sources.runner import IngestionFetchResult, SourceFetchError
from job_agent.storage import JobRepository, StoredJob

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_PREFS_PATH = REPO_ROOT / "config" / "target_roles.example.yaml"
FIXED_NOW = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)


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
