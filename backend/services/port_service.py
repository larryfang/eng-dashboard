"""
Port.io Service

Fetches service catalog data from Port.io using their REST API.
Handles JWT authentication with automatic token caching and refresh.

Uses active-domain Port credentials when configured, falling back to env vars.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

from backend.services.domain_credentials import get_port_settings

logger = logging.getLogger(__name__)

# Module-level token cache
_token: Optional[str] = None
_token_expiry: Optional[datetime] = None
_token_key: Optional[tuple[str, str, str]] = None


def get_port_token() -> Optional[str]:
    """
    Get or refresh the Port.io JWT access token.

    Tokens are cached for 55 minutes (Port tokens expire after 60 minutes).
    Returns None if PORT_CLIENT_ID or PORT_CLIENT_SECRET are not set.
    """
    global _token, _token_expiry, _token_key

    settings = get_port_settings()
    client_id = settings["client_id"]
    client_secret = settings["client_secret"]
    base_url = (settings["base_url"] or "https://api.getport.io").rstrip("/")
    auth_url = f"{base_url}/v1/auth/access_token"
    cache_key = (base_url, client_id, client_secret)

    if not client_id or not client_secret:
        return None

    now = datetime.now(timezone.utc)

    # Return cached token if still valid (with 5-minute buffer)
    if _token and _token_expiry and _token_key == cache_key and now < _token_expiry:
        return _token

    try:
        resp = requests.post(
            auth_url,
            json={"clientId": client_id, "clientSecret": client_secret},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        _token = data["accessToken"]
        _token_key = cache_key
        # Cache for 55 minutes (tokens expire after 60)
        _token_expiry = now + timedelta(minutes=55)
        logger.info("Port.io token refreshed successfully")
        return _token
    except requests.HTTPError as exc:
        logger.error(f"Port.io auth failed (HTTP {exc.response.status_code}): {exc.response.text[:200]}")
        _token = None
        _token_expiry = None
        _token_key = None
        return None
    except Exception as exc:
        logger.error(f"Port.io auth error: {exc}")
        _token = None
        _token_expiry = None
        _token_key = None
        return None


def build_domain_lookup() -> tuple[dict, dict]:
    """
    Build system → domain and system → team mappings by traversing:
      service.system → system.team → team.domain

    Returns (system_to_domain, system_to_team)
      system_to_domain: {system_id: domain_id}
      system_to_team:   {system_id: port_team_id}
    """
    token = get_port_token()
    if token is None:
        return {}, {}
    api_base = f"{(get_port_settings()['base_url'] or 'https://api.getport.io').rstrip('/')}/v1"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        # team → domain
        team_resp = requests.get(f"{api_base}/blueprints/team/entities",
                                 headers=headers, timeout=30)
        team_resp.raise_for_status()
        team_to_domain = {
            t["identifier"]: t.get("relations", {}).get("domain")
            for t in team_resp.json().get("entities", [])
        }

        # system → team and system → domain
        sys_resp = requests.get(f"{api_base}/blueprints/system/entities",
                                headers=headers, timeout=30)
        sys_resp.raise_for_status()
        system_to_domain: dict = {}
        system_to_team: dict = {}
        for s in sys_resp.json().get("entities", []):
            sys_id = s["identifier"]
            team = s.get("relations", {}).get("team")
            if team:
                system_to_team[sys_id] = team
                if team in team_to_domain and team_to_domain[team]:
                    system_to_domain[sys_id] = team_to_domain[team]

        logger.info(f"Domain lookup built: {len(system_to_domain)} systems mapped, "
                    f"{len(system_to_team)} teams resolved")
        return system_to_domain, system_to_team
    except Exception as exc:
        logger.warning(f"Failed to build domain lookup: {exc}")
        return {}, {}


def get_services(team_id: Optional[str] = None) -> dict:
    """
    Fetch services from Port's blueprint entities API.

    Queries the 'service' blueprint for all entities. When team_id is provided,
    filters to entities whose 'team' relation matches.

    Returns a dict with a 'services' list and a 'count', or an error structure
    if Port is not configured or the request fails.
    """
    token = get_port_token()
    if token is None:
        return {"configured": False, "error": "Port credentials are not configured for the active domain"}
    api_base = f"{(get_port_settings()['base_url'] or 'https://api.getport.io').rstrip('/')}/v1"

    try:
        resp = requests.get(
            f"{api_base}/blueprints/service/entities",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        entities = data.get("entities", [])

        if team_id:
            entities = [
                e for e in entities
                if _entity_team_matches(e, team_id)
            ]

        services = [_format_entity(e) for e in entities]
        return {"services": services, "count": len(services), "configured": True}
    except requests.HTTPError as exc:
        logger.error(f"Port.io services fetch failed (HTTP {exc.response.status_code}): {exc.response.text[:200]}")
        return {
            "configured": True,
            "error": f"HTTP {exc.response.status_code}: {exc.response.text[:200]}",
            "services": [],
        }
    except Exception as exc:
        logger.error(f"Port.io services fetch error: {exc}")
        return {"configured": True, "error": str(exc), "services": []}


def _entity_team_matches(entity: dict, team_id: str) -> bool:
    """Check if a Port entity's 'team' relation matches the given team_id."""
    relations = entity.get("relations", {})
    team_relation = relations.get("team")
    if isinstance(team_relation, str):
        return team_relation == team_id
    if isinstance(team_relation, list):
        return team_id in team_relation
    return False


