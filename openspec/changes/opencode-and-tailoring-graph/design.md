## Context

`job-agent` already has a verified deterministic foundation (`schemas-and-ingestion`): Pydantic v2 config/domain schemas (`MasterProfile`, `JobPreferences`, `SourcesConfig`, `JobPosting`), once-daily free/open discovery adapters + Manual Drop, deterministic `da`/`en` language classification, rule-based pre-filtering, and a Postgres-portable SQLite `JobRepository`. Passing postings currently land in `Pending_Scoring`.

This change introduces the **LLM reasoning, scoring, document tailoring, two-pass auditing, Typst PDF compilation, and stateful HITL ideation** layer — keeping the **Deterministic First** principle intact by letting Python handle all math, gating, queue ordering, mechanical auditing, and layout enforcement while reserving LLMs strictly for semantic judgment, authentic bilingual writing, and conversational ideation.

## Goals / Non-Goals

**Goals:**
- Configure OpenCode Go (`https://opencode.ai/zen/go/v1`) via `langchain_openai.ChatOpenAI` with a git-tracked **dual-tier model** config (`config/llm.yaml`): a **free model** (`scoring_model`) for Stage 1 fit scoring and thread intent classification, and a **cheap paid reasoning model** (`reasoning_model`) for planning, writing, auditing, and ideation — with strict native LangChain/LangGraph structured outputs across all LLM nodes (excluding the deterministic Compiler) behind an injectable client protocol.
- Give **every** LLM agent/node (`scorer`, `planner`, `writer`, `auditor`, `ideation`, `intent_router`) a dedicated, version-controlled system prompt file (`prompts/`) loaded automatically at startup (cached, fail-fast), embedding `application-voice` (Writer), `blader/humanizer` (Auditor), diverse transferable-skill examples, and clear senior+/non-technical tell-tales, while removing optional skill-path config fields.
- Implement Stage 1 **Fit Scoring** over *all* `Pending_Scoring` roles (LangChain structured-output free-LLM extraction + deterministic Python rubric, auto-scoring-out non-technical and hidden senior+ roles, and tiered 65% junior / 95% mid-level gating) feeding a SQLite-backed priority FIFO **Draft Queue** (`Queued_For_Drafting`) drained up to `daily_draft_limit` (default `3`, upper cap, never a quota) with pre-draft expiration checks.
- Implement Stage 2 **LangGraph Tailoring & HITL Ideation** (`Planner -> Writer -> Deterministic Auditor -> LLM Auditor -> Compiler -> Human Review Interrupt`) backed by SQLite checkpointing (`langgraph_thread_id`), returning surgical `AuditViolation` diagnostics (document, location, offending snippet, fix instruction), bounded to max 2 internal self-correction passes per generation cycle (always compiling output for the human after pass 2), emitting loud `"Workshopping now..."` progress feedback, and allowing unbounded human ideation/re-iteration cycles.
- Support open conversational ideation without forced rewrites, free-model one-shot `ideation -> re-iterate` routing on explicit rewrite requests, explicit `approve`/`dismiss` completion, and human-as-source-of-truth detection of facts that add to or drift from `MasterProfile` persisted into a SQLite weekly cache (`profile_update_suggestions`) for the Sunday check-in without mutating `master_profile.yaml` during the week.
- Render bilingual (`da`/`en`) single-column ATS-friendly PDFs using the **`typst` Python wheel (`typst-py`)** — the open-source MIT-licensed `basic-resume` template for CVs and a **custom** Typst Cover Letter template matching its header, typography, and margins — fed directly from validated Pydantic JSON, locking body font size to `[9pt, 12pt]` (default `10pt`, excluding headers/sub-headers/footers) and margins, and feeding PDF page overflows back to the Writer.
- Expose a local CLI workflow (`job-agent score`, `job-agent draft`, `job-agent queue`, `job-agent review <job_id>`) and explicit project environment files (`.python-version`, `pyproject.toml`, `uv.lock`, `.env.example`, `.geminiignore`) so the entire agent is reproducible locally and ready for future deployment.
- Verify deterministic scoring, auditing, and queue logic with intent-rooted unit tests (including full multi-paragraph EN/DA & "obviously AI" CV/cover letter fixtures), `mutmut` mutation testing, and a curated **Scoring Evals Suite** (synthetic test profile + structured test job listings) runnable offline and live against OpenCode Go.

