"""Version-controlled dedicated system prompts loaded at startup."""

from job_agent.prompts.loader import (
    PROMPTS_DIR,
    REQUIRED_PROMPTS,
    AgentPromptName,
    get_prompt,
    load_all_prompts,
)

__all__ = [
    "AgentPromptName",
    "PROMPTS_DIR",
    "REQUIRED_PROMPTS",
    "get_prompt",
    "load_all_prompts",
]
