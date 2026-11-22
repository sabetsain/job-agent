## ADDED Requirements

### Requirement: Evaluate all Pending_Scoring postings with hybrid free-LLM extraction and deterministic Python gating
The system SHALL evaluate **all** postings in `Pending_Scoring` (never capped by `daily_draft_limit`). For each posting, the free `scoring_model` SHALL return a LangChain-enforced `ScoringEvidence` Pydantic object containing:
- `is_technical: bool` (false for non-technical roles such as sales, HR, marketing, legal, or pure administrative roles),
- `inferred_min_years: int | None`, `seniority_tier` (`entry_level`, `stretch`, `senior_plus`), and `seniority_signals: list[str]` — guided by clear tell-tales in `prompts/scorer.md` (primarily required years of experience > `max_years_experience`, plus senior ownership/mentoring/architecture-lead scope),
- role must-have skills, matched direct skills, transferable skills with rationale (guided by diverse examples across IaC, cloud platforms, web frameworks, CI/CD, SQL dialects, and container tooling rather than a single example), missing must-haves,
- 0–10 sub-scores (`role_seniority`, `must_have_skills`, `domain_fit`, `nice_to_have`), and major unaddressed gaps.
Python SHALL deterministically reject non-technical and hidden `senior_plus` roles as `Scored_Out`, compute the weighted fit score from `ScoringRubric`, compute `must_have_coverage`, attach `missing_posted_at = (posting.posted_at is None)`, persist `fit_score` and `fit_breakdown_json`, and transition the row to `Queued_For_Drafting` or `Scored_Out`.

#### Scenario: Entry-level role with transferable skills passes at 65% threshold
- **WHEN** an `entry_level` (0–1y) technical posting requests tools/frameworks adjacent to the candidate's verified stack (e.g., AWS with GCP experience, Django with FastAPI experience, or Terraform with Pulumi experience) and Python computes `must_have_coverage >= 0.65` and normalized weighted fit score `>= 0.65`
- **THEN** Python SHALL award `1.0` credit for each transferable skill, persist `fit_score` and `fit_breakdown_json`, and transition the job to `Queued_For_Drafting`

#### Scenario: Entry-level role below 65% fit is scored out
- **WHEN** an `entry_level` posting results in `must_have_coverage < 0.65` or normalized weighted fit score `< 0.65`
- **THEN** Python SHALL persist `fit_score` and `fit_breakdown_json` and transition the job to `Scored_Out`

#### Scenario: Mid-level stretch role rejects transferable-only skill coverage below 95%
- **WHEN** a `stretch` (~2y) posting requests a must-have tool where the candidate only holds a transferable equivalent (not a direct match)
- **THEN** Python MUST award `0.0` credit for the transferable skill toward `must_have_coverage`, fail the `0.95` stretch threshold, and transition the job to `Scored_Out`

#### Scenario: Mid-level stretch role with 95%+ direct coverage passes
- **WHEN** a `stretch` (~2y) technical posting achieves `must_have_coverage >= 0.95` from direct skill matches and normalized weighted fit score `>= 0.95`
- **THEN** Python SHALL transition the job to `Queued_For_Drafting`

#### Scenario: Hidden Senior+ role is scored out via clear seniority tell-tales
- **WHEN** a posting passed title pre-filtering (e.g., titled "Software Engineer") but `ScoringEvidence` identifies `inferred_min_years > max_years_experience` or `seniority_tier == "senior_plus"` from required years of experience and senior scope signals
- **THEN** Python MUST transition the job to `Scored_Out` regardless of skill overlap

#### Scenario: Non-technical role is automatically scored out
- **WHEN** a posting is classified by `ScoringEvidence` as `is_technical == False` (e.g., Account Executive, Recruiter, or Marketing Coordinator)
- **THEN** Python MUST automatically transition the job to `Scored_Out` with a non-technical rejection reason

#### Scenario: Missing posted_at timestamp is flagged in fit breakdown
- **WHEN** a posting with `posted_at=None` is scored
- **THEN** the persisted `fit_breakdown_json` MUST include `missing_posted_at=true` so downstream review surfaces the warning to the user

### Requirement: Pre-draft queue expiration and priority FIFO draining up to daily cap
Before drafting from `Queued_For_Drafting`, the system SHALL deterministically expire any non-manual (`source != "manual"`) queued posting whose `application_deadline` has passed or whose `posted_at` is now older than `FreshnessPolicy.max_age_days` by transitioning it to `Expired` with a structured `rejection_reason`. From the remaining `Queued_For_Drafting` rows, the system SHALL drain at most `FreshnessPolicy.daily_draft_limit` (default `3`, strictly an upper cap, never a quota) ordered with preferred-window postings (`posted_at <= preferred_age_days` OR active future `application_deadline`) ahead of older eligible postings (`8–21d`), and strict FIFO (`created_at ASC`, tie-breaking by `fit_score DESC`) within each tier.

#### Scenario: Expire stale or past-deadline queued job before drafting
- **WHEN** a non-manual job in `Queued_For_Drafting` has an `application_deadline` in the past (or `posted_at` older than `max_age_days` with no future deadline)
- **THEN** the queue drainer MUST transition that job to `Expired` and MUST NOT invoke the tailoring graph for it

#### Scenario: Manual drop queued job is never expired by age
- **WHEN** a `source="manual"` job in `Queued_For_Drafting` has `posted_at` older than `max_age_days`
- **THEN** the queue drainer SHALL keep it eligible for drafting

#### Scenario: Drain backlog FIFO within the same priority tier
- **WHEN** 3 preferred-tier jobs were queued yesterday and 1 new preferred-tier job is queued today with `daily_draft_limit=3`
- **THEN** the drainer SHALL select yesterday's 3 queued jobs first and leave today's job queued for the next run

### Requirement: Curated scoring evals suite with synthetic profile and structured test job listings
The system SHALL include a curated evals suite (`tests/evals/`) containing a synthetic test `MasterProfile` and structured test job listings covering entry-level direct matches, entry-level transferable matches across diverse stacks (≥65%), entry-level misses (<65%), mid-level/stretch transferable-only rejects (0.0 credit, <95%), mid-level/stretch direct matches (≥95%), hidden senior+ rejects, non-technical rejects, Danish (`da`) postings, and missing `posted_at` flagging. The evals suite MUST support both deterministic offline execution (using fixture `ScoringEvidence`) and opt-in live execution against the configured free `scoring_model` (`pytest -m eval`).

#### Scenario: Run offline scoring evals deterministically
- **WHEN** the developer runs the offline evals suite without network access
- **THEN** every curated test case SHALL assert the expected `Queued_For_Drafting` vs. `Scored_Out` transition, transferable credit rule, non-technical rejection, and `missing_posted_at` flag

#### Scenario: Run live scoring evals against configured free scoring_model
- **WHEN** the developer opts in to live evals (`pytest -m eval`) with `OPENCODE_API_KEY` configured
- **THEN** the suite SHALL run the real `scorer` prompt and configured `scoring_model` against the curated test profile and job listings and report pass/fail per use case
