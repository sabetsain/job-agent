## Context

This is the first foundational OpenSpec change for `job-agent`, a personal job-hunting and application co-pilot primarily targeting **entry-level roles** in **Copenhagen, Denmark (Europe)** and **Remote** positions, as defined in `docs/INTENT.md`.

This change establishes the deterministic data contracts, once-daily free/open discovery ingestion pipeline, rule-based pre-filtering, and SQLite persistence layer that downstream changes build upon.

## Goals / Non-Goals

**Goals:**
- Define strict, version-controllable Pydantic v2 schemas and YAML loaders for `MasterProfile`, `JobPreferences`, `SourcesConfig`, and `JobPosting`.
- Encode the tiered seniority & eligibility policy (primarily entry-level roles, hard-rejecting Senior+ roles while keeping `Architect` roles eligible, defining entry-level vs. 2-year stretch skill-coverage thresholds), posting freshness & `daily_draft_limit` upper-cap (default `3`, never a quota) priority rules, layout guardrails (`min_font_size_pt >= 9`, preserve whitespace/margins), and required `voice_skill_path` (default `.agent/skills/application-voice`, enforcing that the writer agent MUST use `/application-voice`) directly in `JobPreferences`.
- Build a pluggable `JobSource` adapter interface executed in a single scheduled pass once per day across free, unauthenticated adapters for Copenhagen/EU + Remote (**Arbeitnow**, **Remotive**, **Himalayas**, **Jobicy**, **Jobindex RSS**) plus a **Manual Drop** CLI path with loud, user-visible failure reporting when a URL is auth-gated, blocked, or unparseable.
- Assign a deterministic internal `job_id` in Python (skipping already-recorded `job_id`s without a separate fuzzy deduplication engine) and detect job language (`da` or `en`).
- Run deterministic pre-filtering (dealbreakers, excluded seniority titles/experience ceilings, posting freshness — discarding stale postings without storing them — and location/work-mode rules) before any LLM scoring occurs.
- Persist ingested postings and application lifecycle rows in a local SQLite database (no Google Drive storage; Slack PDF delivery serves as final document storage) with automatic 6-month cleanup that preserves `Interviewing` rows, designed to migrate cleanly to Cloud SQL Postgres later.
- Deliver thorough, intent-rooted tests grounded in the OpenSpec scenarios and `docs/INTENT.md`, verified with mutation testing so behavioral changes to targeted code reliably fail tests.

**Non-Goals:**
- LLM fit scoring, OpenCode Go wiring, LangGraph tailoring/auditing, or LaTeX compilation.
- Google Sheets sync or Google Drive storage (Slack PDF delivery replaces Google Drive).
- Slack bot ideation/review loop, Gmail polling, Google Calendar sync, or weekly check-ins.
- Fragile web scraping, headless browser automation, or paid/authenticated job board APIs.
- Separate fuzzy cross-board deduplication subsystem (rely solely on canonical internal `job_id`).

## Decisions

1. **Hybrid Storage: YAML for Config/Profile + SQLite for Operational State (No Google Drive)**
   - *Decision:* Store `MasterProfile`, `JobPreferences`, and `SourcesConfig` as Git-tracked YAML files loaded via Pydantic v2; store ingested jobs and application lifecycle records in SQLite (`data/job_agent.db`). Require a non-empty `voice_skill_path` in `JobPreferences` (defaulting to `.agent/skills/application-voice`) so downstream writer nodes load and enforce the `/application-voice` skill. Omit Google Drive columns; store local/Slack PDF references (`cv_pdf_path`, `cover_letter_pdf_path`, `slack_thread_ts`) since Slack PDF delivery is sufficient final storage.
   - *Rationale:* Nested career history is brittle in spreadsheets and cleaner in YAML. Removing Google Drive eliminates an unnecessary OAuth scope and folder-management surface. SQLite provides ACID local state and matches Cloud SQL Postgres for cloud deployment.

