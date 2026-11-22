# job-agent

A personal job-hunting and application co-pilot built for finding entry-level roles in Copenhagen, Europe, and Remote positions. It discovers postings, filters out poor matches deterministically before spending LLM tokens, scores candidates into a daily draft queue, tailors bilingual (`da`/`en`) Typst CVs and cover letters in my voice, audits them with a deterministic gate plus `blader/humanizer`-guided review, and collaborates through an interactive human-in-the-loop (HITL) ideation and approval flow.

The guiding principles, eligibility rules, and full co-pilot workflows live in [`docs/INTENT.md`](docs/INTENT.md).

## What Works Today

- **Domain Schemas (`src/job_agent/schemas/`, `src/job_agent/llm/config.py`):** Pydantic v2 models (`MasterProfile`, `JobPreferences`, `SourcesConfig`, `LLMConfig`, `RawJob`, and `JobPosting`) loaded from YAML. Enforces seniority rules (entry-level primary at ≥65% fit, ~2-year stretch at ≥95% fit, excluding Senior+ titles while keeping Architect roles eligible), freshness bounds (`max_age_days=21`, `preferred_age_days=7`, `daily_draft_limit=3`), and readable body font limits (`9.0pt` floor to `12.0pt` ceiling).
- **Job Discovery (`src/job_agent/sources/`):** Pluggable `JobSource` adapters built for once-daily polling across Arbeitnow, Remotive, Himalayas, Jobicy, and Jobindex RSS, with isolated error handling per source. Supports manual additions via `job-agent add` (`--text`, `--file`, stdin, or `--url`), failing loudly if blocked, behind auth, or unparseable. Assigns a canonical 16-character SHA-256 `job_id` and deterministic `da`/`en` language classification.
- **Pre-Filtering (`src/job_agent/filters/`):** Drops Senior+ roles, postings requiring >2 years of experience, disallowed locations or work modes, configured dealbreakers, and stale postings older than `max_age_days` before any LLM call runs. Preserves postings with a future `application_deadline` (*ansøgningsfrist*), missing `posted_at`, or manual submissions.
- **SQLite State Store (`src/job_agent/storage/`):** Postgres-portable `JobRepository` tracking application lifecycle states (`Pending_Scoring`, `PreFiltered_Out`, `Scored_Out`, `Queued_For_Drafting`, `Expired`, `Pending_Review`, `Revising`, `Ready_to_Submit`, `Applied`, `Interviewing`, `Rejected`), priority FIFO queue draining up to `daily_draft_limit`, pre-draft expiration checks, 180-day retention cleanup (preserving `Interviewing` rows), and the `profile_update_suggestions` weekly cache for user-shared additions and corrections.
- **Dual-Tier OpenCode Go Client & Startup System Prompts (`src/job_agent/llm/`, `src/job_agent/prompts/`):** Connects via `langchain_openai.ChatOpenAI` to `https://opencode.ai/zen/go/v1` with dual-tier model routing (`scoring_model` free tier for Stage 1 scoring and thread intent routing; `reasoning_model` paid tier for planning, writing, auditing, and ideation), native LangChain structured output enforcement with bounded parse-repair retries, and 6 dedicated startup-loaded system prompts embedding Sebastian's `application-voice` and `blader/humanizer` rules.
- **Stage 1 Fit Scorer & Scoring Evals (`src/job_agent/scoring/`, `tests/evals/`):** Evaluates all `Pending_Scoring` postings (no 3-job cap on scoring), automatically scores out non-technical and hidden senior+ roles, applies Option B transferability (`1.0` credit on entry-level, `0.0` on stretch), flags missing `posted_at`, and verifies matching logic with a curated offline + live evals suite.
- **Offline Bilingual Typst Rendering (`src/job_agent/rendering/`):** Compiles single-column ATS-friendly PDFs offline using the `typst` Python package (`typst-py`) from validated `TailoredCV` (`basic-resume` style) and `TailoredCoverLetter` (custom matching layout) JSON payloads, supporting native Danish `æ/ø/å`, `[9.0pt, 12.0pt]` body font bounds, and deterministic `pypdf` page-budget checks.
- **Two-Pass Auditing & LangGraph HITL Workflow (`src/job_agent/auditing/`, `src/job_agent/graph/`):** SQLite-checkpointed `StateGraph` (`Planner -> Writer -> Deterministic Auditor -> LLM Auditor -> Compiler -> Human Review Interrupt`) with surgical `AuditViolation` diagnostics, max-2 internal self-correction passes (always compiling PDFs for human review after pass 2), loud `"Workshopping now..."` progress feedback, direct `apply_url` handoff, conversational ideation without forced rewrites, one-shot `ideation -> re-iterate` routing, weekly profile suggestion caching, and explicit `/approve` / `/dismiss` completion.
- **CLI Harness (`src/job_agent/cli.py`):** Full terminal workflow (`ingest`, `add`, `list`, `score`, `queue`, `draft`, `review <job_id>`).

