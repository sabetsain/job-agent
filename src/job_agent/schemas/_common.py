"""Shared validation and YAML loading helpers for domain schemas."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

import yaml
from pydantic import AfterValidator


def _require_non_empty(value: str) -> str:
    """Ensure a string contains non-whitespace characters and return it stripped."""
    stripped = value.strip()
    if not stripped:
        raise ValueError("must be a non-empty string")
    return stripped


def _ensure_utc_datetime(value: datetime) -> datetime:
    """Attach UTC tzinfo to naive datetimes; preserve already-aware datetimes."""
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value


NonEmptyStr = Annotated[str, AfterValidator(_require_non_empty)]
AwareDatetime = Annotated[datetime, AfterValidator(_ensure_utc_datetime)]


def load_yaml_mapping(path: Path | str) -> dict[str, Any]:
    """Load a YAML file and ensure its top-level value is a mapping."""
    file_path = Path(path)
    raw = yaml.safe_load(file_path.read_text(encoding="utf-8"))
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(
            f"Expected a YAML mapping at top level in {file_path}, got {type(raw).__name__}"
        )
    return raw
