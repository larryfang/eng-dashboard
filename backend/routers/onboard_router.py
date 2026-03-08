"""
Onboarding wizard backend — auto-discovery endpoints.

All endpoints accept credentials in the request body (not from env vars),
so they work before a domain is configured.

POST /api/onboard/validate                  → test GitLab + Jira creds
GET  /api/onboard/discover/gitlab-groups    → list subgroups under a GitLab group path
GET  /api/onboard/discover/jira-projects    → list Jira projects for a site
GET  /api/onboard/discover/gitlab-members   → list members of a GitLab group
GET  /api/onboard/discover/github-orgs      → list GitHub orgs for a token
GET  /api/onboard/discover/github-teams     → list teams in a GitHub org
GET  /api/onboard/discover/github-members   → list members of a GitHub team
POST /api/onboard/create                    → save new domain config + init DB + seed
"""
import logging
import urllib.parse
from pathlib import Path
from typing import Optional

import requests
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/onboard", tags=["onboard"])

DEFAULT_GITLAB_URL = "https://gitlab.com"
GITHUB_API = "https://api.github.com"
CONFIG_DOMAINS_DIR = Path(__file__).resolve().parent.parent.parent / "config" / "domains"


def _gitlab_api_base(gitlab_url: str | None = None) -> str:
    base = (gitlab_url or DEFAULT_GITLAB_URL).rstrip("/")
    return f"{base}/api/v4"


# ── Validate ───────────────────────────────────────────────────────────────────

class ValidateRequest(BaseModel):
    # Code platform
    gitlab_token: Optional[str] = None
    gitlab_url: Optional[str] = None
    github_token: Optional[str] = None
    github_org: Optional[str] = None
    # Issue tracker
    jira_url: Optional[str] = None
    jira_email: Optional[str] = None
    jira_token: Optional[str] = None
    linear_api_key: Optional[str] = None
    monday_token: Optional[str] = None
    asana_token: Optional[str] = None
    # AI
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    # Security
    snyk_token: Optional[str] = None


def _validate_result(ok: bool, user: str | None = None, error: str | None = None) -> dict:
    """Build a consistent validation result dict."""
    return {"ok": ok, "user": user, "error": error}


