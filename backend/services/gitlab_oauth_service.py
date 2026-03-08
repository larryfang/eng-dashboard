#!/usr/bin/env python3
"""
GitLab OAuth 2.0 Service

Direct GitLab API access using OAuth 2.0 with automatic token refresh.
Replaces static PAT-based access for better security and auto-renewal.

Setup:
1. Create OAuth app at https://gitlab.com/-/user_settings/applications
2. Add scopes: api, read_api, read_user, read_repository
3. Run initial auth: python3 gitlab_oauth_service.py --setup
4. Store credentials in .env

Usage:
    from backend.services.gitlab_oauth_service import GitLabOAuthService

    gitlab = GitLabOAuthService()
    mrs = gitlab.get_merge_requests("org/group", days=30)
"""

import os
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any

import requests
from dotenv import load_dotenv

# Load environment
load_dotenv()

# Constants
GITLAB_API_BASE = "https://gitlab.com/api/v4"
GITLAB_GRAPHQL_ENDPOINT = "https://gitlab.com/api/graphql"
DEFAULT_TIMEOUT = 30  # seconds


# Simple in-memory cache for group projects
_group_projects_cache: Dict[str, tuple] = {}  # group_path -> (projects, timestamp)
CACHE_TTL_SECONDS = 300  # 5 minutes


