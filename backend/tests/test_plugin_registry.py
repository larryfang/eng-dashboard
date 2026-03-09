"""Tests for plugin registry."""
import pytest
from backend.plugins.registry import register, get_plugin_class, list_plugins, list_plugin_types, _registry


class TestPluginRegistry:
    def setup_method(self):
        """Save and clear registry state for isolation."""
        self._saved = {k: dict(v) for k, v in _registry.items()}

    def teardown_method(self):
        """Restore registry state."""
        _registry.clear()
        _registry.update(self._saved)

    def test_register_decorator(self):
        @register("test_type", "test_provider")
        class TestPlugin:
            pass

        assert get_plugin_class("test_type", "test_provider") is TestPlugin

    def test_register_multiple_providers(self):
        @register("test_type", "provider_a")
        class PluginA:
            pass

        @register("test_type", "provider_b")
        class PluginB:
            pass

        assert get_plugin_class("test_type", "provider_a") is PluginA
        assert get_plugin_class("test_type", "provider_b") is PluginB

    def test_list_plugins(self):
        @register("test_type", "alpha")
        class Alpha:
            pass

        @register("test_type", "beta")
        class Beta:
            pass

        plugins = list_plugins("test_type")
        assert "alpha" in plugins
        assert "beta" in plugins

    def test_list_plugin_types(self):
        @register("type_a", "x")
        class X:
            pass

        @register("type_b", "y")
        class Y:
            pass

        types = list_plugin_types()
        assert "type_a" in types
        assert "type_b" in types

    def test_get_missing_plugin_raises(self):
        with pytest.raises(KeyError, match="No 'nonexistent'"):
            get_plugin_class("test_type", "nonexistent")

    def test_list_empty_type(self):
        assert list_plugins("nonexistent_type") == []

    def test_register_preserves_class(self):
        """Decorator should return the original class unchanged."""
        @register("test_type", "preserved")
        class Original:
            value = 42

        assert Original.value == 42


class TestBuiltinRegistration:
    """Test that built-in providers are registered correctly."""

    def test_git_providers_registered(self):
        # Force imports to trigger @register decorators
        from backend.services.git_providers.gitlab_provider import GitLabProvider
        from backend.services.git_providers.github_provider import GitHubProvider

        assert get_plugin_class("git_provider", "gitlab") is GitLabProvider
        assert get_plugin_class("git_provider", "github") is GitHubProvider

    def test_issue_trackers_registered(self):
        from backend.issue_tracker.jira_plugin import JiraPlugin
        from backend.issue_tracker.github_plugin import GitHubIssuesPlugin

        assert get_plugin_class("issue_tracker", "jira") is JiraPlugin
        assert get_plugin_class("issue_tracker", "github") is GitHubIssuesPlugin

    def test_code_platforms_registered(self):
        from backend.code_platform.gitlab_plugin import GitLabPlugin
        from backend.code_platform.github_plugin import GitHubPlugin

        assert get_plugin_class("code_platform", "gitlab") is GitLabPlugin
        assert get_plugin_class("code_platform", "github") is GitHubPlugin
