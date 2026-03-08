# Multi-Domain Isolation + Guided Onboarding Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Support multiple independent Engineering Director domains (each with their own config, DB, and teams), and replace manual YAML authoring with a guided wizard that auto-discovers teams and engineers from GitLab/Jira.

**Architecture:** Use the **active domain** pattern — a single global tracks which domain is "active". All existing API endpoints delegate to the active domain's config and DB transparently. No URL changes required. Domain configs live at `config/domains/{slug}.yaml`; each gets its own `data/domains/{slug}.db`.

**Tech Stack:** FastAPI (Python), SQLAlchemy, React + Vite, TypeScript, Tailwind CSS

---

## Current State Summary

- `config/organization.yaml` → single hardcoded config (global singleton in `core/config_loader.py`)
- `data/domains/ecosystem.db` → single hardcoded DB (global singleton in `database_domain.py`)
- `get_ecosystem_session()` + `get_ecosystem_engine()` used by all routers
- Setup wizard (`frontend/src/pages/Setup/`) has 7 manual steps — no auto-discovery
- `POST /api/config` saves config, `POST /api/config/domain/seed` re-seeds DB

---

## Phase 1: Multi-Domain Backend

### Task 1: Config domains directory layout + migration

**Files:**
- Create: `config/domains/.gitkeep`
- Modify: `backend/core/config_loader.py`
- Modify: `backend/main.py`

**Step 1: Create the domains config directory**

```bash
mkdir -p config/domains
touch config/domains/.gitkeep
```

Add to `.gitignore` (if not already there):
```
config/domains/*.yaml
!config/domains/.gitkeep
```

**Step 2: Update `config_loader.py` to support per-domain loading**

Add below the existing `_config_loader` singleton at the bottom of the file (~line 657):

```python
# --- Multi-domain support ---
_CONFIG_DOMAINS_DIR = _CONFIG_DIR / "domains"

_loaders: dict[str, "ConfigLoader"] = {}


def get_domain_config(domain_slug: str) -> OrganizationConfig:
    """Load config for a specific domain slug from config/domains/{slug}.yaml."""
    global _loaders
    if domain_slug not in _loaders:
        path = _CONFIG_DOMAINS_DIR / f"{domain_slug}.yaml"
        _loaders[domain_slug] = ConfigLoader(path)
    return _loaders[domain_slug].load()


def reload_domain_config(domain_slug: str) -> OrganizationConfig:
    """Force reload a domain's config from disk."""
    global _loaders
    if domain_slug in _loaders:
        return _loaders[domain_slug].reload()
    return get_domain_config(domain_slug)


def list_domain_slugs() -> list[str]:
    """Return slugs of all configured domains (config/domains/*.yaml files)."""
    if not _CONFIG_DOMAINS_DIR.exists():
        return []
    return [f.stem for f in sorted(_CONFIG_DOMAINS_DIR.glob("*.yaml"))]
```

**Step 3: Add auto-migration in `main.py` lifespan**

In the lifespan function, before seeding, add:

```python
# Auto-migrate legacy organization.yaml to config/domains/ if needed
from core.config_loader import list_domain_slugs
from pathlib import Path as _Path

_legacy = _Path(__file__).parent.parent / "config" / "organization.yaml"
_domains_dir = _Path(__file__).parent.parent / "config" / "domains"
_domains_dir.mkdir(parents=True, exist_ok=True)

if _legacy.exists() and not any(_domains_dir.glob("*.yaml")):
    import shutil as _shutil
    # Load the slug from the legacy file to name it correctly
    import yaml as _yaml
    _raw = _yaml.safe_load(_legacy.read_text())
    _slug = _raw.get("organization", {}).get("slug", "ecosystem")
    _dest = _domains_dir / f"{_slug}.yaml"
    _shutil.copy2(_legacy, _dest)
    logger.info(f"Migrated organization.yaml → config/domains/{_slug}.yaml")
```

**Step 4: Verify migration works**

Run the backend and check logs show migration message:
```bash
cd /path/to/eng-dashboard
uv run uvicorn backend.main:app --port 9001 --app-dir backend
```
Expected log: `Migrated organization.yaml → config/domains/sinch-ecosystem.yaml`

