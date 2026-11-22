"""SQLite-backed (Postgres-portable) repository for job postings and application state."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from job_agent.schemas.jobs import ApplicationStatus, JobPosting, WorkMode

_UNSET: Any = object()

_SELECT_COLUMNS = (
    "job_id, source, external_id, title, company, location, work_mode, language, "
    "apply_url, description, status, rejection_reason, fit_score, fit_breakdown_json, "
    "cv_pdf_path, cover_letter_pdf_path, slack_thread_ts, gmail_thread_id, "
    "langgraph_thread_id, posted_at, application_deadline, created_at, updated_at"
)

_CREATE_JOBS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    external_id TEXT,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT NOT NULL,
    work_mode TEXT NOT NULL,
    language TEXT NOT NULL,
    apply_url TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL,
    rejection_reason TEXT,
    fit_score REAL,
    fit_breakdown_json TEXT,
    cv_pdf_path TEXT,
    cover_letter_pdf_path TEXT,
    slack_thread_ts TEXT,
    gmail_thread_id TEXT,
    langgraph_thread_id TEXT,
    posted_at TEXT,
    application_deadline TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""


def _to_utc(dt: datetime) -> datetime:
    """Normalize a naive or timezone-aware datetime to UTC."""
    if dt.tzinfo is None or dt.utcoffset() is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _format_dt(dt: datetime | None) -> str | None:
    """Serialize a datetime as fixed-width ISO-8601 UTC string for portable SQL sorting."""
    if dt is None:
        return None
    return _to_utc(dt).isoformat(timespec="microseconds")


def _parse_dt(value: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp string into a UTC-aware datetime."""
    if value is None:
        return None
    return _to_utc(datetime.fromisoformat(value))


class StoredJob(BaseModel):
    """Persisted job and application lifecycle record from the jobs table."""

    job_id: str
    source: str
    external_id: str | None = None
    title: str
    company: str
    location: str
    work_mode: WorkMode
    language: Literal["da", "en"]
    apply_url: str
    description: str
    status: ApplicationStatus
    rejection_reason: str | None = None
    fit_score: float | None = None
    fit_breakdown_json: str | None = None
    cv_pdf_path: str | None = None
    cover_letter_pdf_path: str | None = None
    slack_thread_ts: str | None = None
    gmail_thread_id: str | None = None
    langgraph_thread_id: str | None = None
    posted_at: datetime | None = None
    application_deadline: datetime | None = None
    created_at: datetime
    updated_at: datetime


def _row_to_stored_job(row: sqlite3.Row) -> StoredJob:
    """Map a SQLite row onto a validated StoredJob model."""
    return StoredJob(
        job_id=row["job_id"],
        source=row["source"],
        external_id=row["external_id"],
        title=row["title"],
        company=row["company"],
        location=row["location"],
        work_mode=WorkMode(row["work_mode"]),
        language=row["language"],
        apply_url=row["apply_url"],
        description=row["description"],
        status=ApplicationStatus(row["status"]),
        rejection_reason=row["rejection_reason"],
        fit_score=row["fit_score"],
        fit_breakdown_json=row["fit_breakdown_json"],
        cv_pdf_path=row["cv_pdf_path"],
        cover_letter_pdf_path=row["cover_letter_pdf_path"],
        slack_thread_ts=row["slack_thread_ts"],
        gmail_thread_id=row["gmail_thread_id"],
        langgraph_thread_id=row["langgraph_thread_id"],
        posted_at=_parse_dt(row["posted_at"]),
        application_deadline=_parse_dt(row["application_deadline"]),
        created_at=_parse_dt(row["created_at"]),  # type: ignore[arg-type]
        updated_at=_parse_dt(row["updated_at"]),  # type: ignore[arg-type]
    )


