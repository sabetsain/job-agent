"""LLM configuration and OpenCode Go structured output client."""

from job_agent.llm.config import DEFAULT_OPENCODE_BASE_URL, LLMConfig, load_llm_config

__all__ = [
    "DEFAULT_OPENCODE_BASE_URL",
    "LLMConfig",
    "load_llm_config",
]
