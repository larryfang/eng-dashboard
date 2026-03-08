"""
GitLab code platform plugin implementation.

Wraps the existing gitlab_intelligence module as a thin facade.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from .base import (
    CodePlatformPlugin,
    DORAMetrics,
    MergeRequest,
    Pipeline,
    Repository,
    SearchResult,
)
from ..base import PluginConfig
from ...services.gitlab_intelligence import (
    GitLabCollector,
    DORAService,
    RepoScanner,
    SearchService,
    get_collector,
    get_dora_service,
    get_repo_scanner,
    get_search_service,
)

logger = logging.getLogger(__name__)


class GitLabPlugin(CodePlatformPlugin):
    """
    GitLab integration via the existing gitlab_intelligence module.

    This is a thin facade that delegates to:
    - RepoScanner for repository listing
    - GitLabCollector for pipeline and MR data
    - DORAService for DORA metrics
    - SearchService for code search
    """

    @property
    def name(self) -> str:
        return "gitlab"

    @property
    def provider(self) -> str:
        return "gitlab"

    def __init__(self, config: PluginConfig):
        super().__init__(config)

        self._collector: Optional[GitLabCollector] = None
        self._dora_service: Optional[DORAService] = None
        self._repo_scanner: Optional[RepoScanner] = None
        self._search_service: Optional[SearchService] = None

    def initialize(self) -> None:
        """Initialize by obtaining service instances."""
        super().initialize()

        self._collector = get_collector()
        self._dora_service = get_dora_service()
        self._repo_scanner = get_repo_scanner()
        self._search_service = get_search_service()

        if not self.health_check():
            logger.warning("GitLab plugin initialized but health check failed")

    def health_check(self) -> bool:
        """Test connection to GitLab API."""
        if not self._collector:
            logger.error("GitLab collector not initialized")
            return False

        try:
            result = self._collector.health_check()
            return result.get("status") == "healthy"
        except Exception as e:
            logger.error(f"GitLab health check error: {e}")
            return False

    def get_repos(
        self,
        team: Optional[str] = None
    ) -> List[Repository]:
        """List repositories from database via RepoScanner."""
        if not self._repo_scanner:
            return []

        try:
            if team:
                raw_repos = self._repo_scanner.get_team_repos(team)
            else:
                # Get repos for all teams
                from backend.config.gitlab_teams import TEAM_GITLAB_PATHS
                raw_repos = []
                for team_slug in TEAM_GITLAB_PATHS:
                    raw_repos.extend(self._repo_scanner.get_team_repos(team_slug))

            return [self._map_repo(r) for r in raw_repos]

        except Exception as e:
            logger.error(f"Error fetching repos: {e}")
            return []

    def get_merge_requests(
        self,
        team: Optional[str] = None,
        state: str = "merged",
        days: int = 30
    ) -> List[MergeRequest]:
        """Get merge requests from GitLab via collector."""
        if not self._collector:
            return []

        try:
            from backend.config.gitlab_teams import TEAM_GITLAB_PATHS
            since_date = (
                datetime.now(timezone.utc) - timedelta(days=days)
            ).strftime("%Y-%m-%d")

            teams_to_query = {}
            if team:
                if team in TEAM_GITLAB_PATHS:
                    teams_to_query = {team: TEAM_GITLAB_PATHS[team]}
            else:
                teams_to_query = TEAM_GITLAB_PATHS

            all_mrs = []
            for team_slug, paths in teams_to_query.items():
                for path in paths:
                    try:
                        raw_mrs = self._collector.fetch_merge_requests(path, since_date)
                        for mr in raw_mrs:
                            all_mrs.append(self._map_mr(mr, team_slug))
                    except Exception as e:
                        logger.warning(f"Error fetching MRs from {path}: {e}")

            return all_mrs

        except Exception as e:
            logger.error(f"Error fetching merge requests: {e}")
            return []

    def get_pipelines(
        self,
        team: Optional[str] = None,
        days: int = 30
    ) -> List[Pipeline]:
        """Get pipeline runs from GitLab via collector."""
        if not self._collector:
            return []

        try:
            from backend.config.gitlab_teams import TEAM_GITLAB_PATHS
            since_date = (
                datetime.now(timezone.utc) - timedelta(days=days)
            ).strftime("%Y-%m-%d")

            teams_to_query = {}
            if team:
                if team in TEAM_GITLAB_PATHS:
                    teams_to_query = {team: TEAM_GITLAB_PATHS[team]}
            else:
                teams_to_query = TEAM_GITLAB_PATHS

            all_pipelines = []
            for team_slug, paths in teams_to_query.items():
                for path in paths:
                    try:
                        raw_pipelines = self._collector.fetch_pipelines(path, since_date)
                        for p in raw_pipelines:
                            all_pipelines.append(self._map_pipeline(p, team_slug))
                    except Exception as e:
                        logger.warning(f"Error fetching pipelines from {path}: {e}")

            return all_pipelines

        except Exception as e:
            logger.error(f"Error fetching pipelines: {e}")
            return []

    def get_dora_metrics(
        self,
        team: Optional[str] = None,
        days: int = 30
    ) -> DORAMetrics:
        """Calculate DORA metrics via DORAService."""
        if not self._dora_service:
            return DORAMetrics(team=team or "all", period_days=days, deployment_frequency=0.0)

        try:
            raw = self._dora_service.get_metrics(team=team, days=days)
            return self._map_dora(raw, team, days)
        except Exception as e:
            logger.error(f"Error computing DORA metrics: {e}")
            return DORAMetrics(team=team or "all", period_days=days, deployment_frequency=0.0)

    def search_code(
        self,
        query: str,
        team: Optional[str] = None
    ) -> List[SearchResult]:
        """Search across repositories via SearchService."""
        if not self._search_service:
            return []

        try:
            raw = self._search_service.search(query=query, team=team)
            return [self._map_search_result(r) for r in raw.get("repos", [])]
        except Exception as e:
            logger.error(f"Error searching code: {e}")
            return []

    # ---- Mapping helpers ----

    @staticmethod
    def _map_repo(raw: dict) -> Repository:
        """Map raw repo dict to Repository dataclass."""
        return Repository(
            id=raw.get("repo_id", ""),
            name=raw.get("name", ""),
            team=raw.get("team", ""),
            url="",  # Not stored in get_team_repos output
            primary_language=raw.get("primary_language"),
            has_tests=raw.get("has_tests", False),
            has_ci=raw.get("has_ci", False),
            doc_score=raw.get("doc_score", 0),
            is_orphaned=raw.get("is_orphaned", False),
            days_since_activity=raw.get("days_since_commit"),
        )

    @staticmethod
    def _map_mr(raw: dict, team: str) -> MergeRequest:
        """Map raw MR dict to MergeRequest dataclass."""
        created = None
        merged = None
        if raw.get("created_at"):
            try:
                created = datetime.fromisoformat(
                    raw["created_at"].replace("Z", "+00:00")
                )
            except (ValueError, AttributeError):
                pass
        if raw.get("merged_at"):
            try:
                merged = datetime.fromisoformat(
                    raw["merged_at"].replace("Z", "+00:00")
                )
            except (ValueError, AttributeError):
                pass

        cycle_time = None
        if created and merged:
            cycle_time = (merged - created).total_seconds() / 3600

        return MergeRequest(
            id=str(raw.get("iid", "")),
            title=raw.get("title", ""),
            author=raw.get("author_username", "unknown"),
            project=raw.get("project", ""),
            team=team,
            state=raw.get("state", "merged"),
            url=raw.get("web_url", ""),
            created_at=created,
            merged_at=merged,
            source_branch=raw.get("source_branch"),
            lines_added=raw.get("lines_added"),
            lines_removed=raw.get("lines_removed"),
            files_changed=raw.get("files_changed"),
            cycle_time_hours=cycle_time,
        )

    @staticmethod
    def _map_pipeline(raw: dict, team: str) -> Pipeline:
        """Map raw pipeline dict to Pipeline dataclass."""
        created = None
        finished = None
        if raw.get("created_at"):
            try:
                created = datetime.fromisoformat(
                    raw["created_at"].replace("Z", "+00:00")
                )
            except (ValueError, AttributeError):
                pass
        if raw.get("finished_at"):
            try:
                finished = datetime.fromisoformat(
                    raw["finished_at"].replace("Z", "+00:00")
                )
            except (ValueError, AttributeError):
                pass

        return Pipeline(
            id=f"{raw.get('project', '')}:{raw.get('created_at', '')}",
            project=raw.get("project", ""),
            team=team,
            status=raw.get("status", "unknown").lower(),
            ref=raw.get("ref"),
            duration_seconds=raw.get("duration"),
            created_at=created,
            finished_at=finished,
        )

    @staticmethod
    def _map_dora(raw: dict, team: Optional[str], days: int) -> DORAMetrics:
        """Map raw DORA dict to DORAMetrics dataclass."""
        return DORAMetrics(
            team=team or "all",
            period_days=days,
            deployment_frequency=raw.get("deploymentFrequency", {}).get("current", 0.0),
            lead_time_hours=raw.get("leadTime", {}).get("current"),
            change_failure_rate=raw.get("changeFailureRate", {}).get("current"),
            time_to_restore_hours=raw.get("timeToRestore", {}).get("current"),
            dora_level=raw.get("doraLevel", "unknown"),
            deployment_frequency_trend=raw.get("deploymentFrequency", {}).get("trend"),
            lead_time_trend=raw.get("leadTime", {}).get("trend"),
            change_failure_rate_trend=raw.get("changeFailureRate", {}).get("trend"),
            time_to_restore_trend=raw.get("timeToRestore", {}).get("trend"),
        )

    @staticmethod
    def _map_search_result(raw: dict) -> SearchResult:
        """Map raw search result dict to SearchResult dataclass."""
        return SearchResult(
            repo_id=raw.get("repo_id", ""),
            repo_name=raw.get("name", ""),
            team=raw.get("team", ""),
            primary_language=raw.get("primary_language"),
            frameworks=raw.get("frameworks", []),
            has_tests=raw.get("has_tests", False),
            has_ci=raw.get("has_ci", False),
            is_orphaned=raw.get("is_orphaned", False),
            last_activity=raw.get("last_activity"),
            days_since_activity=raw.get("days_since_commit"),
        )