2. **Once-Daily `JobSource` Pass with Upfront-Verified Free API & RSS Contracts**
   - *Decision:* Define a `JobSource` protocol (`name: str`, `fetch(config) -> list[RawJob]`) configured via `config/sources.yaml`. Ingestion runs as a **single scheduled pass once per day**, iterating through each enabled adapter once, storing new passing jobs in SQLite, and avoiding constant agent wakeups. Documented provider contracts:
     - **Arbeitnow** (`https://www.arbeitnow.com/api/job-board-api`): Public JSON, no key; once-daily call complies with polite polling.
     - **Remotive** (`https://remotive.com/api/remote-jobs`): Public JSON, no key. **Documented limit:** $> 2$ req/min blocked; recommends max 4 polls/day — naturally satisfied by once-daily ingestion.
     - **Himalayas** (`https://himalayas.app/jobs/api` and `/search`): Public JSON, works unauthenticated (optional free `Authorization: Bearer` key supports 60 req/min & 10k req/day).
     - **Jobicy** (`https://jobicy.com/api/jobs`): Public JSON, no key, supports `count`, `geo`, `industry`, `tag`. **Documented limit:** $\ge 1$ second delay between requests (if paginated); honors `HTTP 429` + `Retry-After` header.
     - **Jobindex RSS**: Dynamic RSS URLs derived from any filtered `jobindex.dk` search page (`<link rel="alternate" type="application/rss+xml">`), configured as a list of feed URLs in `sources.yaml`. Covers general Danish job listings across all industries.
   - *Rationale:* A single daily pass naturally respects provider rate limits and prevents unnecessary wakeups, while each adapter still isolates HTTP/schema errors gracefully.

3. **Loud, User-Visible Manual Drop Failure Handling**
   - *Decision:* When `job-agent add` is given a URL (rather than raw text), attempt a single polite HTTP fetch + static HTML extraction. If the fetch encounters HTTP 401/403, a login/auth-wall redirect, a CAPTCHA/anti-bot interstitial, HTTP 404/5xx, a network timeout, or an empty/unparseable job description, abort ingestion with a **non-zero exit code** and a loud, explicit user-facing error explaining the detected cause (e.g., *"Blocked by login/auth gate (HTTP 403)"* or *"Could not extract job description from page"*) and instructing the user to paste the raw JD text instead. Never silently swallow failures or persist empty descriptions.
   - *Rationale:* Aligns with the co-pilot principle of zero fragile scraping and transparent handoff.

4. **Deterministic Internal `job_id` Only (No Fuzzy Deduplication)**
   - *Decision:* Generate `job_id` deterministically as a short SHA-256 hex prefix (16 chars) derived from normalized `(source, canonical_url)` when `canonical_url` is present, or `(source, normalized_company, normalized_title)` for raw text manual drops. On ingestion, if `job_id` already exists in SQLite, skip it.
   - *Rationale:* Simple, predictable, idempotent across daily polls, and avoids maintaining heuristic cross-board matching rules.

5. **Deterministic Language Classifier (`da` / `en`) at Ingestion Time**
   - *Decision:* Combine cleaned `title + description` text and classify as `"da"` or `"en"` using a deterministic two-step heuristic + seeded Naive Bayes n-gram classifier:
     1. Check explicit Danish signals: presence of Danish-specific characters (`æ`, `ø`, `å`) combined with high-frequency Danish function/job words (`og`, `til`, `med`, `erfaring`, `søger`, `stilling`, `arbejde`). If clear Danish lexical density is present, classify as `"da"` (preventing misclassification when English tech keywords dominate a Danish posting).
     2. Otherwise run `langdetect` with `DetectorFactory.seed = 0` (locking its internal PRNG so identical inputs always produce identical results); map `"da"` $\rightarrow$ `"da"` and fall back to `"en"` for English or short/ambiguous inputs.
   - *Rationale:* Reproducible across runs and resilient to mixed Danish/English tech postings on Danish boards like Jobindex.

6. **Two-Layer Seniority Policy (Deterministic Hard Gate + Structured Policy for Downstream Scorer)**
   - *Decision:* Model `SeniorityPolicy` in `JobPreferences` with:
     - `excluded_title_keywords` (e.g., `senior`, `sr.`, `staff`, `principal`, `lead`, `manager`, `director`, `head of`, `vp`, `chief`, plus Danish equivalents like `seniorudvikler`, `chef`, `leder`) — explicitly **excluding `architect`** from the blocklist so roles like *Solutions Architect* remain eligible. Enforced deterministically in pre-filter.
     - `max_years_experience` (default `2`) — deterministic regex check for explicit high minimums (e.g., `5+ years`, `3+ års erfaring`) in pre-filter.
     - `entry_level` tier (primary target: `max_years: 1`, `min_must_have_coverage: 0.65`) and `stretch` tier (`max_years: 2`, `min_must_have_coverage: 0.95`) — validated in schema here and enforced by downstream fit scoring.
   - *Rationale:* Prevents wasting LLM tokens on clearly Senior+ roles while preserving nuanced conditional logic for entry-level and 2-year stretch roles, and keeping associate/junior Solutions Architect roles open.