**Step 5: Commit**

```bash
git add config/domains/.gitkeep backend/core/config_loader.py backend/main.py .gitignore
git commit -m "feat: add multi-domain config directory + auto-migrate legacy organization.yaml"
```

---

### Task 2: Active domain state management

**Files:**
- Create: `backend/services/domain_registry.py`

**Step 1: Create the domain registry service**

```python
# backend/services/domain_registry.py
"""
Active domain state for the multi-domain architecture.

Stores which domain slug is currently active. Defaults to the first available
domain on startup. Changes via POST /api/domains/switch.
"""
import logging
from pathlib import Path
from core.config_loader import list_domain_slugs, get_domain_config, reload_domain_config

logger = logging.getLogger(__name__)

_ACTIVE_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "active_domain.txt"

_active_slug: str | None = None


def get_active_slug() -> str:
    """Return the active domain slug, initialising from file or first available domain."""
    global _active_slug
    if _active_slug:
        return _active_slug

    # Try reading from persistence file
    if _ACTIVE_FILE.exists():
        saved = _ACTIVE_FILE.read_text().strip()
        if saved:
            _active_slug = saved
            return _active_slug

    # Fall back to first available domain
    slugs = list_domain_slugs()
    if slugs:
        _active_slug = slugs[0]
        _persist()
        return _active_slug

    # Legacy fallback
    _active_slug = "ecosystem"
    return _active_slug


def switch_domain(slug: str) -> None:
    """Switch the active domain to a new slug."""
    global _active_slug
    slugs = list_domain_slugs()
    if slug not in slugs:
        raise ValueError(f"Domain '{slug}' not found. Available: {slugs}")
    _active_slug = slug
    _persist()
    logger.info(f"Switched active domain to: {slug}")


def get_active_config():
    """Return OrganizationConfig for the active domain."""
    return get_domain_config(get_active_slug())


def list_domains() -> list[dict]:
    """Return metadata for all configured domains."""
    result = []
    active = get_active_slug()
    for slug in list_domain_slugs():
        try:
            cfg = get_domain_config(slug)
            result.append({
                "slug": slug,
                "name": cfg.name,
                "description": cfg.description,
                "team_count": len(cfg.teams),
                "active": slug == active,
            })
        except Exception as e:
            result.append({"slug": slug, "name": slug, "active": slug == active, "error": str(e)})
    return result


def _persist() -> None:
    _ACTIVE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _ACTIVE_FILE.write_text(_active_slug or "")
```

**Step 2: Commit**

```bash
git add backend/services/domain_registry.py
git commit -m "feat: add active domain registry service"
```

---

### Task 3: Multi-domain database session factory

**Files:**
- Modify: `backend/database_domain.py`

**Step 1: Replace the hardcoded ecosystem singleton with a per-slug pool**

Replace the entire bottom half of `database_domain.py` (from `# Ecosystem domain — the default` onwards) with:

```python
# --- Multi-domain engine pool ---
_engines: dict[str, object] = {}   # slug → Engine
_sessions: dict[str, object] = {}  # slug → sessionmaker


def get_domain_engine(domain_slug: str):
    """Get (or create) the SQLAlchemy engine for a domain slug."""
    if domain_slug not in _engines:
        _engines[domain_slug] = create_domain_engine(domain_slug)
    return _engines[domain_slug]


def get_domain_session(domain_slug: str):
    """FastAPI dependency: yields a session for the given domain slug."""
    from sqlalchemy.orm import sessionmaker as _sm
    if domain_slug not in _sessions:
        _sessions[domain_slug] = _sm(autocommit=False, autoflush=False,
                                      bind=get_domain_engine(domain_slug))
    db = _sessions[domain_slug]()
    try:
        yield db
    finally:
        db.close()


# --- Backward-compat: active domain shims (used by all existing routers) ---

def get_ecosystem_engine():
    """Get engine for the currently active domain (backward compat)."""
    from services.domain_registry import get_active_slug
    return get_domain_engine(get_active_slug())


def get_ecosystem_session():
    """FastAPI dependency: yields a session for the currently active domain."""
    from services.domain_registry import get_active_slug
    yield from get_domain_session(get_active_slug())


def init_domain_db(domain_slug: str | None = None):
    """Create all domain tables for a slug (or active domain if None)."""
    from backend.models_domain import DomainBase as ModelBase
    if domain_slug is None:
        from services.domain_registry import get_active_slug
        domain_slug = get_active_slug()
    ModelBase.metadata.create_all(bind=get_domain_engine(domain_slug))


def init_all_domain_dbs():
    """Initialise DB tables for every configured domain."""
    from core.config_loader import list_domain_slugs
    for slug in list_domain_slugs():
        init_domain_db(slug)
```

