"""
GitLab Intelligence Module

Provides unified access to GitLab codebase analytics, DORA metrics,
knowledge risk analysis, and epic-MR correlation.

All data is collected directly from GitLab API and stored in PA's database.
No external dependencies on gitlab-analysis project.

Components:
- gitlab_collector: Direct GitLab API collection (pipelines, MRs)
- repo_scanner: Repository discovery and metadata scanning
- dora_service: DORA metrics calculations
- risk_service: Knowledge risk and bus factor analysis
- epic_mr_correlator: Links Jira epics to GitLab MRs
- package_service: Package/dependency search and analysis
- search_service: Full-text repository search
- version_service: Language/framework version tracking with EOL risk
"""

from .gitlab_collector import GitLabCollector, get_collector, GitLabCollectorError
from .repo_scanner import RepoScanner, get_repo_scanner, RepoScannerError
from .dora_service import DORAService, get_dora_service
from .risk_service import KnowledgeRiskService, get_risk_service
from .epic_mr_correlator import EpicMRCorrelator, get_epic_mr_correlator
from .package_service import PackageService, get_package_service
from .search_service import SearchService, get_search_service
from .version_service import VersionService, get_version_service

__all__ = [
    # GitLab Data Collection
    "GitLabCollector",
    "get_collector",
    "GitLabCollectorError",
    # Repository Scanning
    "RepoScanner",
    "get_repo_scanner",
    "RepoScannerError",
    # DORA Metrics
    "DORAService",
    "get_dora_service",
    # Knowledge Risk
    "KnowledgeRiskService",
    "get_risk_service",
    # Epic-MR Correlation
    "EpicMRCorrelator",
    "get_epic_mr_correlator",
    # Package Search
    "PackageService",
    "get_package_service",
    # Repository Search
    "SearchService",
    "get_search_service",
    # Version Tracking
    "VersionService",
    "get_version_service",
]
