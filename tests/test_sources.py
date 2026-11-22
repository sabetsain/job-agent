"""Intent-rooted unit tests for job discovery adapters, Manual Drop, and normalization."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx
import pytest
import respx

from job_agent.schemas.jobs import (
    ArbeitnowConfig,
    HimalayasConfig,
    JobicyConfig,
    JobindexRssConfig,
    RawJob,
    RemotiveConfig,
    SourcesConfig,
    WorkMode,
)
from job_agent.sources import (
    ArbeitnowSource,
    HimalayasSource,
    JobicySource,
    JobindexRssSource,
    ManualDropError,
    RemotiveSource,
    build_enabled_sources,
    detect_language,
    fetch_all_sources,
    generate_job_id,
    html_to_text,
    ingest_manual_text,
    ingest_manual_url,
    normalize_raw_job,
)

# ---------------------------------------------------------------------------
# Deterministic job_id & language detection
# ---------------------------------------------------------------------------


def test_generate_job_id_is_deterministic_16_char_hex_and_canonicalizes_urls() -> None:
    id1 = generate_job_id(
        source="Arbeitnow",
        apply_url="HTTPS://Example.COM/jobs/junior-dev/?utm_source=feed&id=42#top",
    )
    id2 = generate_job_id(
        source="arbeitnow",
        apply_url="https://example.com/jobs/junior-dev?id=42&fbclid=abc",
    )
    id_different_query = generate_job_id(
        source="arbeitnow",
        apply_url="https://example.com/jobs/junior-dev?id=99",
    )
    id_different_source = generate_job_id(
        source="remotive",
        apply_url="https://example.com/jobs/junior-dev?id=42",
    )

    assert len(id1) == 16
    assert id1 == id1.lower()
    assert int(id1, 16) >= 0
    assert id1 == id2
    assert id1 != id_different_query
    assert id1 != id_different_source


def test_generate_job_id_fallback_when_url_missing() -> None:
    id1 = generate_job_id(
        source="manual",
        apply_url="   ",
        company="  Nordic   Cloud Labs ",
        title="Junior   Software Engineer",
    )
    id2 = generate_job_id(
        source="manual",
        apply_url="",
        company="nordic cloud labs",
        title="junior software engineer",
    )
    id_other_title = generate_job_id(
        source="manual",
        apply_url="",
        company="nordic cloud labs",
        title="Associate Solutions Architect",
    )

    assert len(id1) == 16
    assert id1 == id2
    assert id1 != id_other_title

    import hashlib

    expected = hashlib.sha256(b"manual\x1fnordic cloud labs\x1fjunior software engineer").hexdigest()[:16]
    assert id1 == expected


def test_detect_language_danish_deterministic_even_with_english_tech_terms() -> None:
    title = "Softwareudvikler til vores team i København"
    description = (
        "Vi søger en nyuddannet udvikler med erfaring i Python, Kubernetes, Docker, "
        "CI/CD og cloud-arkitektur. Du kommer til at arbejde tæt sammen med vores "
        "produktteam på spændende løsninger og automatisering."
    )

    results = {detect_language(title, description) for _ in range(5)}
    assert results == {"da"}


def test_detect_language_english_mentioning_copenhagen_not_misclassified() -> None:
    title = "Junior Backend Engineer (København)"
    description = (
        "We are looking for a Junior Backend Engineer to join our engineering team in "
        "Copenhagen. Contact Søren for questions about Python microservices and APIs."
    )

    results = {detect_language(title, description) for _ in range(5)}
    assert results == {"en"}


def test_detect_language_short_or_empty_falls_back_to_en() -> None:
    assert detect_language("", "") == "en"
    assert detect_language("AI", "ML") == "en"
    assert detect_language("Softwareudvikler til København", "") == "da"


def test_normalize_raw_job_populates_id_language_and_preserves_fields() -> None:
    posted = datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc)
    deadline = datetime(2026, 11, 30, 23, 59, tzinfo=timezone.utc)
    raw = RawJob(
        source="jobindex_rss",
        title="Junior Udvikler",
        company="København Tech ApS",
        location="København",
        work_mode=WorkMode.HYBRID,
        apply_url="https://www.jobindex.dk/jobannonce/12345",
        description="Vi søger en junior udvikler med interesse for Python og data.",
        posted_at=posted,
        application_deadline=deadline,
        external_id="12345",
        raw_metadata={"feed_url": "https://www.jobindex.dk/jobsoegning.rss"},
    )

    posting = normalize_raw_job(raw)
    assert posting.job_id == generate_job_id(raw.source, raw.apply_url)
    assert posting.language == "da"
    assert posting.posted_at == posted
    assert posting.application_deadline == deadline
    assert posting.external_id == "12345"
    assert posting.raw_metadata["feed_url"] == "https://www.jobindex.dk/jobsoegning.rss"


def test_html_to_text_strips_tags_scripts_and_collapses_whitespace() -> None:
    html = (
        "<div><h1>Junior   Engineer</h1><script>alert('x')</script>"
        "<style>.a{color:red}</style><p>Build <strong>Python</strong> APIs.</p></div>"
    )
    assert html_to_text(html) == "Junior Engineer Build Python APIs."


# ---------------------------------------------------------------------------
# JSON API & RSS Adapters
# ---------------------------------------------------------------------------


@respx.mock
def test_arbeitnow_adapter_maps_payload_and_strips_html() -> None:
    endpoint = "https://www.arbeitnow.com/api/job-board-api"
    respx.get(endpoint).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "slug": "junior-python-dev-123",
                        "company_name": "Nordic Systems",
                        "title": "Junior Python Developer",
                        "description": "<p>Build <b>backend</b> services in Europe.</p>",
                        "remote": True,
                        "url": "https://www.arbeitnow.com/jobs/junior-python-dev-123",
                        "tags": ["Python", "Backend"],
                        "job_types": ["Full-time"],
                        "location": "Berlin, Germany",
                        "created_at": 1700000000,
                    },
                    {
                        "slug": "onsite-analyst-456",
                        "company_name": "City Bank",
                        "title": "Data Analyst",
                        "description": "<p>SQL reporting role.</p>",
                        "remote": False,
                        "url": "https://www.arbeitnow.com/jobs/onsite-analyst-456",
                        "location": "Munich",
                        "created_at": 1700003600,
                    },
                ]
            },
        )
    )

    jobs = ArbeitnowSource(ArbeitnowConfig(endpoint=endpoint)).fetch()

    assert len(jobs) == 2
    assert jobs[0].source == "arbeitnow"
    assert jobs[0].title == "Junior Python Developer"
    assert jobs[0].company == "Nordic Systems"
    assert jobs[0].work_mode == WorkMode.REMOTE
    assert jobs[0].description == "Build backend services in Europe."
    assert jobs[0].external_id == "junior-python-dev-123"
    assert jobs[0].posted_at == datetime.fromtimestamp(1700000000, tz=timezone.utc)
    assert jobs[1].work_mode == WorkMode.UNKNOWN


@respx.mock
def test_remotive_adapter_single_get_with_category_param() -> None:
    endpoint = "https://remotive.com/api/remote-jobs"
    route = respx.get(endpoint, params={"category": "software-dev"}).mock(
        return_value=httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "id": 9876,
                        "url": "https://remotive.com/remote-jobs/software-dev/associate-sa-9876",
                        "title": "Associate Solutions Architect",
                        "company_name": "CloudCraft",
                        "category": "Software Development",
                        "job_type": "full_time",
                        "publication_date": "2026-11-15T12:30:00",
                        "candidate_required_location": "Europe",
                        "description": "<p>Help customers deploy APIs.</p>",
                    }
                ]
            },
        )
    )

    jobs = RemotiveSource(RemotiveConfig(endpoint=endpoint, category="software-dev")).fetch()

    assert route.call_count == 1
    assert len(jobs) == 1
    assert jobs[0].source == "remotive"
    assert jobs[0].work_mode == WorkMode.REMOTE
    assert jobs[0].location == "Europe"
    assert jobs[0].description == "Help customers deploy APIs."
    assert jobs[0].posted_at == datetime(2026, 11, 15, 12, 30, tzinfo=timezone.utc)
    assert jobs[0].external_id == "9876"


@respx.mock
def test_himalayas_adapter_without_and_with_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    endpoint = "https://himalayas.app/jobs/api"
    payload = {
        "jobs": [
            {
                "guid": "him-1",
                "title": "Graduate Cloud Engineer",
                "companyName": "Aurora Cloud",
                "locationRestrictions": ["Denmark", "European Union"],
                "applicationLink": "https://himalayas.app/jobs/aurora/graduate-cloud",
                "description": "<p>Entry-level cloud infrastructure role.</p>",
                "pubDate": 1731667200,
            }
        ]
    }

    monkeypatch.delenv("HIMALAYAS_API_KEY", raising=False)
    route = respx.get(endpoint, params={"limit": "25"}).mock(
        return_value=httpx.Response(200, json=payload)
    )

    cfg = HimalayasConfig(endpoint=endpoint, limit=25, api_key_env="HIMALAYAS_API_KEY")
    jobs_unauth = HimalayasSource(cfg).fetch()
    assert len(jobs_unauth) == 1
    assert jobs_unauth[0].location == "Denmark, European Union"
    assert "Authorization" not in route.calls[0].request.headers

    monkeypatch.setenv("HIMALAYAS_API_KEY", "secret-token-123")
    jobs_auth = HimalayasSource(cfg).fetch()
    assert len(jobs_auth) == 1
    assert route.calls[1].request.headers["Authorization"] == "Bearer secret-token-123"


@respx.mock
def test_jobicy_adapter_handles_429_retry_after_and_spacing() -> None:
    endpoint = "https://jobicy.com/api/jobs"
    route = respx.get(endpoint, params={"count": "10", "geo": "europe", "tag": "python"}).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "3"}),
            httpx.Response(
                200,
                json={
                    "jobs": [
                        {
                            "id": 551,
                            "url": "https://jobicy.com/jobs/551-junior-python",
                            "jobTitle": "Junior Python Engineer",
                            "companyName": "EuroRemote",
                            "jobGeo": "Europe",
                            "jobDescription": "<p>Work with FastAPI and Postgres.</p>",
                            "pubDate": "2026-11-18 09:00:00",
                        }
                    ]
                },
            ),
        ]
    )

    sleeps: list[float] = []
    now = [100.0]

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    source = JobicySource(
        config=JobicyConfig(
            endpoint=endpoint,
            count=10,
            geo="europe",
            tag="python",
            min_request_interval_seconds=1.0,
        ),
        sleep_fn=fake_sleep,
        clock_fn=lambda: now[0],
        max_retries=2,
    )

    jobs = source.fetch()

    assert route.call_count == 2
    assert sleeps == [3.0]
    assert len(jobs) == 1
    assert jobs[0].source == "jobicy"
    assert jobs[0].work_mode == WorkMode.REMOTE
    assert jobs[0].description == "Work with FastAPI and Postgres."


@respx.mock
def test_jobicy_adapter_raises_when_429_retries_exhausted() -> None:
    endpoint = "https://jobicy.com/api/jobs"
    respx.get(endpoint).mock(return_value=httpx.Response(429, headers={"Retry-After": "1"}))

    sleeps: list[float] = []
    source = JobicySource(
        config=JobicyConfig(endpoint=endpoint, min_request_interval_seconds=1.0),
        sleep_fn=sleeps.append,
        max_retries=1,
    )

    with pytest.raises(httpx.HTTPStatusError):
        source.fetch()
    assert sleeps == [1.0]


@respx.mock
def test_jobicy_adapter_enforces_min_request_interval_across_calls() -> None:
    endpoint = "https://jobicy.com/api/jobs"
    respx.get(endpoint).mock(return_value=httpx.Response(200, json={"jobs": []}))

    sleeps: list[float] = []
    now = [10.0]

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    source = JobicySource(
        config=JobicyConfig(endpoint=endpoint, min_request_interval_seconds=1.0),
        sleep_fn=fake_sleep,
        clock_fn=lambda: now[0],
    )

    assert source.fetch() == []
    now[0] += 0.25
    assert source.fetch() == []
    assert sleeps == [0.75]


@respx.mock
def test_jobindex_rss_adapter_parses_danish_entries_and_deadline() -> None:
    feed_url = "https://www.jobindex.dk/jobsoegning/it/storkoebenhavn.rss"
    rss_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <title>Jobindex IT Storkøbenhavn</title>
        <item>
          <title>Junior Softwareudvikler til Python-platform</title>
          <link>https://www.jobindex.dk/jobannonce/9001</link>
          <guid>jobindex-9001</guid>
          <author>Copenhagen Data ApS</author>
          <pubDate>Sun, 15 Nov 2026 08:00:00 GMT</pubDate>
          <description><![CDATA[
            <p>Vi søger en engageret udvikler til vores team i København med erfaring i Python og SQL.</p>
            <p>Ansøgningsfrist: 30.11.2026</p>
          ]]></description>
        </item>
      </channel>
    </rss>
    """
    respx.get(feed_url).mock(return_value=httpx.Response(200, text=rss_xml))

    source = JobindexRssSource(JobindexRssConfig(enabled=True, feed_urls=[feed_url]))
    jobs = source.fetch()

    assert len(jobs) == 1
    job = jobs[0]
    assert job.source == "jobindex_rss"
    assert job.title == "Junior Softwareudvikler til Python-platform"
    assert job.company == "Copenhagen Data ApS"
    assert job.apply_url == "https://www.jobindex.dk/jobannonce/9001"
    assert job.posted_at == datetime(2026, 11, 15, 8, 0, tzinfo=timezone.utc)
    assert job.application_deadline == datetime(2026, 11, 30, 0, 0, tzinfo=timezone.utc)
    assert "Vi søger en engageret udvikler" in job.description

    posting = normalize_raw_job(job)
    assert posting.language == "da"


