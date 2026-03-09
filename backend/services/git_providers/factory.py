"""Factory for creating git provider instances from domain configuration."""

from backend.services.git_providers.base import GitProvider
from backend.services.domain_credentials import get_gitlab_settings, get_github_settings


def create_provider(provider_name: str) -> GitProvider:
    """
    Create a GitProvider instance based on the provider name.

    Uses plugin registry first, falls back to direct imports.
    """
    # Try registry first (supports external plugins)
    try:
        from backend.plugins.registry import get_plugin_class
        cls = get_plugin_class("git_provider", provider_name)
        return _instantiate_provider(provider_name, cls)
    except KeyError:
        pass

    # Fallback to built-in providers
    if provider_name == "gitlab":
        from backend.services.git_providers.gitlab_provider import GitLabProvider
        settings = get_gitlab_settings()
        if not settings["token"]:
            raise RuntimeError("GitLab credentials are not configured for the active domain")
        return GitLabProvider(url=settings["url"], token=settings["token"])

    if provider_name == "github":
        from backend.services.git_providers.github_provider import GitHubProvider
        settings = get_github_settings()
        if not settings["token"]:
            raise RuntimeError("GitHub credentials are not configured for the active domain")
        return GitHubProvider(token=settings["token"], org=settings["org"])

    raise ValueError(f"Unsupported git provider: '{provider_name}'. Supported: gitlab, github")


def _instantiate_provider(provider_name: str, cls: type) -> GitProvider:
    """Instantiate a provider class with the right credentials."""
    if provider_name == "gitlab":
        settings = get_gitlab_settings()
        if not settings["token"]:
            raise RuntimeError("GitLab credentials are not configured for the active domain")
        return cls(url=settings["url"], token=settings["token"])

    if provider_name in ("github",):
        settings = get_github_settings()
        if not settings["token"]:
            raise RuntimeError("GitHub credentials are not configured for the active domain")
        return cls(token=settings["token"], org=settings["org"])

    raise ValueError(f"Cannot instantiate unknown provider: {provider_name}")
