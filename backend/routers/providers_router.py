"""Provider capabilities and feature flags for frontend discovery."""

import logging
from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/providers", tags=["Providers"])


class ProviderInfo(BaseModel):
    name: str
    configured: bool
    health: str = "unknown"  # "healthy", "unhealthy", "unknown"


class Capabilities(BaseModel):
    git_providers: list[ProviderInfo]
    issue_trackers: list[ProviderInfo]
    code_platforms: list[ProviderInfo]
    features: dict[str, bool]
    vocabulary: dict[str, str]  # e.g., {"pull_request": "Merge Request"} for GitLab


@router.get("/capabilities", response_model=Capabilities)
async def get_capabilities():
    """
    Return configured providers and feature flags.

    Frontend uses this to:
    - Show/hide nav items based on configured providers
    - Use correct terminology (MR vs PR)
    - Enable/disable features (DORA, issues, etc.)
    """
    git_providers = _detect_git_providers()
    issue_trackers = _detect_issue_trackers()
    code_platforms = _detect_code_platforms()

    # Determine vocabulary based on primary git provider
    primary_git = next((p.name for p in git_providers if p.configured), "github")
    vocabulary = _get_vocabulary(primary_git)

    # Feature flags
    features = {
        "has_git": any(p.configured for p in git_providers),
        "has_issues": any(p.configured for p in issue_trackers),
        "has_dora": any(p.name == "gitlab" and p.configured for p in code_platforms),
        "has_services": _has_port_configured(),
        "has_security": _has_snyk_configured(),
        "has_notifications": _has_telegram_configured(),
    }

    return Capabilities(
        git_providers=git_providers,
        issue_trackers=issue_trackers,
        code_platforms=code_platforms,
        features=features,
        vocabulary=vocabulary,
    )


def _detect_git_providers() -> list[ProviderInfo]:
    """Detect which git providers are configured."""
    import os

    providers = []

    # Check GitLab
    gitlab_configured = bool(os.getenv("GITLAB_TOKEN"))
    providers.append(ProviderInfo(name="gitlab", configured=gitlab_configured))

    # Check GitHub
    github_configured = bool(os.getenv("GITHUB_TOKEN"))
    providers.append(ProviderInfo(name="github", configured=github_configured))

    return providers


def _detect_issue_trackers() -> list[ProviderInfo]:
    """Detect which issue trackers are configured."""
    import os

    providers = []

    # Try domain config first
    configured_provider = None
    try:
        from backend.core.config_loader import get_domain_config
        from backend.services.domain_registry import get_active_slug

        cfg = get_domain_config(get_active_slug())
        it = cfg.integrations.get("issue_tracker")
        if it:
            configured_provider = it.provider
    except Exception:
        pass

    # Jira
    jira_configured = configured_provider == "jira" or bool(os.getenv("JIRA_API_TOKEN"))
    providers.append(ProviderInfo(name="jira", configured=jira_configured))

    # GitHub Issues
    github_configured = configured_provider in ("github", "github-issues")
    providers.append(ProviderInfo(name="github", configured=github_configured))

    return providers


def _detect_code_platforms() -> list[ProviderInfo]:
    """Detect which code platforms are configured."""
    import os

    providers = []

    configured_provider = None
    try:
        from backend.core.config_loader import get_domain_config
        from backend.services.domain_registry import get_active_slug

        cfg = get_domain_config(get_active_slug())
        cp = cfg.integrations.get("code_platform")
        if cp:
            configured_provider = cp.provider
    except Exception:
        pass

    gitlab_configured = configured_provider == "gitlab" or bool(os.getenv("GITLAB_TOKEN"))
    providers.append(ProviderInfo(name="gitlab", configured=gitlab_configured))

    github_configured = configured_provider == "github"
    providers.append(ProviderInfo(name="github", configured=github_configured))

    return providers


def _get_vocabulary(primary_git: str) -> dict[str, str]:
    """Return UI vocabulary based on primary git provider."""
    if primary_git == "gitlab":
        return {
            "pull_request": "Merge Request",
            "pull_request_short": "MR",
            "pull_requests": "Merge Requests",
        }
    return {
        "pull_request": "Pull Request",
        "pull_request_short": "PR",
        "pull_requests": "Pull Requests",
    }


def _has_port_configured() -> bool:
    import os

    return bool(os.getenv("PORT_CLIENT_ID") and os.getenv("PORT_CLIENT_SECRET"))


def _has_snyk_configured() -> bool:
    import os

    return bool(os.getenv("SNYK_TOKEN"))


def _has_telegram_configured() -> bool:
    import os

    return bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"))