def test_jobindex_rss_adapter_skips_cleanly_when_feed_urls_empty() -> None:
    source = JobindexRssSource(JobindexRssConfig(enabled=True, feed_urls=[]))
    assert source.fetch() == []


# ---------------------------------------------------------------------------
# Ingestion orchestrator & partial failure isolation
# ---------------------------------------------------------------------------


@respx.mock
def test_fetch_all_sources_isolates_failing_source_and_ingests_healthy_sources(
    caplog: pytest.LogCaptureFixture,
) -> None:
    config = SourcesConfig(
        arbeitnow=ArbeitnowConfig(enabled=True, endpoint="https://api.example.test/arbeitnow"),
        remotive=RemotiveConfig(enabled=True, endpoint="https://api.example.test/remotive"),
        himalayas=HimalayasConfig(enabled=False),
        jobicy=JobicyConfig(enabled=False),
        jobindex_rss=JobindexRssConfig(enabled=False),
    )

    arbeitnow_route = respx.get("https://api.example.test/arbeitnow").mock(
        return_value=httpx.Response(500, text="Internal Server Error")
    )
    remotive_route = respx.get("https://api.example.test/remotive").mock(
        return_value=httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "id": 101,
                        "url": "https://remotive.com/jobs/101",
                        "title": "Junior Backend Developer",
                        "company_name": "HealthyCorp",
                        "candidate_required_location": "Europe",
                        "description": "<p>Python and PostgreSQL engineering position.</p>",
                        "publication_date": "2026-11-20T10:00:00Z",
                    }
                ]
            },
        )
    )

    enabled = build_enabled_sources(config)
    assert [src.name for src in enabled] == ["arbeitnow", "remotive"]

    with caplog.at_level(logging.WARNING):
        result = fetch_all_sources(config, sources=enabled)

    assert arbeitnow_route.call_count == 1
    assert remotive_route.call_count == 1
    assert len(result.errors) == 1
    assert result.errors[0].source == "arbeitnow"
    assert len(result.postings) == 1
    assert result.postings[0].source == "remotive"
    assert result.postings[0].language == "en"
    assert "arbeitnow" in caplog.text