@router.post("/validate")
async def validate_credentials(body: ValidateRequest):
    results: dict = {}

    # ── GitLab ────────────────────────────────────────────────────────────
    if body.gitlab_token:
        gitlab_api = _gitlab_api_base(body.gitlab_url)
        try:
            r = requests.get(
                f"{gitlab_api}/user",
                headers={"PRIVATE-TOKEN": body.gitlab_token},
                timeout=10,
            )
            if r.ok:
                results["gitlab"] = _validate_result(True, user=r.json().get("username"))
            else:
                results["gitlab"] = _validate_result(False, error=f"HTTP {r.status_code}")
        except Exception as e:
            results["gitlab"] = _validate_result(False, error=str(e))
    else:
        results["gitlab"] = None

    # ── GitHub ────────────────────────────────────────────────────────────
    if body.github_token:
        try:
            r = requests.get(
                "https://api.github.com/user",
                headers={
                    "Authorization": f"Bearer {body.github_token}",
                    "Accept": "application/vnd.github+json",
                },
                timeout=10,
            )
            if r.ok:
                results["github"] = _validate_result(True, user=r.json().get("login"))
            else:
                results["github"] = _validate_result(False, error=f"HTTP {r.status_code}")
        except Exception as e:
            results["github"] = _validate_result(False, error=str(e))
    else:
        results["github"] = None

    # ── Jira ──────────────────────────────────────────────────────────────
    if body.jira_url and body.jira_email and body.jira_token:
        try:
            r = requests.get(
                f"{body.jira_url.rstrip('/')}/rest/api/3/myself",
                auth=(body.jira_email, body.jira_token),
                timeout=10,
            )
            if r.ok:
                results["jira"] = _validate_result(True, user=r.json().get("displayName"))
            else:
                results["jira"] = _validate_result(False, error=f"HTTP {r.status_code}")
        except Exception as e:
            results["jira"] = _validate_result(False, error=str(e))
    else:
        results["jira"] = None

    # ── Linear ────────────────────────────────────────────────────────────
    if body.linear_api_key:
        try:
            r = requests.post(
                "https://api.linear.app/graphql",
                headers={"Authorization": body.linear_api_key},
                json={"query": "{ viewer { id name } }"},
                timeout=10,
            )
            if r.ok:
                data = r.json()
                name = (data.get("data") or {}).get("viewer", {}).get("name")
                results["linear"] = _validate_result(True, user=name)
            else:
                results["linear"] = _validate_result(False, error=f"HTTP {r.status_code}")
        except Exception as e:
            results["linear"] = _validate_result(False, error=str(e))
    else:
        results["linear"] = None

    # ── Monday.com ────────────────────────────────────────────────────────
    if body.monday_token:
        try:
            r = requests.post(
                "https://api.monday.com/v2",
                headers={"Authorization": body.monday_token},
                json={"query": "{ me { id name } }"},
                timeout=10,
            )
            if r.ok:
                data = r.json()
                name = (data.get("data") or {}).get("me", {}).get("name")
                results["monday"] = _validate_result(True, user=name)
            else:
                results["monday"] = _validate_result(False, error=f"HTTP {r.status_code}")
        except Exception as e:
            results["monday"] = _validate_result(False, error=str(e))
    else:
        results["monday"] = None

    # ── Asana ─────────────────────────────────────────────────────────────
    if body.asana_token:
        try:
            r = requests.get(
                "https://app.asana.com/api/1.0/users/me",
                headers={"Authorization": f"Bearer {body.asana_token}"},
                timeout=10,
            )
            if r.ok:
                data = r.json()
                name = (data.get("data") or {}).get("name")
                results["asana"] = _validate_result(True, user=name)
            else:
                results["asana"] = _validate_result(False, error=f"HTTP {r.status_code}")
        except Exception as e:
            results["asana"] = _validate_result(False, error=str(e))
    else:
        results["asana"] = None

    # ── OpenAI ────────────────────────────────────────────────────────────
    if body.openai_api_key:
        try:
            r = requests.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {body.openai_api_key}"},
                timeout=10,
            )
            if r.ok:
                results["openai"] = _validate_result(True)
            else:
                results["openai"] = _validate_result(False, error=f"HTTP {r.status_code}")
        except Exception as e:
            results["openai"] = _validate_result(False, error=str(e))
    else:
        results["openai"] = None

    # ── Anthropic ─────────────────────────────────────────────────────────
    if body.anthropic_api_key:
        try:
            r = requests.get(
                "https://api.anthropic.com/v1/models",
                headers={
                    "x-api-key": body.anthropic_api_key,
                    "anthropic-version": "2023-06-01",
                },
                timeout=10,
            )
            if r.ok:
                results["anthropic"] = _validate_result(True)
            else:
                results["anthropic"] = _validate_result(False, error=f"HTTP {r.status_code}")
        except Exception as e:
            results["anthropic"] = _validate_result(False, error=str(e))
    else:
        results["anthropic"] = None

    # ── Snyk ──────────────────────────────────────────────────────────────
    if body.snyk_token:
        try:
            r = requests.get(
                "https://api.snyk.io/rest/self?version=2024-04-29",
                headers={"Authorization": f"token {body.snyk_token}"},
                timeout=10,
            )
            if r.ok:
                data = r.json()
                name = (data.get("data") or {}).get("attributes", {}).get("name")
                results["snyk"] = _validate_result(True, user=name)
            else:
                results["snyk"] = _validate_result(False, error=f"HTTP {r.status_code}")
        except Exception as e:
            results["snyk"] = _validate_result(False, error=str(e))
    else:
        results["snyk"] = None

    return results


# ── GitLab group discovery ─────────────────────────────────────────────────────

@router.get("/discover/gitlab-groups")
async def discover_gitlab_groups(
    request: Request,
    token: Optional[str] = Query(default=None, description="GitLab personal access token"),
    gitlab_url: Optional[str] = Query(default=None, description="GitLab base URL"),
    group_path: str = Query(..., description="GitLab group path, e.g. my-org/teams"),
):
    """
    List subgroups under a GitLab group path.
    Returns [{id, name, full_path, description}].
    """
    # Prefer header, fall back to query param
    token = request.headers.get("x-gitlab-token") or token
    gitlab_url = request.headers.get("x-gitlab-url") or gitlab_url
    if not token:
        raise HTTPException(status_code=400, detail="GitLab token is required")
    gitlab_api = _gitlab_api_base(gitlab_url)

    # Resolve group path to numeric ID
    encoded = urllib.parse.quote(group_path, safe="")
    try:
        r = requests.get(
            f"{gitlab_api}/groups/{encoded}",
            headers={"PRIVATE-TOKEN": token},
            timeout=15,
        )
        if not r.ok:
            raise HTTPException(
                status_code=r.status_code,
                detail=f"GitLab group not found: {group_path} (HTTP {r.status_code})",
            )
        group_id = r.json()["id"]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Paginate subgroups
    subgroups = []
    page = 1
    while True:
        r = requests.get(
            f"{gitlab_api}/groups/{group_id}/subgroups",
            headers={"PRIVATE-TOKEN": token},
            params={"per_page": 50, "page": page, "order_by": "name"},
            timeout=15,
        )
        if not r.ok:
            raise HTTPException(
                status_code=r.status_code,
                detail=f"GitLab subgroup discovery failed for {group_path} (HTTP {r.status_code})",
            )
        batch = r.json()
        if not batch:
            break
        subgroups.extend([
            {
                "id": g["id"],
                "name": g["name"],
                "full_path": g["full_path"],
                "description": g.get("description", ""),
            }
            for g in batch
        ])
        if len(batch) < 50:
            break
        page += 1

    return {"groups": subgroups}


