"""
Provider-agnostic issue tracker API endpoints.

These endpoints provide the same functionality as /api/jira/index/* but under a
provider-neutral namespace. The /api/jira/* endpoints remain for backward
compatibility.

Alias mapping:
    GET /api/issues/epics                    -> GET /api/jira/index/epics
    GET /api/issues/epics/{key}/contributors -> GET /api/jira/index/epics/{key}/contributors
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/issues", tags=["Issues"])


def _get_ecosystem_db():
    """FastAPI dependency: yields an ecosystem DB session (same as jira_indexer_router)."""
    from backend.database_domain import create_ecosystem_session
    db = create_ecosystem_session()
    try:
        yield db
    finally:
        db.close()


@router.get("/epics")
async def epics(
    team: Optional[str] = Query(None, description="Filter by team key (e.g. EEH, MA)"),
    status: Optional[str] = Query(None, description="Filter by status category: 'In Progress', 'To Do', 'Done'"),
    limit: int = Query(200, ge=1, le=1000),
    eco_db: Session = Depends(_get_ecosystem_db),
):
    """Provider-agnostic epics list -- delegates to jira indexer router."""
    from backend.routers.jira_indexer_router import list_epics
    return await list_epics(team=team, status=status, limit=limit, eco_db=eco_db)


@router.get("/epics/{epic_key}/contributors")
async def epic_contributors(
    epic_key: str,
    eco_db: Session = Depends(_get_ecosystem_db),
):
    """Provider-agnostic epic contributors -- delegates to jira indexer router."""
    from backend.routers.jira_indexer_router import get_epic_contributors
    return await get_epic_contributors(epic_key=epic_key, eco_db=eco_db)
