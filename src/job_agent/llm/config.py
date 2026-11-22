"""Dual-tier OpenCode Go LLMConfig schema and YAML loader."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from job_agent.schemas._common import NonEmptyStr, load_yaml_mapping

DEFAULT_OPENCODE_BASE_URL = "https://opencode.ai/zen/go/v1"


class LLMConfig(BaseModel):
    """Configuration for dual-tier OpenCode Go models and structured outputs."""

    base_url: NonEmptyStr = DEFAULT_OPENCODE_BASE_URL
    api_key_env: NonEmptyStr = "OPENCODE_API_KEY"
    scoring_model: NonEmptyStr = "deepseek-v4.1-flash"
    reasoning_model: NonEmptyStr = "deepseek-v4-pro"
    scoring_base_url: NonEmptyStr | None = None
    scoring_api_key_env: NonEmptyStr | None = None
    reasoning_effort: Literal["low", "medium", "high"] | None = None
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    timeout_seconds: float = Field(default=60.0, gt=0.0)
    max_parse_retries: int = Field(default=2, ge=0)
    structured_output_method: Literal["json_schema", "function_calling"] = "json_schema"


def load_llm_config(path: Path | str) -> LLMConfig:
    """Load and validate LLMConfig from a YAML file."""
    data = load_yaml_mapping(path)
    return LLMConfig.model_validate(data)
