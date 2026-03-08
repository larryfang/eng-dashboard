#!/usr/bin/env python3
"""
Jira OAuth 2.0 (3LO) Service

Direct Jira API access using OAuth 2.0 with automatic token refresh.
Replaces MCP-based Jira access for better reliability and control.

Setup:
1. Create OAuth app at https://developer.atlassian.com/console/myapps/
2. Add Jira scopes: read:jira-work, read:jira-user, offline_access
3. Run initial auth: python3 jira_oauth_service.py --setup
4. Store credentials in .env

Usage:
    from backend.services.jira_oauth_service import JiraOAuthService

    jira = JiraOAuthService()
    epics = jira.search_epics(projects=['NS', 'SF', 'SMTHZ', 'NEXT'])
"""

import os
import json
import time
import webbrowser
import http.server
import socketserver
import urllib.parse
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from pathlib import Path

import requests
from dotenv import load_dotenv, set_key

# Load environment
load_dotenv()

# Constants
AUTH_URL = "https://auth.atlassian.com/authorize"
TOKEN_URL = "https://auth.atlassian.com/oauth/token"
RESOURCES_URL = "https://api.atlassian.com/oauth/token/accessible-resources"
JIRA_API_BASE = "https://api.atlassian.com/ex/jira"

# Required scopes for epic tracking
REQUIRED_SCOPES = [
    "read:jira-work",      # Read issues, projects, etc.
    "read:jira-user",      # Read user info
    "offline_access",      # Get refresh token
]