7. **Posting Freshness Policy, Application Deadline Priority & Daily Draft Cap**
   - *Decision:* Model `FreshnessPolicy` in `JobPreferences` with `max_age_days` (default `21`), `preferred_age_days` (default `7`), and `daily_draft_limit` (default `3`, strictly an **upper cap, never a quota**). Include optional `application_deadline` on `JobPosting`.
     - **Enforced pre-filter rules:**
       - Postings whose `posted_at` is older than `max_age_days` without a future `application_deadline` MUST fail freshness pre-filtering and **MUST NOT be stored in SQLite** (discarded immediately).
       - **Enforced missing-timestamp safeguard:** Postings with `posted_at=None` MUST pass the freshness gate (never silently dropped); downstream agent logic will flag missing `posted_at` to the user.
       - **Enforced Manual Drop bypass:** Postings submitted by the user (`source="manual"`) MUST bypass the freshness cutoff.
     - **Priority ordering for daily drafting cap (`daily_draft_limit`):** The system still discovers, filters, and evaluates *all* eligible postings, and caps application drafting to **at most** `daily_draft_limit` (3) per day — if 0, 1, or 2 roles qualify, only those are drafted. Postings with `posted_at` within `preferred_age_days` (7 days) **or** with a future `application_deadline` (supporting Danish *ansøgningsfrist* listings) share the **preferred priority tier**; older eligible postings (8–21 days) are only selected when no un-drafted/un-applied preferred-tier postings remain.
   - *Rationale:* Gives `preferred_age_days` concrete behavioral meaning, avoids cluttering SQLite with stale listings, avoids forcing low-quality drafts to hit a quota, and treats active-deadline Nordic postings as first-class priorities.

8. **SQLite Repository Abstraction & 6-Month Retention Cleanup**
   - *Decision:* Encapsulate all database queries in a `JobRepository` class using standard SQL (Postgres-portable). Provide `prune_old_jobs(retention_days=180)` invoked automatically during `job-agent ingest` (and callable standalone) to delete rows ingested more than 180 days (~6 months) ago, **except** rows with `status == "Interviewing"`, which MUST always be preserved.
   - *Rationale:* Keeps local and future cloud databases clean with minimal logic while protecting active interview history.

9. **Intent-Rooted Testing & Mutation Testing**
   - *Decision:* Structure `tests/` directly around the scenarios in `specs/` and `docs/INTENT.md`, and configure mutation testing (`mutmut`) targeting core business logic (`schemas/`, `filters/`, `sources/normalize.py`, `storage/`). Because default `dealbreakers` starts empty in user config, pre-filter tests SHALL test both empty-default pass-through and synthetic populated dealbreaker fixtures. Every requirement's boundary conditions MUST kill mutants when logic is altered.
   - *Rationale:* Ensures tests verify real behavioral guarantees rooted in user intent rather than merely achieving line coverage.

## Risks / Trade-offs

- **[Risk] Jobindex RSS descriptions may be partial summaries rather than full JDs** $\rightarrow$ Mitigation: Store `description` as provided and mark `description_is_partial` metadata if length is below a threshold, allowing optional static-page HTML extraction (no browser/JS scraping) or manual enrichment if needed.
- **[Risk] Deterministic regex for years-of-experience can misread non-requirement numbers (e.g., "company founded 10 years ago")** $\rightarrow$ Mitigation: Match only explicit experience patterns (e.g., `\b(\d+)\+?\s*(?:years?|yrs?|år|års)\s+(?:of\s+)?(?:experience|erfaring)`), and err on the side of letting ambiguous postings pass to downstream LLM verification.
- **[Risk] Upstream free APIs may still change response fields or experience transient outages despite upfront verification** $\rightarrow$ Mitigation: Each `JobSource` adapter isolates HTTP/schema errors, logs a structured warning, respects `Retry-After` on HTTP 429, and fails gracefully so one broken board never aborts other enabled sources.
- **[Risk] `langdetect` can be noisy on very short or mixed Danish/English tech postings** $\rightarrow$ Mitigation: Combine explicit Danish character/lexical signals (`æ`, `ø`, `å` + Danish function words) with seeded `langdetect` (`DetectorFactory.seed = 0`).
