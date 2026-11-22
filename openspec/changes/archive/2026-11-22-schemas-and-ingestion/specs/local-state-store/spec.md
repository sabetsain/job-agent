## ADDED Requirements

### Requirement: SQLite job and application state persistence
The system SHALL persist ingested jobs and application lifecycle metadata in a local SQLite database (`data/job_agent.db`) via a `JobRepository` abstraction using standard SQL compatible with future migration to Cloud SQL Postgres. Because Slack PDF delivery serves as final document storage (no Google Drive required), each record SHALL store `job_id` (primary key), `source`, `external_id`, `title`, `company`, `location`, `work_mode`, `language`, `apply_url`, `description`, `status` (`Pending_Scoring`, `PreFiltered_Out`, `Pending_Review`, `Revising`, `Ready_to_Submit`, `Applied`, `Interviewing`, `Rejected`), `rejection_reason`, `fit_score`, `fit_breakdown_json`, `cv_pdf_path`, `cover_letter_pdf_path`, `slack_thread_ts`, `gmail_thread_id`, `langgraph_thread_id`, `posted_at`, `application_deadline`, `created_at`, and `updated_at`.

#### Scenario: Persist passing job as Pending_Scoring
- **WHEN** a new job posting passes deterministic pre-filtering
- **THEN** the repository SHALL insert the record with `status="Pending_Scoring"` and `rejection_reason=None`

#### Scenario: Persist non-freshness pre-filtered job as PreFiltered_Out
- **WHEN** a new job posting passes freshness but fails seniority, location, or dealbreaker pre-filtering
- **THEN** the repository SHALL insert the record with `status="PreFiltered_Out"` and the structured `rejection_reason` populated

#### Scenario: Do not persist stale job rejected by freshness pre-filter
- **WHEN** a discovered job posting fails the posting freshness pre-filter (`posted_at` older than `max_age_days` with no future `application_deadline`)
- **THEN** the pipeline MUST discard it without inserting a row into SQLite

### Requirement: Idempotent job_id skip on re-ingestion
The system SHALL check whether a generated `job_id` already exists in the repository before inserting or running pre-filtering, and MUST skip existing `job_id`s without overwriting downstream status or metadata.

#### Scenario: Skip already-ingested job_id on subsequent run
- **WHEN** an ingestion run encounters a `job_id` that already exists in SQLite with `status="Applied"`
- **THEN** the system SHALL skip the posting, leave the existing row untouched, and increment the skipped count in the run summary

### Requirement: Freshness-priority candidate ordering up to daily draft cap
The repository SHALL provide a query returning un-drafted, un-applied eligible jobs ordered so that postings within `preferred_age_days` (default `7`) OR carrying a future `application_deadline` are ranked in the preferred tier ahead of older eligible postings (`8–21` days), capped at **at most** `daily_draft_limit` (default `3`, strictly an upper cap and never a quota — returning 0, 1, or 2 rows when fewer qualify).

#### Scenario: Preferred 7-day and future-deadline postings rank before older eligible postings
- **WHEN** SQLite contains un-drafted `Pending_Scoring` postings aged 3 days, 15 days, and 24 days (with an active future `application_deadline`)
- **THEN** the priority query MUST return the 3-day posting and the future-deadline posting ahead of the 15-day posting

#### Scenario: Fallback to older eligible postings when no preferred-tier postings remain
- **WHEN** all preferred-tier postings have already been drafted or applied to, and un-drafted eligible postings aged 12 days remain
- **THEN** the priority query SHALL return the 12-day postings up to `daily_draft_limit`

#### Scenario: Daily draft limit acts as a cap, not a quota
- **WHEN** only 1 eligible un-drafted posting exists in SQLite and `daily_draft_limit` is `3`
- **THEN** the priority query SHALL return only that 1 posting (or 0 when none exist)

### Requirement: Six-month retention cleanup preserving active interviews
The repository SHALL provide a cleanup method (`prune_old_jobs(retention_days=180)`) invoked automatically during `job-agent ingest` that deletes rows whose `created_at` timestamp is older than 180 days (~6 months), EXCEPT rows with `status="Interviewing"`, which MUST be preserved.

#### Scenario: Prune roles ingested more than 6 months ago
- **WHEN** SQLite contains a `Rejected` role and a `Pending_Scoring` role ingested 200 days ago
- **THEN** `prune_old_jobs(180)` MUST delete both rows

#### Scenario: Preserve roles marked Interviewing even if older than 6 months
- **WHEN** SQLite contains an `Interviewing` role ingested 200 days ago
- **THEN** `prune_old_jobs(180)` MUST preserve that row untouched

### Requirement: CLI ingestion, manual drop, and state inspection commands
The system SHALL provide CLI commands (`job-agent ingest`, `job-agent add`, and `job-agent list`) to execute once-daily discovery + pre-filtering + retention cleanup, manually submit a job posting with loud failure reporting, and inspect stored jobs filtered by status or language.

#### Scenario: Run ingestion via CLI
- **WHEN** the user executes `job-agent ingest`
- **THEN** the CLI SHALL load YAML configs, run all enabled `JobSource` adapters once, skip existing `job_id`s, discard stale postings without storing them, persist remaining results to SQLite, run 6-month retention cleanup, and print a summary of fetched, skipped, discarded-stale, passed (`Pending_Scoring`), pre-filtered (`PreFiltered_Out`), and pruned counts

#### Scenario: Manual drop CLI fails loudly on inaccessible or unparseable link
- **WHEN** the user executes `job-agent add --url <blocked-or-invalid-url>` and the link is behind an auth wall (HTTP 401/403 or login redirect), blocked by CAPTCHA/anti-bot, times out, or yields no extractable job description
- **THEN** the CLI MUST exit with a non-zero status code, print a clear user-facing explanation of why the link failed (and recommend supplying the raw JD text), and MUST NOT insert a row into SQLite

#### Scenario: List pending jobs via CLI
- **WHEN** the user executes `job-agent list --status Pending_Scoring`
- **THEN** the CLI SHALL display matching rows from SQLite including `job_id`, `company`, `title`, `location`, `language`, `posted_at`, `application_deadline`, and `source`
