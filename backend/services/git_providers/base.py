"""Abstract base class for git platform providers (GitLab, GitHub)."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass
class PullRequestData:
    """Normalized PR/MR data from any git platform."""
    pr_iid: int
    repo_id: str
    title: str
    source_branch: str | None
    author_username: str
    state: str  # "opened", "merged", "closed"
    created_at: datetime | None
    merged_at: datetime | None
    web_url: str | None
    lines_added: int | None = None
    lines_removed: int | None = None
    files_changed: int | None = None
    description: str | None = None


class GitProvider(ABC):
    """
    Interface for git platform API interactions.

    Each provider (GitLab, GitHub) implements these methods to fetch
    engineer activity data using platform-specific APIs.
    """

    @abstractmethod
    def fetch_pull_requests(
        self, username: str, since_iso: str
    ) -> list[PullRequestData]:
        """Fetch all PRs/MRs authored by username since the given date."""
        ...

    @abstractmethod
    def fetch_commit_count(self, username: str, since_iso: str) -> int:
        """Count commits by username since the given date."""
        ...

    @abstractmethod
    def fetch_review_count(self, username: str, since_iso: str) -> int:
        """Count PR/MR reviews by username since the given date."""
        ...

    @abstractmethod
    def close(self) -> None:
        """Release any held resources (HTTP sessions, etc)."""
        ...
