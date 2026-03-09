"""Factory for creating git provider instances from domain configuration."""

from backend.services.git_providers.base import GitProvider
from backend.services.domain_credentials import get_gitlab_settings, get_github_settings


def create_provider(provider_name: str) -> GitProvider:
    """
    Create a GitProvider instance based on the provider name.

    Args:
        provider_name: "gitlab" or "github"

    Returns:
        Configured GitProvider instance.

    Raises:
        ValueError: If provider_name is not supported.
        RuntimeError: If credentials are not configured.
    """
    if provider_name == "gitlab":
        settings = get_gitlab_settings()
        if not settings["token"]:
            raise RuntimeError("GitLab credentials are not configured for the active domain")
        from backend.services.git_providers.gitlab_provider import GitLabProvider
        return GitLabProvider(url=settings["url"], token=settings["token"])

    if provider_name == "github":
        settings = get_github_settings()
        if not settings["token"]:
            raise RuntimeError("GitHub credentials are not configured for the active domain")
        from backend.services.git_providers.github_provider import GitHubProvider
        return GitHubProvider(token=settings["token"], org=settings["org"])

    raise ValueError(f"Unsupported git provider: '{provider_name}'. Supported: gitlab, github")
