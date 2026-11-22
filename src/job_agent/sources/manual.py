"""Manual Drop ingestion for user-supplied job text or direct URLs."""

from __future__ import annotations

from datetime import datetime
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup

from job_agent.schemas.jobs import JobPosting, RawJob, WorkMode
from job_agent.sources.base import open_http_client
from job_agent.sources.normalize import normalize_raw_job

_DEFAULT_MANUAL_HINT = (
    "Paste or provide the raw job description text directly instead (e.g., via --text or --file)."
)

_CAPTCHA_MARKERS = (
    "g-recaptcha",
    "h-captcha",
    "hcaptcha",
    "cf-turnstile",
    "cf-challenge",
    "challenge-platform",
    "verify you are human",
    "attention required! | cloudflare",
    "enable javascript and cookies to continue",
    "px-captcha",
    "datadome",
)

_LOGIN_PATH_MARKERS = (
    "/login",
    "/signin",
    "/sign-in",
    "/auth",
    "/sso",
    "/uas/login",
    "accounts.google.com",
)

_LOGIN_TEXT_MARKERS = (
    "sign in to view",
    "log in to view",
    "log in to apply",
    "sign in to apply",
)

_MIN_EXTRACTED_DESCRIPTION_CHARS = 40
_MIN_EXTRACTED_DESCRIPTION_WORDS = 5


class ManualDropError(Exception):
    """Raised when a Manual Drop URL or raw payload cannot be ingested."""

    def __init__(self, reason: str, hint: str = _DEFAULT_MANUAL_HINT) -> None:
        self.reason = reason
        self.hint = hint
        message = f"{reason}. {hint}" if hint else reason
        super().__init__(message)


def _has_captcha_markers(html_lower: str) -> bool:
    return any(marker in html_lower for marker in _CAPTCHA_MARKERS)


def _is_login_wall(final_url: str, html_lower: str, soup: BeautifulSoup) -> bool:
    parsed = urlsplit(final_url.lower())
    url_target = f"{parsed.netloc}{parsed.path}"
    if any(marker in url_target for marker in _LOGIN_PATH_MARKERS):
        return True

    if soup.find("input", attrs={"type": "password"}) is not None:
        return True

    return any(marker in html_lower for marker in _LOGIN_TEXT_MARKERS)


def _extract_title_and_description(soup: BeautifulSoup, explicit_title: str) -> tuple[str, str]:
    resolved_title = explicit_title.strip()
    if not resolved_title:
        h1 = soup.find("h1")
        if h1 is not None:
            resolved_title = " ".join(h1.get_text(" ", strip=True).split())
    if not resolved_title and soup.title is not None:
        resolved_title = " ".join(soup.title.get_text(" ", strip=True).split())

    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    main_container = (
        soup.find("main")
        or soup.find("article")
        or soup.find(attrs={"role": "main"})
        or soup.body
        or soup
    )
    description = " ".join(main_container.get_text(separator=" ", strip=True).split())
    return resolved_title, description


def ingest_manual_text(
    title: str,
    company: str,
    apply_url: str,
    description: str,
    location: str = "",
    work_mode: WorkMode = WorkMode.UNKNOWN,
    posted_at: datetime | None = None,
    application_deadline: datetime | None = None,
) -> JobPosting:
    """Normalize a manually submitted raw job description into a JobPosting."""
    clean_title = title.strip()
    clean_description = description.strip()
    if not clean_title:
        raise ManualDropError(
            reason="Job title cannot be empty",
            hint="Provide a non-empty --title for the job posting.",
        )
    if not clean_description:
        raise ManualDropError(
            reason="Job description cannot be empty",
            hint="Provide non-empty job description text.",
        )

    raw = RawJob(
        source="manual",
        title=clean_title,
        company=company.strip(),
        location=location.strip(),
        work_mode=work_mode,
        apply_url=apply_url.strip(),
        description=clean_description,
        posted_at=posted_at,
        application_deadline=application_deadline,
    )
    return normalize_raw_job(raw)


def ingest_manual_url(
    url: str,
    title: str = "",
    company: str = "",
    location: str = "",
    work_mode: WorkMode = WorkMode.UNKNOWN,
    client: httpx.Client | None = None,
) -> JobPosting:
    """Fetch a single job URL politely and normalize it, or fail loudly with ManualDropError."""
    target_url = url.strip()
    if not target_url:
        raise ManualDropError(reason="Job URL cannot be empty")

    try:
        with open_http_client(client, follow_redirects=True, timeout=15.0) as http_client:
            response = http_client.get(target_url, follow_redirects=True)
    except httpx.TimeoutException as exc:
        raise ManualDropError(
            reason=f"Network/HTTP error fetching URL: request timed out ({exc})"
        ) from exc
    except httpx.RequestError as exc:
        raise ManualDropError(
            reason=f"Network/HTTP error fetching URL: {exc}"
        ) from exc

    html_lower = response.text.lower()

    if response.status_code == 401:
        raise ManualDropError(reason="Blocked by login/auth gate (HTTP 401)")

    if response.status_code == 403:
        if _has_captcha_markers(html_lower):
            raise ManualDropError(reason="Blocked by CAPTCHA or anti-bot verification")
        raise ManualDropError(reason="Blocked by login/auth gate (HTTP 403)")

    if response.status_code >= 400:
        raise ManualDropError(
            reason=f"Network/HTTP error fetching URL: HTTP {response.status_code}"
        )

    if _has_captcha_markers(html_lower):
        raise ManualDropError(reason="Blocked by CAPTCHA or anti-bot verification")

    soup = BeautifulSoup(response.text, "html.parser")
    final_url = str(response.url) if response.url else target_url

    if _is_login_wall(final_url, html_lower, soup):
        raise ManualDropError(reason="Redirected to a login/auth page")

    resolved_title, description = _extract_title_and_description(soup, title)
    if (
        not description
        or len(description) < _MIN_EXTRACTED_DESCRIPTION_CHARS
        or len(description.split()) < _MIN_EXTRACTED_DESCRIPTION_WORDS
    ):
        raise ManualDropError(reason="Could not extract a job description from the page")

    if not resolved_title:
        raise ManualDropError(
            reason="Could not extract a job title from the page",
            hint="Supply --title explicitly or paste the raw job description text instead.",
        )

    return ingest_manual_text(
        title=resolved_title,
        company=company,
        apply_url=final_url,
        description=description,
        location=location,
        work_mode=work_mode,
    )
