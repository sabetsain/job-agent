## ADDED Requirements

### Requirement: MasterProfile YAML schema and validation
The system SHALL define a Pydantic v2 `MasterProfile` schema and YAML loader representing verified candidate facts: personal contact/links, summary seed, work experiences (company, title, start/end dates, location, verified bullet points with metrics), projects, education, certifications, languages (including `en` and `da` proficiency), and categorized skills.

#### Scenario: Load a valid MasterProfile YAML file
- **WHEN** the loader reads a valid `master_profile.yaml` file with roles, projects, education, and skills
- **THEN** it SHALL return a validated `MasterProfile` instance with all fields typed and normalized

#### Scenario: Reject invalid MasterProfile data
- **WHEN** `master_profile.yaml` is missing required identity fields or contains an experience entry without a company, title, or start date
- **THEN** the loader MUST raise a Pydantic `ValidationError` identifying the invalid field path

### Requirement: JobPreferences schema with tiered seniority, freshness cap, layout guardrails, and required voice skill
The system SHALL define a Pydantic v2 `JobPreferences` schema and YAML loader containing:
- target roles and adjacent titles (centered on entry-level roles),
- allowed locations, regions, and work modes (`remote`, `hybrid`, `onsite`),
- `SeniorityPolicy` specifying excluded seniority title keywords (excluding `Architect` so roles like Solutions Architect remain eligible), `max_years_experience` ceiling, `entry_level` tier rules (0–1 years, slightly lenient must-have skill coverage), and `stretch` tier rules (up to 2 years, requiring maximized must-have skill coverage),
- `FreshnessPolicy` specifying `max_age_days` (default `21`), `preferred_age_days` (default `7`), and `daily_draft_limit` (default `3`, strictly an upper cap and never a daily quota),
- must-have and nice-to-have skills/domains,
- dealbreakers (excluded companies, industries, contract types, red-flag keywords; defaults to empty lists),
- weighted scoring rubric weights and `min_fit_score` threshold (without compensation floor requirements),
- document layout guardrails (`max_cv_pages`, `max_cover_letter_pages`, `min_font_size_pt` constrained to `>= 9.0`, and `preserve_whitespace_and_margins: true`),
- a required, non-empty `voice_skill_path` (defaulting to `.agent/skills/application-voice`) enforcing that the writer agent MUST use the `/application-voice` skill.

#### Scenario: Enforce minimum font size guardrail in schema validation
- **WHEN** `target_roles.yaml` specifies `min_font_size_pt` below `9.0`
- **THEN** Pydantic validation MUST reject the configuration with a validation error

#### Scenario: Enforce stretch tier requires stricter skill coverage than entry-level tier
- **WHEN** `target_roles.yaml` configures `stretch.min_must_have_coverage` lower than `entry_level.min_must_have_coverage`
- **THEN** Pydantic validation MUST reject the configuration with a validation error

#### Scenario: Enforce FreshnessPolicy bounds
- **WHEN** `target_roles.yaml` configures `preferred_age_days` greater than `max_age_days` or `daily_draft_limit` less than `1`
- **THEN** Pydantic validation MUST reject the configuration with a validation error

#### Scenario: Enforce required voice_skill_path
- **WHEN** `target_roles.yaml` sets `voice_skill_path` to an empty or whitespace-only string
- **THEN** Pydantic validation MUST reject the configuration with a validation error

#### Scenario: Default voice_skill_path to application-voice skill
- **WHEN** `target_roles.yaml` omits `voice_skill_path`
- **THEN** the loader SHALL default `voice_skill_path` to `.agent/skills/application-voice`

### Requirement: SourcesConfig and JobPosting schemas
The system SHALL define Pydantic v2 schemas for `SourcesConfig` (enabled/disabled whitelist of discovery adapters and adapter-specific parameters) and `JobPosting` (canonical internal `job_id`, `source`, `title`, `company`, `location`, `work_mode`, `apply_url`, `description`, `language` restricted to `"da"` or `"en"`, optional `posted_at`, optional `application_deadline`, `ingested_at`, and optional `external_id` / `raw_metadata`).

#### Scenario: Validate JobPosting language enum
- **WHEN** a `JobPosting` is constructed with `language` set to `"da"` or `"en"`
- **THEN** validation SHALL succeed
- **WHEN** a `JobPosting` is constructed with an unsupported language code
- **THEN** validation MUST raise a `ValidationError`

#### Scenario: Accept optional application_deadline on JobPosting
- **WHEN** a `JobPosting` includes an ISO-8601 `application_deadline` alongside `posted_at`
- **THEN** validation SHALL succeed and preserve both timestamps as timezone-aware datetimes