**Non-Goals:**
- Slack bot event/Block Kit integration (deferred to `slack-copilot-loop`; designed here to be channel-agnostic so Slack can cleanly separate `#job-drafts`, `#profile-updates`, and `#job-updates`).
- Mutating `config/master_profile.yaml` during tailoring threads (deferred to `weekly-profile-checkin`, which will consume the `profile_update_suggestions` SQLite cache built in this change).
- Google Sheets tracker sync, Gmail inbox polling, Google Calendar sync, or GCP Cloud Run deployment.
- Re-implementing LaTeX rendering (superseded by Typst).

## Decisions

### 1. Two-Stage Pipeline: Stateless Batch Scoring + SQLite Priority FIFO Draft Queue
- **Decision:** Separate evaluation from drafting:
  1. **Stage 1 (Stateless Fit Scorer):** Evaluate *all* `Pending_Scoring` rows (no 3-job cap). Persist `fit_score` and `fit_breakdown_json` on every row, transitioning passing rows to `Queued_For_Drafting` and failing rows to `Scored_Out`.
  2. **Stage 2 (Daily Queue Drain):** Before drafting, expire any non-manual `Queued_For_Drafting` row whose `application_deadline` has passed or whose `posted_at` aged beyond `max_age_days` (`Expired`). Then select up to `daily_draft_limit` (default `3`, upper cap, never a quota) ordered by:
     - Preferred tier (`posted_at <= preferred_age_days` OR active future `application_deadline`) ahead of fallback tier (`8–21d`),
     - **Strict FIFO** (`created_at ASC`, tie-breaking by `fit_score DESC`) within each tier so the backlog always drains predictably without starving older queued roles.
- **Alternatives Considered:**
  - *Querying `Pending_Scoring LIMIT 3` before scoring:* Violates `docs/INTENT.md` ("evaluates all eligible postings") and wastes daily slots when top-3 candidates fail scoring.
  - *Score-first (`fit_score DESC`) ordering across the queue:* Risks starving queued backlog items indefinitely and adds unnecessary complexity for a rare backlog scenario.
- **Rationale:** Keeps human review volume bounded to a manageable daily cap while ensuring every eligible job is evaluated and backlog visibility (`job-agent queue`) is trivial.

### 2. Hybrid Python + Free-LLM Split for Fit Scoring (Tiered 65% Junior / 95% Mid-Level, Non-Technical & Senior+ Gates)
- **Decision:** The free `scoring_model` extracts structured evidence via LangChain's `with_structured_output(ScoringEvidence)` including:
  - `is_technical: bool` (identifying non-technical roles such as sales, HR, marketing, legal, or pure administrative roles),
  - `inferred_min_years: int | None` and `seniority_tier` (`entry_level`, `stretch`, `senior_plus`) plus explicit `seniority_signals: list[str]` — guided by clear tell-tales in `prompts/scorer.md` (primarily required years of experience > `max_years_experience`, plus lead/ownership/mentoring scope),
  - role must-have skills, direct matches, transferable matches with rationale (guided by diverse examples across IaC, cloud providers, web frameworks, CI/CD, databases, and containers — never anchored on a single example), missing must-haves, 0–10 sub-scores (`role_seniority`, `must_have_skills`, `domain_fit`, `nice_to_have`), and major unaddressed gaps.
  **Python** deterministically computes:
  - Immediate `Scored_Out` if `is_technical is False`, `inferred_min_years > max_years_experience`, or `seniority_tier == "senior_plus"`.
  - `must_have_coverage` and tiered eligibility using **Option B**:
    - `entry_level` (junior, `<= 1` yr): direct match = `1.0`, transferable match = `1.0`; requires **minimum fit ≥ 65%** (`must_have_coverage >= 0.65` and normalized weighted fit score `>= 0.65`, i.e., `6.5 / 10`).
    - `stretch` (mid-level, `~2` yrs): direct match = `1.0`, transferable match = `0.0`; requires **minimum fit ≥ 95%** (`must_have_coverage >= 0.95` and normalized weighted fit score `>= 0.95`, i.e., `9.5 / 10` — exact must-haves required).
  - Weighted `fit_score` from `JobPreferences.scoring_rubric` (removing the separate flat `min_fit_score = 7.5` in favor of the tiered `entry_level` 65% and `stretch` 95% thresholds).
  - `missing_posted_at: bool` warning whenever `posted_at is None`.
- **Alternatives Considered:** Keeping a separate flat `min_fit_score = 7.5` alongside `0.65`/`0.95` coverage thresholds; or using the paid reasoning model for high-volume initial scoring.
- **Rationale:** Running high-volume batch scoring on a free model keeps daily costs near zero while deterministic Python math and clear classifier tell-tales enforce exact, mutation-testable gating.