# ── Jira project discovery ─────────────────────────────────────────────────────

@router.get("/discover/jira-projects")
async def discover_jira_projects(
    request: Request,
    jira_url: str = Query(...),
    jira_email: Optional[str] = Query(default=None),
    jira_token: Optional[str] = Query(default=None),
):
    """List Jira software projects. Returns [{key, name, type}]."""
    # Prefer headers, fall back to query params
    jira_token = request.headers.get("x-jira-token") or jira_token
    jira_email = request.headers.get("x-jira-email") or jira_email
    if not jira_email or not jira_token:
        raise HTTPException(status_code=400, detail="Jira email and token are required")

    try:
        r = requests.get(
            f"{jira_url.rstrip('/')}/rest/api/3/project/search",
            auth=(jira_email, jira_token),
            params={"maxResults": 100, "orderBy": "name", "typeKey": "software"},
            timeout=15,
        )
        if not r.ok:
            raise HTTPException(
                status_code=r.status_code,
                detail=f"Jira project list failed: HTTP {r.status_code}",
            )
        data = r.json()
        projects = [
            {"key": p["key"], "name": p["name"], "type": p.get("projectTypeKey", "software")}
            for p in data.get("values", [])
        ]
        return {"projects": projects}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── GitLab member discovery ────────────────────────────────────────────────────

@router.get("/discover/gitlab-members")
async def discover_gitlab_members(
    request: Request,
    token: Optional[str] = Query(default=None),
    gitlab_url: Optional[str] = Query(default=None, description="GitLab base URL"),
    group_path: str = Query(..., description="GitLab group full_path"),
):
    """List direct members of a GitLab group. Returns [{username, name, role}]."""
    # Prefer header, fall back to query param
    token = request.headers.get("x-gitlab-token") or token
    gitlab_url = request.headers.get("x-gitlab-url") or gitlab_url
    if not token:
        raise HTTPException(status_code=400, detail="GitLab token is required")
    gitlab_api = _gitlab_api_base(gitlab_url)

    encoded = urllib.parse.quote(group_path, safe="")
    members = []
    page = 1
    while True:
        r = requests.get(
            f"{gitlab_api}/groups/{encoded}/members/all",
            headers={"PRIVATE-TOKEN": token},
            params={"per_page": 50, "page": page},
            timeout=15,
        )
        if not r.ok:
            raise HTTPException(
                status_code=r.status_code,
                detail=f"GitLab member discovery failed for {group_path} (HTTP {r.status_code})",
            )
        batch = r.json()
        if not batch:
            break
        members.extend([
            {
                "username": m["username"],
                "name": m["name"],
                "role": _access_to_role(m.get("access_level", 30)),
            }
            for m in batch
        ])
        if len(batch) < 50:
            break
        page += 1

    return {"members": members}


def _access_to_role(level: int) -> str:
    """Map GitLab access level integer to role string."""
    if level >= 50:
        return "owner"
    if level >= 40:
        return "TL"       # Maintainer
    if level >= 30:
        return "engineer"  # Developer
    return "observer"


# ── GitHub org discovery ──────────────────────────────────────────────────────

@router.get("/discover/github-orgs")
async def discover_github_orgs(
    request: Request,
    token: Optional[str] = Query(default=None, description="GitHub personal access token"),
):
    """List GitHub organizations the token owner belongs to."""
    token = request.headers.get("x-github-token") or token
    if not token:
        raise HTTPException(status_code=400, detail="GitHub token is required")

    try:
        r = requests.get(
            f"{GITHUB_API}/user/orgs",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
            params={"per_page": 100},
            timeout=15,
        )
        if not r.ok:
            raise HTTPException(
                status_code=r.status_code,
                detail=f"GitHub org discovery failed: HTTP {r.status_code}",
            )
        orgs = [
            {"login": o["login"], "description": o.get("description", "") or ""}
            for o in r.json()
        ]
        return {"orgs": orgs}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── GitHub team discovery ─────────────────────────────────────────────────────

