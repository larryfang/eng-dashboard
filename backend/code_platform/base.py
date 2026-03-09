"""
Base types and abstract interface for code platform plugins.

Defines the data classes shared across all code platform implementations
(GitLab, GitHub, etc.) and the CodePlatformPlugin ABC that each must implement.
"""

from abc import abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from backend.base import BasePlugin


# -- Data classes ----------------------------------------------------------


@dataclass
class Repository:
    id: str
    name: str
    team: str
    url: str
    primary_language: Optional[str] = None
    has_tests: bool = False
    has_ci: bool = False
    doc_score: int = 0
    is_orphaned: bool = False
    days_since_activity: Optional[int] = None


@dataclass
class MergeRequest:
    id: str
    title: str
    author: str
    project: str
    team: str
    state: str  # "opened", "merged", "closed"
    url: str
    created_at: Optional[datetime] = None
    merged_at: Optional[datetime] = None
    source_branch: Optional[str] = None
    lines_added: Optional[int] = None
    lines_removed: Optional[int] = None
    files_changed: Optional[int] = None
    cycle_time_hours: Optional[float] = None


@dataclass
class Pipeline:
    id: str
    project: str
    team: str
    status: str  # "success", "failed", "running", etc.
    ref: Optional[str] = None
    duration_seconds: Optional[float] = None
    created_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


@dataclass
class DORAMetrics:
    team: str
    period_days: int
    deployment_frequency: float
    lead_time_hours: Optional[float] = None
    change_failure_rate: Optional[float] = None
    time_to_restore_hours: Optional[float] = None
    dora_level: str = "unknown"
    deployment_frequency_trend: Optional[float] = None
    lead_time_trend: Optional[float] = None
    change_failure_rate_trend: Optional[float] = None
    time_to_restore_trend: Optional[float] = None


@dataclass
class SearchResult:
    repo_id: str
    repo_name: str
    team: str
    primary_language: Optional[str] = None
    frameworks: list = field(default_factory=list)
    has_tests: bool = False
    has_ci: bool = False
    is_orphaned: bool = False
    last_activity: Optional[str] = None
    days_since_activity: Optional[int] = None


# -- Abstract base ---------------------------------------------------------


class CodePlatformPlugin(BasePlugin):
    """Abstract base for code platform integrations (GitLab, GitHub, etc.).

    Each implementation must provide methods for fetching repositories,
    merge/pull requests, CI pipelines, DORA metrics, and code search results.
    """

    @abstractmethod
    def get_repos(
        self,
        team: Optional[str] = None,
    ) -> List[Repository]:
        """List repositories, optionally filtered by team slug."""
        ...

    @abstractmethod
    def get_merge_requests(
        self,
        team: Optional[str] = None,
        state: str = "merged",
        days: int = 30,
    ) -> List[MergeRequest]:
        """Fetch merge/pull requests for the given period and state."""
        ...

    @abstractmethod
    def get_pipelines(
        self,
        team: Optional[str] = None,
        days: int = 30,
    ) -> List[Pipeline]:
        """Fetch CI pipeline runs for the given period."""
        ...

    @abstractmethod
    def get_dora_metrics(
        self,
        team: Optional[str] = None,
        days: int = 30,
    ) -> DORAMetrics:
        """Compute DORA metrics for the given team and period."""
        ...

    @abstractmethod
    def search_code(
        self,
        query: str,
        team: Optional[str] = None,
    ) -> List[SearchResult]:
        """Search across repositories for code matching *query*."""
        ...
