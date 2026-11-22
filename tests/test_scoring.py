"""Intent-rooted unit tests for hybrid fit scoring and deterministic boundary gates."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TypeVar

import pytest
from pydantic import BaseModel

from job_agent.schemas import (
    ApplicationStatus,
    JobPosting,
    JobPreferences,
    MasterProfile,
    WorkMode,
    load_job_preferences,
    load_master_profile,
)
from job_agent.scoring import (
    ScoringEvidence,
    TransferableMatch,
    evaluate_scoring_evidence,
    score_pending_jobs,
)
from job_agent.storage import JobRepository

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "config"
FIXED_NOW = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)

T = TypeVar("T", bound=BaseModel)


def _prefs() -> JobPreferences:
    return load_job_preferences(CONFIG_DIR / "target_roles.example.yaml")


def _profile() -> MasterProfile:
    return load_master_profile(CONFIG_DIR / "master_profile.example.yaml")


def _posting(**overrides: object) -> JobPosting:
    defaults: dict[str, object] = {
        "job_id": "job_000000000001",
        "source": "arbeitnow",
        "title": "Junior Software Engineer",
        "company": "Nordic Labs",
        "location": "Copenhagen, Denmark",
        "work_mode": WorkMode.HYBRID,
        "apply_url": "https://example.com/jobs/1",
        "description": "Entry-level backend role with Python, SQL, and cloud infrastructure.",
        "language": "en",
        "posted_at": FIXED_NOW - timedelta(days=2),
    }
    defaults.update(overrides)
    return JobPosting(**defaults)  # type: ignore[arg-type]


def _evidence(**overrides: object) -> ScoringEvidence:
    defaults: dict[str, object] = {
        "is_technical": True,
        "inferred_min_years": 1,
        "seniority_tier": "entry_level",
        "seniority_signals": [],
        "must_have_skills": ["Python", "SQL", "Git"],
        "direct_matches": ["Python", "SQL"],
        "transferable_matches": [],
        "missing_must_haves": ["Git"],
        "role_seniority_score": 8.0,
        "must_have_skills_score": 7.0,
        "domain_fit_score": 7.0,
        "nice_to_have_score": 6.0,
        "major_gaps": [],
        "rationale": "Strong junior backend alignment.",
    }
    defaults.update(overrides)
    return ScoringEvidence(**defaults)  # type: ignore[arg-type]


class _FakeScorerClient:
    def __init__(self, evidences: dict[str, ScoringEvidence]) -> None:
        self._evidences = evidences
        self.calls: list[tuple[str, str]] = []

    def invoke_structured(
        self,
        tier: str,
        system_prompt: str,
        user_prompt: str,
        schema: type[T],
    ) -> T:
        payload = json.loads(user_prompt)
        job_id = payload["job"]["job_id"]
        self.calls.append((tier, job_id))
        return self._evidences[job_id]  # type: ignore[return-value]


def test_entry_level_transferable_skills_get_full_credit_at_65_percent() -> None:
    prefs = _prefs()
    posting = _posting()
    evidence = _evidence(
        must_have_skills=["Python", "Terraform", "Docker"],
        direct_matches=["Python"],
        transferable_matches=[
            TransferableMatch(
                requested_skill="Terraform",
                candidate_skill="Pulumi",
                rationale="Both are IaC tools.",
            )
        ],
        missing_must_haves=["Docker"],
        # Weighted score: 7*0.30 + 6.5*0.35 + 6.5*0.20 + 6.0*0.15 = 6.575 >= 6.5
        role_seniority_score=7.0,
        must_have_skills_score=6.5,
        domain_fit_score=6.5,
        nice_to_have_score=6.0,
    )

    decision = evaluate_scoring_evidence(posting, evidence, prefs)
    assert decision.passed is True
    assert decision.status == ApplicationStatus.QUEUED_FOR_DRAFTING
    assert decision.must_have_coverage == pytest.approx(2 / 3, abs=1e-4)
    assert decision.fit_score == pytest.approx(6.575, abs=1e-4)
    assert decision.tier_threshold == 0.65


def test_entry_level_fails_below_65_percent_coverage_or_fit() -> None:
    prefs = _prefs()
    posting = _posting()

    low_coverage = evaluate_scoring_evidence(
        posting,
        _evidence(
            must_have_skills=["Python", "Go", "Kubernetes"],
            direct_matches=["Python"],
            missing_must_haves=["Go", "Kubernetes"],
            role_seniority_score=8.0,
            must_have_skills_score=8.0,
            domain_fit_score=8.0,
            nice_to_have_score=8.0,
        ),
        prefs,
    )
    assert low_coverage.passed is False
    assert low_coverage.status == ApplicationStatus.SCORED_OUT
    assert low_coverage.must_have_coverage == pytest.approx(1 / 3, abs=1e-4)

    low_fit = evaluate_scoring_evidence(
        posting,
        _evidence(
            must_have_skills=["Python", "SQL"],
            direct_matches=["Python", "SQL"],
            missing_must_haves=[],
            role_seniority_score=6.4,
            must_have_skills_score=6.4,
            domain_fit_score=6.4,
            nice_to_have_score=6.4,
        ),
        prefs,
    )
    assert low_fit.passed is False
    assert low_fit.status == ApplicationStatus.SCORED_OUT
    assert low_fit.fit_score == pytest.approx(6.4, abs=1e-4)


def test_stretch_role_gives_zero_transferable_credit_and_requires_95_percent() -> None:
    prefs = _prefs()
    posting = _posting(title="Software Engineer (2 years)")

    # 1 direct + 1 transferable out of 2 -> 0.50 coverage in stretch tier (0.0 transferable credit)
    transfer_only = evaluate_scoring_evidence(
        posting,
        _evidence(
            inferred_min_years=2,
            seniority_tier="stretch",
            must_have_skills=["Python", "Terraform"],
            direct_matches=["Python"],
            transferable_matches=[
                TransferableMatch(
                    requested_skill="Terraform",
                    candidate_skill="Pulumi",
                    rationale="Adjacent IaC",
                )
            ],
            missing_must_haves=[],
            role_seniority_score=9.5,
            must_have_skills_score=9.5,
            domain_fit_score=9.5,
            nice_to_have_score=9.5,
        ),
        prefs,
    )
    assert transfer_only.passed is False
    assert transfer_only.status == ApplicationStatus.SCORED_OUT
    assert transfer_only.effective_tier == "stretch"
    assert transfer_only.must_have_coverage == 0.5
    assert transfer_only.tier_threshold == 0.95

    # Exact 9.5/10 fit and 100% direct coverage -> passes
    exact_direct = evaluate_scoring_evidence(
        posting,
        _evidence(
            inferred_min_years=2,
            seniority_tier="entry_level",  # Python promotes to stretch because inferred_min_years == 2 > 1
            must_have_skills=["Python", "SQL"],
            direct_matches=["Python", "SQL"],
            missing_must_haves=[],
            role_seniority_score=9.5,
            must_have_skills_score=9.5,
            domain_fit_score=9.5,
            nice_to_have_score=9.5,
        ),
        prefs,
    )
    assert exact_direct.passed is True
    assert exact_direct.status == ApplicationStatus.QUEUED_FOR_DRAFTING
    assert exact_direct.effective_tier == "stretch"
    assert exact_direct.tier_threshold == 0.95


def test_rejects_non_technical_and_hidden_senior_plus_and_flags_missing_posted_at() -> None:
    prefs = _prefs()

    non_tech = evaluate_scoring_evidence(
        _posting(title="Account Executive"),
        _evidence(
            is_technical=False,
            must_have_skills=[],
            direct_matches=[],
            missing_must_haves=[],
            role_seniority_score=9.0,
            must_have_skills_score=9.0,
            domain_fit_score=9.0,
            nice_to_have_score=9.0,
        ),
        prefs,
    )
    assert non_tech.passed is False
    assert non_tech.status == ApplicationStatus.SCORED_OUT
    assert "non-technical" in (non_tech.rejection_reason or "").lower()

    hidden_senior = evaluate_scoring_evidence(
        _posting(title="Software Engineer", posted_at=None),
        _evidence(
            inferred_min_years=4,
            seniority_tier="senior_plus",
            seniority_signals=["4+ years required", "lead cross-team architecture"],
            must_have_skills=["Python"],
            direct_matches=["Python"],
            missing_must_haves=[],
            role_seniority_score=9.0,
            must_have_skills_score=10.0,
            domain_fit_score=9.0,
            nice_to_have_score=9.0,
        ),
        prefs,
    )
    assert hidden_senior.passed is False
    assert hidden_senior.status == ApplicationStatus.SCORED_OUT
    assert hidden_senior.missing_posted_at is True


def test_score_pending_jobs_evaluates_all_rows_without_daily_cap() -> None:
    repo = JobRepository(":memory:")
    prefs = _prefs()
    profile = _profile()

    evidences: dict[str, ScoringEvidence] = {}
    for idx in range(5):
        job_id = f"job_{idx:012d}"
        repo.insert_job(
            _posting(job_id=job_id, posted_at=None if idx == 0 else FIXED_NOW - timedelta(days=1)),
            ApplicationStatus.PENDING_SCORING,
            created_at=FIXED_NOW,
        )
        evidences[job_id] = _evidence(
            must_have_skills=["Python", "SQL"],
            direct_matches=["Python", "SQL"] if idx < 4 else ["Python"],
            missing_must_haves=[] if idx < 4 else ["SQL"],
            role_seniority_score=8.0 if idx < 4 else 4.0,
            must_have_skills_score=8.0 if idx < 4 else 4.0,
            domain_fit_score=8.0 if idx < 4 else 4.0,
            nice_to_have_score=8.0 if idx < 4 else 4.0,
        )

    client = _FakeScorerClient(evidences)
    summary = score_pending_jobs(repo, profile, prefs, client, now=FIXED_NOW)

    # All 5 evaluated (never capped by daily_draft_limit=3)
    assert summary.evaluated == 5
    assert summary.queued_for_drafting == 4
    assert summary.scored_out == 1
    assert summary.missing_posted_at_count == 1
    assert repo.count_queued_jobs() == 4
    assert all(tier == "scoring" for tier, _ in client.calls)

    stored_0 = repo.get_job("job_000000000000")
    assert stored_0 is not None
    assert stored_0.status == ApplicationStatus.QUEUED_FOR_DRAFTING
    assert stored_0.fit_breakdown_json is not None
    assert '"missing_posted_at":true' in stored_0.fit_breakdown_json.replace(" ", "")