### 3. Curated Scoring Evals Suite
- **Decision:** Build a dedicated evals suite (`tests/evals/`) containing a synthetic `test_profile.yaml` and structured test job listings exercising all intended matching behaviors:
  - Entry-level direct match (≥65%) → `Queued_For_Drafting`
  - Entry-level transferable match across diverse stacks (≥65%) → `Queued_For_Drafting`
  - Entry-level insufficient fit (<65%) → `Scored_Out`
  - Mid-level / stretch (~2y) with transferable-only gap (transferable credit = `0.0`, <95%) → `Scored_Out`
  - Mid-level / stretch (~2y) with ≥95% direct must-have coverage → `Queued_For_Drafting`
  - Hidden Senior+ role (neutral title, 5+ years / senior scope in JD) → `Scored_Out`
  - Non-technical role (e.g., Account Executive / Recruiter / Operations Coordinator) → `Scored_Out`
  - Danish (`da`) posting and missing `posted_at` flagging
  Support running the suite both **deterministically offline** (fixture `ScoringEvidence` verifying Python rubric/gating logic) and **live against OpenCode Go** (opt-in `pytest -m eval`) to measure real `scoring_model` accuracy and validate model swaps.
- **Rationale:** Gives repeatable, objective confidence that the prompt + free model + Python gating accurately implement the tiered scoring policy before trusting it on live boards.

### 4. Two-Pass Auditing with Surgical Failure Diagnostics & Clear Major-Gap Definition
- **Decision:**
  - **Definition of Major Unaddressed Gap:** A core, primary requirement explicitly emphasized as mandatory in the job posting that has **neither** a direct match **nor** a closely transferable equivalent in `MasterProfile` (e.g., a primary programming language, core paradigm like embedded C++ or native iOS, required certification/clearance, or mandatory spoken language). Secondary/nice-to-have tools, specific SaaS utilities (Jira, Datadog, Linear), or swappable library variants where the candidate holds transferable foundations MUST NOT be flagged as major gaps.
  - **Two Sequential Audit Passes:**
    1. **Pass 1 — Deterministic Python Gate (0 tokens):** Checks zero em-dashes (`—`, `--`), zero contractions in English cover letters (`language == "en"`), banned AI cliché phrases, cover letter word count window (~250–380 words) & exact sign-off (`Kind Regards,` / `Med venlig hilsen,`), max one `!` on closing line, zero leftover placeholder tokens (`{{...}}`, `[Company]`), and exact company/title/date anchor verification against `MasterProfile` (plus `session_verified_facts`). Failures bounce directly back to the Writer without calling the LLM Auditor.
    2. **Pass 2 — Reasoning LLM Auditor (`reasoning_model`):** Evaluates semantic truthfulness (zero fabrication against `MasterProfile` + `session_verified_facts`), honest transferability framing, Danish naturalness (when `language == "da"`), major-only gap discipline, and AI-tell detection guided by `blader/humanizer` rules embedded in `prompts/auditor.md`.
  - **Surgical `AuditViolation` Diagnostics:** Both passes MUST return structured `AuditViolation(document, location, rule, offending_snippet, fix_instruction)` items pinpointing exactly what failed and where (e.g., `cover_letter`, `paragraph 2`, `contraction`, `"I'm excited"`, `"Replace contraction with 'I am'"`) so the Writer edits surgically with minimal guesswork.
- **Rationale:** Pairing a mutation-tested Python gate (verified against full multi-paragraph EN/DA and "obviously AI" fixtures) with targeted `AuditViolation` pointers prevents vague retry loops and preserves high-quality sections during fixes.

### 5. Bounded Internal Passes (Max 2, Always Compile for Human), Loud Progress Feedback & Unbounded Human Ideation
- **Decision:** Track `internal_retry_count` in LangGraph state:
  - Whenever drafting or `re-iterate` begins, emit an explicit user-visible progress message (e.g., `"Workshopping now..."`) via an injectable status callback so the user immediately knows work is underway (both in CLI and future Slack threads).
  - Within a single generation or user-triggered `re-iterate` cycle, the internal self-correction loop (Deterministic Auditor fail, LLM Auditor fail, or Compiler page overflow) routes back to the Writer **at most 2 times**.
  - When the second internal pass finishes, the output **must always be routed to the Compiler** to produce compiled PDFs and present the response (alongside any remaining audit/overflow warnings) to the human at the `Human Review Interrupt`.
  - The outer **Human Review ↔ Ideation ↔ Re-iterate** loop is **unbounded** — the user can ideate and request re-iteration as many times as desired; each user-triggered `re-iterate` resets `internal_retry_count = 0`.