@router.get("/discover/github-teams")
async def discover_github_teams(
    request: Request,
    token: Optional[str] = Query(default=None, description="GitHub personal access token"),
    org: str = Query(..., description="GitHub organization login"),
):
    """List teams in a GitHub organization."""
    token = request.headers.get("x-github-token") or token
    if not token:
        raise HTTPException(status_code=400, detail="GitHub token is required")

    try:
        r = requests.get(
            f"{GITHUB_API}/orgs/{org}/teams",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
            params={"per_page": 100},
            timeout=15,
        )
        if not r.ok:
            raise HTTPException(
                status_code=r.status_code,
                detail=f"GitHub team discovery failed for {org}: HTTP {r.status_code}",
            )
        teams = [
            {
                "slug": t["slug"],
                "name": t["name"],
                "description": t.get("description", "") or "",
            }
            for t in r.json()
        ]
        return {"teams": teams}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── GitHub team member discovery ──────────────────────────────────────────────

@router.get("/discover/github-members")
async def discover_github_members(
    request: Request,
    token: Optional[str] = Query(default=None, description="GitHub personal access token"),
    org: str = Query(..., description="GitHub organization login"),
    team_slug: str = Query(..., description="GitHub team slug"),
):
    """List members of a GitHub team. Returns [{username, name, role}]."""
    token = request.headers.get("x-github-token") or token
    if not token:
        raise HTTPException(status_code=400, detail="GitHub token is required")

    try:
        r = requests.get(
            f"{GITHUB_API}/orgs/{org}/teams/{team_slug}/members",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
            params={"per_page": 100},
            timeout=15,
        )
        if not r.ok:
            raise HTTPException(
                status_code=r.status_code,
                detail=f"GitHub member discovery failed for {org}/{team_slug}: HTTP {r.status_code}",
            )
        members = [
            {
                "username": m["login"],
                "name": m["login"],  # GitHub members API doesn't return display name
                "role": "engineer",
            }
            for m in r.json()
            if m.get("type") == "User"
        ]
        return {"members": members}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Create domain ──────────────────────────────────────────────────────────────

class DomainCreateRequest(BaseModel):
    organization: dict
    user: dict
    teams: list
    # Code platform (pick one or none)
    gitlab: Optional[dict] = None
    github: Optional[dict] = None
    # Issue tracker (pick one or none)
    jira: Optional[dict] = None
    linear: Optional[dict] = None
    monday: Optional[dict] = None
    asana: Optional[dict] = None
    # AI
    llm: Optional[dict] = None
    # Other
    optional: Optional[dict] = None


