"""Tests for GitHub credential settings."""
import pytest


class TestGitHubCredentials:
    def test_returns_token_from_env(self, monkeypatch):
        from backend.services.domain_credentials import get_github_settings

        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test123")
        monkeypatch.setenv("GITHUB_ORG", "acme-corp")
        monkeypatch.setattr(
            "backend.services.domain_credentials.load_domain_secrets",
            lambda slug=None: {},
        )
        settings = get_github_settings()
        assert settings["token"] == "ghp_test123"
        assert settings["org"] == "acme-corp"

    def test_secrets_override_env(self, monkeypatch):
        from backend.services.domain_credentials import get_github_settings

        monkeypatch.setenv("GITHUB_TOKEN", "ghp_env")
        monkeypatch.setenv("GITHUB_ORG", "env-org")
        monkeypatch.setattr(
            "backend.services.domain_credentials.load_domain_secrets",
            lambda slug=None: {"github": {"token": "ghp_secret", "org": "secret-org"}},
        )
        settings = get_github_settings()
        assert settings["token"] == "ghp_secret"
        assert settings["org"] == "secret-org"

    def test_empty_when_nothing_configured(self, monkeypatch):
        from backend.services.domain_credentials import get_github_settings

        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GITHUB_ORG", raising=False)
        monkeypatch.setattr(
            "backend.services.domain_credentials.load_domain_secrets",
            lambda slug=None: {},
        )
        settings = get_github_settings()
        assert settings["token"] == ""
        assert settings["org"] == ""