- **Rationale:** Guarantees bounded autonomous token spend per cycle, ensures the human always sees active progress and receives compiled artifacts, and never restricts conversational iteration.

### 6. LangGraph Topology: Conversational Ideation, Free-Model Intent Router, Human-as-Source-of-Truth & Weekly Profile Cache
- **Decision:** Model Stage 2 as a persistent LangGraph `StateGraph` checkpointed in SQLite (`SqliteSaver`, portable to `PostgresSaver`):
  - **Flow:** `Planner -> Writer -> Deterministic Auditor -> LLM Auditor -> Compiler -> Human Review Interrupt`.
  - **Human Review Handling:**
    - Explicit `approve` action (CLI `/approve`; future Slack `[Approve]` button) → status `Ready_to_Submit`, graph ends.
    - Explicit `dismiss` action (CLI `/dismiss`; future Slack `[Dismiss]` button) → status `Rejected`, graph ends.
    - Free-form text message → **Intent router** (using the free `scoring_model`, strongly biased toward `CHAT` unless the user gives an explicit rewrite/retry instruction):
      - `CHAT`: Runs `Ideation` node (`reasoning_model`), returns reply, pauses at `Human Review Interrupt` **without regenerating PDFs**.
      - `REITERATE` (e.g., *"retry, swapping the education and work experience sections"*): Emits `"Workshopping now..."`, captures the instruction and any new/updated facts into state (and weekly cache), sets `status = Revising`, resets `internal_retry_count = 0`, and routes directly back to `Planner` in a single turn (`ideation -> re-iterate`).
  - **Human as Final Source of Truth & Weekly Profile Cache:** `prompts/ideation.md` explicitly instructs the Ideation node to detect any user-stated facts that **add to OR drift from/contradict** `MasterProfile`. The **human is always the final source of truth** — overriding stale `MasterProfile` facts for the current application via `session_verified_facts`, and persisting each detected addition or correction into SQLite `profile_update_suggestions(id, job_id, kind, fact_text, category, created_at, consumed_at)` where `kind` is `"addition"` or `"correction"`. During the week `master_profile.yaml` is never mutated; the future `weekly-profile-checkin` session reads all unconsumed rows (`consumed_at IS NULL`) on Sunday.
- **Rationale:** Keeps intent routing free, preserves channel-agnostic graph I/O for both the local CLI harness and future multi-channel Slack bots (`#job-drafts`, `#profile-updates`, `#job-updates`), and ensures zero user-shared profile updates are lost between tailoring sessions and Sunday check-ins.

### 7. OpenCode Go Dual-Tier Client (`config/llm.yaml`), Startup-Loaded Prompts & Secrets Hygiene
- **Decision:**
  - Store non-secret provider/model settings in git-tracked `config/llm.yaml` (`base_url: "https://opencode.ai/zen/go/v1"`, `api_key_env: "OPENCODE_API_KEY"`, `scoring_model` [free model], `reasoning_model` [cheap paid model], optional `scoring_base_url` / `scoring_api_key_env` overrides, optional `reasoning_effort`, `temperature`, `timeout_seconds`, `max_parse_retries`, `structured_output_method`), validated via `LLMConfig`.
  - Wrap `langchain_openai.ChatOpenAI` with native `with_structured_output(PydanticModel)` behind an injectable `StructuredLLMClient` protocol across every **LLM** node (explicitly excluding the deterministic Typst `Compiler`), so all nodes are 100% unit-testable offline.
  - Remove `voice_skill_path` from `JobPreferences`. Every LLM agent/node has a dedicated, version-controlled system prompt file under `src/job_agent/prompts/` (`scorer.md`, `planner.md`, `writer.md`, `auditor.md`, `ideation.md`, `intent_router.md`) **loaded automatically at startup** (cached in memory, failing fast if missing/empty — no hooks required).
  - Add `.geminiignore` (alongside `.gitignore`) shielding `.env`, `.env.*`, and local secrets/databases from AI coding tools.
- **Alternatives Considered:** Single model for all tasks (higher cost on high-volume daily scoring & intent routing); loading prompts via external hooks (adds unnecessary indirection compared to fail-fast startup loading in Python).
- **Rationale:** Free model for scoring/classification + cheap paid model for reasoning optimizes cost without sacrificing writing/auditing quality, while startup-loaded prompts are deterministic and zero-magic.

