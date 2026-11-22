# job-agent

A deterministic-first, bilingual (`da`/`en`) personal job-hunting and application co-pilot targeting entry-level roles in **Copenhagen, Denmark (Europe)** and **Remote** positions.

> **Living Source of Truth:** See [`docs/INTENT.md`](docs/INTENT.md) for the project's guiding principles, eligibility rules, and co-pilot workflows.

## Current Capabilities (`schemas-and-ingestion`)

- **Validated Domain Schemas (`src/job_agent/schemas/`):**
  - `MasterProfile`, `JobPreferences`, `SourcesConfig`, `RawJob`, and `JobPosting` validated with Pydantic v2 and loaded from YAML.
  - Encodes tiered seniority rules (primarily entry-level, hard-excluding Senior+ titles while keeping *Architect* roles eligible), posting freshness bounds (`max_age_days=21`, `preferred_age_days=7`, `daily_draft_limit=3` upper cap), design-preserving layout guardrails (`min_font_size_pt >= 9.0`), and the required `/application-voice` skill path (`.agent/skills/application-voice`).
- **Free & Open Job Discovery (`src/job_agent/sources/`):**
  - Pluggable `JobSource` adapters designed for once-daily polling across **Arbeitnow**, **Remotive**, **Himalayas**, **Jobicy**, and **Jobindex RSS**, with isolated per-source error handling.
  - **Manual Drop (`job-agent add`)** supporting raw text (`--text`, `--file`, stdin) or direct URLs, failing loudly with a clear user-facing error if blocked, auth-gated, or unparseable.
  - Deterministic canonical `job_id` generation (16-char SHA-256 hex prefix) and deterministic Danish/English (`da`/`en`) language classification.
- **Deterministic Pre-Filter (`src/job_agent/filters/`):**
  - Filters out Senior+ roles, explicit `> 2` years experience requirements, stale postings older than `max_age_days` (discarded without storing, while preserving future `application_deadline` *ansøgningsfrist* roles, missing `posted_at`, and `manual` submissions), disallowed locations/work modes, and configured dealbreakers before any LLM tokens are spent.
- **Local SQLite State Store & CLI (`src/job_agent/storage/`, `src/job_agent/cli.py`):**
  - Postgres-portable `JobRepository` tracking application lifecycle, freshness-priority candidate ordering (prioritizing `<= 7`-day and future-deadline postings up to the daily cap), idempotent `job_id` skipping, and automatic 6-month (`180`-day) cleanup that preserves `Interviewing` rows.

## Quickstart

### 1. Install Dependencies

Requires Python 3.11+ and [`uv`](https://docs.astral.sh/uv/):

```bash
uv sync --extra dev
```

### 2. Configure Your Profile, Preferences & Sources

Copy the example YAML templates into personal config files (gitignored automatically):

```bash
cp config/master_profile.example.yaml config/master_profile.yaml
cp config/target_roles.example.yaml config/target_roles.yaml
cp config/sources.example.yaml config/sources.yaml
```

Edit `config/target_roles.yaml` and `config/sources.yaml` (e.g., add your filtered Jobindex RSS feed URLs under `jobindex_rss.feed_urls`).

### 3. Run the CLI

```bash
# Run once-daily discovery, pre-filtering, persistence, and 180-day cleanup
.venv/bin/job-agent ingest

# Manually add a job from raw text
.venv/bin/job-agent add \
  --title "Junior Software Engineer" \
  --company "Nordic Cloud" \
  --location "Copenhagen, Denmark" \
  --work-mode hybrid \
  --text "Entry-level Python and SQL role in Copenhagen."

# Or manually add a job from a direct URL (fails loudly if auth-gated or unparseable)
.venv/bin/job-agent add --url "https://example.com/careers/junior-engineer"

# Inspect stored jobs filtered by status or language
.venv/bin/job-agent list --status Pending_Scoring --language en
```

## Testing

Run the full intent-rooted test suite:

```bash
.venv/bin/pytest -v
```

Run mutation testing against core modules (`schemas/`, `filters/`, `sources/normalize.py`, `storage/`):

```bash
.venv/bin/mutmut run
.venv/bin/mutmut results
```

## Repository Layout

- `docs/INTENT.md` — Living intent document (non-technical source of truth)
- `AGENTS.md` — Project agent & git worktree workflow rules
- `openspec/` — OpenSpec configuration, specs, designs, and task checklists
- `config/` — Example YAML templates (`*.example.yaml`)
- `src/job_agent/` — Core Python package (`schemas/`, `sources/`, `filters/`, `storage/`, `pipeline.py`, `cli.py`)
- `tests/` — Intent-rooted unit and integration tests
