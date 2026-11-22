"""Jobicy public JSON API job source adapter with rate-limit & 429 Retry-After handling."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from job_agent.schemas.jobs import JobicyConfig, RawJob, WorkMode
from job_agent.sources.base import html_to_text, open_http_client, parse_timestamp


def _parse_retry_after(header_value: str | None, fallback_seconds: float) -> float:
    """Parse an HTTP Retry-After header (seconds or HTTP-date) into delay seconds."""
    if not header_value or not header_value.strip():
        return fallback_seconds

    raw = header_value.strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        pass

    try:
        retry_dt = parsedate_to_datetime(raw)
        if retry_dt.tzinfo is None or retry_dt.utcoffset() is None:
            retry_dt = retry_dt.replace(tzinfo=timezone.utc)
        delta = (retry_dt - datetime.now(timezone.utc)).total_seconds()
        return max(0.0, delta)
    except (TypeError, ValueError):
        return fallback_seconds


class JobicySource:
    """Fetch remote job postings from the Jobicy public JSON API."""

    name: str = "jobicy"

    def __init__(
        self,
        config: JobicyConfig | None = None,
        client: httpx.Client | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        clock_fn: Callable[[], float] = time.monotonic,
        max_retries: int = 2,
    ) -> None:
        self.config = config or JobicyConfig()
        self._client = client
        self._sleep_fn = sleep_fn
        self._clock_fn = clock_fn
        self._max_retries = max_retries
        self._last_request_ts: float | None = None

    def _build_params(self) -> dict[str, Any]:
        params: dict[str, Any] = {"count": self.config.count}
        if self.config.geo:
            params["geo"] = self.config.geo
        if self.config.industry:
            params["industry"] = self.config.industry
        if self.config.tag:
            params["tag"] = self.config.tag
        return params

    def _enforce_request_spacing(self) -> None:
        min_interval = self.config.min_request_interval_seconds
        if self._last_request_ts is not None and min_interval > 0:
            elapsed = self._clock_fn() - self._last_request_ts
            remaining = min_interval - elapsed
            if remaining > 0:
                self._sleep_fn(remaining)

    def fetch(self) -> list[RawJob]:
        """Fetch Jobicy listings while honoring spacing and HTTP 429 Retry-After."""
        params = self._build_params()

        with open_http_client(self._client) as client:
            response: httpx.Response | None = None
            for attempt in range(self._max_retries + 1):
                if attempt == 0:
                    self._enforce_request_spacing()
                self._last_request_ts = self._clock_fn()
                response = client.get(self.config.endpoint, params=params)

                if response.status_code != 429:
                    break

                if attempt >= self._max_retries:
                    response.raise_for_status()

                retry_delay = _parse_retry_after(
                    response.headers.get("Retry-After"),
                    fallback_seconds=max(self.config.min_request_interval_seconds, 1.0),
                )
                delay = max(retry_delay, self.config.min_request_interval_seconds)
                if delay > 0:
                    self._sleep_fn(delay)

            assert response is not None
            response.raise_for_status()
            payload = response.json()

        items = payload.get("jobs", []) if isinstance(payload, dict) else []
        if not isinstance(items, list):
            raise ValueError("Jobicy payload 'jobs' field must be a list")

        jobs: list[RawJob] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            title = str(item.get("jobTitle") or item.get("title") or "").strip()
            if not title:
                continue
            jobs.append(self._map_item(item, title))
        return jobs

    def _map_item(self, item: dict[str, Any], title: str) -> RawJob:
        job_id = item.get("id")
        return RawJob(
            source=self.name,
            title=title,
            company=str(item.get("companyName") or item.get("company_name") or "").strip(),
            location=str(item.get("jobGeo") or item.get("location") or "").strip(),
            work_mode=WorkMode.REMOTE,
            apply_url=str(item.get("url") or "").strip(),
            description=html_to_text(
                str(item.get("jobDescription") or item.get("jobExcerpt") or item.get("description") or "")
            ),
            posted_at=parse_timestamp(item.get("pubDate") or item.get("publication_date")),
            external_id=str(job_id) if job_id is not None else None,
            raw_metadata={
                "jobLevel": item.get("jobLevel"),
                "jobIndustry": item.get("jobIndustry"),
                "jobType": item.get("jobType"),
            },
        )
