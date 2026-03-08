"""
Config API Router

Provides endpoints for reading/writing organization.yaml configuration
and validating external service connections (Jira, GitLab, Port, Email).

Endpoints:
- GET  /api/config          → load organization.yaml as JSON
- POST /api/config          → write organization.yaml from JSON body
- POST /api/config/validate → test Jira + GitLab connections
"""

import logging
import os
from pathlib import Path

import requests
import yaml
from fastapi import APIRouter, HTTPException, Query

from backend.services.domain_credentials import get_gitlab_settings, get_jira_settings, get_port_settings, save_llm_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/config", tags=["config"])

# Project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _get_config_file(domain_slug: str | None = None) -> Path:
    """Resolve the config file path for a domain slug (or active domain)."""
    from backend.services.domain_registry import get_active_slug
    slug = domain_slug or get_active_slug()
    domains_dir = _PROJECT_ROOT / "config" / "domains"
    domains_dir.mkdir(parents=True, exist_ok=True)
    return domains_dir / f"{slug}.yaml"


def _config_to_dict(config) -> dict:
    """
    Convert an OrganizationConfig dataclass to a plain dict suitable for JSON serialisation.

    We rebuild a dict that mirrors the structure of organization.yaml rather than using
    dataclasses.asdict, which would expose private _team_by_* lookup indexes and would
    not be round-trip safe back to YAML.
    """
    teams = []
    for t in config.teams:
        gitlab_members = [
            {
                "username": m.username,
                "name": m.name,
                "role": m.role,
                "exclude_from_metrics": m.exclude_from_metrics,
                **({"jira_account_id": m.jira_account_id} if m.jira_account_id else {}),
            }
            for m in t.gitlab_members
        ]
        github_members = [
            {
                "username": m.username,
                "name": m.name,
                "role": m.role,
                "exclude_from_metrics": m.exclude_from_metrics,
                **({"jira_account_id": m.jira_account_id} if m.jira_account_id else {}),
            }
            for m in t.github_members
        ]
        team_dict = {
            "key": t.key,
            "name": t.name,
            "headcount": t.headcount,
        }
        if t.slug:
            team_dict["slug"] = t.slug
        if t.scrum_name and t.scrum_name != t.name:
            team_dict["scrum_name"] = t.scrum_name
        if t.aliases:
            team_dict["aliases"] = t.aliases
        if t.lead:
            team_dict["lead"] = t.lead
        if t.lead_email:
            team_dict["lead_email"] = t.lead_email
        if t.effective_engineers is not None and t.effective_engineers != t.headcount:
            team_dict["effective_engineers"] = t.effective_engineers
        if t.products:
            team_dict["products"] = t.products
        if t.jira_project:
            team_dict["jira_project"] = t.jira_project
        if t.gitlab_path:
            team_dict["gitlab_path"] = t.gitlab_path
        if t.additional_gitlab_paths:
            team_dict["additional_gitlab_paths"] = t.additional_gitlab_paths
        if t.github_repos:
            team_dict["github_repos"] = t.github_repos
        if t.snyk_org:
            team_dict["snyk_org"] = t.snyk_org
        if t.port_team_id:
            team_dict["port_team_id"] = t.port_team_id
        if gitlab_members:
            team_dict["gitlab_members"] = gitlab_members
        if github_members:
            team_dict["github_members"] = github_members
        teams.append(team_dict)

    stakeholders = [
        {
            "name": s.name,
            "role": s.role,
            **({"relationship": s.relationship} if s.relationship else {}),
            **({"email": s.email} if s.email else {}),
            **({"title": s.title} if s.title else {}),
            **({"importance": s.importance} if s.importance else {}),
        }
        for s in config.stakeholders
    ]

    integrations = {
        k: {"provider": v.provider, "config": v.config}
        for k, v in config.integrations.items()
    }

    result = {
        "organization": {
            "name": config.name,
            "slug": config.slug,
            "description": config.description,
        },
        "user": {
            "name": config.user_name,
            "email": config.user_email,
            "role": config.user_role,
            "timezone": config.user_timezone,
        },
        "teams": teams,
        "stakeholders": stakeholders,
        "integrations": integrations,
        "metrics": {
            "cache_ttl_hours": config.metrics.cache_ttl_hours,
            "stale_epic_days": config.metrics.stale_epic_days,
            "dora_targets": config.metrics.dora_targets,
        },
    }

    if config.atlassian_cloud_id:
        result["organization"]["atlassian_cloud_id"] = config.atlassian_cloud_id
    if config.atlassian_site_url:
        result["organization"]["atlassian_site_url"] = config.atlassian_site_url
    if config.jira_roadmap_url:
        result["organization"]["jira_roadmap_url"] = config.jira_roadmap_url
    if config.dora:
        result["dora"] = {"provider": config.dora.provider, "config": config.dora.config}
    if config.knowledge_base:
        result["knowledge_base"] = config.knowledge_base

    return result


