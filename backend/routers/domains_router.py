"""
Domains API — list and switch between director domains.

GET  /api/domains        → list all configured domains
GET  /api/domains/active → active domain info
POST /api/domains/switch → switch active domain
"""
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/domains", tags=["domains"])


@router.get("")
async def list_domains_endpoint():
    from backend.services.domain_registry import list_domains
    return {"domains": list_domains()}


@router.get("/active")
async def get_active_domain():
    from backend.services.domain_registry import get_active_slug, get_active_config
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
    from backend.services.domain_registry import switch_domain as _switch
    try:
        _switch(body.slug)
        return {"ok": True, "active": body.slug}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
