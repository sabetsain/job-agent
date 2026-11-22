"""Hybrid free-LLM + deterministic Python Stage 1 fit scorer."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from job_agent.llm.client import StructuredLLMClient
from job_agent.prompts import get_prompt
from job_agent.schemas.jobs import ApplicationStatus, JobPosting
from job_agent.schemas.preferences import JobPreferences
from job_agent.schemas.profile import MasterProfile
from job_agent.scoring.models import FitDecision, ScoringEvidence, ScoringRunSummary
from job_agent.storage.repository import JobRepository, StoredJob


def _compute_weighted_fit_score(evidence: ScoringEvidence, preferences: JobPreferences) -> float:
    """Compute weighted 0-10 fit score deterministically from ScoringRubric."""
    rubric = preferences.scoring_rubric
    total_weight = (
        rubric.role_seniority_weight
        + rubric.must_have_skills_weight
        + rubric.domain_fit_weight
        + rubric.nice_to_have_weight
    )
    if total_weight <= 0.0:
        return 0.0

    weighted = (
        evidence.role_seniority_score * rubric.role_seniority_weight
        + evidence.must_have_skills_score * rubric.must_have_skills_weight
        + evidence.domain_fit_score * rubric.domain_fit_weight
        + evidence.nice_to_have_score * rubric.nice_to_have_weight
    ) / total_weight
    return round(min(10.0, max(0.0, weighted)), 4)


def _compute_must_have_coverage(
    evidence: ScoringEvidence,
    effective_tier: str,
) -> float:
    """Compute must-have skill coverage with Option B transferability credit."""
    total_must_haves = len(evidence.must_have_skills)
    if total_must_haves == 0:
        total_must_haves = (
            len(evidence.direct_matches)
            + len(evidence.transferable_matches)
            + len(evidence.missing_must_haves)
        )
    if total_must_haves == 0:
        return 1.0

    direct_count = len(evidence.direct_matches)
    transfer_credit = 1.0 if effective_tier == "entry_level" else 0.0
    covered = direct_count + (transfer_credit * len(evidence.transferable_matches))
    return round(min(1.0, max(0.0, covered / total_must_haves)), 4)


def evaluate_scoring_evidence(
    posting: JobPosting | StoredJob,
    evidence: ScoringEvidence,
    preferences: JobPreferences,
) -> FitDecision:
    """Apply deterministic seniority, non-technical, and tiered threshold gates."""
    missing_posted_at = posting.posted_at is None
    fit_score = _compute_weighted_fit_score(evidence, preferences)
    policy = preferences.seniority_policy

    if not evidence.is_technical:
        coverage = _compute_must_have_coverage(evidence, "entry_level")
        return FitDecision(
            passed=False,
            status=ApplicationStatus.SCORED_OUT,
            fit_score=fit_score,
            must_have_coverage=coverage,
            effective_tier="entry_level",
            tier_threshold=policy.entry_level.min_must_have_coverage,
            missing_posted_at=missing_posted_at,
            rejection_reason="Non-technical role automatically scored out.",
            evidence=evidence,
        )

    if (
        evidence.seniority_tier == "senior_plus"
        or (
            evidence.inferred_min_years is not None
            and evidence.inferred_min_years > policy.max_years_experience
        )
    ):
        coverage = _compute_must_have_coverage(evidence, "senior_plus")
        signals = ", ".join(evidence.seniority_signals) if evidence.seniority_signals else "senior scope"
        years_note = (
            f"requires {evidence.inferred_min_years}+ years (max {policy.max_years_experience})"
            if evidence.inferred_min_years is not None
            and evidence.inferred_min_years > policy.max_years_experience
            else signals
        )
        return FitDecision(
            passed=False,
            status=ApplicationStatus.SCORED_OUT,
            fit_score=fit_score,
            must_have_coverage=coverage,
            effective_tier="senior_plus",
            tier_threshold=policy.stretch.min_must_have_coverage,
            missing_posted_at=missing_posted_at,
            rejection_reason=f"Hidden Senior+ role scored out: {years_note}",
            evidence=evidence,
        )

    effective_tier: str = evidence.seniority_tier
    if (
        evidence.inferred_min_years is not None
        and evidence.inferred_min_years > policy.entry_level.max_years
    ):
        effective_tier = "stretch"

    tier_threshold = (
        policy.entry_level.min_must_have_coverage
        if effective_tier == "entry_level"
        else policy.stretch.min_must_have_coverage
    )
    coverage = _compute_must_have_coverage(evidence, effective_tier)
    normalized_fit = round(fit_score / 10.0, 4)

    if coverage < tier_threshold or normalized_fit < tier_threshold:
        reasons: list[str] = []
        if coverage < tier_threshold:
            reasons.append(
                f"must_have_coverage {coverage:.2f} below {effective_tier} threshold {tier_threshold:.2f}"
            )
        if normalized_fit < tier_threshold:
            reasons.append(
                f"fit_score {fit_score:.2f}/10 below {effective_tier} threshold {tier_threshold * 10:.2f}/10"
            )
        return FitDecision(
            passed=False,
            status=ApplicationStatus.SCORED_OUT,
            fit_score=fit_score,
            must_have_coverage=coverage,
            effective_tier=effective_tier,  # type: ignore[arg-type]
            tier_threshold=tier_threshold,
            missing_posted_at=missing_posted_at,
            rejection_reason="; ".join(reasons),
            evidence=evidence,
        )

    return FitDecision(
        passed=True,
        status=ApplicationStatus.QUEUED_FOR_DRAFTING,
        fit_score=fit_score,
        must_have_coverage=coverage,
        effective_tier=effective_tier,  # type: ignore[arg-type]
        tier_threshold=tier_threshold,
        missing_posted_at=missing_posted_at,
        rejection_reason=None,
        evidence=evidence,
    )


def build_scorer_user_prompt(
    posting: JobPosting | StoredJob,
    profile: MasterProfile,
    preferences: JobPreferences,
) -> str:
    """Serialize posting, verified MasterProfile, and preferences for the scorer LLM."""
    payload = {
        "job": {
            "job_id": posting.job_id,
            "title": posting.title,
            "company": posting.company,
            "location": posting.location,
            "work_mode": posting.work_mode.value,
            "language": posting.language,
            "posted_at": posting.posted_at.isoformat() if posting.posted_at else None,
            "application_deadline": (
                posting.application_deadline.isoformat()
                if posting.application_deadline
                else None
            ),
            "description": posting.description,
        },
        "seniority_policy": {
            "max_years_experience": preferences.seniority_policy.max_years_experience,
            "entry_level_max_years": preferences.seniority_policy.entry_level.max_years,
            "stretch_max_years": preferences.seniority_policy.stretch.max_years,
        },
        "target_roles": preferences.target_roles.model_dump(),
        "preferred_skills": preferences.skills.model_dump(),
        "master_profile": profile.model_dump(),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def score_single_job(
    posting: JobPosting | StoredJob,
    profile: MasterProfile,
    preferences: JobPreferences,
    llm_client: StructuredLLMClient,
) -> FitDecision:
    """Extract ScoringEvidence via scoring tier and apply deterministic Python gates."""
    system_prompt = get_prompt("scorer")
    user_prompt = build_scorer_user_prompt(posting, profile, preferences)
    evidence = llm_client.invoke_structured(
        "scoring",
        system_prompt,
        user_prompt,
        ScoringEvidence,
    )
    return evaluate_scoring_evidence(posting, evidence, preferences)


def score_pending_jobs(
    repository: JobRepository,
    profile: MasterProfile,
    preferences: JobPreferences,
    llm_client: StructuredLLMClient,
    *,
    now: datetime | None = None,
) -> ScoringRunSummary:
    """Evaluate all Pending_Scoring rows into Queued_For_Drafting or Scored_Out."""
    pending = repository.list_jobs(status=ApplicationStatus.PENDING_SCORING)
    current_time = now if now is not None else datetime.now(timezone.utc)
    summary = ScoringRunSummary()

    for job in pending:
        decision = score_single_job(job, profile, preferences, llm_client)
        repository.update_job(
            job.job_id,
            status=decision.status,
            rejection_reason=decision.rejection_reason,
            fit_score=decision.fit_score,
            fit_breakdown_json=decision.to_breakdown_json(),
            updated_at=current_time,
        )
        summary.evaluated += 1
        if decision.passed:
            summary.queued_for_drafting += 1
        else:
            summary.scored_out += 1
        if decision.missing_posted_at:
            summary.missing_posted_at_count += 1

    return summary
