"""
Engineering Director Dashboard — Backend
Port: 9001
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import os
import logging
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from pathlib import Path

_repo_env = Path(__file__).resolve().parent.parent / ".env"
if _repo_env.exists():
    load_dotenv(_repo_env, override=False)
load_dotenv()

from backend.database import init_db
from backend.database_domain import init_all_domain_dbs, migrate_all_domain_dbs, get_domain_engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()

    # Auto-migrate legacy organization.yaml → config/domains/{slug}.yaml
    _legacy = Path(__file__).parent.parent / "config" / "organization.yaml"
    _domains_dir = Path(__file__).parent.parent / "config" / "domains"
    _domains_dir.mkdir(parents=True, exist_ok=True)

    if _legacy.exists() and not any(_domains_dir.glob("*.yaml")):
        import shutil as _shutil
        import yaml as _yaml
        _raw = _yaml.safe_load(_legacy.read_text())
        _slug = _raw.get("organization", {}).get("slug", "ecosystem")
        _dest = _domains_dir / f"{_slug}.yaml"
        _shutil.copy2(_legacy, _dest)
        logger.info(f"Migrated organization.yaml → config/domains/{_slug}.yaml")

    # Initialise DB tables for all configured domains
    init_all_domain_dbs()
    # Run additive schema migrations (safe to run on every startup)
    migrate_all_domain_dbs()

    # Seed reference data for ALL configured domains
    from backend.services.domain_seeder import seed_reference_data
    from backend.core.config_loader import list_domain_slugs
    from sqlalchemy.orm import sessionmaker as _sessionmaker

    for _slug in list_domain_slugs():
        _eng = get_domain_engine(_slug)
        _seed_db = _sessionmaker(bind=_eng)()
        try:
            _result = seed_reference_data(_seed_db, domain_slug=_slug)
            logger.info(f"Domain '{_slug}' seeded: {_result}")
        except Exception as _e:
            logger.warning(f"Seed failed for '{_slug}': {_e}")
        finally:
            _seed_db.close()

    from backend.services.domain_registry import get_active_slug
    logger.info(f"Active domain: {get_active_slug()}")
    logger.info("Engineering Director Dashboard started on port 9001")

    # Warn if no domains are configured yet
    if not list_domain_slugs():
        logger.warning("=" * 60)
        logger.warning("No domain config found in config/domains/!")
        logger.warning("Open http://localhost:5173 to complete the setup wizard.")
        logger.warning("=" * 60)

    # Start background sync scheduler
    from backend.services.scheduler import start as start_scheduler, stop as stop_scheduler
    await start_scheduler()

    yield

    # Shutdown scheduler
    await stop_scheduler()
    logger.info("Engineering Director Dashboard shutting down")


app = FastAPI(
    title="Engineering Director Dashboard",
    description="Engineering metrics and team intelligence dashboard",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Jira routers
from backend.routers.jira_indexer_router import router as jira_indexer_router
from backend.routers.jira_report_router import router as jira_report_router

app.include_router(jira_indexer_router)
app.include_router(jira_report_router)

# GitLab routers
from backend.routers.gitlab_collector_router import router as gitlab_router

app.include_router(gitlab_router)

# Config router (has its own /api/config prefix)
from backend.routers.config_router import router as config_router

app.include_router(config_router)

# Port.io router (has its own /api/port prefix)
from backend.routers.port_router import router as port_router

app.include_router(port_router)

# Sync status router (has its own /api/sync prefix)
from backend.routers.sync_router import router as sync_router

app.include_router(sync_router)

# Domains router (has its own /api/domains prefix)
from backend.routers.domains_router import router as domains_router

app.include_router(domains_router)

# Onboarding router (has its own /api/onboard prefix)
from backend.routers.onboard_router import router as onboard_router

app.include_router(onboard_router)

# Search router
from backend.routers.search_router import router as search_router

app.include_router(search_router)

# Executive reporting router
from backend.routers.reports_router import router as reports_router

app.include_router(reports_router)

# Alerts summary router
from backend.routers.alerts_router import router as alerts_router

app.include_router(alerts_router)


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "eng-dashboard", "version": "1.0.0"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=9001, reload=True)
