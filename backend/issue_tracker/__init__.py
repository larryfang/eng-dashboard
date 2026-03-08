"""
Issue tracker plugins.

Supports:
- Jira Cloud (JiraPlugin)
- GitHub Issues (GitHubIssuesPlugin)
"""

from .base import IssueTrackerPlugin, Epic, Sprint, Issue
from .jira_plugin import JiraPlugin
from .github_plugin import GitHubIssuesPlugin

__all__ = [
    "IssueTrackerPlugin",
    "Epic",
    "Sprint",
    "Issue",
    "JiraPlugin",
    "GitHubIssuesPlugin",
]