**Step 2: Update `main.py` to init + seed all domains**

Replace the lifespan seeding block with:

```python
from database_domain import init_all_domain_dbs, get_domain_engine
from core.config_loader import list_domain_slugs
from services.domain_registry import get_active_slug

init_all_domain_dbs()

# Seed ALL configured domains
from services.domain_seeder import seed_reference_data
from sqlalchemy.orm import sessionmaker as _sm

for _slug in list_domain_slugs():
    _eng = get_domain_engine(_slug)
    _seed_db = _sm(bind=_eng)()
    try:
        _result = seed_reference_data(_seed_db)
        logger.info(f"Domain '{_slug}' seeded: {_result}")
    except Exception as e:
        logger.warning(f"Seed failed for '{_slug}': {e}")
    finally:
        _seed_db.close()

logger.info(f"Active domain: {get_active_slug()}")
```

**Step 3: Update `domain_seeder.py` to use the slug-specific config**

In `seed_reference_data()`, add a `domain_slug` parameter so it loads the right config:

```python
def seed_reference_data(db: Session, domain_slug: str | None = None) -> Dict[str, Any]:
    from core.config_loader import get_domain_config, get_config
    from backend.models_domain import RefTeam, RefMember

    # Load domain-specific config if slug provided, else fall back to default
    if domain_slug:
        config = get_domain_config(domain_slug)
    else:
        config = get_config()
    # ... rest unchanged
```

**Step 4: Test that backend still works for existing ecosystem domain**

```bash
curl http://localhost:9001/health
curl http://localhost:9001/api/gitlab/team-summary
```
Both should return 200.

**Step 5: Commit**

```bash
git add backend/database_domain.py backend/main.py backend/services/domain_seeder.py
git commit -m "feat: multi-domain DB engine pool + backward-compat active domain shims"
```

---

### Task 4: Domains API router

**Files:**
- Create: `backend/routers/domains_router.py`
- Modify: `backend/main.py`

**Step 1: Create the router**

```python
# backend/routers/domains_router.py
"""
Domains API — list, create, and switch between director domains.

GET  /api/domains          → list all configured domains
GET  /api/domains/active   → active domain info
POST /api/domains/switch   → switch active domain
POST /api/domains/create   → create a new domain from wizard payload
"""
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/domains", tags=["domains"])


@router.get("")
async def list_domains_endpoint():
    from services.domain_registry import list_domains
    return {"domains": list_domains()}


@router.get("/active")
async def get_active_domain():
    from services.domain_registry import get_active_slug, get_active_config
    slug = get_active_slug()
    try:
        cfg = get_active_config()
        return {"slug": slug, "name": cfg.name, "team_count": len(cfg.teams)}
    except Exception as e:
        return {"slug": slug, "name": slug, "error": str(e)}


class SwitchRequest(BaseModel):
    slug: str


@router.post("/switch")
async def switch_domain(body: SwitchRequest):
    from services.domain_registry import switch_domain
    try:
        switch_domain(body.slug)
        return {"ok": True, "active": body.slug}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
```

**Step 2: Register the router in `main.py`**

```python
from routers.domains_router import router as domains_router
app.include_router(domains_router)
```

**Step 3: Test the endpoints**

```bash
curl http://localhost:9001/api/domains
curl http://localhost:9001/api/domains/active
```
Expected: JSON with `domains` list including the migrated sinch-ecosystem domain.

**Step 4: Commit**

