## ADDED Requirements

### Requirement: Dual-tier OpenCode Go client configuration and secrets hygiene
The system SHALL load non-secret LLM provider settings from a git-tracked YAML file (`config/llm.yaml`, with `config/llm.example.yaml` committed as template) into an `LLMConfig` Pydantic model specifying:
- `base_url` (default `"https://opencode.ai/zen/go/v1"`),
- `api_key_env` (default `"OPENCODE_API_KEY"`),
- `scoring_model` (free model used for Stage 1 fit scoring and thread intent classification),
- `reasoning_model` (cheap paid model used for planning, writing, auditing, and ideation),
- optional per-tier `scoring_base_url` / `scoring_api_key_env` overrides (defaulting to the shared OpenCode Go config),
- optional `reasoning_effort`, `temperature`, `timeout_seconds`, `max_parse_retries`, and `structured_output_method`.
API keys MUST be read strictly from environment variables and MUST never be stored in YAML config files. The project SHALL also include `.geminiignore` (alongside `.gitignore` and `.env.example`) shielding `.env`, `.env.*`, and local databases from AI coding tools.

#### Scenario: Construct dual-tier ChatOpenAI clients from valid config and env
- **WHEN** `config/llm.yaml` specifies `scoring_model` (free tier) and `reasoning_model` (paid tier) and `OPENCODE_API_KEY` is set in the environment
- **THEN** the client factory SHALL construct `langchain_openai.ChatOpenAI` instances for both tiers routed to `https://opencode.ai/zen/go/v1` (or the configured per-tier override)

#### Scenario: Fail loudly when API key environment variable is missing
- **WHEN** the client factory is invoked for a live LLM call and the environment variable named in `LLMConfig.api_key_env` (or `scoring_api_key_env`) is unset or empty
- **THEN** the system MUST raise a clear configuration error naming the missing environment variable without making any network request

### Requirement: Native LangChain structured output enforcement for LLM nodes
The system SHALL enforce structured Pydantic v2 outputs across every **LLM** agent node (`scorer`, `planner`, `writer`, `auditor`, `ideation`, `intent_router` — explicitly excluding the deterministic Typst `Compiler`, which makes no LLM calls) via LangChain's native `with_structured_output(schema)` behind an injectable `StructuredLLMClient` protocol. If a model returns malformed JSON or fails Pydantic validation, the wrapper SHALL retry with the validation error message up to `max_parse_retries` (default `2`) before raising a structured failure.

#### Scenario: Return validated Pydantic model on valid structured output
- **WHEN** an LLM node invokes `StructuredLLMClient.invoke_structured(messages, ScoringEvidence)` and the model returns schema-compliant output
- **THEN** the client SHALL return a validated `ScoringEvidence` instance

#### Scenario: Retry and recover on transient schema validation error
- **WHEN** the first model response fails Pydantic validation and the second response (after receiving the validation error feedback) conforms to the schema
- **THEN** the client SHALL return the validated Pydantic instance within `max_parse_retries`

#### Scenario: Offline testability via injectable client protocol
- **WHEN** unit tests inject a mock `StructuredLLMClient` implementation
- **THEN** all scorer and LangGraph LLM nodes SHALL execute deterministically with zero network requests

### Requirement: Startup-loaded dedicated system prompts for every LLM agent node
The system SHALL provide a dedicated, version-controlled system prompt file under `src/job_agent/prompts/` for every LLM agent node: `scorer.md`, `planner.md`, `writer.md`, `auditor.md`, `ideation.md`, and `intent_router.md`. Prompts SHALL be loaded automatically on application startup (cached in memory, failing fast if missing or empty — without relying on runtime hooks or probabilistic skill invocation). Each prompt SHALL capture its agent's full intent directly — with `writer.md` incorporating Sebastian's `application-voice` rules (`da` and `en`), `auditor.md` incorporating `blader/humanizer` anti-AI rules, `scorer.md` incorporating diverse transferable-skill examples plus clear senior+ and non-technical tell-tales, and `ideation.md` instructing the agent to detect facts that add to or drift from `MasterProfile` while treating the human as the final source of truth.

#### Scenario: Load all required agent system prompts automatically at startup
- **WHEN** the prompt loader initializes at startup for `scorer`, `planner`, `writer`, `auditor`, `ideation`, and `intent_router`
- **THEN** each agent MUST load and cache a non-empty system prompt from `src/job_agent/prompts/<agent>.md`

#### Scenario: Fail loudly if a required system prompt file is missing or empty
- **WHEN** a required prompt file in `src/job_agent/prompts/` is missing or contains only whitespace
- **THEN** startup prompt loading MUST raise a `FileNotFoundError` or `ValueError` identifying the missing prompt
