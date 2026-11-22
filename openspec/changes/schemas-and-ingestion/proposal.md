## Why

As defined in `docs/INTENT.md`, this project builds a personal job-hunting and application co-pilot primarily targeting entry-level roles in Copenhagen, Denmark (Europe) and Remote. Before introducing LLM scoring, LangGraph tailoring, or Google Sheets sync, the co-pilot needs a rock-solid, deterministic foundation: strongly typed domain schemas, reliable once-daily free/open job discovery, rule-based pre-filtering that enforces hard seniority, posting freshness, location, and dealbreaker rules before any LLM tokens are spent, and persistent local state tracking with automatic 6-month cleanup. Building this as the first standalone change keeps the core data contracts clean, testable, and independent of external LLM or chat APIs.

## What Changes

- Initialize the Python 3.11+ project structure (`pyproject.toml`, package layout, CLI entrypoint, and intent-rooted test suite with mutation testing support).
- Define Pydantic v2 schemas and YAML config loaders for `MasterProfile`, `JobPreferences` (including tiered seniority eligibility policy centered on entry-level roles, posting freshness & `daily_draft_limit` cap rules, location/work-mode rules, dealbreakers, weighted scoring rubric, layout constraints, and required `voice_skill_path` pointing to `.agent/skills/application-voice` so the writer agent MUST use `/application-voice`), `SourcesConfig`, and `JobPosting` (including `posted_at` and optional `application_deadline`).
- Implement a pluggable `JobSource` adapter interface for once-daily scheduled discovery across free, unauthenticated adapters targeting Copenhagen/Europe + Remote: **Arbeitnow**, **Remotive**, **Himalayas**, **Jobicy**, and **Jobindex RSS**, plus a **Manual Drop** CLI command (`job-agent add`) that fails loudly with a clear explanation if a dropped URL is blocked, auth-gated, or unparseable.
- Generate a canonical internal `job_id` deterministically in Python (skipping already-stored `job_id`s without a separate fuzzy deduplication subsystem) and detect posting language (`da` or `en`).
- Implement a deterministic pre-filter engine that rejects postings matching dealbreakers, excluded seniority levels (`Senior`, `Staff`, `Principal`, `Lead`, etc. — keeping `Architect` eligible), expired posting freshness (older than ~2–3 weeks unless an explicit future application deadline is listed; stale postings are discarded and not stored), or disallowed locations/work modes before LLM scoring.
- Implement a local SQLite state store (structured for clean future migration to Cloud SQL Postgres, without Google Drive columns since Slack PDF delivery serves as final document storage), 6-month retention cleanup preserving `Interviewing` rows, freshness-priority candidate ordering up to the daily cap, and CLI commands (`job-agent ingest`, `job-agent add`, `job-agent list`).

## Capabilities

### New Capabilities
- `domain-schemas`: Pydantic v2 schemas, validation rules, and YAML loaders for `MasterProfile`, `JobPreferences`, `SourcesConfig`, and `JobPosting`.
- `job-discovery-ingestion`: Pluggable `JobSource` adapter interface for once-daily polling, free/open EU/Copenhagen/Remote board adapters, Manual Drop input with loud user-visible failure reporting, internal `job_id` generation, and deterministic `da`/`en` language detection.
- `deterministic-prefilter`: Rule-based pre-filtering for dealbreakers, excluded seniority titles/experience ceilings, posting freshness (discarding stale roles without storing them, with future application deadline and missing-timestamp safeguards), and location/work-mode eligibility.
- `local-state-store`: SQLite persistence layer for ingested postings and application tracking metadata, with `job_id`-based skip behavior, freshness-priority candidate ordering up to the daily cap, 6-month cleanup preserving `Interviewing` rows, and Postgres-compatible relational schema.

### Modified Capabilities
<!-- None — this is the initial foundational change in the repository. -->

## Impact

- **New codebase files:** `pyproject.toml`, `config/` example templates (`master_profile.example.yaml`, `target_roles.example.yaml`, `sources.example.yaml`), `src/job_agent/` package (`schemas/`, `sources/`, `filters/`, `storage/`, `cli.py`), and `tests/`.
- **Dependencies:** `pydantic>=2`, `pyyaml`, `httpx`, `feedparser`, `beautifulsoup4`, `langdetect`, `typer`, and dev dependencies `pytest`, `respx`, `mutmut`.
- **Downstream impact:** Establishes the validated contracts (`MasterProfile`, `JobPreferences`, `JobPosting`, and SQLite `jobs` rows) consumed by subsequent scoring, tailoring, Slack delivery, and Sheets sync changes.