```bash
git add backend/routers/domains_router.py backend/main.py
git commit -m "feat: add /api/domains endpoints for listing and switching domains"
```

---

## Phase 2: Guided Onboarding — Auto-Discovery Backend

### Task 5: Onboarding discovery endpoints

**Files:**
- Create: `backend/routers/onboard_router.py`
- Modify: `backend/main.py`

**Step 1: Write the router with discovery endpoints**

```python
# backend/routers/onboard_router.py
"""
Onboarding wizard backend — auto-discovery endpoints.

All endpoints accept credentials in the request body (not from env vars),
so they work before a domain is configured.

POST /api/onboard/validate              → test GitLab + Jira creds
GET  /api/onboard/discover/gitlab-groups  → list subgroups under a GitLab group path
GET  /api/onboard/discover/jira-projects  → list Jira projects for a site
GET  /api/onboard/discover/gitlab-members → list members of a GitLab group
POST /api/onboard/create                → save new domain config + init DB + seed
"""
import logging
import requests
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/onboard", tags=["onboard"])

GITLAB_API = "https://gitlab.com/api/v4"


# ── Validate ──────────────────────────────────────────────────────────────────

class ValidateRequest(BaseModel):
    gitlab_token: str
    jira_url: Optional[str] = None
    jira_email: Optional[str] = None
    jira_token: Optional[str] = None


@router.post("/validate")
async def validate_credentials(body: ValidateRequest):
    results = {}

    # GitLab
    try:
        r = requests.get(f"{GITLAB_API}/user",
                         headers={"PRIVATE-TOKEN": body.gitlab_token}, timeout=10)
        if r.ok:
            data = r.json()
            results["gitlab"] = {"ok": True, "user": data.get("username"), "error": None}
        else:
            results["gitlab"] = {"ok": False, "user": None, "error": f"HTTP {r.status_code}"}
    except Exception as e:
        results["gitlab"] = {"ok": False, "user": None, "error": str(e)}

    # Jira (optional)
    if body.jira_url and body.jira_email and body.jira_token:
        try:
            r = requests.get(f"{body.jira_url.rstrip('/')}/rest/api/3/myself",
                             auth=(body.jira_email, body.jira_token), timeout=10)
            if r.ok:
                data = r.json()
                results["jira"] = {"ok": True, "user": data.get("displayName"), "error": None}
            else:
                results["jira"] = {"ok": False, "user": None, "error": f"HTTP {r.status_code}"}
        except Exception as e:
            results["jira"] = {"ok": False, "user": None, "error": str(e)}
    else:
        results["jira"] = None

    return results


# ── GitLab group discovery ────────────────────────────────────────────────────

@router.get("/discover/gitlab-groups")
async def discover_gitlab_groups(
    token: str = Query(..., description="GitLab personal access token"),
    group_path: str = Query(..., description="GitLab group path, e.g. sinch/sinch-projects/applications/smb/teams"),
):
    """
    List subgroups under a GitLab group path.
    Returns [{id, name, full_path, description}].
    """
    # First resolve group path to numeric ID
    try:
        import urllib.parse
        encoded = urllib.parse.quote(group_path, safe="")
        r = requests.get(f"{GITLAB_API}/groups/{encoded}",
                         headers={"PRIVATE-TOKEN": token}, timeout=15)
        if not r.ok:
            raise HTTPException(status_code=r.status_code,
                                detail=f"GitLab group not found: {group_path}")
        group_id = r.json()["id"]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # List subgroups
    subgroups = []
    page = 1
    while True:
        r = requests.get(
            f"{GITLAB_API}/groups/{group_id}/subgroups",
            headers={"PRIVATE-TOKEN": token},
            params={"per_page": 50, "page": page, "order_by": "name"},
            timeout=15,
        )
        if not r.ok:
            break
        batch = r.json()
        if not batch:
            break
        subgroups.extend([
            {"id": g["id"], "name": g["name"], "full_path": g["full_path"],
             "description": g.get("description", "")}
            for g in batch
        ])
        if len(batch) < 50:
            break
        page += 1

    return {"groups": subgroups}


# ── Jira project discovery ────────────────────────────────────────────────────

@router.get("/discover/jira-projects")
async def discover_jira_projects(
    jira_url: str = Query(...),
    jira_email: str = Query(...),
    jira_token: str = Query(...),
):
    """List all Jira software projects. Returns [{key, name, type}]."""
    try:
        r = requests.get(
            f"{jira_url.rstrip('/')}/rest/api/3/project/search",
            auth=(jira_email, jira_token),
            params={"maxResults": 100, "orderBy": "name", "typeKey": "software"},
            timeout=15,
        )
        if not r.ok:
            raise HTTPException(status_code=r.status_code,
                                detail=f"Jira project list failed: HTTP {r.status_code}")
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


# ── GitLab member discovery ───────────────────────────────────────────────────

@router.get("/discover/gitlab-members")
async def discover_gitlab_members(
    token: str = Query(...),
    group_path: str = Query(..., description="GitLab group full_path"),
):
    """List direct members of a GitLab group. Returns [{username, name, role}]."""
    import urllib.parse
    encoded = urllib.parse.quote(group_path, safe="")
    members = []
    page = 1
    while True:
        r = requests.get(
            f"{GITLAB_API}/groups/{encoded}/members",
            headers={"PRIVATE-TOKEN": token},
            params={"per_page": 50, "page": page},
            timeout=15,
        )
        if not r.ok:
            break
        batch = r.json()
        if not batch:
            break
        members.extend([
            {"username": m["username"], "name": m["name"],
             "role": _access_to_role(m.get("access_level", 30))}
            for m in batch
        ])
        if len(batch) < 50:
            break
        page += 1
    return {"members": members}


def _access_to_role(level: int) -> str:
    """Map GitLab access level to role string."""
    if level >= 50: return "owner"
    if level >= 40: return "TL"      # Maintainer
    if level >= 30: return "engineer" # Developer
    return "observer"


# ── Create domain ─────────────────────────────────────────────────────────────

class DomainCreateRequest(BaseModel):
    organization: dict
    user: dict
    teams: list
    jira: Optional[dict] = None
    gitlab: Optional[dict] = None
    optional: Optional[dict] = None


@router.post("/create")
async def create_domain(body: DomainCreateRequest):
    """
    Persist a new domain config from wizard payload, initialise its DB, and seed it.
    Switches to the new domain as the active domain.
    """
    import yaml
    from pathlib import Path

    slug = body.organization.get("slug", "").strip()
    if not slug:
        raise HTTPException(status_code=422, detail="organization.slug is required")

    domains_dir = Path(__file__).resolve().parent.parent.parent / "config" / "domains"
    domains_dir.mkdir(parents=True, exist_ok=True)
    config_path = domains_dir / f"{slug}.yaml"

    if config_path.exists():
        raise HTTPException(status_code=409, detail=f"Domain '{slug}' already exists")

    # Build YAML-compatible config dict
    config_dict = {
        "organization": body.organization,
        "user": body.user,
        "teams": body.teams,
    }
    if body.jira:
        config_dict["organization"].update({
            "atlassian_site_url": body.jira.get("url", ""),
        })
    if body.optional:
        config_dict["integrations"] = {}
        if body.optional.get("snyk_token"):
            config_dict["integrations"]["security"] = {
                "provider": "snyk", "config": {"token": body.optional["snyk_token"]}
            }

    config_path.write_text(
        yaml.dump(config_dict, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    logger.info(f"Domain config written: {config_path}")

    # Init DB + seed
    from database_domain import init_domain_db, get_domain_engine
    from services.domain_seeder import seed_reference_data
    from core.config_loader import get_domain_config, reload_domain_config
    from sqlalchemy.orm import sessionmaker as _sm
    from services.domain_registry import switch_domain

    init_domain_db(slug)
    cfg = get_domain_config(slug)
    eng = get_domain_engine(slug)
    db = _sm(bind=eng)()
    try:
        seed_result = seed_reference_data(db, domain_slug=slug)
    finally:
        db.close()

    switch_domain(slug)

    return {"ok": True, "slug": slug, "name": cfg.name, "seeded": seed_result}
```