class GitLabOAuthService:
    """
    GitLab API service using a Personal Access Token (GITLAB_TOKEN env var).
    """

    def __init__(self):
        self._token = os.getenv("GITLAB_TOKEN")

    def _get_token(self) -> Optional[str]:
        """Return the configured GitLab token."""
        return self._token

    def _get_headers(self) -> Dict[str, str]:
        """Get authorization headers."""
        token = self._get_token()
        if not token:
            raise RuntimeError("No GitLab token available. Run setup or set GITLAB_TOKEN.")

        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

    # ==================== REST API METHODS ====================

    def get_current_user(self) -> Optional[Dict[str, Any]]:
        """
        Get current authenticated user info.

        Returns:
            User data or None
        """
        response = requests.get(
            f"{GITLAB_API_BASE}/user",
            headers=self._get_headers()
        )

        if response.status_code != 200:
            print(f"  Failed to get user: {response.status_code}")
            return None

        return response.json()

    def get_project(self, project_path: str) -> Optional[Dict[str, Any]]:
        """
        Get project details by path.

        Args:
            project_path: Project path (e.g., 'acme/teams/billing')

        Returns:
            Project data or None
        """
        encoded_path = urllib.parse.quote(project_path, safe='')
        response = requests.get(
            f"{GITLAB_API_BASE}/projects/{encoded_path}",
            headers=self._get_headers()
        )

        if response.status_code != 200:
            print(f"  Failed to get project: {response.status_code}")
            return None

        return response.json()

    def get_merge_requests(
        self,
        project_path: str,
        state: str = "merged",
        days: int = 30,
        per_page: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get merge requests for a project.

        Args:
            project_path: Project path
            state: MR state ('merged', 'opened', 'closed', 'all')
            days: Number of days to look back
            per_page: Results per page

        Returns:
            List of merge requests
        """
        encoded_path = urllib.parse.quote(project_path, safe='')
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        all_mrs = []
        page = 1

        while True:
            params = {
                "state": state,
                "updated_after": since,
                "per_page": per_page,
                "page": page,
            }

            try:
                response = requests.get(
                    f"{GITLAB_API_BASE}/projects/{encoded_path}/merge_requests",
                    headers=self._get_headers(),
                    params=params,
                    timeout=DEFAULT_TIMEOUT
                )
            except requests.Timeout:
                print(f"  Timeout fetching MRs for {project_path}")
                break

            if response.status_code != 200:
                print(f"  Failed to get MRs: {response.status_code}")
                break

            mrs = response.json()
            if not mrs:
                break

            all_mrs.extend(mrs)
            page += 1

            if len(mrs) < per_page:
                break

        return all_mrs

    def get_group_projects(
        self,
        group_path: str,
        include_subgroups: bool = True,
        use_cache: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Get all projects in a group.

        Args:
            group_path: Group path (e.g., 'acme/teams')
            include_subgroups: Include projects from subgroups
            use_cache: Use cached results if available (default: True)

        Returns:
            List of projects
        """
        import time
        
        # Check cache first
        cache_key = f"{group_path}:{include_subgroups}"
        if use_cache and cache_key in _group_projects_cache:
            projects, cached_at = _group_projects_cache[cache_key]
            if time.time() - cached_at < CACHE_TTL_SECONDS:
                return projects
        
        encoded_path = urllib.parse.quote(group_path, safe='')

        all_projects = []
        page = 1

        while True:
            params = {
                "include_subgroups": str(include_subgroups).lower(),
                "per_page": 100,
                "page": page,
            }

            try:
                response = requests.get(
                    f"{GITLAB_API_BASE}/groups/{encoded_path}/projects",
                    headers=self._get_headers(),
                    params=params,
                    timeout=DEFAULT_TIMEOUT
                )
            except requests.Timeout:
                print(f"  Timeout fetching projects for {group_path} (page {page})")
                break

            if response.status_code != 200:
                print(f"  Failed to get projects: {response.status_code}")
                break

            projects = response.json()
            if not projects:
                break

            all_projects.extend(projects)
            page += 1

            if len(projects) < 100:
                break

        # Cache the results
        _group_projects_cache[cache_key] = (all_projects, time.time())
        
        return all_projects

    # ==================== GRAPHQL API METHODS ====================

    def graphql_query(self, query: str, variables: Optional[Dict] = None) -> Optional[Dict]:
        """
        Execute a GraphQL query.

        Args:
            query: GraphQL query string
            variables: Optional query variables

        Returns:
            Query response data or None
        """
        payload: Dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables

        response = requests.post(
            GITLAB_GRAPHQL_ENDPOINT,
            headers=self._get_headers(),
            json=payload
        )

        if response.status_code != 200:
            print(f"  GraphQL query failed: {response.status_code}")
            return None

        data = response.json()

        if "errors" in data:
            print(f"  GraphQL errors: {data['errors']}")
            return None

        return data.get("data")

    def get_group_mr_stats(
        self,
        group_path: str,
        days: int = 30
    ) -> Dict[str, Any]:
        """
        Get merge request statistics for a group using GraphQL.

        Args:
            group_path: Group path
            days: Number of days to analyze

        Returns:
            MR statistics
        """
        since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")

        query = """
        query($groupPath: ID!, $mergedAfter: Time) {
          group(fullPath: $groupPath) {
            name
            mergeRequests(state: merged, mergedAfter: $mergedAfter, first: 100) {
              count
              nodes {
                iid
                title
                mergedAt
                author {
                  username
                }
                project {
                  name
                  fullPath
                }
              }
            }
          }
        }
        """

        variables = {
            "groupPath": group_path,
            "mergedAfter": f"{since}T00:00:00Z"
        }

        data = self.graphql_query(query, variables)
        if not data or not data.get("group"):
            return {"error": "Failed to fetch MR stats", "count": 0, "mrs": []}

        group = data["group"]
        mrs = group.get("mergeRequests", {})

        return {
            "group_name": group.get("name"),
            "count": mrs.get("count", 0),
            "mrs": mrs.get("nodes", []),
            "period_days": days
        }

    def get_project_pipelines(
        self,
        project_path: str,
        days: int = 7,
        per_page: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get recent pipelines for a project.

        Args:
            project_path: Project path
            days: Number of days to look back
            per_page: Results per page

        Returns:
            List of pipelines
        """
        encoded_path = urllib.parse.quote(project_path, safe='')
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        all_pipelines = []
        page = 1

        while True:
            params = {
                "updated_after": since,
                "per_page": per_page,
                "page": page,
            }

            response = requests.get(
                f"{GITLAB_API_BASE}/projects/{encoded_path}/pipelines",
                headers=self._get_headers(),
                params=params
            )

            if response.status_code != 200:
                print(f"  Failed to get pipelines: {response.status_code}")
                break

            pipelines = response.json()
            if not pipelines:
                break

            all_pipelines.extend(pipelines)
            page += 1

            if len(pipelines) < per_page:
                break

        return all_pipelines


# ==================== CLI ====================

def main():
    """CLI for GitLab OAuth service."""
    import argparse

    parser = argparse.ArgumentParser(description="GitLab OAuth 2.0 Service")
    parser.add_argument("--test", action="store_true", help="Test API connection")
    parser.add_argument("--status", action="store_true", help="Show token status")
    parser.add_argument("--mrs", metavar="GROUP", help="Get MR stats for a group")
    parser.add_argument("--days", type=int, default=30, help="Days to look back (default: 30)")
    args = parser.parse_args()

    gitlab = GitLabOAuthService()

    if args.status:
        token = gitlab._get_token()
        print("\n=== GitLab Token Status ===")
        print(f"  GITLAB_TOKEN configured: {'Yes' if token else 'No'}")
        return

    if args.test:
        print("Testing GitLab API connection...")
        user = gitlab.get_current_user()
        if user:
            print(f"  ✓ Connected as: {user.get('username')} ({user.get('name')})")
            print(f"    Email: {user.get('email')}")
        else:
            print("  ✗ Could not connect to GitLab API")
        return

    if args.mrs:
        print(f"Getting MR stats for {args.mrs} (last {args.days} days)...")
        stats = gitlab.get_group_mr_stats(args.mrs, days=args.days)

        if "error" in stats:
            print(f"  Error: {stats['error']}")
        else:
            print(f"\n  Group: {stats['group_name']}")
            print(f"  Merged MRs: {stats['count']}")
            if stats['mrs']:
                print(f"\n  Recent MRs:")
                for mr in stats['mrs'][:5]:
                    author = mr.get('author', {}).get('username', 'unknown')
                    print(f"    - {mr['title'][:50]}... by @{author}")
        return

    # Default: show help
    parser.print_help()


if __name__ == "__main__":
    main()