class JiraOAuthService:
    """
    Jira OAuth 2.0 service with automatic token refresh.

    This service manages OAuth tokens and provides methods for
    querying Jira directly without MCP middleware.
    """

    def __init__(self, env_path: Optional[str] = None):
        """
        Initialize Jira OAuth service.

        Args:
            env_path: Path to .env file (default: project root)
        """
        self.env_path = env_path or str(Path(__file__).parent.parent.parent / ".env")

        # Load credentials from environment
        self.client_id = os.getenv("JIRA_OAUTH_CLIENT_ID")
        self.client_secret = os.getenv("JIRA_OAUTH_CLIENT_SECRET")
        self.refresh_token = os.getenv("JIRA_OAUTH_REFRESH_TOKEN")
        self.access_token = os.getenv("JIRA_OAUTH_ACCESS_TOKEN")
        self.token_expiry = os.getenv("JIRA_OAUTH_TOKEN_EXPIRY")
        self.cloud_id = os.getenv("ATLASSIAN_CLOUD_ID", "")

        # Parse token expiry
        if self.token_expiry:
            try:
                self.token_expiry_dt = datetime.fromisoformat(self.token_expiry)
            except Exception:
                self.token_expiry_dt = None
        else:
            self.token_expiry_dt = None

    @property
    def is_configured(self) -> bool:
        """Check if OAuth credentials are configured."""
        return all([self.client_id, self.client_secret, self.refresh_token])

    @property
    def needs_refresh(self) -> bool:
        """Check if access token needs refresh (expired or expiring soon)."""
        if not self.access_token or not self.token_expiry_dt:
            return True
        # Refresh 5 minutes before expiry
        return datetime.now() >= (self.token_expiry_dt - timedelta(minutes=5))

    def refresh_access_token(self) -> bool:
        """
        Refresh the access token using the refresh token.

        Returns:
            True if refresh successful, False otherwise
        """
        if not self.refresh_token:
            print("  No refresh token available. Run --setup first.")
            return False

        try:
            response = requests.post(
                TOKEN_URL,
                json={
                    "grant_type": "refresh_token",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": self.refresh_token
                },
                headers={"Content-Type": "application/json"}
            )

            if response.status_code != 200:
                print(f"  Token refresh failed: {response.status_code}")
                print(f"  Response: {response.text[:200]}")
                return False

            data = response.json()

            # Update tokens
            self.access_token = data.get("access_token")
            new_refresh_token = data.get("refresh_token")
            expires_in = data.get("expires_in", 3600)

            # Calculate expiry time
            self.token_expiry_dt = datetime.now() + timedelta(seconds=expires_in)
            self.token_expiry = self.token_expiry_dt.isoformat()

            # Rotating refresh tokens - update if we got a new one
            if new_refresh_token and new_refresh_token != self.refresh_token:
                self.refresh_token = new_refresh_token
                self._save_to_env("JIRA_OAUTH_REFRESH_TOKEN", new_refresh_token)

            # Save new access token and expiry
            self._save_to_env("JIRA_OAUTH_ACCESS_TOKEN", self.access_token)
            self._save_to_env("JIRA_OAUTH_TOKEN_EXPIRY", self.token_expiry)

            print(f"  Access token refreshed, expires: {self.token_expiry_dt.strftime('%H:%M:%S')}")
            return True

        except Exception as e:
            print(f"  Token refresh error: {e}")
            return False

    def _save_to_env(self, key: str, value: str):
        """Save a value to the .env file."""
        try:
            set_key(self.env_path, key, value)
        except Exception as e:
            print(f"  Warning: Could not save {key} to .env: {e}")

    def _get_headers(self) -> Dict[str, str]:
        """Get authorization headers, refreshing token if needed."""
        if self.needs_refresh:
            if not self.refresh_access_token():
                raise RuntimeError("Failed to refresh access token")

        return {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json"
        }

    def _api_url(self, endpoint: str) -> str:
        """Build full API URL."""
        return f"{JIRA_API_BASE}/{self.cloud_id}/rest/api/3/{endpoint}"

    # ==================== JIRA API METHODS ====================

    def search_issues(
        self,
        jql: str,
        fields: Optional[List[str]] = None,
        max_results: int = 100,
        start_at: int = 0
    ) -> Dict[str, Any]:
        """
        Search Jira issues using JQL.

        Args:
            jql: JQL query string
            fields: List of fields to return
            max_results: Maximum results per page (max 100)
            start_at: Pagination offset

        Returns:
            API response with issues
        """
        if fields is None:
            fields = ["summary", "status", "assignee", "priority", "updated", "issuetype", "project"]

        payload = {
            "jql": jql,
            "fields": fields,
            "maxResults": min(max_results, 100),
            "startAt": start_at
        }

        response = requests.post(
            self._api_url("search"),
            json=payload,
            headers=self._get_headers()
        )

        if response.status_code != 200:
            print(f"  JQL search failed: {response.status_code}")
            print(f"  Response: {response.text[:300]}")
            return {"issues": [], "total": 0}

        return response.json()

    def search_all_issues(
        self,
        jql: str,
        fields: Optional[List[str]] = None,
        max_total: int = 500
    ) -> List[Dict[str, Any]]:
        """
        Search all issues matching JQL with automatic pagination.

        Args:
            jql: JQL query string
            fields: List of fields to return
            max_total: Maximum total results to fetch

        Returns:
            List of all matching issues
        """
        all_issues = []
        start_at = 0
        page_size = 100

        while len(all_issues) < max_total:
            result = self.search_issues(jql, fields, page_size, start_at)
            issues = result.get("issues", [])
            total = result.get("total", 0)

            all_issues.extend(issues)

            if len(issues) < page_size or len(all_issues) >= total:
                break

            start_at += page_size
            print(f"  Fetched {len(all_issues)}/{min(total, max_total)} issues...")

        return all_issues[:max_total]

    def search_epics(
        self,
        projects: List[str],
        statuses: Optional[List[str]] = None,
        fields: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Search for epics in specified projects.

        Args:
            projects: List of project keys (e.g., ['NS', 'SF'])
            statuses: Optional list of statuses to filter
            fields: Fields to return

        Returns:
            List of epic issues
        """
        if fields is None:
            fields = ["summary", "status", "assignee", "priority", "updated", "issuetype", "project"]

        # Build JQL
        project_clause = f"project in ({', '.join(projects)})"
        jql = f"{project_clause} AND issuetype = Epic"

        if statuses:
            status_clause = f"status in ({', '.join(f'\"{s}\"' for s in statuses)})"
            jql = f"{jql} AND {status_clause}"

        jql = f"{jql} ORDER BY updated DESC"

        print(f"  JQL: {jql}")
        return self.search_all_issues(jql, fields)

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

        response = requests.get(
            self._api_url(f"issue/{issue_key}"),
            params=params,
            headers=self._get_headers()
        )

        if response.status_code != 200:
            print(f"  Failed to get issue {issue_key}: {response.status_code}")
            return None

        return response.json()

    def get_accessible_resources(self) -> List[Dict[str, Any]]:
        """
        Get list of accessible Atlassian resources (sites).

        Returns:
            List of accessible resources with cloud IDs
        """
        response = requests.get(
            RESOURCES_URL,
            headers=self._get_headers()
        )

        if response.status_code != 200:
            print(f"  Failed to get resources: {response.status_code}")
            return []

        return response.json()

    # ==================== SETUP / INITIAL AUTH ====================

    def setup_oauth(self, callback_port: int = 8765):
        """
        Interactive setup for OAuth credentials.
        Opens browser for authorization and captures tokens.

        Args:
            callback_port: Port for OAuth callback server
        """
        print("\n=== Jira OAuth 2.0 Setup ===\n")

        # Check for client credentials
        if not self.client_id or not self.client_secret:
            print("First, create an OAuth 2.0 (3LO) app:")
            print("1. Go to: https://developer.atlassian.com/console/myapps/")
            print("2. Create a new app")
            print("3. Go to Authorization > Configure OAuth 2.0 (3LO)")
            print("4. Add callback URL: http://localhost:8765/callback")
            print("5. Add scopes: read:jira-work, read:jira-user")
            print()

            self.client_id = input("Enter Client ID: ").strip()
            self.client_secret = input("Enter Client Secret: ").strip()

            # Save to .env
            self._save_to_env("JIRA_OAUTH_CLIENT_ID", self.client_id)
            self._save_to_env("JIRA_OAUTH_CLIENT_SECRET", self.client_secret)

        # Build authorization URL
        callback_url = f"http://localhost:{callback_port}/callback"
        scope = " ".join(REQUIRED_SCOPES)

        auth_params = {
            "audience": "api.atlassian.com",
            "client_id": self.client_id,
            "scope": scope,
            "redirect_uri": callback_url,
            "response_type": "code",
            "prompt": "consent"
        }

        auth_url = f"{AUTH_URL}?{urllib.parse.urlencode(auth_params)}"

        print(f"\nOpening browser for authorization...")
        print(f"If browser doesn't open, go to:\n{auth_url}\n")

        # Start callback server
        auth_code = self._run_callback_server(callback_port)

        if not auth_code:
            print("Authorization failed - no code received")
            return

        print(f"Authorization code received, exchanging for tokens...")

        # Exchange code for tokens
        response = requests.post(
            TOKEN_URL,
            json={
                "grant_type": "authorization_code",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "code": auth_code,
                "redirect_uri": callback_url
            },
            headers={"Content-Type": "application/json"}
        )

        if response.status_code != 200:
            print(f"Token exchange failed: {response.status_code}")
            print(f"Response: {response.text}")
            return

        data = response.json()

        # Save tokens
        self.access_token = data.get("access_token")
        self.refresh_token = data.get("refresh_token")
        expires_in = data.get("expires_in", 3600)
        self.token_expiry_dt = datetime.now() + timedelta(seconds=expires_in)
        self.token_expiry = self.token_expiry_dt.isoformat()

        self._save_to_env("JIRA_OAUTH_ACCESS_TOKEN", self.access_token)
        self._save_to_env("JIRA_OAUTH_REFRESH_TOKEN", self.refresh_token)
        self._save_to_env("JIRA_OAUTH_TOKEN_EXPIRY", self.token_expiry)

        print(f"\n Setup complete!")
        print(f"  Access token expires: {self.token_expiry_dt}")
        print(f"  Refresh token saved to .env")

        # Get and display cloud ID
        resources = self.get_accessible_resources()
        if resources:
            print(f"\n  Accessible sites:")
            for r in resources:
                print(f"    - {r.get('name')}: {r.get('id')}")
                from backend.core.paths import get_jira_site_url
                site = get_jira_site_url()
                if site and site.split("//")[-1].split(".")[0] in r.get("url", "").lower():
                    self._save_to_env("ATLASSIAN_CLOUD_ID", r.get("id"))
                    print(f"      ^ Saved as ATLASSIAN_CLOUD_ID")

        print("\nYou can now use JiraOAuthService for direct API access!")

    def _run_callback_server(self, port: int) -> Optional[str]:
        """Run temporary server to capture OAuth callback."""
        auth_code = None

        class CallbackHandler(http.server.SimpleHTTPRequestHandler):
            def do_GET(self):
                nonlocal auth_code

                parsed = urllib.parse.urlparse(self.path)
                params = urllib.parse.parse_qs(parsed.query)

                if "code" in params:
                    auth_code = params["code"][0]
                    self.send_response(200)
                    self.send_header("Content-type", "text/html")
                    self.end_headers()
                    self.wfile.write(b"""
                        <html><body style="font-family: sans-serif; text-align: center; padding: 50px;">
                        <h1>Authorization Successful!</h1>
                        <p>You can close this window and return to the terminal.</p>
                        </body></html>
                    """)
                else:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b"Authorization failed")

            def log_message(self, format, *args):
                pass  # Suppress logging

        # Open browser
        auth_params = {
            "audience": "api.atlassian.com",
            "client_id": self.client_id,
            "scope": " ".join(REQUIRED_SCOPES),
            "redirect_uri": f"http://localhost:{port}/callback",
            "response_type": "code",
            "prompt": "consent"
        }
        auth_url = f"{AUTH_URL}?{urllib.parse.urlencode(auth_params)}"
        webbrowser.open(auth_url)

        # Run server until we get the code
        with socketserver.TCPServer(("", port), CallbackHandler) as httpd:
            httpd.timeout = 120  # 2 minute timeout
            while auth_code is None:
                httpd.handle_request()

        return auth_code


# ==================== CLI ====================

def main():
    """CLI for Jira OAuth service."""
    import argparse

    parser = argparse.ArgumentParser(description="Jira OAuth 2.0 Service")
    parser.add_argument("--setup", action="store_true", help="Run interactive OAuth setup")
    parser.add_argument("--test", action="store_true", help="Test API connection")
    parser.add_argument("--epics", nargs="+", metavar="PROJECT", help="Fetch epics for projects")
    parser.add_argument("--refresh", action="store_true", help="Force token refresh")
    args = parser.parse_args()

    jira = JiraOAuthService()

    if args.setup:
        jira.setup_oauth()
        return

    if not jira.is_configured:
        print("Jira OAuth not configured. Run with --setup first.")
        return

    if args.refresh:
        print("Refreshing access token...")
        if jira.refresh_access_token():
            print("Token refreshed successfully!")
        return

    if args.test:
        print("Testing API connection...")
        resources = jira.get_accessible_resources()
        if resources:
            print(f"Connected! Found {len(resources)} accessible sites:")
            for r in resources:
                print(f"  - {r.get('name')} ({r.get('url')})")
        else:
            print("Could not connect to Atlassian API")
        return

    if args.epics:
        print(f"Fetching epics for: {args.epics}")
        epics = jira.search_epics(args.epics)
        print(f"\nFound {len(epics)} epics:")
        for epic in epics[:10]:
            fields = epic.get("fields", {})
            key = epic.get("key")
            summary = fields.get("summary", "No summary")[:50]
            status = fields.get("status", {}).get("name", "Unknown")
            print(f"  {key}: {summary}... [{status}]")
        if len(epics) > 10:
            print(f"  ... and {len(epics) - 10} more")
        return

    # Default: show status
    print("Jira OAuth Service Status")
    print(f"  Configured: {jira.is_configured}")
    if jira.is_configured:
        print(f"  Token expiry: {jira.token_expiry}")
        print(f"  Needs refresh: {jira.needs_refresh}")
        print(f"  Cloud ID: {jira.cloud_id}")


if __name__ == "__main__":
    main()
