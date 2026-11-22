## 1. Environment, Config & Project Hygiene

- [x] 1.1 Pin Python version in `.python-version`, add runtime dependencies (`langchain-openai`, `langgraph`, `langgraph-checkpoint-sqlite`, `typst`, `pypdf`) to `pyproject.toml`, update `uv.lock`, and configure `pytest` markers (`eval`) plus expanded `[tool.mutmut]` target paths (`scoring/`, `auditing/`, `storage/`, `schemas/`).
- [x] 1.2 Add `.env.example` documenting `OPENCODE_API_KEY` (and optional per-tier API key overrides), ensure `.gitignore` covers `.env*` and compiled artifacts, and add `.antigravityignore` shielding `.env*` and local SQLite DBs from AI coding tools.
- [x] 1.3 Update `openspec/config.yaml` (LaTeX → Typst via `typst-py`, `/inference/go/openai` → `https://opencode.ai/zen/go/v1`, free scoring/classification model + cheap paid reasoning model, dedicated system prompts replacing `voice_skill_path`).
- [x] 1.4 Add `config/llm.example.yaml` and local `config/llm.yaml` template for dual-tier OpenCode Go configuration (`scoring_model` + `reasoning_model`), and update `config/target_roles.yaml` and `config/target_roles.example.yaml` (remove `voice_skill_path` and flat `min_fit_score`, add `max_body_font_size_pt: 12.0`).

## 2. Domain Schema & State Store Deltas

- [x] 2.1 Update `src/job_agent/schemas/jobs.py` to add `Scored_Out`, `Queued_For_Drafting`, and `Expired` to `ApplicationStatus`.
- [x] 2.2 Update `src/job_agent/schemas/preferences.py` to remove `voice_skill_path` and flat `ScoringRubric.min_fit_score`, enforce body font bounds (`min_font_size_pt` in `[9.0, 12.0]` and `max_body_font_size_pt` in `[min_font_size_pt, 12.0]`), and keep tiered `SeniorityPolicy` thresholds (`0.65` entry-level, `0.95` stretch).
- [x] 2.3 Create `src/job_agent/llm/config.py` with the `LLMConfig` Pydantic v2 schema and `load_llm_config` YAML loader supporting dual-tier `scoring_model` / `reasoning_model` and optional per-tier `base_url` / `api_key_env` overrides.
- [x] 2.4 Update `src/job_agent/storage/repository.py` to drain `Queued_For_Drafting` in freshness-priority + strict FIFO order (`created_at ASC`, `fit_score DESC`), add `expire_stale_queued_jobs(max_age_days=21)` (preserving `source="manual"`), add `count_queued_jobs()`, and add the `profile_update_suggestions` table (`id`, `job_id`, `kind`, `fact_text`, `category`, `created_at`, `consumed_at`) with insert, list-unconsumed, and mark-consumed methods.
- [x] 2.5 Update existing `tests/test_schemas.py` and `tests/test_storage_and_cli.py` (and add new tests for `LLMConfig`, body font bounds, FIFO queue draining, queue expiration, and `profile_update_suggestions`).

## 3. OpenCode Go Client & Startup-Loaded System Prompts

- [x] 3.1 Implement `src/job_agent/llm/client.py` providing the injectable `StructuredLLMClient` protocol, dual-tier `langchain_openai.ChatOpenAI` factory (`scoring` and `reasoning` clients), native `with_structured_output(schema)` invocation with bounded parse-repair retries (`max_parse_retries`), and fail-loud missing env-var checks.
- [x] 3.2 Author dedicated, version-controlled system prompts under `src/job_agent/prompts/`: `scorer.md` (diverse transferable-skill examples, clear senior+ years/scope tell-tales, non-technical role detection), `planner.md` (explicit major-gap criteria, 1-page selection), `writer.md` (synthesizing `application-voice` rules for `da` and `en`), `auditor.md` (synthesizing `blader/humanizer` rules, truthfulness, Danish naturalness, surgical `AuditViolation` output), `ideation.md` (human-as-final-source-of-truth profile addition & drift detection), and `intent_router.md` (biased safely toward `CHAT` vs. explicit `REITERATE`).
- [x] 3.3 Implement `src/job_agent/prompts/loader.py` to load and cache all 6 required prompts automatically on startup (failing fast if any prompt is missing or empty) and add unit tests in `tests/test_llm_and_prompts.py`.

## 4. Stage 1 Fit Scorer & Curated Scoring Evals Suite

- [x] 4.1 Implement `src/job_agent/scoring/models.py` and `src/job_agent/scoring/scorer.py`: LangChain structured-output `ScoringEvidence` extraction via `scoring_model`, deterministic Python rejection of `is_technical == False` and `senior_plus` / `inferred_min_years > max_years_experience`, Option B transferable credit (`1.0` for `entry_level` @ ≥65%, `0.0` for `stretch` @ ≥95%), weighted `fit_score` computation, `missing_posted_at` flagging, and batch runner evaluating all `Pending_Scoring` rows into `Queued_For_Drafting` or `Scored_Out`.
- [x] 4.2 Add thorough unit tests for deterministic scoring boundaries in `tests/test_scoring.py`.
- [x] 4.3 Create the curated scoring evals suite under `tests/evals/` (`test_profile.yaml`, structured test job listings covering entry-level direct, entry-level transferable across diverse stacks, entry-level miss, stretch transferable-only reject, stretch direct pass, hidden senior+ reject, non-technical reject, Danish posting, and missing `posted_at`) runnable offline by default and live against OpenCode Go via `pytest -m eval`.