**Step 2: Register in `main.py`**

```python
from routers.onboard_router import router as onboard_router
app.include_router(onboard_router)
```

**Step 3: Smoke test the discovery endpoints**

```bash
# Test validate (replace TOKEN with your real token)
curl -X POST http://localhost:9001/api/onboard/validate \
  -H "Content-Type: application/json" \
  -d '{"gitlab_token": "YOUR_TOKEN"}'

# Test group discovery
curl "http://localhost:9001/api/onboard/discover/gitlab-groups?token=YOUR_TOKEN&group_path=sinch/sinch-projects/applications/smb/teams"
```

**Step 4: Commit**

```bash
git add backend/routers/onboard_router.py backend/main.py
git commit -m "feat: add onboarding discovery endpoints (validate, gitlab groups/members, jira projects)"
```

---

## Phase 3: Frontend — Domain Selector + Enhanced Wizard

### Task 6: Domain context + switcher in Layout

**Files:**
- Create: `frontend/src/contexts/DomainContext.tsx`
- Modify: `frontend/src/components/Layout.tsx`
- Modify: `frontend/src/api/client.ts`

**Step 1: Create domain context**

```tsx
// frontend/src/contexts/DomainContext.tsx
import { createContext, useContext, useState, useEffect, ReactNode } from 'react'
import axios from 'axios'

interface DomainInfo {
  slug: string
  name: string
  team_count?: number
  active: boolean
}

interface DomainContextValue {
  activeDomain: DomainInfo | null
  domains: DomainInfo[]
  switchDomain: (slug: string) => Promise<void>
  refreshDomains: () => Promise<void>
}

const DomainContext = createContext<DomainContextValue>({
  activeDomain: null,
  domains: [],
  switchDomain: async () => {},
  refreshDomains: async () => {},
})

export function DomainProvider({ children }: { children: ReactNode }) {
  const [domains, setDomains] = useState<DomainInfo[]>([])
  const [activeDomain, setActiveDomain] = useState<DomainInfo | null>(null)

  const refreshDomains = async () => {
    const r = await axios.get('/api/domains')
    const list: DomainInfo[] = r.data.domains
    setDomains(list)
    setActiveDomain(list.find(d => d.active) ?? null)
  }

  const switchDomain = async (slug: string) => {
    await axios.post('/api/domains/switch', { slug })
    await refreshDomains()
    // Reload the page so all cached data refreshes
    window.location.reload()
  }

  useEffect(() => { refreshDomains() }, [])

  return (
    <DomainContext.Provider value={{ activeDomain, domains, switchDomain, refreshDomains }}>
      {children}
    </DomainContext.Provider>
  )
}

export const useDomain = () => useContext(DomainContext)
```