## Quickstart

### 1. Install Dependencies

Requires Python 3.11+ (pinned in `.python-version`) and [`uv`](https://docs.astral.sh/uv/):

```bash
uv sync --extra dev
```

*(Typst is bundled directly via the `typst` Python wheel—no separate `brew install typst` is needed.)*

### 2. Configure Profile, Preferences, Sources & LLM

Copy the example config and environment templates into personal files (these are gitignored and shielded by `.antigravityignore`):

```bash
cp config/master_profile.example.yaml config/master_profile.yaml
cp config/target_roles.example.yaml config/target_roles.yaml
cp config/sources.example.yaml config/sources.yaml
cp config/llm.example.yaml config/llm.yaml
cp .env.example .env
```

Set `OPENCODE_API_KEY` in `.env` (or export it in your shell), customize `config/llm.yaml` (`scoring_model` + `reasoning_model`), and add filtered Jobindex RSS feed URLs under `jobindex_rss.feed_urls` in `config/sources.yaml`.

### 3. Run the CLI

```bash
# Run daily discovery, pre-filtering, persistence, and 180-day cleanup
.venv/bin/job-agent ingest

# Manually add a job from raw text or direct URL (fails loudly if auth-gated/unparseable)
.venv/bin/job-agent add \
  --title "Junior Software Engineer" \
  --company "Nordic Cloud" \
  --location "Copenhagen, Denmark" \
  --work-mode hybrid \
  --text "Entry-level Python and SQL role in Copenhagen."
.venv/bin/job-agent add --url "https://example.com/careers/junior-engineer"

# Score all Pending_Scoring postings into the draft queue, inspect queue, and draft up to daily limit
.venv/bin/job-agent score
.venv/bin/job-agent queue
.venv/bin/job-agent draft

# Interactive review session (displays Apply URL + compiled PDFs; supports chat, one-shot re-iterate, /approve, /dismiss)
.venv/bin/job-agent review <job_id>

# Inspect stored jobs filtered by status or language
.venv/bin/job-agent list --status Pending_Review --language en
```

## Testing

Run the full offline test suite (including offline scoring evals and real Typst PDF compilation):

```bash
.venv/bin/pytest -v
```

Run live scoring evals against the configured OpenCode Go `scoring_model` (requires `OPENCODE_API_KEY`):

```bash
.venv/bin/pytest -v -m eval
```

Run mutation testing on deterministic core modules (`schemas/`, `filters/`, `sources/normalize.py`, `storage/`, `scoring/`, `auditing/deterministic.py`):

```bash
.venv/bin/mutmut run
.venv/bin/mutmut results
```

## Repository Layout

- `docs/INTENT.md`: Living intent document covering project scope, principles, and workflows.
- `AGENTS.md`: Project agent and git worktree workflow rules.
- `.agent/skills/application-voice/`: Embedded Voice DNA and anti-AI rules for CVs and cover letters.
- `.python-version`, `.env.example`, `.antigravityignore`: Explicit runtime pinning and secrets hygiene.
- `openspec/`: OpenSpec configuration, specs, designs, and task checklists.
- `config/`: Example YAML templates (`*.example.yaml`).
- `src/job_agent/`: Core Python package (`schemas/`, `sources/`, `filters/`, `storage/`, `llm/`, `prompts/`, `scoring/`, `rendering/`, `auditing/`, `graph/`, `pipeline.py`, `cli.py`).
- `tests/`: Unit, integration, rendering, auditor, graph, and `evals/` suites.
