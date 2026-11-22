"""Arbeitnow public JSON API job source adapter."""

from __future__ import annotations

from typing import Any

import httpx

from job_agent.schemas.jobs import ArbeitnowConfig, RawJob, WorkMode
from job_agent.sources.base import html_to_text, open_http_client, parse_timestamp


class ArbeitnowSource:
    """Fetch job postings from the Arbeitnow public JSON board API."""

    name: str = "arbeitnow"

    def __init__(
        self,
        config: ArbeitnowConfig | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.config = config or ArbeitnowConfig()
        self._client = client

    def fetch(self) -> list[RawJob]:
        """Perform a single GET request to Arbeitnow and map items to RawJob."""
        with open_http_client(self._client) as client:
            response = client.get(self.config.endpoint)
            response.raise_for_status()
            payload = response.json()

        items = payload.get("data", []) if isinstance(payload, dict) else []
        if not isinstance(items, list):
            raise ValueError("Arbeitnow payload 'data' field must be a list")

        jobs: list[RawJob] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            jobs.append(self._map_item(item, title))
        return jobs

    def _map_item(self, item: dict[str, Any], title: str) -> RawJob:
        work_mode = WorkMode.REMOTE if item.get("remote") is True else WorkMode.UNKNOWN
        slug = item.get("slug")
        return RawJob(
            source=self.name,
            title=title,
            company=str(item.get("company_name") or "").strip(),
            location=str(item.get("location") or "").strip(),
            work_mode=work_mode,
            apply_url=str(item.get("url") or "").strip(),
            description=html_to_text(str(item.get("description") or "")),
            posted_at=parse_timestamp(item.get("created_at")),
            external_id=str(slug) if slug is not None else None,
            raw_metadata={
                "tags": item.get("tags", []),
                "job_types": item.get("job_types", []),
            },
        )
