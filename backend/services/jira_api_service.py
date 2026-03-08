#!/usr/bin/env python3
"""
Jira REST API Service (Basic Auth with API Token)

Direct Jira API access using Basic Authentication with API tokens.
No admin approval needed - any user can create their own API token.

Setup:
1. Create API token at: https://id.atlassian.com/manage-profile/security/api-tokens
2. Add to .env:
   JIRA_EMAIL=your.email@company.com
   JIRA_API_TOKEN=your_api_token
   JIRA_URL=https://yoursite.atlassian.net

Usage:
    from backend.services.jira_api_service import JiraAPIService

    jira = JiraAPIService()
    epics = jira.search_epics(projects=['NS', 'SF', 'SMTHZ', 'NEXT'])

Configuration:
    Team mappings are now loaded from config/organization.yaml.
    The PROJECT_TO_TEAM variable is kept for backward compatibility.
"""

import os
import base64
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

import requests
from dotenv import load_dotenv

from backend.services.domain_credentials import get_jira_settings

# Load environment
load_dotenv()

# ==================== OBSERVABILITY ====================
# Add agent-observability SDK to path
_obs_path = Path(__file__).parent.parent.parent / "agent-observability"
if _obs_path.exists():
    sys.path.insert(0, str(_obs_path))
    try:
        from integrations.em_copilot import trace_jira, trace_service
        from src import SpanKind
        from src.semantic.conventions import ToolAttributes, HTTPAttributes
        _OBSERVABILITY_ENABLED = True
    except ImportError:
        _OBSERVABILITY_ENABLED = False
else:
    _OBSERVABILITY_ENABLED = False

# No-op decorators when observability is disabled
if not _OBSERVABILITY_ENABLED:
    def trace_jira(func):
        return func
    def trace_service(name, category=None):
        def decorator(func):
            return func
        return decorator

logger = logging.getLogger(__name__)


def _get_project_to_team_from_config() -> Dict[str, str]:
    """
    Get PROJECT_TO_TEAM mapping from organization config.

    Falls back to empty dict if config not available.
    """
    try:
        from backend.core.config_loader import get_config
        return get_config().project_to_team_map
    except Exception as e:
        logger.debug(f"Config not available, using empty mapping: {e}")
        return {}


def _get_default_jira_url() -> str:
    """
    Get default Jira URL from config or environment.

    Priority:
    1. JIRA_URL environment variable
    2. Organization config atlassian_site_url
    3. Hardcoded fallback (for backward compatibility)
    """
    return get_jira_settings()["url"]


def get_project_to_team() -> Dict[str, str]:
    """Get PROJECT_TO_TEAM mapping for the active domain."""
    return _get_project_to_team_from_config()


# Backward compatibility - expose as module-level variable
# Uses lazy loading so config is only accessed when needed
# Note: Call get_project_to_team() for guaranteed fresh data
PROJECT_TO_TEAM: Dict[str, str] = {}  # Will be populated on first access via get_project_to_team()


def _resolve_team_name(project_key: str) -> str:
    """Resolve project key to team name using config."""
    mapping = get_project_to_team()
    return mapping.get(project_key, project_key)


