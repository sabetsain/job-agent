"""Startup-loaded, cached loader for dedicated agent system prompts."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

AgentPromptName = Literal[
    "scorer",
    "planner",
    "writer",
    "auditor",
    "ideation",
    "intent_router",
]

REQUIRED_PROMPTS: tuple[AgentPromptName, ...] = (
    "scorer",
    "planner",
    "writer",
    "auditor",
    "ideation",
    "intent_router",
)

PROMPTS_DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=4)
def load_all_prompts(prompts_dir: Path | str | None = None) -> dict[AgentPromptName, str]:
    """Load and cache all required agent system prompts, failing fast if missing/empty."""
    base_dir = Path(prompts_dir) if prompts_dir is not None else PROMPTS_DIR
    loaded: dict[AgentPromptName, str] = {}

    for name in REQUIRED_PROMPTS:
        path = base_dir / f"{name}.md"
        if not path.is_file():
            raise FileNotFoundError(
                f"Required system prompt file for agent '{name}' not found at {path}"
            )
        content = path.read_text(encoding="utf-8").strip()
        if not content:
            raise ValueError(
                f"Required system prompt file for agent '{name}' at {path} is empty"
            )
        loaded[name] = content

    return loaded


def get_prompt(name: AgentPromptName, prompts_dir: Path | str | None = None) -> str:
    """Return the cached system prompt text for a given agent."""
    prompts = load_all_prompts(prompts_dir)
    if name not in prompts:
        raise KeyError(f"Unknown agent prompt name: {name!r}")
    return prompts[name]
