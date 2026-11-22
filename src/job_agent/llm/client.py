"""Dual-tier OpenCode Go LLM client with native LangChain structured output enforcement."""

from __future__ import annotations

import os
from typing import Any, Literal, Protocol, TypeVar

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, SecretStr, ValidationError

from job_agent.llm.config import LLMConfig

ModelTier = Literal["scoring", "reasoning"]
T = TypeVar("T", bound=BaseModel)


class LLMConfigurationError(RuntimeError):
    """Raised when required LLM provider configuration or API key env var is missing."""


class StructuredOutputError(RuntimeError):
    """Raised when structured output parsing/validation fails after bounded retries."""


class StructuredLLMClient(Protocol):
    """Injectable protocol for structured Pydantic outputs across all LLM nodes."""

    def invoke_structured(
        self,
        tier: ModelTier,
        system_prompt: str,
        user_prompt: str,
        schema: type[T],
    ) -> T:
        """Invoke the configured model tier and return a validated Pydantic instance."""
        ...


def _resolve_tier_settings(config: LLMConfig, tier: ModelTier) -> tuple[str, str, str]:
    """Return (model_name, base_url, api_key) for the requested tier, failing loudly if unset."""
    if tier == "scoring":
        model_name = config.scoring_model
        base_url = config.scoring_base_url or config.base_url
        api_key_env = config.scoring_api_key_env or config.api_key_env
    else:
        model_name = config.reasoning_model
        base_url = config.base_url
        api_key_env = config.api_key_env

    api_key = os.environ.get(api_key_env, "").strip()
    if not api_key:
        raise LLMConfigurationError(
            f"Missing required environment variable '{api_key_env}' for LLM tier '{tier}'."
        )
    return model_name, base_url, api_key


def build_chat_model(config: LLMConfig, tier: ModelTier) -> ChatOpenAI:
    """Construct a ChatOpenAI client configured for the requested OpenCode Go tier."""
    model_name, base_url, api_key = _resolve_tier_settings(config, tier)
    kwargs: dict[str, Any] = {
        "model": model_name,
        "base_url": base_url,
        "api_key": SecretStr(api_key),
        "temperature": config.temperature,
        "timeout": config.timeout_seconds,
    }
    if tier == "reasoning" and config.reasoning_effort is not None:
        kwargs["reasoning_effort"] = config.reasoning_effort
    return ChatOpenAI(**kwargs)


class OpenCodeLLMClient:
    """OpenCode Go dual-tier client enforcing LangChain native structured outputs."""

    def __init__(self, config: LLMConfig) -> None:
        self._config = config
        self._models: dict[ModelTier, Any] = {}

    def _get_model(self, tier: ModelTier) -> Any:
        if tier not in self._models:
            self._models[tier] = build_chat_model(self._config, tier)
        return self._models[tier]

    def invoke_structured(
        self,
        tier: ModelTier,
        system_prompt: str,
        user_prompt: str,
        schema: type[T],
    ) -> T:
        """Call native with_structured_output with bounded Pydantic parse-repair retries."""
        model = self._get_model(tier)
        runnable = model.with_structured_output(
            schema,
            method=self._config.structured_output_method,
            include_raw=True,
        )

        messages: list[BaseMessage] = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        last_error: Exception | None = None

        for attempt in range(self._config.max_parse_retries + 1):
            try:
                result = runnable.invoke(messages)
            except (ValidationError, ValueError, TypeError) as exc:
                last_error = exc
                if attempt >= self._config.max_parse_retries:
                    break
                messages.append(
                    HumanMessage(
                        content=(
                            "Your previous response failed structured schema validation: "
                            f"{exc}. Return strictly valid output matching {schema.__name__}."
                        )
                    )
                )
                continue

            if isinstance(result, schema):
                return result

            if isinstance(result, dict) and "parsed" in result:
                parsing_error = result.get("parsing_error")
                parsed = result.get("parsed")
                if parsing_error is None and parsed is not None:
                    if isinstance(parsed, schema):
                        return parsed
                    return schema.model_validate(parsed)

                err_text = str(parsing_error or "Model returned null parsed output")
                last_error = ValueError(err_text)
                if attempt >= self._config.max_parse_retries:
                    break
                messages.append(
                    HumanMessage(
                        content=(
                            "Your previous response failed structured schema validation: "
                            f"{err_text}. Fix all field types and required fields for "
                            f"{schema.__name__}."
                        )
                    )
                )
                continue

            try:
                return schema.model_validate(result)
            except ValidationError as exc:
                last_error = exc
                if attempt >= self._config.max_parse_retries:
                    break
                messages.append(
                    HumanMessage(
                        content=(
                            "Your previous response failed Pydantic validation: "
                            f"{exc}. Return strictly valid output matching {schema.__name__}."
                        )
                    )
                )

        raise StructuredOutputError(
            f"Failed to obtain valid {schema.__name__} after "
            f"{self._config.max_parse_retries + 1} attempts: {last_error}"
        )
