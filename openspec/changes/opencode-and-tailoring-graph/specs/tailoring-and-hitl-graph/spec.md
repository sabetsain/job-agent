## ADDED Requirements

### Requirement: Persistent LangGraph tailoring workflow with SQLite checkpointing and explicit major-gap criteria
The system SHALL implement Stage 2 document tailoring as a LangGraph `StateGraph` (`Planner -> Writer -> Deterministic Auditor -> LLM Auditor -> Compiler -> Human Review Interrupt`) persisted via `SqliteSaver` (portable to `PostgresSaver`) and keyed by `langgraph_thread_id` stored on the job row, using `reasoning_model` for planning, writing, auditing, and ideation. Each run SHALL produce structured `TailoredCV` and `TailoredCoverLetter` models in `posting.language` (`"da"` or `"en"`), surfacing transferable skills honestly and listing only **major** unaddressed gaps alongside the draft.
A **major unaddressed gap** is defined as a core, primary requirement explicitly emphasized as mandatory in the job posting that has **neither** a direct match **nor** a closely transferable equivalent in `MasterProfile` (e.g., a primary programming language, core engineering paradigm such as embedded C++ or native iOS, required certification/clearance, or mandatory spoken language). Secondary/nice-to-have tools, specific SaaS utilities (e.g., Jira, Datadog, Linear), or swappable library/tool variants where the candidate holds transferable foundations MUST NOT be flagged as major gaps.

#### Scenario: Draft and checkpoint a queued job through to Pending_Review
- **WHEN** the tailoring graph executes for a `Queued_For_Drafting` job and passes auditing and compilation
- **THEN** it SHALL persist `langgraph_thread_id`, `cv_pdf_path`, and `cover_letter_pdf_path` in SQLite, transition the job to `Pending_Review`, emit a review-ready summary, and pause at the Human Review interrupt

#### Scenario: Resume an interrupted job thread across process restarts
- **WHEN** the user later opens review for the same `job_id` in a new process
- **THEN** the graph SHALL restore the full conversation state, previous draft, ideation notes, and `session_verified_facts` from the SQLite checkpointer

### Requirement: Two-pass auditing with surgical violation diagnostics and blader/humanizer LLM pass
After the Writer produces structured CV and Cover Letter content, the graph SHALL run two sequential audit passes:
1. **Pass 1 — Deterministic Python Gate (0 tokens):** MUST reject drafts containing em-dashes (`—`, `--`), English contractions in English cover letters (`language == "en"`), banned AI cliché phrases, cover letter word counts outside the target single-page range (~250–380 words), missing or wrong language sign-offs (`Kind Regards,` for `en`; `Med venlig hilsen,` for `da`), more than one `!` on the closing line, leftover placeholder tokens (`{{...}}`, `[Company]`), or CV company/title/date anchors absent from `MasterProfile` (plus `session_verified_facts`). If Pass 1 fails, the graph MUST route back to the Writer without calling the LLM Auditor.
2. **Pass 2 — Reasoning LLM Auditor (`reasoning_model`):** SHALL audit semantic truthfulness against `MasterProfile` + `session_verified_facts`, honest transferability framing, Danish naturalness (when `language == "da"`), major-only gap discipline, and AI-tell detection using `blader/humanizer` rules encoded in `prompts/auditor.md`.
Both Pass 1 and Pass 2 MUST return structured `AuditViolation` diagnostics specifying `document` (`"cv"` or `"cover_letter"`), `location` (exact section, paragraph, or bullet index), `rule`, `offending_snippet`, and `fix_instruction`, so the Writer receives exact failure locations and concrete fixes with minimal guesswork.

#### Scenario: Deterministic Python gate catches AI tells with exact location before calling LLM Auditor
- **WHEN** a Writer draft contains an em-dash, an English contraction ("I'm"), a banned cliché ("I am writing to apply for"), or a fabricated company name
- **THEN** Pass 1 MUST fail with structured `AuditViolation` items identifying the exact document, section/paragraph, offending snippet, and fix instruction, and route back to the Writer without invoking the LLM Auditor

#### Scenario: Deterministic Python gate verified against full multi-paragraph EN/DA and obviously-AI fixtures
- **WHEN** the test suite and `mutmut` mutation testing execute against the deterministic auditor
- **THEN** full multi-paragraph "obviously AI" CV and cover letter fixtures MUST trigger every mechanical rule and clean authentic EN/DA fixtures MUST pass cleanly

#### Scenario: LLM Auditor runs only after Pass 1 succeeds
- **WHEN** Pass 1 succeeds on a draft
- **THEN** the graph SHALL invoke the LLM Auditor (`reasoning_model` with `prompts/auditor.md`) and return structured `AuditViolation` items if any semantic truthfulness, transferability, Danish naturalness, or `blader/humanizer` check fails