class JiraAPIService:
    """
    Jira REST API service using Basic Auth with API tokens.

    API tokens don't expire and don't need admin approval.
    Each user can create their own at:
    https://id.atlassian.com/manage-profile/security/api-tokens
    """

    def __init__(
        self,
        email: Optional[str] = None,
        api_token: Optional[str] = None,
        jira_url: Optional[str] = None
    ):
        """
        Initialize Jira API service.

        Args:
            email: Jira account email (default from JIRA_EMAIL env)
            api_token: API token (default from JIRA_API_TOKEN env)
            jira_url: Jira instance URL (default from JIRA_URL env)
        """
        settings = get_jira_settings()
        self.email = email or settings["email"]
        self.api_token = api_token or settings["token"]
        self.jira_url = (jira_url or settings["url"] or _get_default_jira_url()).rstrip("/")

        # Build Basic Auth header
        if self.email and self.api_token:
            credentials = f"{self.email}:{self.api_token}"
            encoded = base64.b64encode(credentials.encode()).decode()
            self._auth_header = f"Basic {encoded}"
        else:
            self._auth_header = None

    @property
    def is_configured(self) -> bool:
        """Check if API credentials are configured."""
        return all([self.email, self.api_token, self.jira_url])

    def _get_headers(self) -> Dict[str, str]:
        """Get request headers with Basic Auth."""
        if not self._auth_header:
            raise RuntimeError("Jira credentials are not configured for the active domain")

        return {
            "Authorization": self._auth_header,
            "Accept": "application/json",
            "Content-Type": "application/json"
        }

    def _api_url(self, endpoint: str) -> str:
        """Build full API URL."""
        return f"{self.jira_url}/rest/api/3/{endpoint}"

    # ==================== JIRA API METHODS ====================

    @trace_jira
    def search_issues(
        self,
        jql: str,
        fields: Optional[List[str]] = None,
        max_results: int = 100,
        next_page_token: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Search Jira issues using JQL.

        Uses the new /rest/api/3/search/jql endpoint (old /search was deprecated Dec 2024).
        See: https://developer.atlassian.com/changelog/#CHANGE-2046

        New API uses token-based pagination:
        - Response includes 'nextPageToken' and 'isLast'
        - Pass nextPageToken to get next page

        Args:
            jql: JQL query string
            fields: List of fields to return
            max_results: Maximum results per page (max 100)
            next_page_token: Token for pagination (from previous response)

        Returns:
            API response with issues, nextPageToken, and isLast flag
        """
        if fields is None:
            fields = ["summary", "status", "assignee", "priority", "updated", "issuetype", "project"]

        payload = {
            "jql": jql,
            "fields": fields,
            "maxResults": min(max_results, 100)
        }

        if next_page_token:
            payload["nextPageToken"] = next_page_token

        try:
            # Use new search/jql endpoint (old /search deprecated Dec 2024)
            response = requests.post(
                self._api_url("search/jql"),
                json=payload,
                headers=self._get_headers(),
                timeout=30
            )

            if response.status_code == 401:
                print("  ERROR: Authentication failed. Check JIRA_EMAIL and JIRA_API_TOKEN")
                return {"issues": [], "isLast": True, "error": "auth_failed"}

            if response.status_code == 403:
                print("  ERROR: Permission denied. Your account may not have access.")
                return {"issues": [], "isLast": True, "error": "forbidden"}

            if response.status_code != 200:
                print(f"  JQL search failed: {response.status_code}")
                print(f"  Response: {response.text[:300]}")
                return {"issues": [], "isLast": True, "error": f"http_{response.status_code}"}

            return response.json()

        except requests.exceptions.Timeout:
            print("  ERROR: Request timed out")
            return {"issues": [], "isLast": True, "error": "timeout"}
        except requests.exceptions.RequestException as e:
            print(f"  ERROR: Request failed: {e}")
            return {"issues": [], "isLast": True, "error": str(e)}

    @trace_jira
    def search_all_issues(
        self,
        jql: str,
        fields: Optional[List[str]] = None,
        max_total: int = 500
    ) -> List[Dict[str, Any]]:
        """
        Search all issues matching JQL with automatic pagination.

        Uses token-based pagination from the new Jira API.

        Args:
            jql: JQL query string
            fields: List of fields to return
            max_total: Maximum total results to fetch

        Returns:
            List of all matching issues
        """
        all_issues = []
        next_token = None
        page_size = 100
        page_num = 1

        while len(all_issues) < max_total:
            result = self.search_issues(jql, fields, page_size, next_token)

            # Check for errors
            if result.get("error"):
                break

            issues = result.get("issues", [])
            is_last = result.get("isLast", True)
            next_token = result.get("nextPageToken")

            all_issues.extend(issues)
            print(f"  Page {page_num}: fetched {len(issues)} issues (total: {len(all_issues)})")

            if is_last or not next_token or len(issues) == 0:
                break

            page_num += 1

        return all_issues[:max_total]

    @trace_jira
    def search_epics(
        self,
        projects: List[str],
        statuses: Optional[List[str]] = None,
        exclude_done: bool = True,
        fields: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Search for epics in specified projects.

        Args:
            projects: List of project keys (e.g., ['NS', 'SF'])
            statuses: Optional list of statuses to filter
            exclude_done: Exclude Done/Closed epics (default True)
            fields: Fields to return

        Returns:
            List of epic issues
        """
        if fields is None:
            fields = ["summary", "status", "assignee", "priority", "updated", "issuetype", "project"]

        # JQL note: the new /search/jql endpoint silently returns 0 results
        # for double-quoted project keys. Use bare keys, backtick-quoting only
        # for reserved words (e.g. NEXT) which would otherwise be misinterpreted.
        _RESERVED = {"NEXT", "ORDER", "BY", "AND", "OR", "NOT", "IN", "IS", "WAS"}
        def _jql_project(key: str) -> str:
            return f"`{key}`" if key.upper() in _RESERVED else key
        quoted_projects = ', '.join(_jql_project(p) for p in projects)
        project_clause = f"project in ({quoted_projects})"
        jql = f"{project_clause} AND issuetype = Epic"

        if statuses:
            status_clause = f"status in ({', '.join(f'\"{s}\"' for s in statuses)})"
            jql = f"{jql} AND {status_clause}"
        elif exclude_done:
            jql = f"{jql} AND status not in (Done, Closed, Cancelled)"

        jql = f"{jql} ORDER BY updated DESC"

        print(f"  JQL: {jql}")
        return self.search_all_issues(jql, fields)

    @trace_jira
    def get_issue(self, issue_key: str, fields: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
        """
        Get a single issue by key.

        Args:
            issue_key: Issue key (e.g., 'NS-123')
            fields: Fields to return

        Returns:
            Issue data or None
        """
        params = {}
        if fields:
            params["fields"] = ",".join(fields)

        try:
            response = requests.get(
                self._api_url(f"issue/{issue_key}"),
                params=params,
                headers=self._get_headers(),
                timeout=30
            )

            if response.status_code != 200:
                print(f"  Failed to get issue {issue_key}: {response.status_code}")
                return None

            return response.json()

        except Exception as e:
            print(f"  Error fetching {issue_key}: {e}")
            return None

    @trace_jira
    def test_connection(self) -> bool:
        """
        Test API connection by fetching current user.

        Returns:
            True if connection successful
        """
        try:
            response = requests.get(
                f"{self.jira_url}/rest/api/3/myself",
                headers=self._get_headers(),
                timeout=10
            )

            if response.status_code == 200:
                user = response.json()
                print(f"  Connected as: {user.get('displayName')} ({user.get('emailAddress')})")
                return True
            else:
                print(f"  Connection failed: {response.status_code}")
                return False

        except Exception as e:
            print(f"  Connection error: {e}")
            return False

    # ==================== AGILE / BOARD METHODS ====================

    @trace_jira
    def get_boards(
        self,
        project_key: Optional[str] = None,
        board_type: str = "scrum"
    ) -> List[Dict[str, Any]]:
        """
        Get Jira boards, optionally filtered by project.

        Uses Jira Agile REST API.

        Args:
            project_key: Optional project key to filter boards
            board_type: Board type ('scrum', 'kanban', or None for all)

        Returns:
            List of board objects with id, name, type
        """
        all_boards = []
        start_at = 0
        max_results = 50

        while True:
            params = {
                "startAt": start_at,
                "maxResults": max_results,
            }
            if project_key:
                params["projectKeyOrId"] = project_key
            if board_type:
                params["type"] = board_type

            try:
                response = requests.get(
                    f"{self.jira_url}/rest/agile/1.0/board",
                    headers=self._get_headers(),
                    params=params,
                    timeout=30
                )

                if response.status_code != 200:
                    print(f"  Failed to get boards: {response.status_code}")
                    break

                data = response.json()
                boards = data.get("values", [])
                all_boards.extend(boards)

                if data.get("isLast", True) or len(boards) < max_results:
                    break

                start_at += max_results

            except Exception as e:
                print(f"  Error getting boards: {e}")
                break

        return all_boards

    @trace_jira
    def get_sprints(
        self,
        board_id: int,
        state: str = "active,closed"
    ) -> List[Dict[str, Any]]:
        """
        Get sprints for a board.

        Args:
            board_id: Board ID
            state: Sprint state filter ('active', 'closed', 'future', or comma-separated)

        Returns:
            List of sprint objects
        """
        all_sprints = []
        start_at = 0
        max_results = 50

        while True:
            params = {
                "startAt": start_at,
                "maxResults": max_results,
                "state": state,
            }

            try:
                response = requests.get(
                    f"{self.jira_url}/rest/agile/1.0/board/{board_id}/sprint",
                    headers=self._get_headers(),
                    params=params,
                    timeout=30
                )

                if response.status_code != 200:
                    print(f"  Failed to get sprints: {response.status_code}")
                    break

                data = response.json()
                sprints = data.get("values", [])
                all_sprints.extend(sprints)

                if data.get("isLast", True) or len(sprints) < max_results:
                    break

                start_at += max_results

            except Exception as e:
                print(f"  Error getting sprints: {e}")
                break

        return all_sprints

    # ==================== CHILD ISSUE HELPERS ====================

    @trace_jira
    def get_child_issues_last_updated(
        self,
        epic_keys: List[str]
    ) -> Dict[str, datetime]:
        """
        Get the most recent child issue update for each epic.

        Only queries epics that might be stale (optimization).
        Uses "Epic Link" field to find child issues.

        Args:
            epic_keys: List of epic keys to check

        Returns:
            Dict mapping epic key to most recent child updated datetime
        """
        if not epic_keys:
            return {}

        # Query children for all provided epics, ordered by updated DESC
        # Use "parent" for next-gen projects or "Epic Link" for classic
        quoted_keys = ', '.join(f'"{k}"' for k in epic_keys)

        # Try both parent field (next-gen) and Epic Link (classic)
        jql = f'("Epic Link" in ({quoted_keys}) OR parent in ({quoted_keys})) ORDER BY updated DESC'

        print(f"  Checking child activity for {len(epic_keys)} potentially stale epics...")

        try:
            # Fetch children - we only need key, parent, and updated
            result = self.search_issues(
                jql,
                fields=["updated", "parent", "customfield_10014"],  # customfield_10014 is Epic Link
                max_results=100
            )

            if result.get("error"):
                print(f"  Warning: Could not fetch child issues: {result.get('error')}")
                return {}

            # Build mapping of epic -> most recent child update
            epic_child_updates: Dict[str, datetime] = {}

            for issue in result.get("issues", []):
                fields = issue.get("fields", {})
                updated_raw = fields.get("updated", "")

                if not updated_raw:
                    continue

                try:
                    updated_dt = datetime.fromisoformat(updated_raw.replace("Z", "+00:00").split("+")[0])
                except Exception:
                    continue

                # Find parent epic key - check both parent and Epic Link
                parent_key = None

                # Check parent field (next-gen projects)
                parent_obj = fields.get("parent")
                if parent_obj and parent_obj.get("key") in epic_keys:
                    parent_key = parent_obj.get("key")

                # Check Epic Link (classic projects) - customfield_10014
                if not parent_key:
                    epic_link = fields.get("customfield_10014")
                    if epic_link and isinstance(epic_link, str) and epic_link in epic_keys:
                        parent_key = epic_link

                if parent_key:
                    # Keep the most recent update for this epic
                    if parent_key not in epic_child_updates or updated_dt > epic_child_updates[parent_key]:
                        epic_child_updates[parent_key] = updated_dt

            print(f"  Found child activity for {len(epic_child_updates)} epics")
            return epic_child_updates

        except Exception as e:
            print(f"  Warning: Error checking child issues: {e}")
            return {}

    # ==================== PARSING HELPERS ====================

    @trace_service("jira_api", category="parsing")
    def parse_epics_to_dict(self, issues: List[Dict[str, Any]], check_child_activity: bool = True) -> List[Dict[str, Any]]:
        """
        Parse raw Jira issues into clean epic dictionaries.

        Args:
            issues: Raw Jira issue data
            check_child_activity: If True, check child issues for stale epics
                                  (epic is not stale if children were updated recently)

        Same format as jira_epic_parser.py for consistency.

        STALE EPIC DETECTION RULES:
        ---------------------------
        An epic is considered STALE only if BOTH conditions are met:
        1. The epic itself has not been updated for >14 days
        2. NONE of the epic's child issues have been updated for >14 days

        This prevents false positives where an epic hasn't been touched but
        its child stories/tasks are actively being worked on.

        The 14-day threshold is defined by `stale_threshold_days`.
        Child activity is checked via `get_child_issues_last_updated()`.
        """
        parsed = []
        stale_threshold_days = 14

        for issue in issues:
            fields = issue.get("fields", {})
            key = issue.get("key", "UNKNOWN")

            # Extract nested fields safely
            project_obj = fields.get("project", {})
            project_key = project_obj.get("key", key.split("-")[0] if "-" in key else "UNKNOWN")

            status_obj = fields.get("status", {})
            status = status_obj.get("name", "Unknown")

            assignee_obj = fields.get("assignee")
            assignee = assignee_obj.get("displayName", "Unassigned") if assignee_obj else "Unassigned"

            priority_obj = fields.get("priority", {})
            priority = priority_obj.get("name", "Medium")

            issuetype_obj = fields.get("issuetype", {})
            issuetype = issuetype_obj.get("name", "Unknown")

            # Parse updated date
            updated_raw = fields.get("updated", "")
            if updated_raw:
                try:
                    updated_dt = datetime.fromisoformat(updated_raw.replace("Z", "+00:00").split("+")[0])
                    updated = updated_dt.strftime("%Y-%m-%d")
                    days_since = (datetime.now() - updated_dt).days
                except Exception:
                    updated = updated_raw[:10]
                    days_since = 0
                    updated_dt = None
            else:
                updated = "Unknown"
                days_since = 0
                updated_dt = None

            parsed.append({
                "key": key,
                "project": project_key,
                "team": _resolve_team_name(project_key),
                "summary": fields.get("summary", "No summary"),
                "issuetype": issuetype,
                "status": status,
                "assignee": assignee,
                "priority": priority,
                "updated": updated,
                "updated_dt": updated_dt,  # Keep datetime for child activity comparison
                "days_since_update": days_since,
                "is_stale": days_since > stale_threshold_days,  # Preliminary - may be updated
                "is_unassigned": assignee == "Unassigned",
                "url": f"{self.jira_url}/browse/{key}"
            })

        # Check child activity for epics that appear stale
        if check_child_activity:
            stale_epic_keys = [e["key"] for e in parsed if e["is_stale"]]

            if stale_epic_keys:
                # Get child activity for stale epics
                child_updates = self.get_child_issues_last_updated(stale_epic_keys)

                # Update staleness based on child activity
                now = datetime.now()
                updated_count = 0

                for epic in parsed:
                    if epic["key"] in child_updates:
                        child_last_updated = child_updates[epic["key"]]
                        child_days_since = (now - child_last_updated).days

                        # Epic is not stale if children were updated recently
                        if child_days_since <= stale_threshold_days:
                            epic["is_stale"] = False
                            epic["child_last_updated"] = child_last_updated.strftime("%Y-%m-%d")
                            epic["effective_days_since"] = child_days_since
                            updated_count += 1

                if updated_count > 0:
                    print(f"  {updated_count} epics marked as active based on child updates")

        # Clean up internal field
        for epic in parsed:
            epic.pop("updated_dt", None)

        return parsed

    def generate_markdown_report(self, epics: List[Dict[str, Any]]) -> str:
        """Generate markdown table from parsed epics."""
        # Group by team
        by_team = {}
        for epic in epics:
            team = epic["team"]
            if team not in by_team:
                by_team[team] = []
            by_team[team].append(epic)

        lines = ["## Epic Summary by Team\n"]
        lines.append("| Team | Total | In Progress | Unassigned | Stale (>14d) |")
        lines.append("|------|-------|-------------|------------|-------------|")

        for team in sorted(by_team.keys()):
            team_epics = by_team[team]
            total = len(team_epics)
            in_progress = sum(1 for e in team_epics if e["status"] == "In Progress")
            unassigned = sum(1 for e in team_epics if e["is_unassigned"])
            stale = sum(1 for e in team_epics if e["is_stale"])
            lines.append(f"| {team} | {total} | {in_progress} | {unassigned} | {stale} |")

        lines.append("")

        # Detailed tables per team
        for team in sorted(by_team.keys()):
            team_epics = by_team[team]
            project_key = team_epics[0]["project"] if team_epics else "?"

            lines.append(f"### {team} ({project_key})\n")
            lines.append("| Epic | Summary | Status | Assignee | Updated |")
            lines.append("|------|---------|--------|----------|---------|")

            for epic in sorted(team_epics, key=lambda x: x["updated"], reverse=True):
                stale = " (STALE)" if epic["is_stale"] else ""
                unassigned = " (UNASSIGNED)" if epic["is_unassigned"] else ""
                summary = epic["summary"][:50] + "..." if len(epic["summary"]) > 50 else epic["summary"]

                lines.append(
                    f"| [{epic['key']}]({epic['url']}) | {summary} | "
                    f"{epic['status']}{stale} | {epic['assignee']}{unassigned} | {epic['updated']} |"
                )

            lines.append("")

        return "\n".join(lines)


# ==================== CLI ====================

def main():
    """CLI for Jira API service."""
    import argparse

    parser = argparse.ArgumentParser(description="Jira REST API Service (Basic Auth)")
    parser.add_argument("--test", action="store_true", help="Test API connection")
    parser.add_argument("--epics", nargs="+", metavar="PROJECT", help="Fetch epics for projects")
    parser.add_argument("--all-teams", action="store_true", help="Fetch epics for all Ecosystem teams")
    parser.add_argument("--output", "-o", type=str, help="Output file path")
    parser.add_argument("--format", "-f", choices=["json", "markdown"], default="markdown", help="Output format")
    args = parser.parse_args()

    jira = JiraAPIService()

    if not jira.is_configured:
        print("Jira API not configured.")
        print("\nSetup:")
        print("1. Create API token: https://id.atlassian.com/manage-profile/security/api-tokens")
        print("2. Add to .env:")
        print("   JIRA_EMAIL=your.email@company.com")
        print("   JIRA_API_TOKEN=your_token_here")
        print("   JIRA_URL=https://your-site.atlassian.net")
        return

    if args.test:
        print("Testing API connection...")
        jira.test_connection()
        return

    projects = args.epics
    if args.all_teams:
        projects = list(get_project_to_team().keys())

    if projects:
        print(f"Fetching epics for: {projects}")
        raw_epics = jira.search_epics(projects)

        if not raw_epics:
            print("No epics found or error occurred.")
            return

        # Parse to clean format
        epics = jira.parse_epics_to_dict(raw_epics)
        print(f"\nFound {len(epics)} epics")

        # Generate output
        if args.format == "markdown":
            output = jira.generate_markdown_report(epics)
        else:
            output = json.dumps(epics, indent=2, default=str)

        # Save or print
        if args.output:
            with open(args.output, "w") as f:
                f.write(output)
            print(f"Saved to: {args.output}")
        else:
            print(output)

        return

    # Default: show status
    print("Jira API Service Status")
    print(f"  Configured: {jira.is_configured}")
    print(f"  URL: {jira.jira_url}")
    print(f"  Email: {jira.email}")
    print(f"\nRun with --test to verify connection")
    print(f"Run with --all-teams to fetch all Ecosystem epics")


if __name__ == "__main__":
    main()