# ---------------------------------------------------------------------------
# Manual Drop ingestion & loud failure reporting
# ---------------------------------------------------------------------------


def test_ingest_manual_text_normalizes_posting_and_rejects_empty_description() -> None:
    deadline = datetime(2026, 12, 15, 12, 0, tzinfo=timezone.utc)
    posting = ingest_manual_text(
        title="Graduate Solutions Architect",
        company="Nordic Cloud",
        apply_url="https://careers.nordiccloud.dk/jobs/12",
        description="Join our Copenhagen team to design cloud architectures with Python.",
        location="Copenhagen",
        work_mode=WorkMode.HYBRID,
        application_deadline=deadline,
    )

    assert posting.source == "manual"
    assert posting.language == "en"
    assert posting.application_deadline == deadline
    assert posting.job_id == generate_job_id("manual", "https://careers.nordiccloud.dk/jobs/12")

    with pytest.raises(ManualDropError, match="empty"):
        ingest_manual_text(
            title="Graduate Engineer",
            company="Nordic Cloud",
            apply_url="https://careers.nordiccloud.dk/jobs/12",
            description="   ",
        )


@respx.mock
def test_ingest_manual_url_succeeds_for_clean_html_page() -> None:
    url = "https://careers.example.dk/jobs/junior-dev"
    html = """
    <html>
      <head><title>Careers at Example</title></head>
      <body>
        <main>
          <h1>Junior Softwareudvikler</h1>
          <p>Vi søger en junior udvikler til vores team i København med erfaring i Python og databaser.</p>
        </main>
      </body>
    </html>
    """
    respx.get(url).mock(return_value=httpx.Response(200, text=html))

    posting = ingest_manual_url(url=url, company="Example ApS", location="Copenhagen")

    assert posting.source == "manual"
    assert posting.title == "Junior Softwareudvikler"
    assert posting.company == "Example ApS"
    assert posting.language == "da"
    assert "Vi søger en junior udvikler" in posting.description


