"""
Port.io API Router

Provides endpoints for querying the Port.io service catalog.

Endpoints:
- GET  /api/port/services  → all services (from DB cache; live fallback if empty)
- POST /api/port/sync      → fetch from Port API and store to DB
- GET  /api/port/status    → Port connection status
"""

import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException

from backend.services.port_service import get_services, get_port_status, get_services_from_db, sync_services_to_db, enrich_versions_background

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/port", tags=["port"])


@router.get("/status")
async def port_status():
    """Check Port.io connection status."""
    return get_port_status()


@router.get("/services")
async def list_services():
    """
    List services from Port.io.

    Returns cached data from DB when available (fast).
    Falls back to live Port API if the DB cache is empty.
    Trigger POST /api/port/sync to refresh the cache.
    """
    cached = get_services_from_db()
    if cached["count"] > 0:
        return cached

    # DB empty — fall back to live API (first load)
    status = get_port_status()
    if not status.get("configured"):
        raise HTTPException(
            status_code=503,
            detail="Port credentials are not configured for the active domain.",
        )

    result = get_services()
    if result.get("configured") is False:
        raise HTTPException(status_code=503, detail="Port.io not configured.")

    return result


@router.post("/sync")
async def sync_services(background_tasks: BackgroundTasks):
    """
    Trigger a background sync of Port.io service catalog to the domain DB.

    The sync fetches all Port entities and upserts them into port_services.
    Subsequent GET /api/port/services calls will read from DB.
    """
    status = get_port_status()
    if not status.get("configured"):
        raise HTTPException(
            status_code=503,
            detail="Port credentials are not configured for the active domain.",
        )

    background_tasks.add_task(_run_sync)
    return {"status": "syncing", "message": "Port services sync started in background"}


def _run_sync():
    result = sync_services_to_db()
    if result.get("error"):
        logger.error(f"Port sync failed: {result['error']}")
    else:
        logger.info(f"Port sync complete: {result['synced']} services stored at {result['synced_at']}")


@router.post("/enrich-versions")
async def enrich_versions(background_tasks: BackgroundTasks):
    """
    Trigger background version scanning for Port services.

    Fetches language versions from GitLab API for all services that have a URL
    but no language_version yet. Stores the result in the domain DB.
    """
    background_tasks.add_task(enrich_versions_background)
    return {"status": "enriching", "message": "Version enrichment started in background"}
