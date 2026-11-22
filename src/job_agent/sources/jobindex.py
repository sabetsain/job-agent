"""Jobindex dynamic RSS feed adapter."""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Any

import feedparser
import httpx

from job_agent.schemas.jobs import JobindexRssConfig, RawJob, WorkMode
from job_agent.sources.base import html_to_text, open_http_client, parse_timestamp

_DEADLINE_RE = re.compile(
    r"(?:ansøgningsfrist|application\s+deadline|deadline)\s*[:\-]\s*"
    r"(\d{4}-\d{2}-\d{2}|\d{1,2}[./-]\d{1,2}[./-]\d{4})",
    re.IGNORECASE,
)


def _struct_time_to_utc(value: Any) -> datetime | None:
    if isinstance(value, time.struct_time):
        return datetime(*value[:6], tzinfo=timezone.utc)
    return None


def _parse_deadline_date(raw_date: str) -> datetime | None:
    candidate = raw_date.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", candidate):
        return datetime.strptime(candidate, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    for fmt in ("%d.%m.%Y", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(candidate, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _extract_deadline(entry: Any, description: str) -> datetime | None:
    for field in ("application_deadline_parsed", "deadline_parsed", "expires_parsed"):
        parsed = _struct_time_to_utc(entry.get(field))
        if parsed is not None:
            return parsed

    for field in ("application_deadline", "deadline", "expires"):
        raw = entry.get(field)
        if raw:
            parsed = parse_timestamp(raw) or _parse_deadline_date(str(raw))
            if parsed is not None:
                return parsed

    match = _DEADLINE_RE.search(description)
    if match:
        return _parse_deadline_date(match.group(1))
    return None


def _extract_company(entry: Any) -> str:
    for key in ("company", "author", "dc_creator"):
        val = entry.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()

    author_detail = entry.get("author_detail")
    if isinstance(author_detail, dict):
        name = author_detail.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()

    return ""


class JobindexRssSource:
    """Fetch job postings from configured Jobindex RSS feed URLs."""

    name: str = "jobindex_rss"

    def __init__(
        self,
        config: JobindexRssConfig | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.config = config or JobindexRssConfig()
        self._client = client

    def fetch(self) -> list[RawJob]:
        """Fetch and parse all configured Jobindex RSS feed URLs."""
        if not self.config.feed_urls:
            return []

        jobs: list[RawJob] = []
        with open_http_client(self._client) as client:
            for feed_url in self.config.feed_urls:
                response = client.get(feed_url)
                response.raise_for_status()
                parsed_feed = feedparser.parse(response.text)

                if getattr(parsed_feed, "bozo", False) and not parsed_feed.entries:
                    exc = getattr(parsed_feed, "bozo_exception", "malformed RSS")
                    raise ValueError(f"Failed to parse RSS feed {feed_url}: {exc}")

                for entry in parsed_feed.entries:
                    title = str(entry.get("title") or "").strip()
                    if not title:
                        continue
                    jobs.append(self._map_entry(entry, title, feed_url))

        return jobs

    def _map_entry(self, entry: Any, title: str, feed_url: str) -> RawJob:
        raw_summary = entry.get("summary") or entry.get("description") or ""
        if not raw_summary and entry.get("content"):
            first_content = entry.get("content")[0]
            if isinstance(first_content, dict):
                raw_summary = first_content.get("value") or ""

        description = html_to_text(str(raw_summary))
        posted_at = (
            _struct_time_to_utc(entry.get("published_parsed"))
            or _struct_time_to_utc(entry.get("updated_parsed"))
            or parse_timestamp(entry.get("published") or entry.get("updated"))
        )
        deadline = _extract_deadline(entry, description)
        external_id = entry.get("id") or entry.get("guid")

        return RawJob(
            source=self.name,
            title=title,
            company=_extract_company(entry),
            location=str(entry.get("location") or "").strip(),
            work_mode=WorkMode.UNKNOWN,
            apply_url=str(entry.get("link") or "").strip(),
            description=description,
            posted_at=posted_at,
            application_deadline=deadline,
            external_id=str(external_id) if external_id else None,
            raw_metadata={
                "feed_url": feed_url,
                "description_is_partial": len(description) < 200,
            },
        )