@respx.mock
@pytest.mark.parametrize("status_code", [401, 403])
def test_ingest_manual_url_fails_loudly_on_auth_gate_http_status(status_code: int) -> None:
    url = "https://example.com/private-job"
    respx.get(url).mock(return_value=httpx.Response(status_code, text="Unauthorized"))

    with pytest.raises(ManualDropError) as exc_info:
        ingest_manual_url(url)

    assert f"Blocked by login/auth gate (HTTP {status_code})" in exc_info.value.reason
    assert "raw" in exc_info.value.hint.lower()


@respx.mock
def test_ingest_manual_url_fails_loudly_on_login_redirect() -> None:
    url = "https://linkedin.com/jobs/view/123456"
    login_url = "https://www.linkedin.com/uas/login?session_redirect=..."
    respx.get(url).mock(
        return_value=httpx.Response(302, headers={"Location": login_url})
    )
    respx.get(login_url).mock(
        return_value=httpx.Response(200, text="<html><body>Sign in</body></html>")
    )

    with pytest.raises(ManualDropError) as exc_info:
        ingest_manual_url(url)

    assert "Redirected to a login/auth page" in exc_info.value.reason
    assert exc_info.value.hint


@respx.mock
def test_ingest_manual_url_fails_loudly_on_login_form_page() -> None:
    url = "https://portal.example.com/job/55"
    respx.get(url).mock(
        return_value=httpx.Response(
            200,
            text="<html><body><form><input type='password' name='pw'/></form></body></html>",
        )
    )

    with pytest.raises(ManualDropError) as exc_info:
        ingest_manual_url(url)

    assert "Redirected to a login/auth page" in exc_info.value.reason