class JobRepository:
    """Encapsulated SQLite state store for ingested jobs and application lifecycle rows."""

    def __init__(self, db_path: Path | str) -> None:
        self._is_memory = str(db_path) == ":memory:"
        self._memory_conn: sqlite3.Connection | None = None

        if self._is_memory:
            self._db_target = ":memory:"
            self._memory_conn = sqlite3.connect(":memory:")
            self._memory_conn.row_factory = sqlite3.Row
        else:
            path = Path(db_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            self._db_target = str(path)

        self._init_schema()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        if self._memory_conn is not None:
            with self._memory_conn:
                yield self._memory_conn
            return

        conn = sqlite3.connect(self._db_target)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def close(self) -> None:
        """Close the underlying connection when using an in-memory database."""
        if self._memory_conn is not None:
            self._memory_conn.close()
            self._memory_conn = None

    def _init_schema(self) -> None:
        with self._connection() as conn:
            conn.execute(_CREATE_JOBS_TABLE_SQL)

    def exists(self, job_id: str) -> bool:
        """Return True if a row with the given job_id already exists."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM jobs WHERE job_id = ? LIMIT 1",
                (job_id,),
            ).fetchone()
            return row is not None

    def insert_job(
        self,
        posting: JobPosting,
        status: ApplicationStatus | str,
        rejection_reason: str | None = None,
        created_at: datetime | None = None,
    ) -> None:
        """Insert a normalized JobPosting with its initial status."""
        status_value = ApplicationStatus(status).value
        created_dt = _to_utc(created_at) if created_at is not None else datetime.now(timezone.utc)
        created_str = _format_dt(created_dt)

        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO jobs (
                    job_id, source, external_id, title, company, location, work_mode,
                    language, apply_url, description, status, rejection_reason,
                    posted_at, application_deadline, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    posting.job_id,
                    posting.source,
                    posting.external_id,
                    posting.title,
                    posting.company,
                    posting.location,
                    posting.work_mode.value,
                    posting.language,
                    posting.apply_url,
                    posting.description,
                    status_value,
                    rejection_reason,
                    _format_dt(posting.posted_at),
                    _format_dt(posting.application_deadline),
                    created_str,
                    created_str,
                ),
            )

    def get_job(self, job_id: str) -> StoredJob | None:
        """Fetch a single StoredJob by job_id, or None if not found."""
        with self._connection() as conn:
            row = conn.execute(
                f"SELECT {_SELECT_COLUMNS} FROM jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            return _row_to_stored_job(row) if row is not None else None

    def update_job(
        self,
        job_id: str,
        *,
        status: ApplicationStatus | str | None = _UNSET,
        rejection_reason: str | None = _UNSET,
        fit_score: float | None = _UNSET,
        fit_breakdown_json: str | None = _UNSET,
        cv_pdf_path: str | None = _UNSET,
        cover_letter_pdf_path: str | None = _UNSET,
        slack_thread_ts: str | None = _UNSET,
        gmail_thread_id: str | None = _UNSET,
        langgraph_thread_id: str | None = _UNSET,
        updated_at: datetime | None = None,
    ) -> bool:
        """Update selected lifecycle fields for an existing job_id."""
        assignments: list[str] = []
        params: list[Any] = []

        if status is not _UNSET:
            assignments.append("status = ?")
            params.append(ApplicationStatus(status).value)
        if rejection_reason is not _UNSET:
            assignments.append("rejection_reason = ?")
            params.append(rejection_reason)
        if fit_score is not _UNSET:
            assignments.append("fit_score = ?")
            params.append(fit_score)
        if fit_breakdown_json is not _UNSET:
            assignments.append("fit_breakdown_json = ?")
            params.append(fit_breakdown_json)
        if cv_pdf_path is not _UNSET:
            assignments.append("cv_pdf_path = ?")
            params.append(cv_pdf_path)
        if cover_letter_pdf_path is not _UNSET:
            assignments.append("cover_letter_pdf_path = ?")
            params.append(cover_letter_pdf_path)
        if slack_thread_ts is not _UNSET:
            assignments.append("slack_thread_ts = ?")
            params.append(slack_thread_ts)
        if gmail_thread_id is not _UNSET:
            assignments.append("gmail_thread_id = ?")
            params.append(gmail_thread_id)
        if langgraph_thread_id is not _UNSET:
            assignments.append("langgraph_thread_id = ?")
            params.append(langgraph_thread_id)

        if not assignments:
            return False

        updated_dt = _to_utc(updated_at) if updated_at is not None else datetime.now(timezone.utc)
        assignments.append("updated_at = ?")
        params.append(_format_dt(updated_dt))
        params.append(job_id)

        with self._connection() as conn:
            cursor = conn.execute(
                f"UPDATE jobs SET {', '.join(assignments)} WHERE job_id = ?",
                params,
            )
            return cursor.rowcount > 0

    def list_jobs(
        self,
        status: ApplicationStatus | str | None = None,
        language: str | None = None,
    ) -> list[StoredJob]:
        """Return stored jobs optionally filtered by status and/or language."""
        clauses: list[str] = []
        params: list[Any] = []

        if status is not None:
            clauses.append("status = ?")
            params.append(ApplicationStatus(status).value)
        if language is not None:
            clauses.append("language = ?")
            params.append(language.strip().lower())

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = (
            f"SELECT {_SELECT_COLUMNS} FROM jobs "
            f"{where_sql} "
            "ORDER BY created_at DESC, job_id ASC"
        )
        with self._connection() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [_row_to_stored_job(row) for row in rows]

    def list_prioritized_candidates(
        self,
        preferred_age_days: int = 7,
        limit: int = 3,
        now: datetime | None = None,
    ) -> list[StoredJob]:
        """Return un-drafted Pending_Scoring candidates ordered by freshness priority up to limit."""
        if limit <= 0:
            return []

        current_time = _to_utc(now) if now is not None else datetime.now(timezone.utc)
        preferred_cutoff = current_time - timedelta(days=preferred_age_days)
        now_str = _format_dt(current_time)
        cutoff_str = _format_dt(preferred_cutoff)

        sql = f"""
        SELECT {_SELECT_COLUMNS}
        FROM jobs
        WHERE status = ?
          AND cv_pdf_path IS NULL
          AND cover_letter_pdf_path IS NULL
        ORDER BY
          CASE
            WHEN (posted_at IS NOT NULL AND posted_at >= ?)
              OR (application_deadline IS NOT NULL AND application_deadline > ?)
            THEN 0
            ELSE 1
          END ASC,
          COALESCE(posted_at, created_at) DESC,
          created_at DESC,
          job_id ASC
        LIMIT ?
        """
        with self._connection() as conn:
            rows = conn.execute(
                sql,
                (
                    ApplicationStatus.PENDING_SCORING.value,
                    cutoff_str,
                    now_str,
                    limit,
                ),
            ).fetchall()
            return [_row_to_stored_job(row) for row in rows]

    def prune_old_jobs(
        self,
        retention_days: int = 180,
        now: datetime | None = None,
    ) -> int:
        """Delete rows older than retention_days while preserving Interviewing rows."""
        current_time = _to_utc(now) if now is not None else datetime.now(timezone.utc)
        cutoff_str = _format_dt(current_time - timedelta(days=retention_days))

        with self._connection() as conn:
            cursor = conn.execute(
                "DELETE FROM jobs WHERE created_at < ? AND status != ?",
                (cutoff_str, ApplicationStatus.INTERVIEWING.value),
            )
            return cursor.rowcount
