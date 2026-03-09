"""
Provider-agnostic code/git API endpoints.

These endpoints provide the same functionality as /api/gitlab/* but under a
provider-neutral namespace. The /api/gitlab/* endpoints remain for backward
compatibility.

Alias mapping:
    GET /api/code/team-summary   -> GET /api/gitlab/team-summary
    GET /api/code/team-trend     -> GET /api/gitlab/team-trend
    GET /api/code/engineers      -> GET /api/gitlab/engineers
    GET /api/code/engineers/{u}  -> GET /api/gitlab/engineers/{u}
    GET /api/code/activity       -> GET /api/gitlab/activity
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.database_domain import get_ecosystem_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/code", tags=["Code"])


@router.get("/team-summary")
async def team_summary(
    days: int = Query(default=30, ge=1, le=365),
    compare: bool = Query(default=False, description="Include period-over-period comparison"),
    db: Session = Depends(get_ecosystem_session),
):
    """Provider-agnostic team summary -- delegates to gitlab router."""
    from backend.routers.gitlab_collector_router import get_team_summary
    return await get_team_summary(days=days, compare=compare, db=db)


@router.get("/team-trend")
async def team_trend(
    team: str = Query(..., description="Team slug"),
    days: int = Query(default=90, ge=7, le=365),
    db: Session = Depends(get_ecosystem_session),
):
    """Provider-agnostic team trend -- delegates to gitlab router."""
    from backend.routers.gitlab_collector_router import get_team_trend
    return await get_team_trend(team=team, days=days, db=db)


@router.get("/engineers")
async def engineers(
    team: Optional[str] = Query(default=None),
    days: int = Query(default=30, ge=1, le=365),
    compare: bool = Query(default=False, description="Include period-over-period deltas"),
    db: Session = Depends(get_ecosystem_session),
):
    """Provider-agnostic engineer list -- delegates to gitlab router."""
    from backend.routers.gitlab_collector_router import list_engineers
    return await list_engineers(team=team, days=days, compare=compare, db=db)


@router.get("/engineers/{username}")
async def engineer_detail(
    username: str,
    days: int = Query(default=90, ge=1, le=365),
    db: Session = Depends(get_ecosystem_session),
):
    """Provider-agnostic engineer detail -- delegates to gitlab router."""
    from backend.routers.gitlab_collector_router import get_engineer
    return await get_engineer(username=username, days=days, db=db)


@router.get("/activity")
async def activity(
    team: str | None = Query(default=None, description="Filter by team slug"),
    engineer: str | None = Query(default=None, description="Filter by engineer username"),
    epic: str | None = Query(default=None, description="Filter by epic or ticket reference"),
    state: str | None = Query(default=None, description="Filter by MR state"),
    days: int = Query(default=30, ge=1, le=365),
    compare: bool = Query(default=False, description="Split results into current and previous windows"),
    limit: int = Query(default=100, ge=1, le=300),
    db: Session = Depends(get_ecosystem_session),
):
    """Provider-agnostic activity feed -- delegates to gitlab router."""
    from backend.routers.gitlab_collector_router import get_merge_request_activity
    return await get_merge_request_activity(
        team=team,
        engineer=engineer,
        epic=epic,
        state=state,
        days=days,
        compare=compare,
        limit=limit,
        db=db,
    )
