"""
Issue tracker plugin interface.

Supports Jira, GitHub Issues, Linear, etc.
"""

from abc import abstractmethod
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime

from backend.base import BasePlugin


@dataclass
class Epic:
    """Normalized epic/issue representation across all issue trackers."""
    key: str
    project: str
    team: str
    summary: str
    status: str
    assignee: Optional[str]
    priority: str
    updated: datetime
    days_since_update: int
    is_stale: bool
    is_unassigned: bool
    url: str

    # Optional child activity tracking
    child_last_updated: Optional[datetime] = None
    effective_days_since: Optional[int] = None

    # Additional metadata
    labels: List[str] = field(default_factory=list)
    issue_type: str = "Epic"


@dataclass
class Sprint:
    """Normalized sprint representation."""
    id: str
    name: str
    team: str
    state: str  # active, closed, future
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    story_points_committed: float = 0.0
    story_points_completed: float = 0.0
    issues_total: int = 0
    issues_completed: int = 0


@dataclass
class Issue:
    """Normalized issue representation (stories, tasks, bugs)."""
    key: str
    project: str
    team: str
    summary: str
    issue_type: str
    status: str
    assignee: Optional[str]
    priority: str
    updated: datetime
    parent_key: Optional[str] = None  # Epic key
    story_points: Optional[float] = None
    labels: List[str] = field(default_factory=list)
    url: str = ""


class IssueTrackerPlugin(BasePlugin):
    """
    Abstract base for issue tracking integrations.

    Implement this interface for Jira, GitHub Issues, Linear, etc.
    """

    @abstractmethod
    def search_epics(
        self,
        team_keys: List[str],
        exclude_done: bool = True
    ) -> List[Epic]:
        """
        Search for epics/issues across teams.

        Args:
            team_keys: Team identifiers (keys from config)
            exclude_done: Whether to exclude completed epics

        Returns:
            List of Epic objects
        """
        pass

    @abstractmethod
    def get_epic(self, key: str) -> Optional[Epic]:
        """
        Get single epic by key.

        Args:
            key: Epic key (e.g., 'EEH-123' for Jira, '#123' for GitHub)

        Returns:
            Epic if found, None otherwise
        """
        pass

    @abstractmethod
    def get_sprints(
        self,
        team_key: str,
        state: str = "closed"
    ) -> List[Sprint]:
        """
        Get sprints for a team.

        Args:
            team_key: Team identifier
            state: Sprint state filter (active, closed, future)

        Returns:
            List of Sprint objects
        """
        pass

    @abstractmethod
    def get_child_issues(
        self,
        epic_key: str
    ) -> List[Issue]:
        """
        Get child issues (stories, tasks) for an epic.

        Args:
            epic_key: Parent epic key

        Returns:
            List of Issue objects
        """
        pass

    def get_child_issues_activity(
        self,
        epic_keys: List[str]
    ) -> Dict[str, datetime]:
        """
        Get most recent child activity for epics.

        Default implementation fetches children and finds max updated date.
        Override for more efficient bulk queries.

        Args:
            epic_keys: List of epic keys to check

        Returns:
            Dict mapping epic key to most recent child updated datetime
        """
        result = {}
        for key in epic_keys:
            children = self.get_child_issues(key)
            if children:
                most_recent = max(c.updated for c in children)
                result[key] = most_recent
        return result

    def get_stale_epics(
        self,
        team_keys: List[str],
        days: int = 14
    ) -> List[Epic]:
        """
        Get epics not updated in N days.

        Args:
            team_keys: Team identifiers
            days: Stale threshold in days

        Returns:
            List of stale Epic objects
        """
        epics = self.search_epics(team_keys)
        return [e for e in epics if e.days_since_update > days]

    def get_unassigned_epics(
        self,
        team_keys: List[str]
    ) -> List[Epic]:
        """
        Get epics without assignee.

        Args:
            team_keys: Team identifiers

        Returns:
            List of unassigned Epic objects
        """
        epics = self.search_epics(team_keys)
        return [e for e in epics if e.is_unassigned]
