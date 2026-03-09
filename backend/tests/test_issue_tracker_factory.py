"""Tests for issue tracker factory."""
import pytest
from unittest.mock import MagicMock
from backend.issue_tracker.factory import create_issue_tracker, get_issue_tracker, reset_issue_tracker
from backend.issue_tracker.base import IssueTrackerPlugin


def _mock_org_config():
    """Build a minimal mock of OrganizationConfig for plugin constructors."""
    cfg = MagicMock()
    cfg.atlassian_site_url = "https://test.atlassian.net"
    cfg.metrics.stale_epic_days = 14
    cfg.get_team.return_value = None
    return cfg


class TestIssueTrackerFactory:
    def setup_method(self):
        reset_issue_tracker()

    def teardown_method(self):
        reset_issue_tracker()

    def test_create_jira_tracker(self, monkeypatch):
        """Jira plugin should be instantiable with env vars."""
        monkeypatch.setenv("JIRA_EMAIL", "test@example.com")
        monkeypatch.setenv("JIRA_API_TOKEN", "test-token")
        monkeypatch.setenv("JIRA_URL", "https://test.atlassian.net")

        # Mock get_config so JiraPlugin.__init__ doesn't need organization.yaml
        monkeypatch.setattr(
            "backend.issue_tracker.jira_plugin.get_config",
            _mock_org_config,
        )

        tracker = create_issue_tracker("jira")
        assert isinstance(tracker, IssueTrackerPlugin)
        assert tracker.name == "jira"

    def test_create_github_tracker(self, monkeypatch):
        """GitHub issues plugin should be instantiable."""
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")

        # Mock get_config for GitHubIssuesPlugin.__init__
        monkeypatch.setattr(
            "backend.issue_tracker.github_plugin.get_config",
            _mock_org_config,
        )
        # Mock get_github_settings used by the factory (lazy import from domain_credentials)
        monkeypatch.setattr(
            "backend.services.domain_credentials.get_github_settings",
            lambda *a, **kw: {"token": "ghp_test", "org": "acme"},
        )

        tracker = create_issue_tracker("github")
        assert isinstance(tracker, IssueTrackerPlugin)
        assert tracker.name == "github-issues"

    def test_create_unknown_raises(self):
        with pytest.raises(ValueError, match="Unsupported issue tracker"):
            create_issue_tracker("linear")

    def test_singleton_caching(self, monkeypatch):
        """get_issue_tracker() should return same instance."""
        monkeypatch.setenv("JIRA_EMAIL", "test@example.com")
        monkeypatch.setenv("JIRA_API_TOKEN", "test-token")
        monkeypatch.setenv("JIRA_URL", "https://test.atlassian.net")
        monkeypatch.setattr(
            "backend.issue_tracker.jira_plugin.get_config",
            _mock_org_config,
        )
        monkeypatch.setattr(
            "backend.issue_tracker.factory._get_configured_provider",
            lambda: "jira",
        )

        a = get_issue_tracker()
        b = get_issue_tracker()
        assert a is b

    def test_reset_clears_singleton(self, monkeypatch):
        monkeypatch.setenv("JIRA_EMAIL", "test@example.com")
        monkeypatch.setenv("JIRA_API_TOKEN", "test-token")
        monkeypatch.setenv("JIRA_URL", "https://test.atlassian.net")
        monkeypatch.setattr(
            "backend.issue_tracker.jira_plugin.get_config",
            _mock_org_config,
        )
        monkeypatch.setattr(
            "backend.issue_tracker.factory._get_configured_provider",
            lambda: "jira",
        )

        a = get_issue_tracker()
        reset_issue_tracker()
        b = get_issue_tracker()
        assert a is not b