**Step 2: Add domain switcher chip to the Layout header**

Find the existing header/nav section in `Layout.tsx`. Add a `DomainSwitcher` component below the app title:

```tsx
// Inside Layout.tsx, add after imports:
import { useDomain } from '../contexts/DomainContext'

// Add a DomainSwitcher component:
function DomainSwitcher() {
  const { activeDomain, domains, switchDomain } = useDomain()
  const [open, setOpen] = useState(false)

  if (domains.length <= 1) {
    // Single domain — show name as non-interactive chip
    return (
      <span className="text-xs text-gray-500 font-mono px-2 py-0.5 bg-gray-800 rounded">
        {activeDomain?.name ?? '—'}
      </span>
    )
  }

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(o => !o)}
        className="text-xs text-blue-400 font-mono px-2 py-0.5 bg-gray-800 rounded hover:bg-gray-700 flex items-center gap-1"
      >
        {activeDomain?.name ?? '—'}
        <span className="text-gray-500">▾</span>
      </button>
      {open && (
        <div className="absolute top-full left-0 mt-1 bg-gray-900 border border-gray-700 rounded-lg shadow-xl z-50 min-w-[180px]">
          {domains.map(d => (
            <button
              key={d.slug}
              onClick={() => { setOpen(false); switchDomain(d.slug) }}
              className={`w-full text-left px-3 py-2 text-sm hover:bg-gray-800 first:rounded-t-lg last:rounded-b-lg flex items-center justify-between ${d.active ? 'text-blue-400' : 'text-gray-300'}`}
            >
              <span>{d.name}</span>
              {d.active && <span className="text-xs text-gray-500">active</span>}
            </button>
          ))}
          <div className="border-t border-gray-800">
            <a href="/setup/new" className="block px-3 py-2 text-xs text-gray-500 hover:text-gray-300 hover:bg-gray-800 rounded-b-lg">
              + Add domain
            </a>
          </div>
        </div>
      )}
    </div>
  )
}
```

