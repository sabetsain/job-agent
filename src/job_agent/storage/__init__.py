"""Local SQLite state persistence."""

from job_agent.storage.repository import (
    JobRepository,
    ProfileUpdateSuggestion,
    StoredJob,
)

__all__ = [
    "JobRepository",
    "ProfileUpdateSuggestion",
    "StoredJob",
]