@respx.mock
@pytest.mark.parametrize(
    "status_code,html",
    [
        (200, "<html><body><div class='cf-turnstile'></div>Verify you are human</body></html>"),
        (403, "<html><body>Attention Required! | Cloudflare <div id='cf-challenge'></div></body></html>"),
        (200, "<html><body><div class='g-recaptcha'></div></body></html>"),
    ],
)
def test_ingest_manual_url_fails_loudly_on_captcha_interstitial(
    status_code: int, html: str
) -> None:
    url = "https://protected.example.com/jobs/1"
    respx.get(url).mock(return_value=httpx.Response(status_code, text=html))

    with pytest.raises(ManualDropError) as exc_info:
        ingest_manual_url(url)

    assert "Blocked by CAPTCHA or anti-bot verification" in exc_info.value.reason


@respx.mock
@pytest.mark.parametrize("status_code", [404, 500, 503])
def test_ingest_manual_url_fails_loudly_on_http_404_and_5xx(status_code: int) -> None:
    url = "https://example.com/missing-job"
    respx.get(url).mock(return_value=httpx.Response(status_code, text="Error"))

    with pytest.raises(ManualDropError) as exc_info:
        ingest_manual_url(url)

    assert f"HTTP {status_code}" in exc_info.value.reason


@respx.mock
def test_ingest_manual_url_fails_loudly_on_network_timeout() -> None:
    url = "https://slow.example.com/jobs/1"
    respx.get(url).mock(side_effect=httpx.ReadTimeout("timed out"))

    with pytest.raises(ManualDropError) as exc_info:
        ingest_manual_url(url)

    assert "Network/HTTP error fetching URL" in exc_info.value.reason


@respx.mock
def test_ingest_manual_url_fails_loudly_on_empty_or_unparseable_html() -> None:
    url = "https://spa.example.com/jobs/1"
    respx.get(url).mock(
        return_value=httpx.Response(
            200,
            text="<html><head><title>Jobs</title></head><body><div id='root'>Loading...</div></body></html>",
        )
    )

    with pytest.raises(ManualDropError) as exc_info:
        ingest_manual_url(url)

    assert "Could not extract a job description from the page" in exc_info.value.reason
