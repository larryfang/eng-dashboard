"""
GitHub Issues plugin implementation.

Uses GitHub GraphQL API for efficient querying.
"""

import os
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any

import requests

from backend.issue_tracker.base import IssueTrackerPlugin, Epic, Sprint, Issue
from backend.base import PluginConfig
from backend.core.config_loader import get_config
from backend.plugins.registry import register

logger = logging.getLogger(__name__)

# GraphQL query for issues with 'epic' label
EPICS_QUERY = """
query($owner: String!, $repo: String!, $labels: [String!], $states: [IssueState!], $after: String) {
  repository(owner: $owner, name: $repo) {
    issues(first: 100, labels: $labels, states: $states, after: $after, orderBy: {field: UPDATED_AT, direction: DESC}) {
      pageInfo {
        hasNextPage
        endCursor
      }
      nodes {
        number
        title
        state
        url
        updatedAt
        assignees(first: 1) {
          nodes { login name }
        }
        labels(first: 10) {
          nodes { name }
        }
        milestone {
          title
          state
        }
      }
    }
  }
}
"""

ISSUE_QUERY = """
query($owner: String!, $repo: String!, $number: Int!) {
  repository(owner: $owner, name: $repo) {
    issue(number: $number) {
      number
      title
      state
      url
      updatedAt
      body
      assignees(first: 5) {
        nodes { login name }
      }
      labels(first: 20) {
        nodes { name }
      }
      milestone {
        title
        state
      }
      timelineItems(first: 100, itemTypes: [CONNECTED_EVENT, CROSS_REFERENCED_EVENT]) {
        nodes {
          ... on ConnectedEvent {
            subject {
              ... on Issue { number title state }
            }
          }
        }
      }
    }
  }
}
"""