# ==================== Endpoints ====================

@router.get("")
async def get_config():
    """
    Return the current active domain's config as JSON.

    Returns 404 with setup instructions if no domain config exists yet.
    """
    config_file = _get_config_file()
    if not config_file.exists():
        raise HTTPException(
            status_code=404,
            detail={"configured": False, "message": "Run setup wizard"},
        )

    try:
        from backend.core.config_loader import get_domain_config
        from backend.services.domain_registry import get_active_slug
        config = get_domain_config(get_active_slug())
        return _config_to_dict(config)
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"configured": False, "message": "Run setup wizard"},
        )
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("")
async def save_config(
    body: dict,
    validate_first: bool = Query(default=False, description="Validate service connections before saving"),
):
    """
    Write the supplied JSON body to organization.yaml and reload the config singleton.

    Optionally validate Jira/GitLab connections before persisting (validate_first=true).
    """
    if validate_first:
        # Run a lightweight validation pass; reject if any configured service fails
        validation = await validate_connections()
        failures = [svc for svc, result in validation.items() if result and not result.get("ok")]
        if failures:
            raise HTTPException(
                status_code=422,
                detail={"message": "Service validation failed", "failures": failures, "results": validation},
            )

    try:
        config_file = _get_config_file()

        yaml_text = yaml.dump(body, allow_unicode=True, default_flow_style=False, sort_keys=False)
        config_file.write_text(yaml_text, encoding="utf-8")
        logger.info(f"Config written to {config_file}")

        # Reload the domain config so subsequent requests see the new values
        from backend.core.config_loader import reload_domain_config
        from backend.services.domain_registry import get_active_slug
        reload_domain_config(get_active_slug())

        return {"ok": True, "message": "Configuration saved", "path": str(config_file)}
    except Exception as e:
        logger.error(f"Failed to save config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/domain/seed")
async def reseed_reference_data():
    """Re-seed ref_teams and ref_members for the active domain."""
    from backend.services.domain_seeder import seed_reference_data
    from backend.services.domain_registry import get_active_slug
    from backend.database_domain import get_domain_engine
    from sqlalchemy.orm import sessionmaker as _sm
    slug = get_active_slug()
    db = _sm(bind=get_domain_engine(slug))()
    try:
        result = seed_reference_data(db, domain_slug=slug)
    finally:
        db.close()
    return {"status": "seeded", "domain": slug, **result}


@router.post("/validate")
async def validate_connections():
    """
    Test Jira, GitLab, Port, and email delivery connections.

    Reads credentials from environment variables:
      - JIRA_URL, JIRA_EMAIL, JIRA_API_TOKEN
      - GITLAB_TOKEN
      - PORT_CLIENT_ID, PORT_CLIENT_SECRET (optional)
      - EMAIL_PROVIDER or Mailgun/Gmail env vars (optional)

    Returns per-service status with authenticated username or error message.
    """
    results: dict = {}

    # ── Jira ──────────────────────────────────────────────────────────────────
    jira_settings = get_jira_settings()
    jira_url = jira_settings["url"]
    jira_email = jira_settings["email"]
    jira_token = jira_settings["token"]

    if jira_url and jira_email and jira_token:
        try:
            resp = requests.get(
                f"{jira_url}/rest/api/3/myself",
                auth=(jira_email, jira_token),
                timeout=10,
            )
            if resp.ok:
                data = resp.json()
                results["jira"] = {
                    "ok": True,
                    "user": data.get("displayName") or data.get("emailAddress", ""),
                    "error": None,
                }
            else:
                results["jira"] = {
                    "ok": False,
                    "user": None,
                    "error": f"HTTP {resp.status_code}: {resp.text[:200]}",
                }
        except Exception as exc:
            results["jira"] = {"ok": False, "user": None, "error": str(exc)}
    else:
        results["jira"] = {
            "ok": False,
            "user": None,
            "error": "Jira credentials not configured for the active domain",
        }

    # ── GitLab ────────────────────────────────────────────────────────────────
    gitlab_settings = get_gitlab_settings()
    gitlab_token = gitlab_settings["token"]

    if gitlab_token:
        try:
            gitlab_url = gitlab_settings["url"]
            resp = requests.get(
                f"{gitlab_url.rstrip('/')}/api/v4/user",
                headers={"Private-Token": gitlab_token},
                timeout=10,
            )
            if resp.ok:
                data = resp.json()
                results["gitlab"] = {
                    "ok": True,
                    "user": data.get("username") or data.get("name", ""),
                    "error": None,
                }
            else:
                results["gitlab"] = {
                    "ok": False,
                    "user": None,
                    "error": f"HTTP {resp.status_code}: {resp.text[:200]}",
                }
        except Exception as exc:
            results["gitlab"] = {"ok": False, "user": None, "error": str(exc)}
    else:
        results["gitlab"] = {
            "ok": False,
            "user": None,
            "error": "GitLab credentials not configured for the active domain",
        }

    # ── Port (optional) ───────────────────────────────────────────────────────
    port_settings = get_port_settings()
    port_client_id = port_settings["client_id"]
    port_client_secret = port_settings["client_secret"]

    if port_client_id and port_client_secret:
        try:
            resp = requests.post(
                "https://api.getport.io/v1/auth/access_token",
                json={"clientId": port_client_id, "clientSecret": port_client_secret},
                timeout=10,
            )
            if resp.ok:
                token_data = resp.json()
                results["port"] = {
                    "ok": True,
                    "user": token_data.get("context", {}).get("clientId", port_client_id),
                    "error": None,
                }
            else:
                results["port"] = {
                    "ok": False,
                    "user": None,
                    "error": f"HTTP {resp.status_code}: {resp.text[:200]}",
                }
        except Exception as exc:
            results["port"] = {"ok": False, "user": None, "error": str(exc)}
    else:
        # Port is optional - return null when not configured
        results["port"] = None

    # ── Email delivery (optional) ────────────────────────────────────────────
    from backend.services.email_service import get_email_service

    email = get_email_service()
    validation = email.validate()
    if email.is_configured:
        results["email"] = {
            "ok": validation.success,
            "user": email.default_from or email.provider_name,
            "error": validation.error,
            "provider": email.provider_name,
        }
    else:
        results["email"] = {
            "ok": False,
            "user": None,
            "error": validation.error,
            "provider": email.provider_name,
        }

    return results


