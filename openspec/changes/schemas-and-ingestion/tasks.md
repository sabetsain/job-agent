## 1. Project Setup

- [x] 1.1 Initialize `pyproject.toml` (Python 3.11+, dependencies: `pydantic>=2`, `pyyaml`, `httpx`, `feedparser`, `beautifulsoup4`, `langdetect`, `typer`, and dev dependencies: `pytest`, `respx`, `mutmut`) with `job-agent` CLI entrypoint and `mutmut` config targeting `src/job_agent/`
- [x] 1.2 Create package layout under `src/job_agent/` (`schemas/`, `sources/`, `filters/`, `storage/`, `cli.py`) and `tests/`
- [x] 1.3 Add example configuration files under `config/` (`master_profile.example.yaml`, `target_roles.example.yaml`, `sources.example.yaml`) and `.gitignore` (ignoring `data/*.db` and personal `config/*.yaml` overrides)

## 2. Domain Schemas & Config Loaders

- [x] 2.1 Implement Pydantic v2 `MasterProfile` schema and YAML loader in `src/job_agent/schemas/profile.py`
- [x] 2.2 Implement Pydantic v2 `JobPreferences` schema (including `SeniorityPolicy` excluding `Architect` from the blocklist and validating entry-level vs. stretch coverage, `FreshnessPolicy` with `max_age_days=21`, `preferred_age_days=7`, `daily_draft_limit=3` upper cap, location/work-mode rules, empty-default dealbreakers, scoring rubric, layout guardrails with `min_font_size_pt >= 9.0`, and required non-empty `voice_skill_path` defaulting to `.agent/skills/application-voice`) in `src/job_agent/schemas/preferences.py`
- [x] 2.3 Implement Pydantic v2 `SourcesConfig`, `RawJob`, and `JobPosting` (with `Literal["da", "en"]` language, optional `posted_at` & `application_deadline`, and `ApplicationStatus` enum) schemas in `src/job_agent/schemas/jobs.py`
- [x] 2.4 Add intent-rooted unit tests in `tests/test_schemas.py` covering valid YAML loading, `min_font_size_pt < 9.0` rejection, seniority tier coverage validation, `FreshnessPolicy` bounds, required `voice_skill_path`, `application_deadline`, and invalid language rejection

## 3. Job Discovery & Ingestion Adapters

- [x] 3.1 Implement canonical internal `job_id` generator (16-char SHA-256 hex prefix) and deterministic `da`/`en` language classifier (Danish character/lexical markers + seeded `langdetect` with `DetectorFactory.seed = 0`) in `src/job_agent/sources/normalize.py`
- [x] 3.2 Implement `JobSource` protocol/base class and HTML-to-text cleaner in `src/job_agent/sources/base.py`
- [x] 3.3 Implement free JSON API adapters in `src/job_agent/sources/` for Arbeitnow, Remotive, Himalayas (optional Bearer token), and Jobicy (`https://jobicy.com/api/jobs` with `>= 1s` spacing if paginated and `HTTP 429` + `Retry-After` handling)
- [x] 3.4 Implement Jobindex dynamic per-search public RSS adapter in `src/job_agent/sources/jobindex.py`
- [x] 3.5 Implement Manual Drop URL fetcher & raw-text normalizer (`src/job_agent/sources/manual.py`) with loud, user-visible failure reporting (non-zero exit + clear cause for HTTP 401/403, login redirects, CAPTCHA/anti-bot blocks, HTTP 404/5xx, timeouts, or unparseable descriptions)
- [x] 3.6 Implement once-daily ingestion orchestrator (`src/job_agent/sources/runner.py`) that loads enabled sources from `sources.yaml`, invokes each adapter once per run, isolates per-source failures, normalizes postings, assigns `job_id`, and detects `da`/`en` language
- [x] 3.7 Add intent-rooted unit tests in `tests/test_sources.py` using mocked HTTP/RSS fixtures covering adapter parsing, Jobicy `429`/`Retry-After`, partial source failure isolation, loud Manual Drop failure cases, `job_id` determinism, and Danish/English detection

## 4. Deterministic Pre-Filter Engine

- [x] 4.1 Implement seniority hard-gate filter (excluded title keywords in EN/DA — keeping `Architect` eligible — plus explicit years-of-experience ceiling regex) in `src/job_agent/filters/prefilter.py`
- [x] 4.2 Implement posting freshness filter (`max_age_days` cutoff with enforced future `application_deadline` pass-through, enforced `posted_at=None` pass-through, and enforced `source="manual"` bypass; stale postings marked for discard without storage) in `src/job_agent/filters/prefilter.py`
- [x] 4.3 Implement location & work-mode eligibility filter (Copenhagen/Denmark/EU + EU/CET-compatible remote; rejecting US-only or disallowed locations) in `src/job_agent/filters/prefilter.py`
- [x] 4.4 Implement dealbreaker negative filter (excluded companies, industries, contract types, red-flag keywords; clean pass-through when empty) and composite `PreFilterResult(passed, reason, discard_without_storing)`
- [x] 4.5 Add intent-rooted unit tests in `tests/test_prefilter.py` covering Senior/Staff/Lead rejections, Associate Solutions Architect pass-through, 5+ years rejection, entry-level/2-year pass-through, freshness boundaries (21 vs. 22 days discard, future deadline, missing `posted_at`, manual bypass), Copenhagen/EU-remote vs. US-only remote, and both empty-default and populated dealbreaker fixtures

## 5. SQLite State Store, Cleanup, CLI & Mutation Testing

- [x] 5.1 Implement `JobRepository` in `src/job_agent/storage/repository.py` with Postgres-compatible standard SQL schema initialization (including `application_deadline`, `cv_pdf_path`, `cover_letter_pdf_path`, `slack_thread_ts` — no Google Drive columns), `exists(job_id)`, `insert_job(...)`, `list_jobs(status, language)`, `list_prioritized_candidates(preferred_age_days, limit)` (cap, not quota), and `prune_old_jobs(retention_days=180)` preserving `Interviewing` rows
- [x] 5.2 Wire idempotent `job_id`-skip + pre-filter + stale-discard + persistence + 6-month cleanup pipeline in `src/job_agent/pipeline.py`
- [x] 5.3 Implement CLI commands in `src/job_agent/cli.py`: `job-agent ingest`, `job-agent add` (Manual Drop with loud error reporting & non-zero exit), and `job-agent list`
- [x] 5.4 Add intent-rooted integration tests in `tests/test_storage_and_cli.py` verifying idempotent re-ingestion skips, stale postings not stored, `Pending_Scoring` vs. `PreFiltered_Out` persistence, preferred-tier priority ordering & cap behavior (`< 3` roles), 6-month retention cleanup preserving `Interviewing`, Manual Drop success & loud CLI failure exit codes, and CLI output
- [ ] 5.5 Run `mutmut` mutation testing against core modules (`schemas/`, `filters/`, `sources/normalize.py`, `storage/`) and strengthen intent-rooted tests until behavioral mutants on all spec boundaries are killed
