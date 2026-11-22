"""Scoring evals suite: deterministic offline by default, live OpenCode Go via `pytest -m eval`."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from job_agent.llm import OpenCodeLLMClient, load_llm_config
from job_agent.schemas import load_job_preferences, load_master_profile
from job_agent.scoring import evaluate_scoring_evidence, score_single_job
from tests.evals.cases import EVAL_CASES, ScoringEvalCase

EVALS_DIR = Path(__file__).resolve().parent
REPO_ROOT = EVALS_DIR.parent.parent
TEST_PROFILE_PATH = EVALS_DIR / "test_profile.yaml"
PREFS_PATH = REPO_ROOT / "config" / "target_roles.example.yaml"
LLM_CONFIG_PATH = REPO_ROOT / "config" / "llm.example.yaml"


@pytest.mark.parametrize("case", EVAL_CASES, ids=[c.case_id for c in EVAL_CASES])
def test_offline_scoring_eval(case: ScoringEvalCase) -> None:
    prefs = load_job_preferences(PREFS_PATH)
    decision = evaluate_scoring_evidence(case.posting, case.offline_evidence, prefs)

    assert decision.status == case.expected_status, (
        f"{case.case_id}: expected {case.expected_status}, got {decision.status} "
        f"(reason={decision.rejection_reason})"
    )
    assert decision.missing_posted_at is case.expected_missing_posted_at


@pytest.mark.eval
@pytest.mark.parametrize("case", EVAL_CASES, ids=[c.case_id for c in EVAL_CASES])
def test_live_scoring_eval(case: ScoringEvalCase) -> None:
    cfg = load_llm_config(LLM_CONFIG_PATH)
    if not os.environ.get(cfg.api_key_env):
        pytest.skip(f"{cfg.api_key_env} not set for live eval")

    profile = load_master_profile(TEST_PROFILE_PATH)
    prefs = load_job_preferences(PREFS_PATH)
    client = OpenCodeLLMClient(cfg)

    decision = score_single_job(case.posting, profile, prefs, client)
    assert decision.status == case.expected_status, (
        f"Live eval {case.case_id} failed: expected {case.expected_status}, got {decision.status} "
        f"(fit={decision.fit_score}, cov={decision.must_have_coverage}, reason={decision.rejection_reason})"
    )
    assert decision.missing_posted_at is case.expected_missing_posted_at
