"""
Domain-scoped credentials helpers.

Secrets captured during onboarding are stored per domain in data/domains/*.secrets.json
so they can be used at runtime without exposing them through /api/config.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DOMAIN_DATA_DIR = PROJECT_ROOT / "data" / "domains"


def _slug(domain_slug: str | None) -> str:
    if domain_slug:
        return domain_slug
    from backend.services.domain_registry import get_active_slug
    return get_active_slug()


def get_domain_secret_path(domain_slug: str | None = None) -> Path:
    DOMAIN_DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DOMAIN_DATA_DIR / f"{_slug(domain_slug)}.secrets.json"


def load_domain_secrets(domain_slug: str | None = None) -> dict[str, Any]:
    path = get_domain_secret_path(domain_slug)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_domain_secrets(domain_slug: str, payload: dict[str, Any]) -> Path:
    """Persist non-empty secret payloads for a domain."""
    path = get_domain_secret_path(domain_slug)
    current = load_domain_secrets(domain_slug)
    current.update({k: v for k, v in payload.items() if v})
    path.write_text(json.dumps(current, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _get_domain_config(domain_slug: str | None = None):
    try:
        from backend.core.config_loader import get_domain_config
        return get_domain_config(_slug(domain_slug))
    except Exception:
        return None


def get_gitlab_settings(domain_slug: str | None = None) -> dict[str, str]:
    secrets = load_domain_secrets(domain_slug).get("gitlab", {}) or {}
    cfg = _get_domain_config(domain_slug)
    config = ((cfg.integrations.get("code_platform").config if cfg and cfg.integrations.get("code_platform") else {}) or {})
    return {
        "url": (
            secrets.get("url")
            or config.get("url")
            or os.getenv("GITLAB_URL", "https://gitlab.com")
        ).rstrip("/"),
        "token": secrets.get("token") or config.get("token") or os.getenv("GITLAB_TOKEN", ""),
        "base_group": secrets.get("base_group") or config.get("base_group") or "",
    }


def get_jira_settings(domain_slug: str | None = None) -> dict[str, str]:
    secrets = load_domain_secrets(domain_slug).get("jira", {}) or {}
    cfg = _get_domain_config(domain_slug)
    issue_tracker = ((cfg.integrations.get("issue_tracker").config if cfg and cfg.integrations.get("issue_tracker") else {}) or {})
    return {
        "url": (
            secrets.get("url")
            or issue_tracker.get("url")
            or (cfg.atlassian_site_url if cfg and cfg.atlassian_site_url else "")
            or os.getenv("JIRA_URL", "")
        ).rstrip("/"),
        "email": secrets.get("email") or issue_tracker.get("email") or os.getenv("JIRA_EMAIL", ""),
        "token": (
            secrets.get("token")
            or issue_tracker.get("api_token")
            or issue_tracker.get("token")
            or os.getenv("JIRA_API_TOKEN", "")
        ),
    }


def get_port_settings(domain_slug: str | None = None) -> dict[str, str]:
    secrets = load_domain_secrets(domain_slug).get("port", {}) or {}
    cfg = _get_domain_config(domain_slug)
    dora_config = (cfg.dora.config if cfg and cfg.dora else {}) or {}
    return {
        "client_id": (
            secrets.get("client_id")
            or dora_config.get("client_id")
            or os.getenv("PORT_CLIENT_ID", "")
        ),
        "client_secret": (
            secrets.get("client_secret")
            or dora_config.get("client_secret")
            or os.getenv("PORT_CLIENT_SECRET", "")
        ),
        "base_url": (
            secrets.get("base_url")
            or dora_config.get("base_url")
            or "https://api.getport.io"
        ).rstrip("/"),
    }


def get_snyk_settings(domain_slug: str | None = None) -> dict[str, str]:
    secrets = load_domain_secrets(domain_slug).get("snyk", {}) or {}
    cfg = _get_domain_config(domain_slug)
    security_config = ((cfg.integrations.get("security").config if cfg and cfg.integrations.get("security") else {}) or {})
    return {
        "token": (
            secrets.get("token")
            or security_config.get("token")
            or os.getenv("SNYK_TOKEN", "")
        ),
    }


def get_llm_settings(domain_slug: str | None = None) -> dict[str, str]:
    """Get LLM API keys — domain secrets take priority over env vars."""
    secrets = load_domain_secrets(domain_slug).get("llm", {}) or {}
    return {
        "anthropic_api_key": secrets.get("anthropic_api_key") or os.getenv("ANTHROPIC_API_KEY", ""),
        "openai_api_key": secrets.get("openai_api_key") or os.getenv("OPENAI_API_KEY", ""),
    }


def save_llm_settings(domain_slug: str | None = None, **keys: str) -> None:
    """Save LLM API keys to domain secrets. Pass empty string to remove a key."""
    slug = _slug(domain_slug)
    current = load_domain_secrets(slug)
    llm = current.get("llm", {}) or {}
    for k, v in keys.items():
        if v:
            llm[k] = v
        else:
            llm.pop(k, None)
    current["llm"] = llm
    path = get_domain_secret_path(slug)
    path.write_text(json.dumps(current, indent=2, sort_keys=True), encoding="utf-8")
