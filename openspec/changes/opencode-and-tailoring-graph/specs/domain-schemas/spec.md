## RENAMED Requirements

- FROM: `### Requirement: JobPreferences schema with tiered seniority, freshness cap, layout guardrails, and required voice skill`
- TO: `### Requirement: JobPreferences schema with tiered seniority, freshness cap, and layout guardrails`

## MODIFIED Requirements

### Requirement: JobPreferences schema with tiered seniority, freshness cap, and layout guardrails
The system SHALL define a Pydantic v2 `JobPreferences` schema and YAML loader containing:
- target roles and adjacent titles (centered on entry-level roles),
- allowed locations, regions, and work modes (`remote`, `hybrid`, `onsite`),
- `SeniorityPolicy` specifying excluded seniority title keywords (excluding `Architect` so roles like Solutions Architect remain eligible), `max_years_experience` ceiling, `entry_level` tier rules (0–1 years, minimum fit / coverage threshold defaulting to `0.65` / 65%), and `stretch` tier rules (up to 2 years, minimum fit / coverage threshold defaulting to `0.95` / 95%),
- `FreshnessPolicy` specifying `max_age_days` (default `21`), `preferred_age_days` (default `7`), and `daily_draft_limit` (default `3`, strictly an upper cap and never a daily quota),
- must-have and nice-to-have skills/domains,
- dealbreakers (excluded companies, industries, contract types, red-flag keywords; defaults to empty lists),
- weighted scoring rubric weights (`role_seniority_weight`, `must_have_skills_weight`, `domain_fit_weight`, `nice_to_have_weight`) without compensation floor requirements and without a separate flat `min_fit_score` (minimum fit is governed by `SeniorityPolicy` tiers),
- document layout guardrails (`max_cv_pages`, `max_cover_letter_pages`, body text `min_font_size_pt` constrained to `>= 9.0` and `<= 12.0` defaulting to `10.0`, body text `max_body_font_size_pt` constrained to `>= min_font_size_pt` and `<= 12.0` defaulting to `12.0` — scoped to body text only, excluding headers, sub-headers, and footers — and `preserve_whitespace_and_margins: true`).
`JobPreferences` MUST NOT require or define `voice_skill_path` or optional skill-path fields, as all LLM agents use dedicated version-controlled system prompts loaded at startup.

#### Scenario: Enforce body font size floor and ceiling in schema validation
- **WHEN** `target_roles.yaml` specifies `min_font_size_pt` below `9.0` or `max_body_font_size_pt` above `12.0` (or `min_font_size_pt > max_body_font_size_pt`)
- **THEN** Pydantic validation MUST reject the configuration with a validation error

#### Scenario: Enforce stretch tier requires stricter fit threshold than entry-level tier
- **WHEN** `target_roles.yaml` configures `stretch.min_must_have_coverage` lower than `entry_level.min_must_have_coverage`
- **THEN** Pydantic validation MUST reject the configuration with a validation error

#### Scenario: Enforce FreshnessPolicy bounds
- **WHEN** `target_roles.yaml` configures `preferred_age_days` greater than `max_age_days` or `daily_draft_limit` less than `1`
- **THEN** Pydantic validation MUST reject the configuration with a validation error

#### Scenario: Load JobPreferences cleanly without voice_skill_path or flat min_fit_score
- **WHEN** `target_roles.yaml` omits `voice_skill_path` and `scoring_rubric.min_fit_score`
- **THEN** `load_job_preferences` SHALL validate cleanly with tiered thresholds (`0.65` entry-level, `0.95` stretch) and body font bounds (`[9.0, 12.0]`)

## ADDED Requirements

### Requirement: ApplicationStatus lifecycle enum with draft queue and expiration states
The system SHALL define `ApplicationStatus` containing `Pending_Scoring`, `PreFiltered_Out`, `Scored_Out`, `Queued_For_Drafting`, `Expired`, `Pending_Review`, `Revising`, `Ready_to_Submit`, `Applied`, `Interviewing`, and `Rejected`.

#### Scenario: Validate new queue and scoring statuses
- **WHEN** `ApplicationStatus` is constructed with `"Queued_For_Drafting"`, `"Scored_Out"`, or `"Expired"`
- **THEN** validation SHALL succeed

### Requirement: Dual-tier LLMConfig YAML schema and validation
The system SHALL define a Pydantic v2 `LLMConfig` schema and YAML loader (`load_llm_config`) validating `base_url` (default `"https://opencode.ai/zen/go/v1"`), `api_key_env` (default `"OPENCODE_API_KEY"`), `scoring_model` (non-empty string, free model for scoring & classification), `reasoning_model` (non-empty string, cheap paid model for planning, writing, auditing, and ideation), optional `scoring_base_url` / `scoring_api_key_env` overrides, optional `reasoning_effort`, `temperature` (`>= 0.0`, `<= 2.0`), `timeout_seconds` (`> 0`), `max_parse_retries` (`>= 0`, default `2`), and `structured_output_method` (`"json_schema"` or `"function_calling"`).

#### Scenario: Load valid dual-tier config/llm.yaml
- **WHEN** `load_llm_config` reads a valid `config/llm.yaml` specifying `scoring_model`, `reasoning_model`, and `base_url`
- **THEN** it SHALL return a validated `LLMConfig` instance

#### Scenario: Reject empty scoring_model or reasoning_model in LLMConfig
- **WHEN** `config/llm.yaml` sets `scoring_model` or `reasoning_model` to an empty or whitespace-only string
- **THEN** Pydantic validation MUST raise a `ValidationError`
