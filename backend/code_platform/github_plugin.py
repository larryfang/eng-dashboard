"""
GitHub code platform plugin — stub implementation.

Returns empty/default results for all methods.  This will be fleshed out
once the GitHub provider integration is fully wired up.
"""

import logging
from typing import List, Optional

from backend.code_platform.base import (
    CodePlatformPlugin,
    DORAMetrics,
    MergeRequest,
    Pipeline,
    Repository,
    SearchResult,
)
from backend.base import PluginConfig
from backend.plugins.registry import register

logger = logging.getLogger(__name__)


@register("code_platform", "github")
class GitHubPlugin(CodePlatformPlugin):
    """GitHub integration (stub).

    All data-fetching methods return empty lists or zero-value defaults.
    """

    @property
    def name(self) -> str:
        return "github"

    @property
    def provider(self) -> str:
        return "github"

    def __init__(self, config: PluginConfig) -> None:
        super().__init__(config)
        # TODO: store GitHub API token, org name, etc. from config.settings
        self._token: Optional[str] = config.settings.get("token")
        self._org: Optional[str] = config.settings.get("org")

    def initialize(self) -> None:
        """Initialize the GitHub plugin."""
        super().initialize()
        # TODO: validate credentials and set up API client
        logger.info("GitHubPlugin initialized (stub — no live API calls)")

    def health_check(self) -> bool:
        """Check connectivity to the GitHub API."""
        # TODO: call GET /user or GET /orgs/{org} to verify credentials
        if not self._token:
            logger.warning("GitHubPlugin health check: no token configured")
            return False
        return True

    # -- data methods (all stubs) ------------------------------------------

    def get_repos(
        self,
        team: Optional[str] = None,
    ) -> List[Repository]:
        """List repositories from GitHub."""
        # TODO: call GitHub REST/GraphQL API to list org repos
        #       and map them to Repository dataclass instances
        logger.debug("GitHubPlugin.get_repos called (stub)")
        return []

    def get_merge_requests(
        self,
        team: Optional[str] = None,
        state: str = "merged",
        days: int = 30,
    ) -> List[MergeRequest]:
        """Fetch pull requests from GitHub."""
        # TODO: call GitHub REST API for pull requests
        #       Map PR state ("open", "closed" + merged flag) to our state enum
        logger.debug("GitHubPlugin.get_merge_requests called (stub)")
        return []

    def get_pipelines(
        self,
        team: Optional[str] = None,
        days: int = 30,
    ) -> List[Pipeline]:
        """Fetch GitHub Actions workflow runs."""
        # TODO: call GET /repos/{owner}/{repo}/actions/runs
        #       and map workflow runs to Pipeline dataclass instances
        logger.debug("GitHubPlugin.get_pipelines called (stub)")
        return []

    def get_dora_metrics(
        self,
        team: Optional[str] = None,
        days: int = 30,
    ) -> DORAMetrics:
        """Compute DORA metrics from GitHub data."""
        # TODO: aggregate deployment frequency from merged PRs to default branch,
        #       lead time from PR open→merge, change failure rate from reverts, etc.
        logger.debug("GitHubPlugin.get_dora_metrics called (stub)")
        return DORAMetrics(
            team=team or "all",
            period_days=days,
            deployment_frequency=0.0,
        )

    def search_code(
        self,
        query: str,
        team: Optional[str] = None,
    ) -> List[SearchResult]:
        """Search code on GitHub."""
        # TODO: call GET /search/code?q={query}+org:{org}
        #       and map results to SearchResult dataclass instances
        logger.debug("GitHubPlugin.search_code called (stub)")
        return []