def _format_entity(entity: dict) -> dict:
    """Normalise a raw Port entity into a clean service dict."""
    properties = entity.get("properties", {})
    relations = entity.get("relations", {})
    return {
        "id": entity.get("identifier"),
        "title": entity.get("title", ""),
        "blueprint": entity.get("blueprint", "service"),
        "team": relations.get("team"),
        "url": properties.get("url"),
        "language": properties.get("language"),
        "type": properties.get("type"),
        "lifecycle": properties.get("lifecycle"),
        "on_call": properties.get("on_call"),
        "slack_channel": properties.get("slack_channel"),
        "properties": properties,
        "relations": relations,
        "created_at": entity.get("createdAt"),
        "updated_at": entity.get("updatedAt"),
    }


def get_services_from_db() -> dict:
    """
    Read cached Port services from domain DB.

    Returns {"services": [...], "count": N, "synced_at": ISO|None, "from_cache": True}
    or {"services": [], "count": 0, "synced_at": None, "from_cache": True} if empty.
    """
    from backend.database_domain import create_ecosystem_session
    from backend.models_domain import PortService

    session = create_ecosystem_session()
    try:
        rows = session.query(PortService).order_by(PortService.department, PortService.system, PortService.title).all()
        synced_at = max((r.synced_at for r in rows), default=None)
        services = [_row_to_dict(r) for r in rows]
        return {
            "services": services,
            "count": len(services),
            "synced_at": synced_at.isoformat() if synced_at else None,
            "from_cache": True,
            "configured": True,
        }
    finally:
        session.close()


def sync_services_to_db() -> dict:
    """
    Fetch all services from Port API and upsert into domain DB.

    Returns {"synced": N, "synced_at": ISO, "error": None|str}.
    """
    result = get_services()
    if not result.get("configured", True):
        return {"synced": 0, "error": "Port not configured", "synced_at": None}
    if result.get("error"):
        return {"synced": 0, "error": result["error"], "synced_at": None}

    now = datetime.now(timezone.utc)
    services = result.get("services", [])

    # Resolve service → domain and team via system → team → domain chain
    system_to_domain, system_to_team = build_domain_lookup()

    from backend.database_domain import create_ecosystem_session
    from backend.models_domain import PortService

    session = create_ecosystem_session()
    try:
        for svc in services:
            props = svc.get("properties") or {}
            relations = svc.get("relations") or {}
            sys_id = relations.get("system")

            # Try direct team relation first; fall back to system→team chain
            team_id = relations.get("team")
            if isinstance(team_id, list):
                team_id = team_id[0] if team_id else None
            if not team_id and sys_id:
                team_id = system_to_team.get(sys_id)

            row = session.get(PortService, svc["id"])
            if row is None:
                row = PortService(id=svc["id"])
                session.add(row)
            row.title               = svc.get("title", "")
            row.department          = props.get("department") or svc.get("department")
            row.system              = sys_id
            row.domain              = system_to_domain.get(sys_id) if sys_id else None
            row.team                = team_id
            row.language            = svc.get("language")
            row.url                 = svc.get("url")
            row.description         = props.get("description")
            row.service_criticality = props.get("service_criticality")
            row.publicly_exposed    = bool(props.get("publicly_exposed", False))
            row.synced_at           = now
        session.commit()
    finally:
        session.close()

    logger.info(f"Port services synced: {len(services)} services stored")
    return {"synced": len(services), "synced_at": now.isoformat(), "error": None}