@router.post("/create")
async def create_domain(body: DomainCreateRequest):
    """
    Persist a new domain config from wizard payload, initialise its DB, and seed it.
    Switches to the new domain as the active domain.
    """
    import yaml

    import re

    slug = body.organization.get("slug", "").strip()
    if not slug:
        raise HTTPException(status_code=422, detail="organization.slug is required")
    if not re.match(r'^[a-zA-Z0-9_-]+$', slug):
        raise HTTPException(status_code=422, detail="slug must contain only alphanumeric characters, hyphens, and underscores")
    CONFIG_DOMAINS_DIR.mkdir(parents=True, exist_ok=True)
    config_path = CONFIG_DOMAINS_DIR / f"{slug}.yaml"

    if config_path.exists():
        from backend.core.config_loader import get_domain_config
        existing = get_domain_config(slug)
        if existing.teams:
            raise HTTPException(status_code=409, detail=f"Domain '{slug}' already exists")
        # Stub domain (no teams) — allow overwrite to complete setup

    # Build YAML-compatible config dict mirroring organization.yaml structure
    config_dict: dict = {
        "organization": dict(body.organization),
        "user": body.user,
        "teams": body.teams,
    }
    integrations: dict = {}
    if body.jira and body.jira.get("url"):
        config_dict["organization"]["atlassian_site_url"] = body.jira.get("url", "")
        integrations["issue_tracker"] = {
            "provider": "jira",
            "config": {"auth_method": "api_token"},
        }
    if body.linear and body.linear.get("api_key"):
        integrations["issue_tracker"] = {"provider": "linear", "config": {}}
    if body.monday and body.monday.get("token"):
        integrations["issue_tracker"] = {"provider": "monday", "config": {}}
    if body.asana and body.asana.get("token"):
        integrations["issue_tracker"] = {"provider": "asana", "config": {}}
    if body.gitlab:
        gitlab_config: dict = {}
        if body.gitlab.get("base_group"):
            gitlab_config["base_group"] = body.gitlab["base_group"]
        if body.gitlab.get("url"):
            gitlab_config["url"] = body.gitlab["url"]
        integrations["code_platform"] = {
            "provider": "gitlab",
            "config": gitlab_config,
        }
    if body.github and body.github.get("token"):
        github_config: dict = {}
        if body.github.get("org"):
            github_config["org"] = body.github["org"]
        integrations["code_platform"] = {
            "provider": "github",
            "config": github_config,
        }
    if body.optional and body.optional.get("snyk_token"):
        integrations["security"] = {
            "provider": "snyk",
            "config": {},
        }
    if body.llm:
        if body.llm.get("openai_api_key"):
            integrations["ai"] = {"provider": "openai", "config": {}}
        elif body.llm.get("anthropic_api_key"):
            integrations["ai"] = {"provider": "anthropic", "config": {}}
    if integrations:
        config_dict["integrations"] = integrations
    if body.optional and body.optional.get("port_client_id"):
        config_dict["dora"] = {
            "provider": "port",
            "config": {
                "base_url": body.optional.get("port_base_url", "https://api.getport.io"),
            },
        }

    config_path.write_text(
        yaml.dump(config_dict, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    logger.info(f"Domain config written: {config_path}")

    from backend.services.domain_credentials import save_domain_secrets

    secret_payload: dict = {}
    if body.gitlab and body.gitlab.get("token"):
        secret_payload["gitlab"] = {
            "token": body.gitlab.get("token", ""),
            "url": body.gitlab.get("url", "https://gitlab.com"),
            "base_group": body.gitlab.get("base_group", ""),
        }
    if body.jira and body.jira.get("email") and body.jira.get("token"):
        secret_payload["jira"] = {
            "url": body.jira.get("url", ""),
            "email": body.jira.get("email", ""),
            "token": body.jira.get("token", ""),
        }
    if body.optional and body.optional.get("port_client_id"):
        secret_payload["port"] = {
            "client_id": body.optional.get("port_client_id", ""),
            "client_secret": body.optional.get("port_client_secret", ""),
            "base_url": body.optional.get("port_base_url", "https://api.getport.io"),
        }
    if body.optional and body.optional.get("snyk_token"):
        secret_payload["snyk"] = {
            "token": body.optional.get("snyk_token", ""),
        }
    if body.github and body.github.get("token"):
        secret_payload["github"] = {
            "token": body.github.get("token", ""),
            "org": body.github.get("org", ""),
        }
    if body.linear and body.linear.get("api_key"):
        secret_payload["linear"] = {"api_key": body.linear["api_key"]}
    if body.monday and body.monday.get("token"):
        secret_payload["monday"] = {"token": body.monday["token"]}
    if body.asana and body.asana.get("token"):
        secret_payload["asana"] = {"token": body.asana["token"]}
    if body.llm:
        llm_secrets: dict = {}
        if body.llm.get("openai_api_key"):
            llm_secrets["openai_api_key"] = body.llm["openai_api_key"]
        if body.llm.get("anthropic_api_key"):
            llm_secrets["anthropic_api_key"] = body.llm["anthropic_api_key"]
        if llm_secrets:
            secret_payload["llm"] = llm_secrets
    if secret_payload:
        save_domain_secrets(slug, secret_payload)

    # Init DB + seed
    from backend.database_domain import init_domain_db, get_domain_engine
    from backend.services.domain_seeder import seed_reference_data
    from backend.core.config_loader import reload_domain_config
    from sqlalchemy.orm import sessionmaker as _sm
    from backend.services.domain_registry import switch_domain

    init_domain_db(slug)
    cfg = reload_domain_config(slug)  # Force reload from disk (handles stub→full overwrite)
    eng = get_domain_engine(slug)
    db = _sm(bind=eng)()
    try:
        seed_result = seed_reference_data(db, domain_slug=slug)
    finally:
        db.close()

    switch_domain(slug)

    # Kick off initial sync in the background (non-blocking)
    import asyncio
    try:
        from backend.services.scheduler import run_initial_sync
        loop = asyncio.get_event_loop()
        loop.create_task(run_initial_sync())
        logger.info(f"Initial sync triggered for domain '{slug}'")
    except Exception as e:
        logger.warning(f"Could not trigger initial sync: {e}")

    return {"ok": True, "slug": slug, "name": cfg.name, "seeded": seed_result}