### 8. Typst PDF Rendering (Open-Source `basic-resume` CV + Custom Matching Cover Letter) via `typst` Python Wheel
- **Decision:** Use the **`typst` Python package (`typst-py`)** — declared directly in `pyproject.toml` and locked in `uv.lock` — instead of LaTeX or an external system binary:
  - Writer outputs strictly validated Pydantic models (`TailoredCV`, `TailoredCoverLetter`) — never raw markup.
  - Python serializes the model to JSON and calls `typst.compile(..., sys_inputs={"data": json_str})` against two `.typ` templates in `src/job_agent/rendering/templates/`:
    - **CV (`cv.typ`):** Based on the open-source MIT-licensed `basic-resume` Typst package (`https://typst.app/universe/package/basic-resume`), vendored locally for 100% offline deterministic builds.
    - **Cover Letter (`cover_letter.typ`):** A **custom** Typst template engineered to match `basic-resume`'s header, typography, accent, and margins seamlessly.
  - Enforce body text font size strictly within **`[9.0pt, 12.0pt]`** (default `10.0pt`, applying to body text only — headers, sub-headers, and footers are styled independently) and preserve whitespace/margins, with localized `da`/`en` section headers.
  - Deterministically count compiled PDF pages via `pypdf`; if `page_count > max_pages` and `internal_retry_count < 2`, feed exact overflow details back to the Writer to trim prose.
- **Alternatives Considered:** LaTeX + `tectonic` or external `brew install typst` CLI (adds host-level binary drift between local macOS dev and future Cloud Run containers).
- **Rationale:** Bundling `typst` directly inside the `uv`-locked Python environment eliminates host binary prerequisites completely, passes validated JSON via `sys_inputs` with zero escaping bugs, handles Danish UTF-8 (`æ`, `ø`, `å`) natively, and compiles in ~50ms.

## Risks / Trade-offs

- **[Risk] Free `scoring_model` may vary in strict JSON Schema `with_structured_output` adherence** → Mitigation: Support configurable structured-output mode (`json_schema` vs. `function_calling`) in `LLMConfig`, wrap calls in a bounded Pydantic parse-repair retry (max 2), and validate live accuracy via `tests/evals/`.
- **[Risk] Free `scoring_model` intent router could misclassify brainstorming text as `REITERATE`** → Mitigation: Explicitly bias `intent_router.md` toward `CHAT` (requiring clear imperative rewrite/retry intent for `REITERATE`) and unit-test ambiguous brainstorming messages to ensure they stay in `CHAT`.
- **[Risk] Font availability differences between macOS and Linux/Cloud Run containers in Typst** → Mitigation: Pin standard bundled/vendored open-source fonts (or Typst's built-in Libertinus/New Computer Modern fallback) inside the template assets directory so local macOS and future Linux containers render identical line wraps and page counts.
- **[Risk] Removing `voice_skill_path` and flat `min_fit_score` from `JobPreferences` affects existing `config/target_roles.yaml` and schema tests** → Mitigation: Update `config/target_roles.yaml`, `config/target_roles.example.yaml`, and existing schema tests in the same change, verified via `pytest` + `mutmut`.
- **[Risk] `blader/humanizer` guidelines are English-centric and could over-flag natural Danish phrasing** → Mitigation: Explicitly scope English-only mechanical checks (e.g., contractions) to `language == "en"` in the Python gate, and instruct the LLM Auditor in `auditor.md` to evaluate Danish drafts for natural idiomatic Danish rather than English clichés.

## Migration Plan

1. **Config & Docs Alignment:** Update `openspec/config.yaml` (LaTeX → Typst; `/inference/go/openai` → `https://opencode.ai/zen/go/v1`; free scoring/classification model + cheap paid reasoning model), update `config/target_roles*.yaml` (remove `voice_skill_path`, remove flat `min_fit_score`, add `max_body_font_size_pt: 12.0`), and add `config/llm.example.yaml` + local `config/llm.yaml`.
2. **Database Compatibility:** Existing `data/job_agent.db` already stores `status TEXT` without a SQL `CHECK` constraint, so adding `Queued_For_Drafting`, `Scored_Out`, and `Expired` to `ApplicationStatus` requires **no destructive schema migration**. Adding the `profile_update_suggestions` table uses `CREATE TABLE IF NOT EXISTS` on repository init.
3. **Explicit Reproducible Environment & Ignore Hygiene:** Pin Python version in `.python-version`, declare all runtime & dev dependencies (including `typst` wheel, `pypdf`, `langchain-openai`, `langgraph`, `langgraph-checkpoint-sqlite`) in `pyproject.toml` + `uv.lock`, add `.env.example` documenting `OPENCODE_API_KEY`, and add `.geminiignore` shielding `.env*` and local DBs from AI tools. No external system binaries (`brew install`) are required, making `uv sync --frozen` identical across local macOS and future Docker / Cloud Run builds.
