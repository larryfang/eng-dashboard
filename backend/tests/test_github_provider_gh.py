"""Tests for GitHubProvider."""
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock
from backend.services.git_providers.base import GitProvider, PullRequestData
from backend.services.git_providers.github_provider import GitHubProvider


class TestGitHubProvider:
    def test_implements_git_provider(self):
        provider = GitHubProvider(token="ghp_test", org="acme")
        assert isinstance(provider, GitProvider)

    def test_fetch_pull_requests_uses_search_api(self, monkeypatch):
        """GitHubProvider uses GitHub Search API with org: qualifier for cross-repo PRs."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "total_count": 1,
            "incomplete_results": False,
            "items": [
                {
                    "number": 101,
                    "title": "Add new feature",
                    "state": "closed",
                    "created_at": "2026-01-15T10:00:00Z",
                    "pull_request": {
                        "merged_at": "2026-01-16T14:30:00Z",
                        "html_url": "https://github.com/acme/repo/pull/101",
                    },
                    "repository_url": "https://api.github.com/repos/acme/repo",
                    "user": {"login": "jdoe"},
                    "body": "Fixes issue #42",
                },
            ],
        }
        mock_response.raise_for_status = MagicMock()
        mock_response.headers = {}

        provider = GitHubProvider(token="ghp_test", org="acme")
        monkeypatch.setattr(provider._http, "get", lambda *a, **kw: mock_response)

        prs = provider.fetch_pull_requests("jdoe", "2026-01-01T00:00:00Z")
        assert len(prs) == 1
        assert prs[0].pr_iid == 101
        assert prs[0].repo_id == "acme/repo"
        assert prs[0].state == "merged"  # closed + merged_at = "merged"
        assert prs[0].web_url == "https://github.com/acme/repo/pull/101"

    def test_fetch_pull_requests_maps_closed_without_merge_to_closed(self, monkeypatch):
        """PRs that are closed but not merged should have state='closed', not 'merged'."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "total_count": 1,
            "incomplete_results": False,
            "items": [
                {
                    "number": 102,
                    "title": "Rejected PR",
                    "state": "closed",
                    "created_at": "2026-01-15T10:00:00Z",
                    "pull_request": {"merged_at": None, "html_url": "https://github.com/acme/repo/pull/102"},
                    "repository_url": "https://api.github.com/repos/acme/repo",
                    "user": {"login": "jdoe"},
                    "body": None,
                },
            ],
        }
        mock_response.raise_for_status = MagicMock()
        mock_response.headers = {}

        provider = GitHubProvider(token="ghp_test", org="acme")
        monkeypatch.setattr(provider._http, "get", lambda *a, **kw: mock_response)

        prs = provider.fetch_pull_requests("jdoe", "2026-01-01T00:00:00Z")
        assert prs[0].state == "closed"
        assert prs[0].merged_at is None

    def test_fetch_commit_count_uses_search_commits(self, monkeypatch):
        mock_response = MagicMock()
        mock_response.json.return_value = {"total_count": 47}
        mock_response.raise_for_status = MagicMock()

        provider = GitHubProvider(token="ghp_test", org="acme")
        monkeypatch.setattr(provider._http, "get", lambda *a, **kw: mock_response)

        count = provider.fetch_commit_count("jdoe", "2026-01-01T00:00:00Z")
        assert count == 47

    def test_fetch_review_count_uses_search_reviewed_by(self, monkeypatch):
        mock_response = MagicMock()
        mock_response.json.return_value = {"total_count": 12}
        mock_response.raise_for_status = MagicMock()

        provider = GitHubProvider(token="ghp_test", org="acme")
        monkeypatch.setattr(provider._http, "get", lambda *a, **kw: mock_response)

        count = provider.fetch_review_count("jdoe", "2026-01-01T00:00:00Z")
        assert count == 12

    def test_close_closes_http_session(self):
        provider = GitHubProvider(token="ghp_test", org="acme")
        provider._http.close = MagicMock()
        provider.close()
        provider._http.close.assert_called_once()