# ==================== LLM / AI Provider Endpoints ====================

@router.get("/llm")
async def get_llm_config():
    """Return current LLM provider status and model info (no secrets exposed)."""
    from backend.services.llm_helpers import get_llm_status
    return get_llm_status()


@router.post("/llm")
async def save_llm_keys(body: dict):
    """Save and validate LLM API keys.

    Body: { "anthropic_api_key": "sk-ant-...", "openai_api_key": "sk-..." }
    Either or both keys can be provided. Empty string removes a key.
    """
    anthropic_key = body.get("anthropic_api_key")
    openai_key = body.get("openai_api_key")

    if anthropic_key is None and openai_key is None:
        raise HTTPException(status_code=422, detail="Provide at least one API key")

    results: dict = {}

    # Validate Anthropic key if provided (non-empty)
    if anthropic_key:
        try:
            from anthropic import Anthropic
            client = Anthropic(api_key=anthropic_key)
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=10,
                messages=[{"role": "user", "content": "Hi"}],
            )
            results["anthropic"] = {"ok": True, "model": resp.model, "error": None}
        except Exception as exc:
            results["anthropic"] = {"ok": False, "model": None, "error": str(exc)[:200]}

    # Validate OpenAI key if provided (non-empty)
    if openai_key:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=openai_key)
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                max_tokens=10,
                messages=[{"role": "user", "content": "Hi"}],
            )
            results["openai"] = {"ok": True, "model": resp.model, "error": None}
        except Exception as exc:
            results["openai"] = {"ok": False, "model": None, "error": str(exc)[:200]}

    # Only save keys that validated successfully (or empty to remove)
    keys_to_save: dict[str, str] = {}
    if anthropic_key is not None:
        if anthropic_key == "" or results.get("anthropic", {}).get("ok"):
            keys_to_save["anthropic_api_key"] = anthropic_key
        elif not results.get("anthropic", {}).get("ok"):
            # Key was provided but failed validation — don't save, report error
            pass
    if openai_key is not None:
        if openai_key == "" or results.get("openai", {}).get("ok"):
            keys_to_save["openai_api_key"] = openai_key
        elif not results.get("openai", {}).get("ok"):
            pass

    if keys_to_save:
        save_llm_settings(**keys_to_save)
        # Reset cached provider so it picks up the new keys
        from backend.services.llm_helpers import reset_llm_plugin
        reset_llm_plugin()

    from backend.services.llm_helpers import get_llm_status
    return {**results, "status": get_llm_status()}


@router.delete("/llm")
async def remove_llm_keys(provider: str = Query(default="all", description="Provider to remove: anthropic, openai, or all")):
    """Remove stored LLM API keys."""
    keys: dict[str, str] = {}
    if provider in ("anthropic", "all"):
        keys["anthropic_api_key"] = ""
    if provider in ("openai", "all"):
        keys["openai_api_key"] = ""
    if not keys:
        raise HTTPException(status_code=422, detail="Invalid provider. Use: anthropic, openai, or all")

    save_llm_settings(**keys)
    from backend.services.llm_helpers import reset_llm_plugin
    reset_llm_plugin()
    from backend.services.llm_helpers import get_llm_status
    return {"removed": provider, "status": get_llm_status()}
