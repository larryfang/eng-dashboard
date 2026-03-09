"""
Issue tracker plugins.

Supports:
- Jira Cloud (JiraPlugin)
- GitHub Issues (GitHubIssuesPlugin)
"""

from backend.issue_tracker.base import IssueTrackerPlugin, Epic, Sprint, Issue
from backend.issue_tracker.jira_plugin import JiraPlugin
from backend.issue_tracker.github_plugin import GitHubIssuesPlugin

__all__ = [
    "IssueTrackerPlugin",
    "Epic",
    "Sprint",
    "Issue",
    "JiraPlugin",
    "GitHubIssuesPlugin",
]
