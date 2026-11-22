## MODIFIED Requirements

### Requirement: SQLite job and application state persistence
The system SHALL persist ingested jobs and application lifecycle metadata in a local SQLite database (`data/job_agent.db`) via a `JobRepository` abstraction using standard SQL compatible with future migration to Cloud SQL Postgres. Because Slack PDF delivery serves as final document storage (no Google Drive required), each record SHALL store `job_id` (primary key), `source`, `external_id`, `title`, `company`, `location`, `work_mode`, `language`, `apply_url`, `description`, `status` (`Pending_Scoring`, `PreFiltered_Out`, `Scored_Out`, `Queued_For_Drafting`, `Expired`, `Pending_Review`, `Revising`, `Ready_to_Submit`, `Applied`, `Interviewing`, `Rejected`), `rejection_reason`, `fit_score`, `fit_breakdown_json`, `cv_pdf_path`, `cover_letter_pdf_path`, `slack_thread_ts`, `gmail_thread_id`, `langgraph_thread_id`, `posted_at`, `application_deadline`, `created_at`, and `updated_at`.

#### Scenario: Persist passing job as Pending_Scoring
- **WHEN** a new job posting passes deterministic pre-filtering
- **THEN** the repository SHALL insert the record with `status="Pending_Scoring"` and `rejection_reason=None`

#### Scenario: Persist non-freshness pre-filtered job as PreFiltered_Out
- **WHEN** a new job posting passes freshness but fails seniority, location, or dealbreaker pre-filtering
- **THEN** the repository SHALL insert the record with `status="PreFiltered_Out"` and the structured `rejection_reason` populated

#### Scenario: Do not persist stale job rejected by freshness pre-filter
- **WHEN** a discovered job posting fails the posting freshness pre-filter (`posted_at` older than `max_age_days` with no future `application_deadline`)
- **THEN** the pipeline MUST discard it without inserting a row into SQLite

### Requirement: Freshness-priority candidate ordering up to daily draft cap
The repository SHALL provide a query draining un-drafted `Queued_For_Drafting` jobs ordered so that postings within `preferred_age_days` (default `7`) OR carrying a future `application_deadline` are ranked in the preferred tier ahead of older eligible postings (`8–21` days), and within each tier ordered strictly **FIFO** (`created_at ASC`, tie-breaking by `fit_score DESC`), capped at **at most** `daily_draft_limit` (default `3`, strictly an upper cap and never a quota — returning 0, 1, or 2 rows when fewer qualify). The repository SHALL also provide `expire_stale_queued_jobs(max_age_days=21)` (preserving `source="manual"` rows) and `count_queued_jobs()` for queue visibility.

#### Scenario: Preferred 7-day and future-deadline queued postings rank before older queued postings
- **WHEN** SQLite contains `Queued_For_Drafting` postings aged 3 days, 15 days, and 24 days (with an active future `application_deadline`)
- **THEN** the priority queue query MUST return the 3-day posting and the future-deadline posting ahead of the 15-day posting

#### Scenario: FIFO backlog drains before newly queued jobs within the same priority tier
- **WHEN** SQLite contains 3 preferred-tier `Queued_For_Drafting` jobs created yesterday and 1 preferred-tier job created today with `daily_draft_limit=3`
- **THEN** the priority queue query MUST return yesterday's 3 jobs first

#### Scenario: Fallback to older eligible queued postings when no preferred-tier postings remain
- **WHEN** no preferred-tier `Queued_For_Drafting` postings remain and eligible queued postings aged 12 days exist
- **THEN** the priority queue query SHALL return the 12-day postings up to `daily_draft_limit`

#### Scenario: Daily draft limit acts as a cap, not a quota
- **WHEN** only 1 `Queued_For_Drafting` posting exists in SQLite and `daily_draft_limit` is `3`
- **THEN** the priority queue query SHALL return only that 1 posting (or 0 when none exist)

### Requirement: CLI ingestion, manual drop, and state inspection commands
The system SHALL provide CLI commands (`job-agent ingest`, `job-agent add`, `job-agent list`, `job-agent score`, `job-agent draft`, `job-agent queue`, and `job-agent review <job_id>`) to execute once-daily discovery + pre-filtering + retention cleanup, manually submit a job posting with loud failure reporting, score all `Pending_Scoring` jobs into the draft queue, drain up to `daily_draft_limit` queued jobs through the tailoring graph, inspect queue depth and stored jobs, and interactively ideate/re-iterate/approve/dismiss a drafted job from the terminal.

#### Scenario: Run ingestion via CLI
- **WHEN** the user executes `job-agent ingest`
- **THEN** the CLI SHALL load YAML configs, run all enabled `JobSource` adapters once, skip existing `job_id`s, discard stale postings without storing them, persist remaining results to SQLite, run 6-month retention cleanup, and print a summary of fetched, skipped, discarded-stale, passed (`Pending_Scoring`), pre-filtered (`PreFiltered_Out`), and pruned counts

#### Scenario: Manual drop CLI fails loudly on inaccessible or unparseable link
- **WHEN** the user executes `job-agent add --url <blocked-or-invalid-url>` and the link is behind an auth wall (HTTP 401/403 or login redirect), blocked by CAPTCHA/anti-bot, times out, or yields no extractable job description
- **THEN** the CLI MUST exit with a non-zero status code, print a clear user-facing explanation of why the link failed (and recommend supplying the raw JD text), and MUST NOT insert a row into SQLite

#### Scenario: List pending jobs and inspect draft queue depth via CLI
- **WHEN** the user executes `job-agent list --status Pending_Scoring` or `job-agent queue`
- **THEN** the CLI SHALL display matching rows or the current `Queued_For_Drafting` count and queued job summary

#### Scenario: Score, draft, and review via CLI harness
- **WHEN** the user executes `job-agent score`, `job-agent draft`, and `job-agent review <job_id>`
- **THEN** the CLI SHALL score all `Pending_Scoring` rows, drain at most `daily_draft_limit` queued jobs into compiled drafts (emitting `"Workshopping now..."` progress feedback), and open an interactive terminal session supporting free-form ideation, one-shot `re-iterate`, `/approve`, and `/dismiss`

## ADDED Requirements

### Requirement: Weekly profile update suggestions cache
The repository SHALL maintain a `profile_update_suggestions` SQLite table (`id`, `job_id`, `kind` restricted to `"addition"` or `"correction"`, `fact_text`, `category`, `created_at`, `consumed_at`) storing newly shared or corrected verified facts collected during ideation threads throughout the week, with methods to insert suggestions, list unconsumed suggestions (`consumed_at IS NULL`), and mark suggestions consumed when the future `weekly-profile-checkin` workflow processes them.

#### Scenario: Persist and query unconsumed profile additions and corrections
- **WHEN** an ideation session records a new accomplishment (`kind="addition"`) or a correction to stale `MasterProfile` data (`kind="correction"`) for a job
- **THEN** `JobRepository` SHALL insert the row with `consumed_at=None` and `list_unconsumed_profile_suggestions()` SHALL return it in chronological order until marked consumed
