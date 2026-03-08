"""
Centralized path resolution from organization config.

Every hardcoded path in the codebase should go through this module.
Functions fall back to environment variables / sensible defaults
when organization.yaml isn't available (tests, standalone scripts).
"""

import os
from pathlib import Path
from functools import lru_cache

PROJECT_ROOT = Path(__file__).parent.parent.parent


@lru_cache(maxsize=1)
def _safe_config():
    """Load org config once, returning None on failure."""
    try:
        from backend.core.config_loader import get_config
        return get_config()
    except Exception:
        return None


def get_project_root() -> Path:
    """Return the repository root (two levels up from core/)."""
    return PROJECT_ROOT


def get_data_dir() -> Path:
    """Return the data/ directory (for DB files, caches, etc.)."""
    return PROJECT_ROOT / "data"


def get_db_path() -> Path:
    """Return the path to the main SQLite database."""
    url = os.getenv("DATABASE_URL", "")
    if url.startswith("sqlite:///"):
        return Path(url.replace("sqlite:///", ""))
    return PROJECT_ROOT / "data" / "personal_assistant.db"


def get_jira_site_url() -> str:
    """Return the Jira/Atlassian site URL."""
    env = os.getenv("JIRA_URL")
    if env:
        return env.rstrip("/")
    cfg = _safe_config()
    url = cfg.atlassian_site_url if cfg and cfg.atlassian_site_url else ""
    return url.rstrip("/") if url else ""


def get_jira_browse_url(issue_key: str) -> str:
    """Return a full Jira browse URL for an issue key."""
    return f"{get_jira_site_url()}/browse/{issue_key}"
