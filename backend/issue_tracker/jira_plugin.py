"""
Jira Cloud plugin implementation.

Uses REST API with Basic Auth (API tokens).
"""

import os
import base64
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any

import requests

from backend.issue_tracker.base import IssueTrackerPlugin, Epic, Sprint, Issue
from backend.base import PluginConfig
from backend.core.config_loader import get_config
from backend.plugins.registry import register

logger = logging.getLogger(__name__)


@register("issue_tracker", "jira")
class JiraPlugin(IssueTrackerPlugin):
    """
    Jira Cloud integration via REST API.

    Uses Basic Authentication with API tokens (no expiration, no admin approval).
    """

    @property
    def name(self) -> str:
        return "jira"

    @property
    def provider(self) -> str:
        return "jira"

    def __init__(self, config: PluginConfig):
        super().__init__(config)

        # Load from environment
        self.email = os.getenv("JIRA_EMAIL")
        self.api_token = os.getenv("JIRA_API_TOKEN")

        # Get Jira URL from config or environment
        self.jira_url = os.getenv("JIRA_URL")
        if not self.jira_url:
            org_config = get_config()
            self.jira_url = org_config.atlassian_site_url or ""
        self.jira_url = self.jira_url.rstrip("/")

        # Build auth header
        self._auth_header: Optional[str] = None
        if self.email and self.api_token:
            credentials = f"{self.email}:{self.api_token}"
            encoded = base64.b64encode(credentials.encode()).decode()
            self._auth_header = f"Basic {encoded}"

        # Load org config for team resolution
        self._org_config = get_config()

        # Stale threshold from config
        self._stale_days = self._org_config.metrics.stale_epic_days

    def initialize(self) -> None:
        """Initialize and verify connection."""
        super().initialize()
        if not self.health_check():
            logger.warning("Jira plugin initialized but health check failed")

    def health_check(self) -> bool:
        """Test connection to Jira."""
        if not self._auth_header:
            logger.error("Jira credentials not configured")
            return False

        try:
            response = requests.get(
                f"{self.jira_url}/rest/api/3/myself",
                headers=self._get_headers(),
                timeout=10
            )
            if response.status_code == 200:
                user = response.json()
                logger.info(f"Jira connected as: {user.get('displayName')}")
                return True
            logger.error(f"Jira health check failed: {response.status_code}")
            return False
        except Exception as e:
            logger.error(f"Jira health check error: {e}")
            return False

    def _get_headers(self) -> Dict[str, str]:
        """Get request headers with Basic Auth."""
        return {
            "Authorization": self._auth_header or "",
            "Accept": "application/json",
            "Content-Type": "application/json"
        }

    def _resolve_team(self, project_key: str) -> str:
        """Resolve project key to team name using config."""
        team = self._org_config.get_team(project_key)
        return team.name if team else project_key

    def _get_project_keys(self, team_keys: List[str]) -> List[str]:
        """Convert team keys to Jira project keys."""
        project_keys = []
        for key in team_keys:
            team = self._org_config.get_team(key)
            if team and team.jira_project:
                project_keys.append(team.jira_project)
            else:
                # Assume it's already a project key
                project_keys.append(key)
        return project_keys

    def search_epics(
        self,
        team_keys: List[str],
        exclude_done: bool = True
    ) -> List[Epic]:
        """Search epics using config-driven team mapping."""
        project_keys = self._get_project_keys(team_keys)

        if not project_keys:
            return []

        # Build JQL
        quoted = ', '.join(f'"{p}"' for p in project_keys)
        jql = f"project in ({quoted}) AND issuetype = Epic"

        if exclude_done:
            jql += " AND status not in (Done, Closed, Cancelled)"

        jql += " ORDER BY updated DESC"

        logger.debug(f"Jira JQL: {jql}")

        # Execute paginated search
        all_issues = self._search_all(jql)

        # Convert to Epic objects
        return self._parse_epics(all_issues)

    def get_epic(self, key: str) -> Optional[Epic]:
        """Get single epic by key."""
        try:
            response = requests.get(
                f"{self.jira_url}/rest/api/3/issue/{key}",
                headers=self._get_headers(),
                timeout=30
            )

            if response.status_code != 200:
                return None

            issue = response.json()
            epics = self._parse_epics([issue])
            return epics[0] if epics else None

        except Exception as e:
            logger.error(f"Error fetching epic {key}: {e}")
            return None

    def get_sprints(
        self,
        team_key: str,
        state: str = "closed"
    ) -> List[Sprint]:
        """Get sprints for a team."""
        # This requires the Jira Software API and board ID
        # For now, return empty - implement when needed
        logger.warning("get_sprints not yet implemented for Jira plugin")
        return []

    def get_child_issues(self, epic_key: str) -> List[Issue]:
        """Get child issues for an epic."""
        jql = f'"Epic Link" = {epic_key} OR parent = {epic_key}'

        try:
            issues = self._search_all(jql, max_results=100)
            return self._parse_issues(issues)
        except Exception as e:
            logger.error(f"Error fetching children for {epic_key}: {e}")
            return []

    def get_child_issues_activity(
        self,
        epic_keys: List[str]
    ) -> Dict[str, datetime]:
        """Get most recent child activity for epics (optimized bulk query)."""
        if not epic_keys:
            return {}

        # Query children for all epics at once
        quoted_keys = ', '.join(f'"{k}"' for k in epic_keys)
        jql = f'("Epic Link" in ({quoted_keys}) OR parent in ({quoted_keys})) ORDER BY updated DESC'

        try:
            result = self._search(jql, max_results=100)
            if result.get("error"):
                return {}

            # Build mapping of epic -> most recent child update
            epic_child_updates: Dict[str, datetime] = {}

            for issue in result.get("issues", []):
                fields = issue.get("fields", {})
                updated_raw = fields.get("updated", "")

                if not updated_raw:
                    continue

                try:
                    updated_dt = datetime.fromisoformat(
                        updated_raw.replace("Z", "+00:00").split("+")[0]
                    )
                except ValueError:
                    continue

                # Find parent epic key
                parent_key = None

                # Check parent field (next-gen projects)
                parent_obj = fields.get("parent")
                if parent_obj and parent_obj.get("key") in epic_keys:
                    parent_key = parent_obj.get("key")

                # Check Epic Link (classic projects)
                if not parent_key:
                    epic_link = fields.get("customfield_10014")
                    if epic_link and isinstance(epic_link, str) and epic_link in epic_keys:
                        parent_key = epic_link

                if parent_key:
                    if parent_key not in epic_child_updates or updated_dt > epic_child_updates[parent_key]:
                        epic_child_updates[parent_key] = updated_dt

            return epic_child_updates

        except Exception as e:
            logger.error(f"Error checking child activity: {e}")
            return {}

    def _search(
        self,
        jql: str,
        fields: Optional[List[str]] = None,
        max_results: int = 100,
        next_page_token: Optional[str] = None
    ) -> Dict[str, Any]:
        """Execute single Jira search."""
        if fields is None:
            fields = ["summary", "status", "assignee", "priority", "updated",
                      "issuetype", "project", "parent", "customfield_10014"]

        payload = {
            "jql": jql,
            "fields": fields,
            "maxResults": min(max_results, 100)
        }

        if next_page_token:
            payload["nextPageToken"] = next_page_token

        try:
            response = requests.post(
                f"{self.jira_url}/rest/api/3/search/jql",
                json=payload,
                headers=self._get_headers(),
                timeout=30
            )

            if response.status_code != 200:
                logger.error(f"Jira search failed: {response.status_code}")
                return {"issues": [], "isLast": True, "error": f"http_{response.status_code}"}

            return response.json()

        except Exception as e:
            logger.error(f"Jira search error: {e}")
            return {"issues": [], "isLast": True, "error": str(e)}

    def _search_all(
        self,
        jql: str,
        fields: Optional[List[str]] = None,
        max_results: int = 500
    ) -> List[Dict[str, Any]]:
        """Execute paginated Jira search."""
        all_issues = []
        next_token = None

        while len(all_issues) < max_results:
            result = self._search(jql, fields, 100, next_token)

            if result.get("error"):
                break

            issues = result.get("issues", [])
            is_last = result.get("isLast", True)
            next_token = result.get("nextPageToken")

            all_issues.extend(issues)

            if is_last or not next_token or len(issues) == 0:
                break

        return all_issues[:max_results]

    def _parse_epics(self, issues: List[Dict[str, Any]]) -> List[Epic]:
        """Parse Jira issues to normalized Epic objects."""
        epics = []
        now = datetime.now()

        for issue in issues:
            fields = issue.get("fields", {})
            key = issue.get("key", "")

            project_key = fields.get("project", {}).get("key", key.split("-")[0])
            team_name = self._resolve_team(project_key)

            status = fields.get("status", {}).get("name", "Unknown")
            assignee_obj = fields.get("assignee")
            assignee = assignee_obj.get("displayName") if assignee_obj else None
            priority = fields.get("priority", {}).get("name", "Medium")

            # Parse updated date
            updated_raw = fields.get("updated", "")
            try:
                updated_dt = datetime.fromisoformat(
                    updated_raw.replace("Z", "+00:00").split("+")[0]
                )
                days_since = (now - updated_dt).days
            except ValueError:
                updated_dt = now
                days_since = 0

            epics.append(Epic(
                key=key,
                project=project_key,
                team=team_name,
                summary=fields.get("summary", ""),
                status=status,
                assignee=assignee,
                priority=priority,
                updated=updated_dt,
                days_since_update=days_since,
                is_stale=days_since > self._stale_days,
                is_unassigned=assignee is None,
                url=f"{self.jira_url}/browse/{key}",
                issue_type=fields.get("issuetype", {}).get("name", "Epic")
            ))

        return epics

    def _parse_issues(self, issues: List[Dict[str, Any]]) -> List[Issue]:
        """Parse Jira issues to normalized Issue objects."""
        result = []
        now = datetime.now()

        for issue in issues:
            fields = issue.get("fields", {})
            key = issue.get("key", "")

            project_key = fields.get("project", {}).get("key", key.split("-")[0])
            team_name = self._resolve_team(project_key)

            assignee_obj = fields.get("assignee")

            # Parse updated date
            updated_raw = fields.get("updated", "")
            try:
                updated_dt = datetime.fromisoformat(
                    updated_raw.replace("Z", "+00:00").split("+")[0]
                )
            except ValueError:
                updated_dt = now

            # Get parent key
            parent_key = None
            parent_obj = fields.get("parent")
            if parent_obj:
                parent_key = parent_obj.get("key")
            if not parent_key:
                parent_key = fields.get("customfield_10014")

            result.append(Issue(
                key=key,
                project=project_key,
                team=team_name,
                summary=fields.get("summary", ""),
                issue_type=fields.get("issuetype", {}).get("name", ""),
                status=fields.get("status", {}).get("name", "Unknown"),
                assignee=assignee_obj.get("displayName") if assignee_obj else None,
                priority=fields.get("priority", {}).get("name", "Medium"),
                updated=updated_dt,
                parent_key=parent_key,
                url=f"{self.jira_url}/browse/{key}"
            ))

        return result
