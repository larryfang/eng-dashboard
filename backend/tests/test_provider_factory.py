"""Tests for git provider factory."""
import pytest
from backend.services.git_providers.base import GitProvider
from backend.services.git_providers.factory import create_provider
from backend.services.git_providers.gitlab_provider import GitLabProvider
from backend.services.git_providers.github_provider import GitHubProvider


class TestProviderFactory:
    def test_create_gitlab_provider(self, monkeypatch):
        monkeypatch.setattr(
            "backend.services.git_providers.factory.get_gitlab_settings",
            lambda *a, **kw: {"url": "https://gitlab.com", "token": "glpat-xxx", "base_group": ""},
        )
        provider = create_provider("gitlab")
        assert isinstance(provider, GitLabProvider)
        assert isinstance(provider, GitProvider)
        provider.close()

    def test_create_github_provider(self, monkeypatch):
        monkeypatch.setattr(
            "backend.services.git_providers.factory.get_github_settings",
            lambda *a, **kw: {"token": "ghp_xxx", "org": "acme"},
        )
        provider = create_provider("github")
        assert isinstance(provider, GitHubProvider)
        assert isinstance(provider, GitProvider)
        provider.close()

    def test_create_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unsupported git provider"):
            create_provider("bitbucket")

    def test_create_github_without_token_raises(self, monkeypatch):
        monkeypatch.setattr(
            "backend.services.git_providers.factory.get_github_settings",
            lambda *a, **kw: {"token": "", "org": "acme"},
        )
        with pytest.raises(RuntimeError, match="not configured"):
            create_provider("github")

    def test_create_gitlab_without_token_raises(self, monkeypatch):
        monkeypatch.setattr(
            "backend.services.git_providers.factory.get_gitlab_settings",
            lambda *a, **kw: {"url": "https://gitlab.com", "token": "", "base_group": ""},
        )
        with pytest.raises(RuntimeError, match="not configured"):
            create_provider("gitlab")
