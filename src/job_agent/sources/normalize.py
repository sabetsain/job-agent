"""Canonical job_id generation, language detection, and posting normalization."""

from __future__ import annotations

import hashlib
import re
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from langdetect import DetectorFactory, LangDetectException, detect
from langdetect import detector_factory as _langdetect_factory

from job_agent.schemas.jobs import JobPosting, RawJob

_TRACKING_QUERY_KEYS = frozenset({"fbclid", "gclid", "mc_cid", "mc_eid"})
_DANISH_CHARS = frozenset("æøå")
_DANISH_MARKERS = frozenset(
    {
        "og",
        "til",
        "med",
        "erfaring",
        "søger",
        "stilling",
        "arbejde",
        "vi",
        "du",
        "som",
        "i",
        "på",
        "af",
        "er",
    }
)
_WORD_RE = re.compile(r"[a-zæøå]+")


def _normalize_text(value: str) -> str:
    """Lowercase and collapse whitespace for deterministic key construction."""
    return " ".join(value.lower().split())


def canonicalize_url(url: str) -> str:
    """Normalize a job application URL for deterministic ID generation."""
    stripped = url.strip()
    if not stripped:
        return ""

    parts = urlsplit(stripped)
    if parts.scheme and parts.netloc:
        scheme = parts.scheme.lower()
        netloc = parts.netloc.lower()
        path = parts.path.rstrip("/")
        filtered_query = sorted(
            (k, v)
            for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if not (k.lower().startswith("utm_") or k.lower() in _TRACKING_QUERY_KEYS)
        )
        query = urlencode(filtered_query)
        return urlunsplit((scheme, netloc, path, query, ""))

    return stripped.rstrip("/")


def generate_job_id(
    source: str,
    apply_url: str = "",
    company: str = "",
    title: str = "",
) -> str:
    """Return a deterministic 16-char lowercase SHA-256 hex prefix for a job."""
    norm_source = source.strip().lower()
    canonical_url = canonicalize_url(apply_url)

    if canonical_url:
        payload = f"{norm_source}\x1f{canonical_url}"
    else:
        payload = f"{norm_source}\x1f{_normalize_text(company)}\x1f{_normalize_text(title)}"

    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _has_danish_signals(lowered_text: str) -> bool:
    """Return True when Danish characters combine with clear Danish lexical density."""
    if not any(ch in lowered_text for ch in _DANISH_CHARS):
        return False

    words = _WORD_RE.findall(lowered_text)
    if not words:
        return False

    marker_hits = [word for word in words if word in _DANISH_MARKERS]
    non_ambiguous_hits = [word for word in marker_hits if word != "i"]
    if not non_ambiguous_hits:
        return False

    if len(words) <= 6:
        return True

    if len(marker_hits) < 2:
        return False

    density = len(marker_hits) / len(words)
    return len(set(marker_hits)) >= 3 or density >= 0.04


def _detect_with_langdetect(text: str) -> Literal["da", "en"]:
    """Run langdetect with locked seed=0 and map results to 'da' or 'en'."""
    DetectorFactory.seed = 0
    if _langdetect_factory._factory is not None:
        _langdetect_factory._factory.seed = 0

    try:
        detected = detect(text)
    except LangDetectException:
        return "en"

    return "da" if detected == "da" else "en"


def detect_language(title: str, description: str) -> Literal["da", "en"]:
    """Deterministically classify a posting as Danish ('da') or English ('en')."""
    combined = " ".join(f"{title} {description}".split())
    if not combined:
        return "en"

    if _has_danish_signals(combined.lower()):
        return "da"

    return _detect_with_langdetect(combined)


def normalize_raw_job(raw: RawJob) -> JobPosting:
    """Convert a RawJob into a canonical JobPosting with job_id and language."""
    job_id = generate_job_id(
        source=raw.source,
        apply_url=raw.apply_url,
        company=raw.company,
        title=raw.title,
    )
    language = detect_language(raw.title, raw.description)

    return JobPosting(
        job_id=job_id,
        source=raw.source,
        title=raw.title,
        company=raw.company,
        location=raw.location,
        work_mode=raw.work_mode,
        apply_url=raw.apply_url,
        description=raw.description,
        language=language,
        posted_at=raw.posted_at,
        application_deadline=raw.application_deadline,
        external_id=raw.external_id,
        raw_metadata=dict(raw.raw_metadata),
    )