@register("issue_tracker", "github")
class GitHubIssuesPlugin(IssueTrackerPlugin):
    """
    GitHub Issues integration via GraphQL API.

    Uses issues with 'epic' label as epics.
    """

    @property
    def name(self) -> str:
        return "github-issues"

    @property
    def provider(self) -> str:
        return "github"

    def __init__(self, config: PluginConfig):
        super().__init__(config)

        self.token = os.getenv("GITHUB_TOKEN")
        self.organization = config.settings.get("organization", "")
        self.graphql_url = "https://api.github.com/graphql"
        self.epic_label = config.settings.get("epic_label", "epic")

        self._org_config = get_config()
        self._stale_days = self._org_config.metrics.stale_epic_days

    def initialize(self) -> None:
        """Initialize and verify connection."""
        super().initialize()
        if not self.health_check():
            logger.warning("GitHub plugin initialized but health check failed")

    def health_check(self) -> bool:
        """Test connection to GitHub API."""
        if not self.token:
            logger.error("GitHub token not configured (GITHUB_TOKEN)")
            return False

        try:
            response = requests.post(
                self.graphql_url,
                json={"query": "{ viewer { login } }"},
                headers=self._get_headers(),
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                if "data" in data and "viewer" in data["data"]:
                    user = data["data"]["viewer"]["login"]
                    logger.info(f"GitHub connected as: {user}")
                    return True

            logger.error(f"GitHub health check failed: {response.status_code}")
            return False

        except Exception as e:
            logger.error(f"GitHub health check error: {e}")
            return False

    def _get_headers(self) -> Dict[str, str]:
        """Get request headers with Bearer token."""
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "Content-Type": "application/json"
        }

    def _get_repos(self, team_keys: List[str]) -> List[tuple]:
        """Convert team keys to (owner, repo) tuples."""
        repos = []
        for key in team_keys:
            team = self._org_config.get_team(key)
            if team and team.github_repo:
                parts = team.github_repo.split("/")
                if len(parts) >= 2:
                    repos.append((parts[0], parts[1]))
            elif "/" in key:
                parts = key.split("/")
                repos.append((parts[0], parts[1]))
        return repos

    def search_epics(
        self,
        team_keys: List[str],
        exclude_done: bool = True
    ) -> List[Epic]:
        """Search for issues labeled as epics."""
        repos = self._get_repos(team_keys)
        if not repos:
            return []

        all_epics = []
        states = ["OPEN"] if exclude_done else ["OPEN", "CLOSED"]

        for owner, repo in repos:
            team = self._org_config.get_team(f"{owner}/{repo}") or self._org_config.get_team(repo)
            team_name = team.name if team else repo

            try:
                variables = {
                    "owner": owner,
                    "repo": repo,
                    "labels": [self.epic_label],
                    "states": states
                }

                response = requests.post(
                    self.graphql_url,
                    json={"query": EPICS_QUERY, "variables": variables},
                    headers=self._get_headers(),
                    timeout=30
                )

                if response.status_code != 200:
                    logger.error(f"GitHub query failed for {owner}/{repo}: {response.status_code}")
                    continue

                data = response.json()
                issues = data.get("data", {}).get("repository", {}).get("issues", {}).get("nodes", [])

                for issue in issues:
                    epic = self._parse_issue_to_epic(issue, owner, repo, team_name)
                    all_epics.append(epic)

            except Exception as e:
                logger.error(f"Error fetching epics from {owner}/{repo}: {e}")

        return all_epics

    def get_epic(self, key: str) -> Optional[Epic]:
        """Get single epic by key (format: 'owner/repo#123' or just '#123')."""
        try:
            # Parse key
            if "#" in key:
                parts = key.split("#")
                number = int(parts[-1])
                if "/" in parts[0]:
                    owner, repo = parts[0].split("/")
                else:
                    # Use first configured repo
                    repos = self._get_repos([])
                    if not repos:
                        return None
                    owner, repo = repos[0]
            else:
                return None

            variables = {
                "owner": owner,
                "repo": repo,
                "number": number
            }

            response = requests.post(
                self.graphql_url,
                json={"query": ISSUE_QUERY, "variables": variables},
                headers=self._get_headers(),
                timeout=30
            )

            if response.status_code != 200:
                return None

            data = response.json()
            issue = data.get("data", {}).get("repository", {}).get("issue")

            if not issue:
                return None

            team = self._org_config.get_team(f"{owner}/{repo}") or self._org_config.get_team(repo)
            team_name = team.name if team else repo

            return self._parse_issue_to_epic(issue, owner, repo, team_name)

        except Exception as e:
            logger.error(f"Error fetching epic {key}: {e}")
            return None

    def get_sprints(
        self,
        team_key: str,
        state: str = "closed"
    ) -> List[Sprint]:
        """
        Get sprints (milestones) for a team.

        GitHub uses milestones as sprint equivalents.
        """
        team = self._org_config.get_team(team_key)
        if not team or not team.github_repo:
            return []

        # TODO: Implement milestone fetching
        logger.warning("get_sprints not yet fully implemented for GitHub")
        return []

    def get_child_issues(self, epic_key: str) -> List[Issue]:
        """
        Get child issues linked to an epic.

        GitHub doesn't have native parent-child relationships,
        so this looks for issues that reference the epic.
        """
        # TODO: Implement child issue tracking via timeline/references
        logger.warning("get_child_issues not yet implemented for GitHub")
        return []

    def _parse_issue_to_epic(
        self,
        issue: Dict[str, Any],
        owner: str,
        repo: str,
        team_name: str
    ) -> Epic:
        """Parse GitHub issue to Epic object."""
        now = datetime.now()

        number = issue.get("number", 0)
        updated_str = issue.get("updatedAt", "")

        try:
            updated_dt = datetime.fromisoformat(updated_str.replace("Z", "+00:00").split("+")[0])
            days_since = (now - updated_dt).days
        except ValueError:
            updated_dt = now
            days_since = 0

        assignees = issue.get("assignees", {}).get("nodes", [])
        assignee = assignees[0].get("login") if assignees else None

        labels = [l.get("name", "") for l in issue.get("labels", {}).get("nodes", [])]

        # Map GitHub state to status
        state = issue.get("state", "OPEN")
        status = "Open" if state == "OPEN" else "Closed"

        # Priority from labels (p0, p1, p2, etc.)
        priority = "Medium"
        for label in labels:
            if label.lower().startswith("p0") or label.lower() == "critical":
                priority = "Critical"
                break
            elif label.lower().startswith("p1") or label.lower() == "high":
                priority = "High"
                break
            elif label.lower().startswith("p2"):
                priority = "Medium"
                break

        return Epic(
            key=f"{owner}/{repo}#{number}",
            project=f"{owner}/{repo}",
            team=team_name,
            summary=issue.get("title", ""),
            status=status,
            assignee=assignee,
            priority=priority,
            updated=updated_dt,
            days_since_update=days_since,
            is_stale=days_since > self._stale_days,
            is_unassigned=assignee is None,
            url=issue.get("url", f"https://github.com/{owner}/{repo}/issues/{number}"),
            labels=labels,
            issue_type="Epic"
        )
