"""Tests for GitHub Teams API discovery."""
import pytest
from unittest.mock import MagicMock, patch
from backend.services.git_providers.github_discovery import discover_github_teams


class TestGitHubDiscovery:
    def test_discover_teams_returns_team_structure(self, monkeypatch):
        """discover_github_teams returns list of teams with members and repos."""
        import requests

        mock_http = MagicMock(spec=requests.Session)

        # Mock teams list
        teams_response = MagicMock()
        teams_response.json.return_value = [
            {"name": "Platform", "slug": "platform", "parent": None},
            {"name": "Frontend", "slug": "frontend", "parent": {"slug": "platform"}},
        ]
        teams_response.raise_for_status = MagicMock()

        # Mock members list (same for both teams in this test)
        members_response = MagicMock()
        members_response.json.return_value = [
            {"login": "alice", "name": "Alice A"},
            {"login": "bob", "name": None},  # name can be null
        ]
        members_response.raise_for_status = MagicMock()

        # Mock repos list
        repos_response = MagicMock()
        repos_response.json.return_value = [
            {"name": "backend", "full_name": "acme/backend"},
        ]
        repos_response.raise_for_status = MagicMock()

        def mock_get(url, **kwargs):
            if "/teams?" in url or url.endswith("/teams"):
                return teams_response
            if "/members" in url:
                return members_response
            if "/repos" in url:
                return repos_response
            return teams_response

        mock_http.get = mock_get
        mock_http.headers = {}
        mock_http.close = MagicMock()

        # Patch requests.Session to return our mock
        monkeypatch.setattr(
            "backend.services.git_providers.github_discovery.requests.Session",
            lambda: mock_http,
        )

        teams = discover_github_teams(token="ghp_test", org="acme")

        assert len(teams) == 2
        assert teams[0]["slug"] == "platform"
        assert teams[0]["parent_slug"] is None
        assert len(teams[0]["members"]) == 2
        assert teams[0]["members"][0]["username"] == "alice"
        assert teams[0]["members"][1]["username"] == "bob"
        assert teams[0]["members"][1]["name"] == "bob"  # falls back to login
        assert len(teams[0]["repos"]) == 1
        assert teams[0]["repos"][0]["full_name"] == "acme/backend"

        assert teams[1]["slug"] == "frontend"
        assert teams[1]["parent_slug"] == "platform"

    def test_discover_teams_empty_org(self, monkeypatch):
        """Empty org returns empty list."""
        import requests

        mock_http = MagicMock(spec=requests.Session)
        empty_response = MagicMock()
        empty_response.json.return_value = []
        empty_response.raise_for_status = MagicMock()
        mock_http.get = lambda *a, **kw: empty_response
        mock_http.headers = {}
        mock_http.close = MagicMock()

        monkeypatch.setattr(
            "backend.services.git_providers.github_discovery.requests.Session",
            lambda: mock_http,
        )

        teams = discover_github_teams(token="ghp_test", org="empty-org")
        assert teams == []

    def test_paginate_handles_multiple_pages(self, monkeypatch):
        """_paginate fetches all pages until items < per_page."""
        from backend.services.git_providers.github_discovery import _paginate
        import requests

        mock_http = MagicMock(spec=requests.Session)
        call_count = 0

        def mock_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            resp = MagicMock()
            if call_count == 1:
                resp.json.return_value = [{"id": i} for i in range(100)]
            else:
                resp.json.return_value = [{"id": i} for i in range(50)]
            resp.raise_for_status = MagicMock()
            return resp

        mock_http.get = mock_get
        items = _paginate(mock_http, "https://api.github.com/orgs/acme/teams")
        assert len(items) == 150
        assert call_count == 2