### Requirement: Bounded max-2 internal self-correction passes with mandatory compilation and loud progress feedback
The graph SHALL emit an explicit user-visible progress message (e.g., `"Workshopping now..."`) via an injectable status callback whenever drafting or user-triggered `re-iterate` begins, so the human always knows work is actively underway before the graph pauses at the Human Review interrupt. Within each generation or `re-iterate` cycle, the internal self-correction loop (Deterministic Auditor failure, LLM Auditor failure, or Compiler page overflow routing back to the Writer) SHALL be capped at **at most 2 internal retry passes**. When the second internal pass completes, the graph MUST ALWAYS send the output to the Compiler so compiled PDFs and any remaining warnings are delivered to the human at the Human Review interrupt. The outer human ideation and re-iteration loop SHALL be unbounded, resetting `internal_retry_count = 0` on each user-triggered `re-iterate`.

#### Scenario: Loud progress message emitted before active drafting or re-iteration
- **WHEN** the graph begins drafting a queued job or resumes on a `REITERATE` instruction
- **THEN** the system SHALL emit `"Workshopping now..."` via the status callback before executing `Planner -> Writer -> Auditor -> Compiler` and pausing at the Human Review interrupt

#### Scenario: Second internal pass always compiles and delivers to human review
- **WHEN** a draft still has an audit warning or minor issue after 2 internal retry passes
- **THEN** the graph MUST route to the Compiler to compile the PDFs, attach the remaining warnings, and pause at the Human Review interrupt rather than looping further or aborting

#### Scenario: User may ideate and re-iterate across multiple unbounded cycles
- **WHEN** the user triggers `re-iterate` a first, second, or third time after reviewing compiled drafts
- **THEN** each `re-iterate` SHALL emit `"Workshopping now..."`, reset `internal_retry_count = 0`, set `status = Revising`, and allow up to 2 fresh internal passes before returning updated compiled PDFs

### Requirement: Conversational ideation without forced rewrites, free-model one-shot re-iteration, and human-as-source-of-truth weekly cache
At the Human Review interrupt:
- Explicit `approve` actions (CLI `/approve`; future Slack `[Approve]` button) MUST transition the job to `Ready_to_Submit` and terminate the graph.
- Explicit `dismiss` actions (CLI `/dismiss`; future Slack `[Dismiss]` button) MUST transition the job to `Rejected` and terminate the graph.
- Free-form text replies SHALL be classified by the free `scoring_model` using `prompts/intent_router.md` (biased safely toward `CHAT`):
  - `CHAT` replies SHALL invoke the `Ideation` node (`reasoning_model` with `prompts/ideation.md`), return a conversational response, and pause again **without** regenerating PDFs.
  - `REITERATE` replies (explicit rewrite instructions such as *"retry, swapping the education and work experience sections"*) SHALL emit `"Workshopping now..."`, capture the instruction and any new/corrected facts into state (and weekly cache), set `status = Revising`, reset `internal_retry_count = 0`, and route directly back to `Planner` in a single turn (`ideation -> re-iterate`).
- `prompts/ideation.md` SHALL actively detect any user-stated facts that **add to OR drift from/contradict** `MasterProfile`. The **human MUST always be treated as the final source of truth** (overriding stale `MasterProfile` facts for the current application via `session_verified_facts`), and every detected addition or correction snippet SHALL be persisted to the SQLite `profile_update_suggestions` weekly cache (`kind = "addition"` or `"correction"`, `consumed_at = NULL`) without mutating `config/master_profile.yaml`.

#### Scenario: Brainstorming reply stays in ideation without regenerating PDFs
- **WHEN** the user sends a conversational message such as "Should we emphasize my cloud infrastructure project more than the API work?"
- **THEN** the free `scoring_model` intent router SHALL classify it as `CHAT`, the Ideation node SHALL reply conversationally, and the Compiler MUST NOT be invoked

#### Scenario: Explicit rewrite reply executes one-shot ideation to re-iterate
- **WHEN** the user sends "retry, swapping the education and work experience sections"
- **THEN** the free `scoring_model` intent router SHALL classify it as `REITERATE`, emit `"Workshopping now..."`, capture the instruction in `ideation_notes`, reset `internal_retry_count = 0`, and route directly back to `Planner` to produce updated compiled PDFs

#### Scenario: User-stated profile addition or correction overrides MasterProfile and enters weekly cache
- **WHEN** the user states a new accomplishment or corrects a stale date/title/skill from `MasterProfile` during ideation
- **THEN** the system SHALL treat the human's statement as the final source of truth in `session_verified_facts`, insert a row into `profile_update_suggestions` (`kind="addition"` or `"correction"`, `consumed_at=None`), and MUST NOT modify `config/master_profile.yaml`

#### Scenario: Explicit approve or dismiss concludes the workflow
- **WHEN** the user issues `/approve` (or `/dismiss`) in the review harness
- **THEN** the graph SHALL update SQLite status to `Ready_to_Submit` (or `Rejected`) and reach `END`