def enrich_versions_background() -> dict:
    """
    Background task: scan GitLab repos for language versions for all
    Port services that have a GitLab URL but no language_version yet.

    Uses a thread pool (10 workers) to scan repos in parallel, reducing
    runtime from ~60 min sequential to ~3-5 min.
    Returns {"enriched": N, "skipped": N, "errors": N}.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from backend.database_domain import create_ecosystem_session
    from backend.models_domain import PortService
    from backend.services.version_scanner import scan_service_version

    session = create_ecosystem_session()
    try:
        rows = session.query(PortService).filter(
            PortService.url.isnot(None),
            PortService.language_version.is_(None),
        ).all()
        # Only GitLab URLs — Bitbucket/other not supported
        gitlab_rows = [r for r in rows if r.url and "gitlab" in r.url.lower()]
        logger.info(f"Version enrichment: scanning {len(gitlab_rows)} GitLab services (parallel)")
    except Exception:
        session.close()
        raise

    def _scan(row):
        try:
            return row.id, scan_service_version(row.url, hint_language=row.language)
        except Exception as exc:
            logger.debug("Scan error for %s: %s", row.title, exc)
            return row.id, None

    id_to_result: dict = {}
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(_scan, r): r for r in gitlab_rows}
        for future in as_completed(futures):
            svc_id, result = future.result()
            if result:
                id_to_result[svc_id] = result

    # Write results back via a fresh query to avoid stale ORM state
    enriched = skipped = errors = 0
    try:
        for row in gitlab_rows:
            result = id_to_result.get(row.id)
            if result:
                row.language_version = result["language_version"]
                if not row.language:
                    row.language = result["language"]
                enriched += 1
            else:
                skipped += 1
        session.commit()
    except Exception as exc:
        logger.error("Failed to save version results: %s", exc)
        errors += 1
    finally:
        session.close()

    logger.info(f"Version enrichment done: {enriched} enriched, {skipped} skipped, {errors} errors")
    return {"enriched": enriched, "skipped": skipped, "errors": errors}


def _row_to_dict(row) -> dict:
    return {
        "id":                   row.id,
        "title":                row.title,
        "department":           row.department,
        "system":               row.system,
        "domain":               row.domain,
        "team":                 row.team,
        "language":             row.language,
        "language_version":     row.language_version,
        "url":                  row.url,
        "description":          row.description,
        "service_criticality":  row.service_criticality,
        "publicly_exposed":     row.publicly_exposed,
    }


def get_port_status() -> dict:
    """
    Check Port.io connection status.

    Returns whether Port is configured and whether the token can be obtained.
    """
    settings = get_port_settings()
    client_id = settings["client_id"]
    client_secret = settings["client_secret"]

    if not client_id or not client_secret:
        return {
            "configured": False,
            "connected": False,
            "error": "Port credentials are not configured for the active domain",
        }

    token = get_port_token()
    if token:
        return {
            "configured": True,
            "connected": True,
            "token_expires_at": _token_expiry.isoformat() if _token_expiry else None,
        }
    else:
        return {
            "configured": True,
            "connected": False,
            "error": "Failed to obtain access token — check credentials",
        }
