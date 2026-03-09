"""
Code platform plugins.

Supports:
- GitLab (GitLabPlugin)
- GitHub (GitHubPlugin) [stub]
"""

from backend.code_platform.base import (
    CodePlatformPlugin,
    Repository,
    MergeRequest,
    Pipeline,
    DORAMetrics,
    SearchResult,
)
from backend.code_platform.gitlab_plugin import GitLabPlugin
from backend.code_platform.github_plugin import GitHubPlugin

__all__ = [
    "CodePlatformPlugin",
    "Repository",
    "MergeRequest",
    "Pipeline",
    "DORAMetrics",
    "SearchResult",
    "GitLabPlugin",
    "GitHubPlugin",
]
