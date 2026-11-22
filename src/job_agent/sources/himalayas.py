"""Himalayas JSON API job source adapter."""

from __future__ import annotations

import os
from typing import Any

import httpx

from job_agent.schemas.jobs import HimalayasConfig, RawJob, WorkMode
from job_agent.sources.base import html_to_text, open_http_client, parse_timestamp


class HimalayasSource:
    """Fetch remote job postings from the Himalayas public/optional-auth JSON API."""

    name: str = "himalayas"

    def __init__(
        self,
        config: HimalayasConfig | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.config = config or HimalayasConfig()
        self._client = client

    def fetch(self) -> list[RawJob]:
        """Perform a GET request to Himalayas with optional Bearer token auth."""
        headers: dict[str, str] = {}
        if self.config.api_key_env:
            token = os.environ.get(self.config.api_key_env, "").strip()
            if token:
                headers["Authorization"] = f"Bearer {token}"

        params = {"limit": self.config.limit}

        with open_http_client(self._client) as client:
            response = client.get(self.config.endpoint, params=params, headers=headers)
            response.raise_for_status()
            payload = response.json()

        items = payload.get("jobs", []) if isinstance(payload, dict) else []
        if not isinstance(items, list):
            raise ValueError("Himalayas payload 'jobs' field must be a list")

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
        restrictions = item.get("locationRestrictions")
        if isinstance(restrictions, list) and restrictions:
            location = ", ".join(str(loc).strip() for loc in restrictions if str(loc).strip())
        else:
            location = str(item.get("location") or "").strip()

        raw_work_mode = str(item.get("work_mode") or item.get("workplaceType") or "").strip().lower()
        work_mode = {
            "remote": WorkMode.REMOTE,
            "hybrid": WorkMode.HYBRID,
            "onsite": WorkMode.ONSITE,
        }.get(raw_work_mode, WorkMode.REMOTE)

        external_id = item.get("guid") or item.get("id")
        return RawJob(
            source=self.name,
            title=title,
            company=str(item.get("companyName") or item.get("company_name") or "").strip(),
            location=location,
            work_mode=work_mode,
            apply_url=str(
                item.get("applicationLink") or item.get("guid") or item.get("url") or ""
            ).strip(),
            description=html_to_text(str(item.get("description") or item.get("excerpt") or "")),
            posted_at=parse_timestamp(
                item.get("pubDate") or item.get("publishedAt") or item.get("created_at")
            ),
            external_id=str(external_id) if external_id is not None else None,
            raw_metadata={
                "categories": item.get("categories", []),
                "seniority": item.get("seniority", []),
            },
        )
