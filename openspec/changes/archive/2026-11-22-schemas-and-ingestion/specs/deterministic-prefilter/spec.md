## ADDED Requirements

### Requirement: Hard seniority pre-filter gate
The system SHALL deterministically reject any job posting whose title contains an excluded seniority keyword from `JobPreferences.seniority_policy.excluded_title_keywords` (including `Senior`, `Sr.`, `Staff`, `Principal`, `Lead`, `Manager`, `Director`, `Head of`, `VP`, `Chief`, and Danish equivalents like `Seniorudvikler`, `Chef`, `Leder` — while NOT excluding `Architect` so roles such as Solutions Architect remain eligible) OR whose description explicitly mandates minimum years of experience strictly greater than `max_years_experience` (default `2`).

#### Scenario: Reject Senior Software Engineer by title
- **WHEN** a job posting titled "Senior Software Engineer" is evaluated by the pre-filter
- **THEN** the pre-filter MUST return `passed=False` with a structured rejection reason referencing the matched seniority keyword

#### Scenario: Allow Associate or Junior Solutions Architect by title
- **WHEN** a job posting titled "Associate Solutions Architect" satisfies freshness, location, and dealbreaker rules
- **THEN** the pre-filter SHALL return `passed=True`

#### Scenario: Reject role requiring 5+ years of experience
- **WHEN** a job posting titled "Backend Developer" states "Minimum 5+ years of experience in Python" and `max_years_experience` is `2`
- **THEN** the pre-filter MUST return `passed=False` with a structured rejection reason referencing the experience ceiling

#### Scenario: Allow Entry-Level or 2-year role through to LLM scoring
- **WHEN** a job posting titled "Junior Software Engineer" or requiring "2 years of experience" satisfies freshness, location, and dealbreaker rules
- **THEN** the pre-filter SHALL return `passed=True` so downstream scoring can evaluate conditional skill coverage

### Requirement: Posting freshness pre-filter with enforced deadline, discard, and missing-timestamp safeguards
The system SHALL deterministically reject discovered postings whose `posted_at` timestamp is older than `JobPreferences.freshness_policy.max_age_days` (default `21`), and postings rejected for staleness MUST be discarded without being stored in SQLite. Exceptions:
- postings with an explicit `application_deadline` in the future MUST pass the freshness gate,
- postings where `posted_at` is `None` MUST pass the freshness gate (never silently dropped; preserved as `posted_at=None` so downstream agent logic can flag it to the user),
- user-submitted Manual Drop postings (`source="manual"`) MUST bypass the freshness cutoff.

#### Scenario: Reject and discard stale posting older than max_age_days without future deadline
- **WHEN** a discovered posting has `posted_at` 22 days ago, `application_deadline=None`, and `max_age_days=21`
- **THEN** the pre-filter MUST return `passed=False` with a freshness rejection reason and the pipeline MUST NOT store the posting in SQLite

#### Scenario: Accept older posting with a future application deadline
- **WHEN** a discovered posting has `posted_at` 25 days ago and an `application_deadline` 5 days in the future
- **THEN** the freshness pre-filter SHALL pass

#### Scenario: Enforced pass-through when posted_at is missing
- **WHEN** a discovered posting has `posted_at=None` and `application_deadline=None`
- **THEN** the freshness pre-filter MUST return `passed=True` (assuming other filters pass)

#### Scenario: User-submitted manual drop bypasses freshness cutoff
- **WHEN** a user-submitted posting (`source="manual"`) has `posted_at` 30 days ago and `application_deadline=None`
- **THEN** the freshness pre-filter MUST bypass the age cutoff and return `passed=True` (assuming other filters pass)

### Requirement: Location and work-mode pre-filter
The system SHALL deterministically verify that each posting matches at least one allowed location/region (e.g., Copenhagen, Denmark, EU) or an allowed remote work mode compatible with the configured timezone/region constraints.

#### Scenario: Accept Copenhagen on-site or hybrid role
- **WHEN** a posting is located in "Copenhagen, Denmark" (or "København") with work mode `hybrid` or `onsite`
- **THEN** the location pre-filter SHALL pass

#### Scenario: Accept Europe-compatible remote role
- **WHEN** a posting is marked `remote` with allowed region "Europe", "EU", "EMEA", or "Worldwide"
- **THEN** the location pre-filter SHALL pass

#### Scenario: Reject US-only remote or non-allowed city role
- **WHEN** a posting is marked "Remote (US Only)" or "On-site — San Francisco, CA"
- **THEN** the pre-filter MUST return `passed=False` with a location/work-mode rejection reason

### Requirement: Dealbreaker negative filter
The system SHALL deterministically reject any posting matching configured dealbreakers in `JobPreferences` (excluded companies, excluded industries, excluded contract types, or red-flag keywords). When dealbreaker lists are empty (default), no postings SHALL be rejected by this filter.

#### Scenario: Reject posting from an excluded company or keyword
- **WHEN** `JobPreferences.dealbreakers` is configured with an excluded company or red-flag keyword and a posting matches it
- **THEN** the pre-filter MUST return `passed=False` with the matched dealbreaker recorded as the rejection reason

#### Scenario: Pass posting cleanly when dealbreaker lists are empty
- **WHEN** `JobPreferences.dealbreakers` contains empty lists
- **THEN** the dealbreaker filter SHALL return `passed=True`