## 5. Typst Document Rendering (`basic-resume` CV + Custom Matching Cover Letter)

- [ ] 5.1 Define `TailoredCV` and `TailoredCoverLetter` Pydantic v2 models in `src/job_agent/rendering/models.py` (strictly structured text fields; zero raw markup).
- [ ] 5.2 Add offline-capable Typst templates in `src/job_agent/rendering/templates/`: `cv.typ` (vendoring/adapting the open-source MIT `basic-resume` layout) and `cover_letter.typ` (custom matching header, typography, accent, and margins), supporting localized `da`/`en` headings, native UTF-8 Danish characters (`æ`, `ø`, `å`), and locked body font bounds `[9.0pt, 12.0pt]` (body only, excluding headers/sub-headers/footers).
- [ ] 5.3 Implement `src/job_agent/rendering/compiler.py` invoking `typst.compile(..., sys_inputs={"data": json_str})` and counting PDF pages deterministically via `pypdf`, returning structured page-overflow diagnostics when `page_count > max_pages`.
- [ ] 5.4 Add rendering tests in `tests/test_rendering.py` verifying offline EN and DA PDF compilation, UTF-8 Danish characters, body font bounds, single-page pass, and multi-page overflow detection.

## 6. Two-Pass Auditing & LangGraph Tailoring / HITL Ideation Graph

- [ ] 6.1 Implement `src/job_agent/auditing/models.py` (`AuditViolation(document, location, rule, offending_snippet, fix_instruction)`, `AuditResult`) and `src/job_agent/auditing/deterministic.py` (zero-token Python gate checking em-dashes, EN cover letter contractions, banned AI phrases, word count window, language-matched sign-off, max one `!` on closing line, leftover placeholders, and exact `MasterProfile` + `session_verified_facts` company/title/date anchors).
- [ ] 6.2 Implement `tests/test_deterministic_auditor.py` with realistic full-length multi-paragraph EN & DA fixtures and an "obviously AI-written" CV + Cover Letter fixture triggering every mechanical rule and verifying exact `AuditViolation` locations.
- [ ] 6.3 Implement `src/job_agent/auditing/llm_auditor.py` (`reasoning_model` with `prompts/auditor.md` embedding `blader/humanizer` + truthfulness + Danish naturalness + major-only gap discipline, returning structured `AuditViolation` items).
- [ ] 6.4 Implement the SQLite-checkpointed LangGraph `StateGraph` under `src/job_agent/graph/` (`state.py`, `nodes.py`, `workflow.py`): `Planner -> Writer -> Deterministic Auditor -> LLM Auditor -> Compiler -> Human Review Interrupt`, enforcing max-2 internal self-correction passes (always routing to Compiler after pass 2 to deliver PDFs + warnings to human), loud `"Workshopping now..."` progress callback emission, unbounded human ideation/re-iteration cycles, free-model `intent_router` (`CHAT` vs. one-shot `REITERATE`), and human-as-final-source-of-truth profile addition/correction capture into `session_verified_facts` + SQLite `profile_update_suggestions`.
- [ ] 6.5 Add end-to-end mocked LangGraph tests in `tests/test_tailoring_graph.py` covering checkpoint resume across restarts, Pass 1 skip of LLM Auditor, max-2 internal pass mandatory compilation, `"Workshopping now..."` status emission, brainstorming `CHAT` without PDF regen, one-shot `REITERATE` to `Planner`, profile addition/correction weekly cache writes (without mutating `master_profile.yaml`), and `/approve` / `/dismiss` completion.

## 7. Local CLI Harness & Final Verification

- [ ] 7.1 Extend `src/job_agent/cli.py` with `job-agent score`, `job-agent draft`, `job-agent queue`, and the interactive `job-agent review <job_id>` terminal harness (displaying brief, fit breakdown, major gaps, `missing_posted_at` warning, compiled PDF paths, `"Workshopping now..."` status messages, free-form ideation/one-shot re-iterate input, and `/approve` / `/dismiss` commands) and add CLI tests.
- [ ] 7.2 Run full `.venv/bin/pytest -v` test suite (including offline scoring evals) and `.venv/bin/mutmut run` across `schemas/`, `filters/`, `sources/normalize.py`, `storage/`, `scoring/`, and `auditing/deterministic.py`, killing any behavioral survivors.
- [ ] 7.3 Validate OpenSpec artifacts (`openspec validate opencode-and-tailoring-graph --strict`) and verify zero drift with `docs/INTENT.md`.