**Step 3: Wrap App with DomainProvider**

In `main.tsx` or `App.tsx`, wrap the router:

```tsx
import { DomainProvider } from './contexts/DomainContext'
// ... wrap return value in <DomainProvider>
```

**Step 4: Commit**

```bash
git add frontend/src/contexts/DomainContext.tsx frontend/src/components/Layout.tsx frontend/src/main.tsx
git commit -m "feat: add domain switcher to Layout header"
```

---

### Task 7: New domain wizard — auto-discovery for teams and engineers

**Goal:** Enhance the existing Step4Teams and Step5Engineers with "Discover from GitLab" buttons. Users enter a parent group path, click discover, and get a pre-populated checklist to select from.

**Files:**
- Modify: `frontend/src/pages/Setup/Step3GitLab.tsx` (add base group path field)
- Modify: `frontend/src/pages/Setup/Step4Teams.tsx` (add discovery button + checklist)
- Modify: `frontend/src/pages/Setup/Step5Engineers.tsx` (add per-team discovery button)
- Modify: `frontend/src/pages/Setup/index.tsx` (store gitlab_base_group in wizard state)

**Step 1: Add `gitlab_base_group` to wizard state in `index.tsx`**

```tsx
// In WizardConfig interface, add:
gitlab: { token: string; base_group: string }

// In initial state:
gitlab: { token: '', base_group: '' }
```

**Step 2: Add base group field to `Step3GitLab.tsx`**

Below the existing token field, add:

```tsx
<div>
  <label className="block text-xs font-medium text-gray-400 mb-1">
    GitLab Base Group Path <span className="text-gray-600">(optional — for auto-discovery)</span>
  </label>
  <input
    type="text"
    value={data.gitlab.base_group ?? ''}
    onChange={e => onChange({ gitlab: { ...data.gitlab, base_group: e.target.value } })}
    placeholder="my-org/teams"
    className="w-full bg-gray-900 border border-gray-700 text-white rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-500 placeholder-gray-500 font-mono"
  />
  <p className="text-gray-600 text-xs mt-1">If set, Step 4 will offer to auto-discover your teams as subgroups of this path.</p>
</div>
```

**Step 3: Add "Discover from GitLab" to `Step4Teams.tsx`**

Add this block above the manual "Add Team" form:

```tsx
// Add at top of component:
const [discovering, setDiscovering] = useState(false)
const [discovered, setDiscovered] = useState<{ full_path: string; name: string; selected: boolean }[]>([])
const [discoverError, setDiscoverError] = useState<string | null>(null)

// Add handler:
const handleDiscover = async () => {
  if (!gitlabToken || !gitlabBaseGroup) return
  setDiscovering(true)
  setDiscoverError(null)
  try {
    const r = await axios.get('/api/onboard/discover/gitlab-groups', {
      params: { token: gitlabToken, group_path: gitlabBaseGroup }
    })
    setDiscovered(r.data.groups.map((g: any) => ({ ...g, selected: true })))
  } catch (e: any) {
    setDiscoverError(e.response?.data?.detail ?? 'Discovery failed')
  } finally {
    setDiscovering(false)
  }
}

// Add "Import selected" handler:
const handleImportDiscovered = () => {
  const toAdd = discovered.filter(g => g.selected && !teams.some(t => t.gitlab_path === g.full_path))
  const newTeams: TeamEntry[] = toAdd.map(g => ({
    key: g.name.slice(0, 8).toUpperCase().replace(/[^A-Z]/g, ''),
    name: g.name,
    gitlab_path: g.full_path,
    jira_project: '',
  }))
  onTeamsChange([...teams, ...newTeams])
  setDiscovered([])
}
```

