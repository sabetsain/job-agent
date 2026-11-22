"""Base JobSource protocol and shared HTML/timestamp helpers."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Protocol, runtime_checkable

import httpx
from bs4 import BeautifulSoup

from job_agent.schemas.jobs import RawJob

DEFAULT_REQUEST_TIMEOUT_SECONDS = 20.0
DEFAULT_USER_AGENT = "job-agent/0.1 (+https://github.com/job-agent)"


@contextmanager
def open_http_client(
    client: httpx.Client | None = None,
    *,
    follow_redirects: bool = False,
    timeout: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
) -> Iterator[httpx.Client]:
    """Yield an injected httpx.Client or manage a temporary client instance."""
    if client is not None:
        yield client
        return

    with httpx.Client(
        follow_redirects=follow_redirects,
        timeout=timeout,
        headers={"User-Agent": DEFAULT_USER_AGENT},
    ) as owned_client:
        yield owned_client


@runtime_checkable
class JobSource(Protocol):
    """Protocol implemented by all job discovery adapters."""

    name: str

    def fetch(self) -> list[RawJob]:
        """Fetch raw job postings from the configured source."""
        ...


def html_to_text(html: str) -> str:
    """Strip HTML tags and collapse whitespace into clean plain text."""
    if not html or not html.strip():
        return ""

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    text = soup.get_text(separator=" ", strip=True)
    return " ".join(text.split())


def parse_timestamp(value: Any) -> datetime | None:
    """Parse unix timestamps, ISO-8601 strings, or RFC 2822 dates into UTC datetimes."""
    if value is None:
        return None

    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e12:
            ts /= 1000.0
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None

        if text.isdigit():
            return parse_timestamp(int(text))

        iso_candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
        try:
            parsed = datetime.fromisoformat(iso_candidate)
            return parse_timestamp(parsed)
        except ValueError:
            pass

        try:
            parsed_rfc = parsedate_to_datetime(text)
            return parse_timestamp(parsed_rfc)
        except (TypeError, ValueError):
            return None

    return None
