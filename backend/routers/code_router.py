"""
Provider-agnostic code/git API endpoints.

These endpoints provide the same functionality as /api/gitlab/* but under a
provider-neutral namespace. The /api/gitlab/* endpoints remain for backward
compatibility.
"""

import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.orm import Session

from backend.database_domain import get_ecosystem_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/code", tags=["Code"])


@router.get("/health")
async def health():
    from backend.routers.gitlab_collector_router import health_check
    return await health_check()


@router.get("/team-summary")
async def team_summary(
    days: int = Query(default=30, ge=1, le=365),
    compare: bool = Query(default=False, description="Include period-over-period comparison"),
    db: Session = Depends(get_ecosystem_session),
):
    from backend.routers.gitlab_collector_router import get_team_summary
    return await get_team_summary(days=days, compare=compare, db=db)


@router.get("/team-trend")
async def team_trend(
    team: str = Query(..., description="Team slug"),
    days: int = Query(default=90, ge=7, le=365),
    db: Session = Depends(get_ecosystem_session),
):
    from backend.routers.gitlab_collector_router import get_team_trend
    return await get_team_trend(team=team, days=days, db=db)


@router.get("/metrics")
async def metrics(
    days: int = Query(default=30, ge=1, le=365),
    sync_first: bool = Query(default=False),
):
    from backend.routers.gitlab_collector_router import get_all_metrics
    return await get_all_metrics(days=days, sync_first=sync_first)


@router.get("/engineers")
async def engineers(
    team: Optional[str] = Query(default=None),
    days: int = Query(default=30, ge=1, le=365),
    compare: bool = Query(default=False, description="Include period-over-period deltas"),
    db: Session = Depends(get_ecosystem_session),
):
    from backend.routers.gitlab_collector_router import list_engineers
    return await list_engineers(team=team, days=days, compare=compare, db=db)


@router.get("/engineers/{username}")
async def engineer_detail(
    username: str,
    days: int = Query(default=90, ge=1, le=365),
    db: Session = Depends(get_ecosystem_session),
):
    from backend.routers.gitlab_collector_router import get_engineer
    return await get_engineer(username=username, days=days, db=db)


@router.post("/engineers/{username}/sync")
async def sync_single_engineer(
    username: str,
    days: int = Query(default=90, ge=1, le=365),
    db: Session = Depends(get_ecosystem_session),
):
    from backend.routers.gitlab_collector_router import sync_engineer
    return await sync_engineer(username=username, days=days, db=db)


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


@router.get("/security")
async def security_summary(
    sync_first: bool = Query(default=False),
):
    from backend.routers.gitlab_collector_router import get_security_summary
    return await get_security_summary(sync_first=sync_first)


@router.get("/security/teams")
async def security_by_team():
    from backend.routers.gitlab_collector_router import get_security_by_team
    return await get_security_by_team()


@router.get("/security/critical")
async def security_critical():
    from backend.routers.gitlab_collector_router import get_critical_vulnerabilities
    return await get_critical_vulnerabilities()


@router.get("/security/high-risk")
async def security_high_risk(
    threshold: int = Query(default=5, ge=1),
):
    from backend.routers.gitlab_collector_router import get_high_risk_teams
    return await get_high_risk_teams(threshold=threshold)


@router.get("/security/trend")
async def security_trend(
    months: int = Query(default=6, ge=1, le=12),
):
    from backend.routers.gitlab_collector_router import get_security_trend
    return await get_security_trend(months=months)