Show discovery UI only if `gitlabBaseGroup` is provided (pass as a prop from `index.tsx`).

**Step 4: Add per-team member discovery to `Step5Engineers.tsx`**

For each team, add a "Discover members" button that calls:
```
GET /api/onboard/discover/gitlab-members?token=TOKEN&group_path=TEAM_GITLAB_PATH
```
Returns a checklist of members to import. Same selected-then-import pattern as teams.

**Step 5: Make wizard support `/setup/new` route (add new domain vs. first-time setup)**

In `App.tsx`, add a route:

```tsx
<Route path="/setup/new" element={<Setup onComplete={() => navigate('/dashboard')} isNewDomain />} />
```

In `Setup/index.tsx`, accept `isNewDomain?: boolean` and if true, call `POST /api/onboard/create` instead of `POST /api/config` at the final step.

**Step 6: Test full new-domain flow**

1. Visit `http://localhost:5173/setup/new`
2. Fill in org name/slug (different from existing)
3. Enter GitLab token + base group
4. Click "Discover teams" → confirm pre-populated checklist
5. Add Jira project keys to each team
6. Discover engineers per team
7. Validate + submit → verify new domain appears in switcher

**Step 7: Commit**

```bash
git add frontend/src/pages/Setup/
git commit -m "feat: guided onboarding with GitLab team + member auto-discovery"
```

---

## Phase 4: Polish + Config Router Update

### Task 8: Update config router to support domain-scoped operations

**Files:**
- Modify: `backend/routers/config_router.py`

**Step 1: Update `GET /api/config` and `POST /api/config` to write to `config/domains/{slug}.yaml`**

Change `_CONFIG_FILE` to resolve dynamically:

```python
def _get_config_file(domain_slug: str | None = None) -> Path:
    from services.domain_registry import get_active_slug
    slug = domain_slug or get_active_slug()
    domains_dir = _PROJECT_ROOT / "config" / "domains"
    domains_dir.mkdir(parents=True, exist_ok=True)
    return domains_dir / f"{slug}.yaml"
```

Update `get_config()` and `save_config()` to use `_get_config_file()` instead of `_CONFIG_FILE`.

**Step 2: Update reseed endpoint to use active domain**

```python
@router.post("/domain/seed")
async def reseed_reference_data():
    from services.domain_registry import get_active_slug
    from database_domain import get_domain_engine
    from sqlalchemy.orm import sessionmaker as _sm
    slug = get_active_slug()
    db = _sm(bind=get_domain_engine(slug))()
    result = seed_reference_data(db, domain_slug=slug)
    db.close()
    return {"status": "seeded", "domain": slug, **result}
```

**Step 3: Commit**

```bash
git add backend/routers/config_router.py
git commit -m "refactor: config router writes to domain-scoped YAML file"
```

---

## Testing Checklist

After all tasks are complete, verify:

- [ ] Backend starts cleanly, logs show all domains seeded
- [ ] `GET /api/domains` returns all configured domains
- [ ] `GET /api/domains/active` returns the current domain
- [ ] `POST /api/domains/switch` switches domain (verify next API call uses new domain data)
- [ ] `POST /api/onboard/validate` works with real GitLab token
- [ ] `GET /api/onboard/discover/gitlab-groups` returns subgroups
- [ ] `GET /api/onboard/discover/gitlab-members` returns members
- [ ] Setup wizard `/setup/new` allows creating a second domain end-to-end
- [ ] Domain switcher in Layout shows correct active domain
- [ ] All existing dashboard endpoints still work after refactor (backward compat shims)

---

## Execution Order

Implement tasks in this order (each builds on the previous):

1. Task 1 — Config domains directory + migration
2. Task 2 — Active domain registry service
3. Task 3 — Multi-domain DB engine pool
4. Task 4 — Domains API router
5. Task 5 — Onboarding discovery endpoints
6. Task 6 — Frontend domain context + switcher
7. Task 7 — Enhanced wizard with auto-discovery
8. Task 8 — Config router domain scoping
