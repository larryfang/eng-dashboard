"""Factory for creating issue tracker plugin instances from domain configuration."""

import logging
from typing import Optional

from backend.base import PluginConfig
from backend.issue_tracker.base import IssueTrackerPlugin

logger = logging.getLogger(__name__)

# Module-level singleton for caching
_instance: Optional[IssueTrackerPlugin] = None


def create_issue_tracker(provider_name: Optional[str] = None) -> IssueTrackerPlugin:
    """
    Create an IssueTrackerPlugin instance based on provider name.

    If provider_name is None, reads from domain config's integrations.issue_tracker.provider.

    Args:
        provider_name: "jira" or "github". If None, auto-detect from config.

    Returns:
        Configured IssueTrackerPlugin instance.

    Raises:
        ValueError: If provider_name is not supported.
        RuntimeError: If no issue tracker is configured.
    """
    if provider_name is None:
        provider_name = _get_configured_provider()

    if provider_name == "jira":
        from backend.issue_tracker.jira_plugin import JiraPlugin
        plugin = JiraPlugin(config=PluginConfig())
        plugin.initialize()
        return plugin

    if provider_name in ("github", "github-issues"):
        from backend.issue_tracker.github_plugin import GitHubIssuesPlugin
        from backend.services.domain_credentials import get_github_settings
        settings = get_github_settings()
        plugin = GitHubIssuesPlugin(config=PluginConfig(settings={
            "organization": settings.get("org", ""),
        }))
        plugin.initialize()
        return plugin

    raise ValueError(f"Unsupported issue tracker provider: '{provider_name}'. Supported: jira, github")


def get_issue_tracker() -> IssueTrackerPlugin:
    """
    Get or create the issue tracker plugin singleton.

    Returns cached instance if available, otherwise creates a new one.
    """
    global _instance
    if _instance is None:
        _instance = create_issue_tracker()
    return _instance


def reset_issue_tracker() -> None:
    """Reset the cached singleton (useful for testing or config changes)."""
    global _instance
    _instance = None


def _get_configured_provider() -> str:
    """Read the issue tracker provider from domain config."""
    try:
        from backend.core.config_loader import get_domain_config
        from backend.services.domain_registry import get_active_slug
        cfg = get_domain_config(get_active_slug())
        it = cfg.integrations.get("issue_tracker")
        if it:
            return it.provider
    except Exception as e:
        logger.debug(f"Could not read issue tracker config: {e}")

    # Fallback: check if Jira env vars are set
    import os
    if os.getenv("JIRA_API_TOKEN"):
        return "jira"
    if os.getenv("GITHUB_TOKEN"):
        return "github"

    raise RuntimeError("No issue tracker configured. Set integrations.issue_tracker in organization.yaml or provide JIRA_API_TOKEN/GITHUB_TOKEN env vars.")
