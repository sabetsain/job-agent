"""Remotive public JSON API job source adapter."""

from __future__ import annotations

from typing import Any

import httpx

from job_agent.schemas.jobs import RawJob, RemotiveConfig, WorkMode
from job_agent.sources.base import html_to_text, open_http_client, parse_timestamp


class RemotiveSource:
    """Fetch remote job postings from Remotive with a single daily GET call."""

    name: str = "remotive"

    def __init__(
        self,
        config: RemotiveConfig | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.config = config or RemotiveConfig()
        self._client = client

    def fetch(self) -> list[RawJob]:
        """Perform a single GET request to Remotive and map items to RawJob."""
        params: dict[str, str] = {}
        if self.config.category:
            params["category"] = self.config.category

        with open_http_client(self._client) as client:
            response = client.get(self.config.endpoint, params=params)
            response.raise_for_status()
            payload = response.json()

        items = payload.get("jobs", []) if isinstance(payload, dict) else []
        if not isinstance(items, list):
            raise ValueError("Remotive payload 'jobs' field must be a list")

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
        job_id = item.get("id")
        return RawJob(
            source=self.name,
            title=title,
            company=str(item.get("company_name") or "").strip(),
            location=str(item.get("candidate_required_location") or "").strip(),
            work_mode=WorkMode.REMOTE,
            apply_url=str(item.get("url") or "").strip(),
            description=html_to_text(str(item.get("description") or "")),
            posted_at=parse_timestamp(item.get("publication_date")),
            external_id=str(job_id) if job_id is not None else None,
            raw_metadata={
                "category": item.get("category"),
                "job_type": item.get("job_type"),
                "tags": item.get("tags", []),
            },
        )
