# job-agent

A personal job-hunting and application co-pilot built for finding entry-level roles in Copenhagen, Europe, and Remote positions. It discovers postings, filters out poor matches before spending LLM tokens, and supports truthful, tailored applications in both Danish and English while keeping me in control of review and submission.

The guiding principles, eligibility rules, and full co-pilot workflows live in [`docs/INTENT.md`](docs/INTENT.md).

## What Works Today

- **Domain Schemas (`src/job_agent/schemas/`):** Pydantic v2 models (`MasterProfile`, `JobPreferences`, `SourcesConfig`, `RawJob`, and `JobPosting`) loaded from YAML. These enforce seniority rules (targeting entry-level roles and excluding Senior+ titles while keeping Architect roles eligible), freshness bounds (`max_age_days=21`, `preferred_age_days=7`, `daily_draft_limit=3`), readable layout limits (`min_font_size_pt >= 9.0`), and the `.agent/skills/application-voice` skill path.
- **Job Discovery (`src/job_agent/sources/`):** Pluggable `JobSource` adapters built for once-daily polling across Arbeitnow, Remotive, Himalayas, Jobicy, and Jobindex RSS, with isolated error handling per source. Also supports manual additions via `job-agent add` using raw text (`--text`, `--file`, stdin) or direct URLs, failing loudly if a page is blocked, behind auth, or unparseable. Each job gets a canonical 16-character SHA-256 `job_id` and deterministic Danish or English (`da`/`en`) language classification.
- **Pre-Filtering (`src/job_agent/filters/`):** Drops Senior+ roles, postings asking for more than 2 years of experience, disallowed locations or work modes, configured dealbreakers, and stale postings older than `max_age_days` before any LLM call runs. Postings with a future `application_deadline` (*ansøgningsfrist*), missing `posted_at`, or manual submissions are preserved.
- **SQLite State Store & CLI (`src/job_agent/storage/`, `src/job_agent/cli.py`):** A Postgres-portable `JobRepository` that tracks application status, skips already-seen `job_id`s, prioritizes postings from the last 7 days or with future deadlines up to the daily cap, and cleans up entries older than 180 days while keeping `Interviewing` rows intact.

## Quickstart

### 1. Install Dependencies

Requires Python 3.11+ and [`uv`](https://docs.astral.sh/uv/):

```bash
uv sync --extra dev
```

### 2. Configure Profile, Preferences & Sources

Copy the example YAML templates into personal config files (these are gitignored):

```bash
cp config/master_profile.example.yaml config/master_profile.yaml
cp config/target_roles.example.yaml config/target_roles.yaml
cp config/sources.example.yaml config/sources.yaml
```

Fill in `config/target_roles.yaml` and `config/sources.yaml` (for example, add filtered Jobindex RSS feed URLs under `jobindex_rss.feed_urls`).

### 3. Run the CLI

```bash
# Run daily discovery, pre-filtering, persistence, and 180-day cleanup
.venv/bin/job-agent ingest

# Manually add a job from raw text
.venv/bin/job-agent add \
  --title "Junior Software Engineer" \
  --company "Nordic Cloud" \
  --location "Copenhagen, Denmark" \
  --work-mode hybrid \
  --text "Entry-level Python and SQL role in Copenhagen."

# Manually add a job from a direct URL (fails loudly if auth-gated or unparseable)
.venv/bin/job-agent add --url "https://example.com/careers/junior-engineer"

# Inspect stored jobs filtered by status or language
.venv/bin/job-agent list --status Pending_Scoring --language en
```

## Testing

Run the test suite:

```bash
.venv/bin/pytest -v
```

Run mutation testing on the core modules (`schemas/`, `filters/`, `sources/normalize.py`, `storage/`):

```bash
.venv/bin/mutmut run
.venv/bin/mutmut results
```

## Repository Layout

- `docs/INTENT.md`: Living intent document covering project scope, principles, and workflows.
- `AGENTS.md`: Project agent and git worktree workflow rules.
- `.agent/skills/application-voice/`: Embedded Voice DNA and anti-AI rules for CVs and cover letters.
- `openspec/`: OpenSpec configuration, specs, designs, and task checklists.
- `config/`: Example YAML templates (`*.example.yaml`).
- `src/job_agent/`: Core Python package (`schemas/`, `sources/`, `filters/`, `storage/`, `pipeline.py`, `cli.py`).
- `tests/`: Unit and integration tests.
