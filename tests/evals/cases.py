"""Curated scoring eval cases matching intended seniority, transferability, and role gates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from job_agent.schemas.jobs import ApplicationStatus, JobPosting, WorkMode
from job_agent.scoring.models import ScoringEvidence, TransferableMatch

EVAL_NOW = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)


@dataclass(frozen=True)
class ScoringEvalCase:
    """Single curated eval scenario pairing a posting, expected decision, and offline evidence."""

    case_id: str
    posting: JobPosting
    expected_status: ApplicationStatus
    expected_missing_posted_at: bool
    offline_evidence: ScoringEvidence


EVAL_CASES: list[ScoringEvalCase] = [
    ScoringEvalCase(
        case_id="entry_level_direct_match",
        posting=JobPosting(
            job_id="eval_entry_direct_01",
            source="arbeitnow",
            title="Junior Backend Developer",
            company="Copenhagen FinTech",
            location="Copenhagen, Denmark",
            work_mode=WorkMode.HYBRID,
            apply_url="https://example.com/eval/1",
            description=(
                "We are looking for a Junior Backend Developer (0-1 years experience) to build "
                "Python and PostgreSQL APIs, write SQL queries, and ship via Git and Docker."
            ),
            language="en",
            posted_at=EVAL_NOW - timedelta(days=2),
        ),
        expected_status=ApplicationStatus.QUEUED_FOR_DRAFTING,
        expected_missing_posted_at=False,
        offline_evidence=ScoringEvidence(
            is_technical=True,
            inferred_min_years=0,
            seniority_tier="entry_level",
            must_have_skills=["Python", "PostgreSQL", "Git", "Docker"],
            direct_matches=["Python", "PostgreSQL", "Git", "Docker"],
            transferable_matches=[],
            missing_must_haves=[],
            role_seniority_score=9.5,
            must_have_skills_score=9.5,
            domain_fit_score=8.5,
            nice_to_have_score=8.0,
            major_gaps=[],
            rationale="Direct entry-level match across Python, PostgreSQL, Git, and Docker.",
        ),
    ),
    ScoringEvalCase(
        case_id="entry_level_transferable_stacks",
        posting=JobPosting(
            job_id="eval_entry_xfer_02",
            source="arbeitnow",
            title="Associate Cloud & Platform Engineer",
            company="Nordic Platform Co",
            location="Copenhagen, Denmark",
            work_mode=WorkMode.HYBRID,
            apply_url="https://example.com/eval/2",
            description=(
                "Entry-level role (0-1 years) building backend automation in Python with Django, "
                "AWS cloud hosting, Terraform IaC, and GitLab CI pipelines."
            ),
            language="en",
            posted_at=EVAL_NOW - timedelta(days=3),
        ),
        expected_status=ApplicationStatus.QUEUED_FOR_DRAFTING,
        expected_missing_posted_at=False,
        offline_evidence=ScoringEvidence(
            is_technical=True,
            inferred_min_years=1,
            seniority_tier="entry_level",
            must_have_skills=["Python", "Django", "AWS", "Terraform", "GitLab CI"],
            direct_matches=["Python"],
            transferable_matches=[
                TransferableMatch(
                    requested_skill="Django",
                    candidate_skill="FastAPI",
                    rationale="Python backend web framework experience.",
                ),
                TransferableMatch(
                    requested_skill="AWS",
                    candidate_skill="GCP",
                    rationale="Cloud platform deployment and managed services experience.",
                ),
                TransferableMatch(
                    requested_skill="Terraform",
                    candidate_skill="Pulumi",
                    rationale="Infrastructure-as-code experience.",
                ),
                TransferableMatch(
                    requested_skill="GitLab CI",
                    candidate_skill="GitHub Actions",
                    rationale="Automated CI/CD workflow authoring.",
                ),
            ],
            missing_must_haves=[],
            role_seniority_score=8.5,
            must_have_skills_score=7.5,
            domain_fit_score=8.0,
            nice_to_have_score=7.0,
            major_gaps=[],
            rationale="Entry-level role where FastAPI, GCP, Pulumi, and GitHub Actions transfer.",
        ),
    ),
    ScoringEvalCase(
        case_id="entry_level_miss_embedded_cpp",
        posting=JobPosting(
            job_id="eval_entry_miss_03",
            source="arbeitnow",
            title="Junior Embedded Firmware Engineer",
            company="SensorHardware ApS",
            location="Copenhagen, Denmark",
            work_mode=WorkMode.ONSITE,
            apply_url="https://example.com/eval/3",
            description=(
                "Junior firmware engineer (0-1 years) required to write bare-metal C and C++ "
                "drivers for RTOS microcontrollers with JTAG debugging and SPI/I2C protocols."
            ),
            language="en",
            posted_at=EVAL_NOW - timedelta(days=4),
        ),
        expected_status=ApplicationStatus.SCORED_OUT,
        expected_missing_posted_at=False,
        offline_evidence=ScoringEvidence(
            is_technical=True,
            inferred_min_years=0,
            seniority_tier="entry_level",
            must_have_skills=["C", "C++", "RTOS", "SPI/I2C"],
            direct_matches=[],
            transferable_matches=[],
            missing_must_haves=["C", "C++", "RTOS", "SPI/I2C"],
            role_seniority_score=8.0,
            must_have_skills_score=1.5,
            domain_fit_score=2.5,
            nice_to_have_score=2.0,
            major_gaps=["C/C++ embedded firmware", "RTOS microcontrollers"],
            rationale="Core embedded C/C++ firmware requirements have no coverage.",
        ),
    ),
    ScoringEvalCase(
        case_id="stretch_transferable_only_rejected",
        posting=JobPosting(
            job_id="eval_stretch_xfer_04",
            source="arbeitnow",
            title="Backend Software Engineer",
            company="ScaleUp DK",
            location="Copenhagen, Denmark",
            work_mode=WorkMode.HYBRID,
            apply_url="https://example.com/eval/4",
            description=(
                "We require 2 years of production experience building services in Python, "
                "PostgreSQL, Terraform, and AWS."
            ),
            language="en",
            posted_at=EVAL_NOW - timedelta(days=2),
        ),
        expected_status=ApplicationStatus.SCORED_OUT,
        expected_missing_posted_at=False,
        offline_evidence=ScoringEvidence(
            is_technical=True,
            inferred_min_years=2,
            seniority_tier="stretch",
            must_have_skills=["Python", "PostgreSQL", "Terraform", "AWS"],
            direct_matches=["Python", "PostgreSQL"],
            transferable_matches=[
                TransferableMatch(
                    requested_skill="Terraform",
                    candidate_skill="Pulumi",
                    rationale="IaC transferable only.",
                ),
                TransferableMatch(
                    requested_skill="AWS",
                    candidate_skill="GCP",
                    rationale="Cloud platform transferable only.",
                ),
            ],
            missing_must_haves=[],
            role_seniority_score=7.5,
            must_have_skills_score=6.5,
            domain_fit_score=8.0,
            nice_to_have_score=7.0,
            major_gaps=[],
            rationale="2-year stretch role gives 0.0 credit for transferable skills.",
        ),
    ),
    ScoringEvalCase(
        case_id="stretch_direct_match_passes",
        posting=JobPosting(
            job_id="eval_stretch_direct_05",
            source="arbeitnow",
            title="Backend Python Engineer",
            company="CloudNord DK",
            location="Copenhagen, Denmark",
            work_mode=WorkMode.HYBRID,
            apply_url="https://example.com/eval/5",
            description=(
                "Looking for an engineer with 2 years of experience in Python, FastAPI, "
                "PostgreSQL, Docker, and GCP Cloud Run."
            ),
            language="en",
            posted_at=EVAL_NOW - timedelta(days=1),
        ),
        expected_status=ApplicationStatus.QUEUED_FOR_DRAFTING,
        expected_missing_posted_at=False,
        offline_evidence=ScoringEvidence(
            is_technical=True,
            inferred_min_years=2,
            seniority_tier="stretch",
            must_have_skills=["Python", "FastAPI", "PostgreSQL", "Docker", "GCP"],
            direct_matches=["Python", "FastAPI", "PostgreSQL", "Docker", "GCP"],
            transferable_matches=[],
            missing_must_haves=[],
            role_seniority_score=9.5,
            must_have_skills_score=10.0,
            domain_fit_score=9.5,
            nice_to_have_score=9.5,
            major_gaps=[],
            rationale="100% direct must-have coverage for 2-year stretch role.",
        ),
    ),
    ScoringEvalCase(
        case_id="hidden_senior_plus_rejected",
        posting=JobPosting(
            job_id="eval_hidden_senior_06",
            source="arbeitnow",
            title="Software Engineer",
            company="Enterprise Systems A/S",
            location="Copenhagen, Denmark",
            work_mode=WorkMode.HYBRID,
            apply_url="https://example.com/eval/6",
            description=(
                "Join as Software Engineer. You bring 5+ years of production Python experience, "
                "own multi-team architecture decisions, and mentor junior developers."
            ),
            language="en",
            posted_at=EVAL_NOW - timedelta(days=2),
        ),
        expected_status=ApplicationStatus.SCORED_OUT,
        expected_missing_posted_at=False,
        offline_evidence=ScoringEvidence(
            is_technical=True,
            inferred_min_years=5,
            seniority_tier="senior_plus",
            seniority_signals=["5+ years required", "own multi-team architecture", "mentor juniors"],
            must_have_skills=["Python"],
            direct_matches=["Python"],
            missing_must_haves=[],
            role_seniority_score=2.0,
            must_have_skills_score=9.0,
            domain_fit_score=8.0,
            nice_to_have_score=7.0,
            major_gaps=[],
            rationale="Hidden senior role requiring 5+ years despite neutral title.",
        ),
    ),
    ScoringEvalCase(
        case_id="non_technical_role_scored_out",
        posting=JobPosting(
            job_id="eval_nontech_07",
            source="arbeitnow",
            title="Junior Account Executive",
            company="SaaS Growth ApS",
            location="Copenhagen, Denmark",
            work_mode=WorkMode.HYBRID,
            apply_url="https://example.com/eval/7",
            description=(
                "Manage outbound B2B sales pipeline, run product demos for enterprise buyers, "
                "and hit quarterly revenue quotas using HubSpot CRM."
            ),
            language="en",
            posted_at=EVAL_NOW - timedelta(days=2),
        ),
        expected_status=ApplicationStatus.SCORED_OUT,
        expected_missing_posted_at=False,
        offline_evidence=ScoringEvidence(
            is_technical=False,
            inferred_min_years=1,
            seniority_tier="entry_level",
            must_have_skills=["B2B Sales", "HubSpot"],
            direct_matches=[],
            missing_must_haves=["B2B Sales", "HubSpot"],
            role_seniority_score=7.0,
            must_have_skills_score=1.0,
            domain_fit_score=1.0,
            nice_to_have_score=1.0,
            major_gaps=["B2B Sales"],
            rationale="Pure commercial sales role, not technical engineering.",
        ),
    ),
    ScoringEvalCase(
        case_id="danish_entry_level_missing_posted_at",
        posting=JobPosting(
            job_id="eval_da_missing_08",
            source="jobindex_rss",
            title="Junior Softwareudvikler",
            company="Dansk Offentlig Tech",
            location="København",
            work_mode=WorkMode.HYBRID,
            apply_url="https://example.com/eval/8",
            description=(
                "Vi søger en nyuddannet softwareudvikler til vores team i København. "
                "Du skal arbejde med Python, SQL, Git og Docker i moderne dataplatforme."
            ),
            language="da",
            posted_at=None,
        ),
        expected_status=ApplicationStatus.QUEUED_FOR_DRAFTING,
        expected_missing_posted_at=True,
        offline_evidence=ScoringEvidence(
            is_technical=True,
            inferred_min_years=0,
            seniority_tier="entry_level",
            must_have_skills=["Python", "SQL", "Git", "Docker"],
            direct_matches=["Python", "SQL", "Git", "Docker"],
            transferable_matches=[],
            missing_must_haves=[],
            role_seniority_score=9.5,
            must_have_skills_score=9.5,
            domain_fit_score=9.0,
            nice_to_have_score=8.0,
            major_gaps=[],
            rationale="Strong Danish entry-level match.",
        ),
    ),
]
