"""
Code platform plugins.

Supports:
- GitLab (GitLabPlugin)
- GitHub (GitHubPlugin) [stub]
"""

from .base import (
    CodePlatformPlugin,
    Repository,
    MergeRequest,
    Pipeline,
    DORAMetrics,
    SearchResult,
)
from .gitlab_plugin import GitLabPlugin
from .github_plugin import GitHubPlugin

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
