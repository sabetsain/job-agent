"""Unit tests for dual-tier OpenCode Go client and startup-loaded system prompts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from job_agent.llm import (
    DEFAULT_OPENCODE_BASE_URL,
    LLMConfig,
    LLMConfigurationError,
    OpenCodeLLMClient,
    StructuredOutputError,
    build_chat_model,
)
from job_agent.prompts import REQUIRED_PROMPTS, get_prompt, load_all_prompts


class _SamplePayload(BaseModel):
    label: str
    score: int


class _FakeRunnable:
    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.calls: list[Any] = []

    def invoke(self, messages: Any) -> Any:
        self.calls.append(messages)
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class _FakeChatModel:
    def __init__(self, runnable: _FakeRunnable) -> None:
        self._runnable = runnable
        self.with_structured_calls: list[dict[str, Any]] = []

    def with_structured_output(self, schema: type[BaseModel], **kwargs: Any) -> _FakeRunnable:
        self.with_structured_calls.append({"schema": schema, **kwargs})
        return self._runnable


def test_load_all_prompts_loads_and_caches_all_six_required_prompts() -> None:
    load_all_prompts.cache_clear()
    prompts = load_all_prompts()

    assert set(prompts.keys()) == set(REQUIRED_PROMPTS)
    for name in REQUIRED_PROMPTS:
        text = get_prompt(name)
        assert text == prompts[name]
        assert len(text) > 80

    # Key domain rules embedded in dedicated prompts
    assert "Kind Regards," in prompts["writer"]
    assert "Med venlig hilsen," in prompts["writer"]
    assert "blader/humanizer" in prompts["auditor"]
    assert "is_technical" in prompts["scorer"]
    assert "final source of truth" in prompts["ideation"]
    assert "CHAT" in prompts["intent_router"]
    assert "REITERATE" in prompts["intent_router"]


def test_load_all_prompts_fails_loudly_on_missing_or_empty_prompt(tmp_path: Path) -> None:
    load_all_prompts.cache_clear()
    for name in REQUIRED_PROMPTS[:-1]:
        (tmp_path / f"{name}.md").write_text(f"Prompt for {name}", encoding="utf-8")

    with pytest.raises(FileNotFoundError, match=REQUIRED_PROMPTS[-1]):
        load_all_prompts(tmp_path)

    load_all_prompts.cache_clear()
    (tmp_path / f"{REQUIRED_PROMPTS[-1]}.md").write_text("   \n\t ", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        load_all_prompts(tmp_path)
    load_all_prompts.cache_clear()


def test_build_chat_model_fails_loudly_when_api_key_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENCODE_API_KEY", raising=False)
    monkeypatch.delenv("SCORING_API_KEY", raising=False)
    cfg = LLMConfig(scoring_model="free-model", reasoning_model="paid-model")

    with pytest.raises(LLMConfigurationError, match="OPENCODE_API_KEY"):
        build_chat_model(cfg, "reasoning")

    cfg_override = LLMConfig(
        scoring_model="free-model",
        reasoning_model="paid-model",
        scoring_api_key_env="SCORING_API_KEY",
    )
    with pytest.raises(LLMConfigurationError, match="SCORING_API_KEY"):
        build_chat_model(cfg_override, "scoring")


def test_build_chat_model_wires_dual_tier_opencode_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENCODE_API_KEY", "test-secret-key")
    monkeypatch.setenv("SCORING_API_KEY", "free-tier-key")
    cfg = LLMConfig(
        base_url=DEFAULT_OPENCODE_BASE_URL,
        scoring_model="deepseek-v4.1-flash",
        reasoning_model="deepseek-v4-pro",
        scoring_base_url="https://free.opencode.example/v1",
        scoring_api_key_env="SCORING_API_KEY",
        reasoning_effort="medium",
        temperature=0.1,
        timeout_seconds=45.0,
    )

    scoring_llm = build_chat_model(cfg, "scoring")
    reasoning_llm = build_chat_model(cfg, "reasoning")

    assert scoring_llm.model_name == "deepseek-v4.1-flash"
    assert scoring_llm.openai_api_base == "https://free.opencode.example/v1"
    assert scoring_llm.openai_api_key.get_secret_value() == "free-tier-key"

    assert reasoning_llm.model_name == "deepseek-v4-pro"
    assert reasoning_llm.openai_api_base == DEFAULT_OPENCODE_BASE_URL
    assert reasoning_llm.openai_api_key.get_secret_value() == "test-secret-key"


def test_invoke_structured_returns_validated_model_and_retries_on_parse_error() -> None:
    cfg = LLMConfig(
        scoring_model="free-model",
        reasoning_model="paid-model",
        max_parse_retries=2,
    )
    client = OpenCodeLLMClient(cfg)

    fake_runnable = _FakeRunnable(
        [
            {"raw": None, "parsed": None, "parsing_error": ValueError("score must be int")},
            {"raw": None, "parsed": _SamplePayload(label="ok", score=9), "parsing_error": None},
        ]
    )
    fake_model = _FakeChatModel(fake_runnable)
    client._models["scoring"] = fake_model

    result = client.invoke_structured(
        "scoring",
        "system prompt",
        "user prompt",
        _SamplePayload,
    )
    assert result == _SamplePayload(label="ok", score=9)
    assert len(fake_runnable.calls) == 2
    assert "score must be int" in fake_runnable.calls[1][-1].content
    assert fake_model.with_structured_calls[0]["method"] == "json_schema"
    assert fake_model.with_structured_calls[0]["include_raw"] is True


def test_invoke_structured_raises_after_exhausting_parse_retries() -> None:
    cfg = LLMConfig(
        scoring_model="free-model",
        reasoning_model="paid-model",
        max_parse_retries=1,
    )
    client = OpenCodeLLMClient(cfg)

    fake_runnable = _FakeRunnable(
        [
            {"raw": None, "parsed": None, "parsing_error": ValueError("bad json 1")},
            {"raw": None, "parsed": None, "parsing_error": ValueError("bad json 2")},
        ]
    )
    client._models["reasoning"] = _FakeChatModel(fake_runnable)

    with pytest.raises(StructuredOutputError, match="after 2 attempts"):
        client.invoke_structured("reasoning", "sys", "usr", _SamplePayload)
    assert len(fake_runnable.calls) == 2
