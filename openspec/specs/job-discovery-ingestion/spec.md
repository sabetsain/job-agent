# Job Discovery Ingestion

## Purpose

Defines the pluggable `JobSource` adapter interface, once-daily free/open discovery adapters for Copenhagen (EU) and Remote roles, Manual Drop URL/text submission with loud failure reporting, canonical internal `job_id` generation, and deterministic `da`/`en` language detection.

## Requirements

### Requirement: Pluggable JobSource adapter interface for once-daily ingestion
The system SHALL define a `JobSource` interface (`name: str`, `fetch(config) -> list[RawJob]`) driven by `config/sources.yaml`. Automated discovery SHALL execute as a single scheduled pass once per day — iterating through each enabled `JobSource` adapter once, storing new passing jobs in SQLite, and avoiding repeated polling — and MUST isolate per-source network or parsing failures so one failing board does not abort other enabled sources.

#### Scenario: Single source failure does not abort ingestion
- **WHEN** one enabled discovery source returns an HTTP 500 error or times out while another enabled source returns valid postings
- **THEN** the ingestion runner SHALL log the failure for the broken source and still ingest all postings from the healthy source

### Requirement: Free and open Copenhagen, Europe, and Remote discovery adapters
The system SHALL implement free, unauthenticated `JobSource` adapters designed for once-daily polling while respecting documented provider contracts:
- **Arbeitnow** (`https://www.arbeitnow.com/api/job-board-api`),
- **Remotive** (`https://remotive.com/api/remote-jobs`, single call per daily run complying with `<= 2 req/min` and `<= 4 polls/day` guidelines),
- **Himalayas** (`https://himalayas.app/jobs/api` or `/search`, supporting optional free `Authorization: Bearer` token if configured),
- **Jobicy** (`https://jobicy.com/api/jobs`, supporting `count`/`geo`/`industry`/`tag`, enforcing `>= 1s` spacing if paginated and honoring `HTTP 429` + `Retry-After`),
- **Jobindex** dynamic per-search public RSS feed URL(s) configured in `sources.yaml`.

#### Scenario: Fetch and normalize postings from a JSON API adapter
- **WHEN** an enabled JSON adapter (Arbeitnow, Remotive, Himalayas, or Jobicy) returns a valid response payload
- **THEN** the adapter SHALL strip HTML tags into clean plain text descriptions and map each item into a normalized `RawJob` with title, company, location, work mode, apply URL, and `posted_at` (when present)

#### Scenario: Fetch and normalize postings from Jobindex RSS
- **WHEN** the Jobindex RSS adapter parses a configured Jobindex search RSS feed URL from `sources.yaml`
- **THEN** it SHALL extract title, company (when present), summary/description, publication timestamp, optional application deadline (when present), and link into normalized `RawJob` records

#### Scenario: Respect HTTP 429 Retry-After on rate-limited endpoints
- **WHEN** the Jobicy adapter receives an HTTP 429 response with a `Retry-After` header
- **THEN** it SHALL honor the retry delay (within bounded retries) or fail gracefully with a structured warning without aborting other sources

### Requirement: Manual Drop job ingestion with loud failure reporting
The system SHALL provide a CLI command (`job-agent add`) allowing the user to manually submit a job posting (`source="manual"`) by supplying either raw description text (via flag, file, or stdin) or a direct URL. When fetching a URL, if the request is blocked by an authentication/login wall (HTTP 401/403 or login redirect), an anti-bot/CAPTCHA interstitial, HTTP 404/5xx, a network timeout, or yields an empty/unparseable job description, the command MUST fail loudly with a non-zero exit code, print a clear user-visible explanation of why access failed, suggest providing the raw JD text instead, and MUST NOT persist an incomplete record.

#### Scenario: Manually add a job from raw text
- **WHEN** the user runs `job-agent add` with title, company, apply URL, and a raw job description (via flag or file/stdin)
- **THEN** the system SHALL normalize it with `source="manual"`, assign an internal `job_id`, detect its language, run pre-filtering (bypassing the freshness cutoff), and persist it in SQLite

#### Scenario: Fail loudly when a manual drop URL is auth-gated or blocked
- **WHEN** the user runs `job-agent add` with a URL that returns HTTP 401/403, redirects to a login page, or presents a CAPTCHA/anti-bot block
- **THEN** the CLI MUST exit with a non-zero status code, display a clear error message stating that the link is blocked/auth-gated and suggesting raw text input, and MUST NOT write a row to SQLite

#### Scenario: Fail loudly when a manual drop URL cannot be parsed into a job description
- **WHEN** the user runs `job-agent add` with a URL whose HTML yields an empty or unparseable description
- **THEN** the CLI MUST exit with a non-zero status code, report that the job description could not be extracted from the link, and MUST NOT write a row to SQLite

### Requirement: Deterministic internal job_id assignment
The system SHALL generate a deterministic internal `job_id` in Python (16-character SHA-256 hex prefix) from normalized `(source, canonical_url)` when a URL is present, or `(source, normalized_company, normalized_title)` otherwise, and MUST NOT require external board IDs or a separate fuzzy deduplication subsystem.

#### Scenario: Same posting ingested twice produces the same job_id
- **WHEN** the same source returns the same job posting URL across two separate ingestion runs
- **THEN** the system SHALL compute the identical `job_id` both times

### Requirement: Deterministic Danish and English language detection
The system SHALL classify each ingested posting as Danish (`"da"`) or English (`"en"`) deterministically by combining explicit Danish lexical/character markers (`æ`, `ø`, `å` plus common Danish function/job words such as `og`, `til`, `med`, `erfaring`, `søger`, `stilling`) with a fixed-seed `langdetect` Naive Bayes character n-gram classifier (`DetectorFactory.seed = 0`), falling back to `"en"` on short or ambiguous text.

#### Scenario: Detect Danish job posting
- **WHEN** an ingested job posting has a Danish title and description (e.g., "Softwareudvikler til vores team i København — erfaring med Python og samarbejde")
- **THEN** the system SHALL assign `language="da"` identically across repeated runs

#### Scenario: Detect English job posting
- **WHEN** an ingested job posting has an English title and description
- **THEN** the system SHALL assign `language="en"` identically across repeated runs
