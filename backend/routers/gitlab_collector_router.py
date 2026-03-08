"""
GitLab Collector API Router

Provides REST endpoints for the native GitLab metrics collector.
This replaces the external gitlab-analysis project's API.

Endpoints:
- GET /api/gitlab/health - Check GitLab API connectivity
- GET /api/gitlab/status - Get sync status for all teams
- POST /api/gitlab/sync - Sync metrics for all teams
- POST /api/gitlab/sync/{team} - Sync metrics for a specific team
- GET /api/gitlab/metrics - Get aggregated DORA metrics
- GET /api/gitlab/metrics/{team} - Get metrics for a specific team
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.services.gitlab_intelligence import get_collector, GitLabCollectorError
from backend.services.gitlab_intelligence import get_repo_scanner, RepoScannerError
from backend.services.gitlab_intelligence import get_dora_service
from backend.config.gitlab_teams import TEAM_GITLAB_PATHS, TEAM_DISPLAY_NAMES
from backend.database_domain import get_ecosystem_session
from backend.services.domain_credentials import get_gitlab_settings
from backend.services.datetime_utils import ensure_utc, utcnow_naive

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/gitlab", tags=["GitLab Collector"])


# ==================== Response Models ====================

class HealthResponse(BaseModel):
    """GitLab API health check response."""
    status: str
    gitlab_url: Optional[str] = None
    authenticated_as: Optional[str] = None
    error: Optional[str] = None


class SyncStatusResponse(BaseModel):
    """Sync status for a single team."""
    team: str
    display_name: str
    last_sync_date: Optional[str] = None
    status: str


class SyncResultResponse(BaseModel):
    """Result of a sync operation."""
    team: str
    status: str
    days_synced: Optional[int] = None
    pipelines: Optional[int] = None
    mrs: Optional[int] = None
    records_created: Optional[int] = None
    records_updated: Optional[int] = None
    error: Optional[str] = None
    reason: Optional[str] = None


class AllTeamsSyncResponse(BaseModel):
    """Result of syncing all teams."""
    results: dict[str, SyncResultResponse]
    stats: dict
    synced_at: str


class DORAMetricsResponse(BaseModel):
    """DORA metrics response."""
    team: str
    period_days: int
    lead_time: dict
    deployment_frequency: dict
    change_failure_rate: dict
    time_to_restore: dict
    dora_level: str


class RepoResponse(BaseModel):
    """Repository information response."""
    id: int
    team: str
    name: str
    path: str
    language: Optional[str] = None
    framework: Optional[str] = None
    has_tests: bool = False
    has_ci: bool = False
    is_orphaned: bool = False
    last_activity: Optional[str] = None


class RepoScanResultResponse(BaseModel):
    """Result of a repo scan operation."""
    team: str
    status: str
    repos_discovered: Optional[int] = None
    repos_scanned: Optional[int] = None
    repos_updated: Optional[int] = None
    error: Optional[str] = None


class AllReposScanResponse(BaseModel):
    """Result of scanning all teams' repos."""
    results: dict[str, RepoScanResultResponse]
    stats: dict
    scanned_at: str


# ==================== Endpoints ====================

@router.get("/health", response_model=HealthResponse)
async def health_check():
    """
    Check if GitLab API is accessible.

    Verifies the GITLAB_TOKEN is configured and valid.
    """
    try:
        collector = get_collector()
        result = collector.health_check()
        return HealthResponse(**result)
    except Exception as e:
        return HealthResponse(status="error", error=str(e))


@router.get("/status")
async def get_sync_status():
    """
    Get sync status from ecosystem.db sync_status table.
    """
    try:
        from backend.database_domain import create_ecosystem_session
        from sqlalchemy import text
        db = create_ecosystem_session()
        try:
            rows = db.execute(text(
                "SELECT section, status, last_synced_at, records_synced FROM sync_status"
            )).fetchall()
            return {
                "sections": [
                    {
                        "section": r.section,
                        "status": r.status,
                        "last_synced_at": str(r.last_synced_at) if r.last_synced_at else None,
                        "records_synced": r.records_synced,
                    }
                    for r in rows
                ]
            }
        finally:
            db.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _sync_background(days: int, full_sync: bool, teams: Optional[list[str]] = None):
    """Background task to sync GitLab metrics, then pre-warm EngineerStats cache."""
    try:
        collector = get_collector()
        collector.sync_all_teams(days=days, full_sync=full_sync, teams=teams)
    except Exception as e:
        logger.error(f"Background sync error: {e}")

    gitlab_settings = get_gitlab_settings()
    gitlab_token = gitlab_settings["token"]
    gitlab_url = gitlab_settings["url"]
    if gitlab_token:
        try:
            _preload_engineer_stats(gitlab_url, gitlab_token)
        except Exception as e:
            logger.error(f"Engineer stats preload error: {e}")


@router.post("/sync", response_model=AllTeamsSyncResponse)
async def sync_all_teams(
    background_tasks: BackgroundTasks,
    days: int = Query(default=30, ge=1, le=365, description="Max days to sync"),
    full_sync: bool = Query(default=False, description="Force full sync instead of incremental"),
    background: bool = Query(default=True, description="Run sync in background"),
):
    """
    Sync GitLab metrics for all teams.

    By default, performs incremental sync (only fetches data since last sync).
    Use full_sync=true to re-fetch all historical data.

    Args:
        days: Maximum days of history (for full/initial sync)
        full_sync: If True, ignores last sync date and fetches all days
        background: If True, returns immediately and syncs in background
    """
    try:
        collector = get_collector()

        if background:
            background_tasks.add_task(_sync_background, days, full_sync)
            return AllTeamsSyncResponse(
                results={},
                stats={
                    "status": "sync_started",
                    "teams_queued": len(TEAM_GITLAB_PATHS),
                    "mode": "full" if full_sync else "incremental",
                },
                synced_at=datetime.now(timezone.utc).isoformat()
            )

        results = collector.sync_all_teams(days=days, full_sync=full_sync)

        # Convert to response format
        result_responses = {}
        for team, result in results.get("results", {}).items():
            result_responses[team] = SyncResultResponse(**result)

        return AllTeamsSyncResponse(
            results=result_responses,
            stats=results.get("stats", {}),
            synced_at=results.get("synced_at", datetime.now(timezone.utc).isoformat())
        )
    except GitLabCollectorError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync/{team}", response_model=SyncResultResponse)
async def sync_team(
    team: str,
    background_tasks: BackgroundTasks,
    days: int = Query(default=30, ge=1, le=365, description="Max days to sync"),
    full_sync: bool = Query(default=False, description="Force full sync"),
    background: bool = Query(default=True, description="Run in background"),
):
    """
    Sync GitLab metrics for a specific team.

    Args:
        team: Team slug (e.g., "platform", "integrations")
        days: Maximum days of history
        full_sync: If True, ignores last sync date
        background: If True, returns immediately
    """
    # Validate team exists
    if team not in TEAM_GITLAB_PATHS:
        raise HTTPException(status_code=404, detail=f"Team not found: {team}")

    try:
        collector = get_collector()

        if background:
            background_tasks.add_task(
                _sync_background, days, full_sync, [team]
            )
            return SyncResultResponse(
                team=team,
                status="sync_started"
            )

        result = collector.sync_team(
            team=team,
            gitlab_paths=TEAM_GITLAB_PATHS[team],
            days=days,
            full_sync=full_sync
        )

        return SyncResultResponse(**result)
    except GitLabCollectorError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/metrics")
async def get_all_metrics(
    days: int = Query(default=30, ge=1, le=365, description="Period in days"),
    sync_first: bool = Query(default=False, description="Sync from GitLab before returning"),
):
    """
    Get aggregated DORA metrics for all teams.

    Returns metrics calculated from PA's native GitLabMetrics table.
    Pass sync_first=true to refresh data from GitLab before reading.
    """
    try:
        if sync_first:
            collector = get_collector()
            collector.sync_all_teams(days=days)
        dora_service = get_dora_service()
        return dora_service.get_teams_comparison(days=days)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _count_team_mrs(db, since, members_cache=None, until=None):
    """Count MRs per team in [since, until) window. Returns dict[team_slug, count]."""
    from sqlalchemy import func as sqlfunc
    from backend.models_domain import MRActivity, RefMember

    query = (
        db.query(
            sqlfunc.lower(MRActivity.author_username).label("username_lower"),
            sqlfunc.count().label("mrs_opened"),
        )
        .filter(MRActivity.created_at >= since)
    )
    if until is not None:
        query = query.filter(MRActivity.created_at < until)
    rows = query.group_by(sqlfunc.lower(MRActivity.author_username)).all()

    if members_cache is None:
        members_cache = {}
        for m in db.query(RefMember).all():
            members_cache[m.gitlab_username.lower()] = m.team_slug

    team_mrs: dict = {}
    for row in rows:
        team_slug = members_cache.get(row.username_lower)
        if not team_slug:
            continue
        team_mrs[team_slug] = team_mrs.get(team_slug, 0) + row.mrs_opened
    return team_mrs, members_cache


@router.get("/team-summary")
async def get_team_summary(
    days: int = Query(default=30, ge=1, le=365),
    compare: bool = Query(default=False, description="Include period-over-period comparison"),
    db: Session = Depends(get_ecosystem_session),
):
    """
    Per-team MR activity counts from ecosystem.db, filtered by period.
    When compare=true, also returns deltas vs the previous equivalent period.
    """
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)

    team_mrs, members_cache = _count_team_mrs(db, since)
    result: dict = {"teams": team_mrs, "period_days": days}

    if compare:
        prev_since = since - timedelta(days=days)
        prev_mrs, _ = _count_team_mrs(db, prev_since, members_cache, until=since)

        # Build deltas for all teams that appear in either period
        all_teams = set(team_mrs.keys()) | set(prev_mrs.keys())
        deltas = {}
        for slug in all_teams:
            current = team_mrs.get(slug, 0)
            previous = prev_mrs.get(slug, 0)
            delta = current - previous
            pct = round(delta / previous * 100, 1) if previous > 0 else None
            deltas[slug] = {
                "current": current,
                "previous": previous,
                "delta": delta,
                "pct_change": pct,
            }
        result["deltas"] = deltas

    return result


@router.get("/team-trend")
async def get_team_trend(
    team: str = Query(..., description="Team slug"),
    days: int = Query(default=90, ge=7, le=365),
    db: Session = Depends(get_ecosystem_session),
):
    """
    Per-team MR counts bucketed by week for sparkline rendering.
    Returns [{date, mrs}] with one entry per ISO week.
    """
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import func as sqlfunc
    from backend.models_domain import MRActivity, RefMember

    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)

    # Get team member usernames
    members = db.query(RefMember).filter_by(team_slug=team).all()
    if not members:
        return {"team": team, "buckets": []}
    usernames = {m.gitlab_username.lower() for m in members}

    # Query MRs in period for this team's members
    rows = (
        db.query(MRActivity.created_at)
        .filter(
            MRActivity.created_at >= since,
            sqlfunc.lower(MRActivity.author_username).in_(usernames),
        )
        .all()
    )

    # Bucket by ISO week
    from collections import defaultdict
    weekly: dict = defaultdict(int)
    for (created_at,) in rows:
        # Use Monday of the week as bucket key
        dt = created_at
        monday = dt - timedelta(days=dt.weekday())
        weekly[monday.strftime("%Y-%m-%d")] += 1

    # Build sorted list of all weeks in range
    buckets = []
    cursor = since - timedelta(days=since.weekday())  # Start from Monday
    while cursor <= now:
        key = cursor.strftime("%Y-%m-%d")
        buckets.append({"date": key, "mrs": weekly.get(key, 0)})
        cursor += timedelta(weeks=1)

    return {"team": team, "buckets": buckets}


@router.get("/activity")
async def get_merge_request_activity(
    team: str | None = Query(default=None, description="Filter by team slug"),
    engineer: str | None = Query(default=None, description="Filter by engineer username"),
    epic: str | None = Query(default=None, description="Filter by epic or ticket reference"),
    state: str | None = Query(default=None, description="Filter by MR state"),
    days: int = Query(default=30, ge=1, le=365),
    compare: bool = Query(default=False, description="Split results into current and previous windows"),
    limit: int = Query(default=100, ge=1, le=300),
    db: Session = Depends(get_ecosystem_session),
):
    from sqlalchemy import func as sqlfunc, or_
    from backend.models_domain import MRActivity

    from backend.config.gitlab_teams import normalize_team_name

    now = datetime.now(timezone.utc)
    full_window_days = days * 2 if compare else days
    since = utcnow_naive() - timedelta(days=full_window_days)

    query = db.query(MRActivity).filter(MRActivity.created_at >= since)
    normalized_state = None

    if team:
        normalized_team = normalize_team_name(team) or team.strip().lower()
        query = query.filter(sqlfunc.lower(MRActivity.author_team) == normalized_team)
    if engineer:
        query = query.filter(sqlfunc.lower(MRActivity.author_username) == engineer.lower())
    if isinstance(state, str) and state.strip():
        requested_state = state.strip().lower()
        normalized_state = "opened" if requested_state in {"active", "open"} else requested_state
        query = query.filter(sqlfunc.lower(MRActivity.state) == normalized_state)
    if epic:
        pattern = f"%{epic}%"
        query = query.filter(or_(
            MRActivity.epic_keys.ilike(pattern),
            MRActivity.jira_tickets.ilike(pattern),
            MRActivity.source_branch.ilike(pattern),
            MRActivity.title.ilike(pattern),
        ))

    rows = query.order_by(MRActivity.created_at.desc()).limit(limit * (2 if compare else 1)).all()

    def _serialize(mr: MRActivity) -> dict:
        created_at = ensure_utc(mr.created_at)
        merged_at = ensure_utc(mr.merged_at)
        return {
            "id": f"{mr.repo_id}!{mr.mr_iid}",
            "repo_id": mr.repo_id,
            "mr_iid": mr.mr_iid,
            "title": mr.title,
            "author_username": mr.author_username,
            "team": mr.author_team,
            "state": mr.state,
            "source_branch": mr.source_branch,
            "created_at": created_at.isoformat() if created_at else None,
            "merged_at": merged_at.isoformat() if merged_at else None,
            "cycle_time_hours": mr.cycle_time_hours,
            "web_url": mr.web_url,
            "jira_tickets": mr.jira_tickets,
            "epic_keys": mr.epic_keys,
        }

    if compare:
        cutoff = now - timedelta(days=days)
        current = [
            _serialize(mr)
            for mr in rows
            if (created_at := ensure_utc(mr.created_at)) and created_at >= cutoff
        ][:limit]
        previous = [
            _serialize(mr)
            for mr in rows
            if (created_at := ensure_utc(mr.created_at)) and created_at < cutoff
        ][:limit]
        return {
            "filters": {"team": team, "engineer": engineer, "epic": epic, "state": normalized_state, "days": days, "compare": compare},
            "current": current,
            "previous": previous,
            "current_count": len(current),
            "previous_count": len(previous),
        }

    serialized = [_serialize(mr) for mr in rows[:limit]]
    return {
        "filters": {"team": team, "engineer": engineer, "epic": epic, "state": normalized_state, "days": days, "compare": compare},
        "mrs": serialized,
        "count": len(serialized),
    }


@router.get("/metrics/{team}")
async def get_team_metrics(
    team: str,
    days: int = Query(default=30, ge=1, le=365, description="Period in days"),
):
    """
    Get DORA metrics for a specific team.

    Returns metrics from PA's native calculations.
    """
    # Normalize team name
    from backend.config.gitlab_teams import normalize_team_name
    normalized = normalize_team_name(team)

    if not normalized:
        raise HTTPException(status_code=404, detail=f"Team not found: {team}")

    try:
        dora_service = get_dora_service()
        return dora_service.get_metrics(team=normalized, days=days)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/metrics/{team}/timeseries")
async def get_team_timeseries(
    team: str,
    days: int = Query(default=30, ge=1, le=365, description="Period in days"),
):
    """
    Get daily time series data for a team.

    Useful for charting pipeline runs, success rates, lead times over time.
    """
    from backend.config.gitlab_teams import normalize_team_name
    normalized = normalize_team_name(team)

    if not normalized:
        raise HTTPException(status_code=404, detail=f"Team not found: {team}")

    try:
        dora_service = get_dora_service()
        return dora_service.get_timeseries(team=normalized, days=days)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/teams")
async def list_teams():
    """
    List all configured teams.

    Returns team slugs, display names, and GitLab paths.
    """
    teams = []
    for slug, paths in TEAM_GITLAB_PATHS.items():
        teams.append({
            "slug": slug,
            "display_name": TEAM_DISPLAY_NAMES.get(slug, slug),
            "gitlab_paths": paths,
        })
    return {"teams": teams}


# ==================== Repo Scanner Endpoints ====================

def _scan_repos_background(scan_local: bool, teams: Optional[list[str]] = None):
    """Background task to scan GitLab repos."""
    try:
        scanner = get_repo_scanner()
        scanner.scan_all_teams(scan_local=scan_local, teams=teams)
    except Exception as e:
        logger.error(f"Background repo scan error: {e}")


@router.post("/repos/scan", response_model=AllReposScanResponse)
async def scan_all_repos(
    background_tasks: BackgroundTasks,
    scan_local: bool = Query(default=False, description="Scan local clones for deep metadata"),
    background: bool = Query(default=True, description="Run scan in background"),
):
    """
    Scan GitLab repos for all teams.

    Discovers repos via GitLab API and optionally scans local clones
    for framework detection, test presence, and CI configuration.

    Args:
        scan_local: If True, scans local clones (requires repos to be cloned)
        background: If True, returns immediately and scans in background
    """
    try:
        scanner = get_repo_scanner()

        if background:
            background_tasks.add_task(_scan_repos_background, scan_local)
            return AllReposScanResponse(
                results={},
                stats={
                    "status": "scan_started",
                    "teams_queued": len(TEAM_GITLAB_PATHS),
                    "scan_local": scan_local,
                },
                scanned_at=datetime.now(timezone.utc).isoformat()
            )

        results = scanner.scan_all_teams(scan_local=scan_local)

        # Convert to response format
        result_responses = {}
        for team, result in results.get("results", {}).items():
            result_responses[team] = RepoScanResultResponse(**result)

        return AllReposScanResponse(
            results=result_responses,
            stats=results.get("stats", {}),
            scanned_at=results.get("scanned_at", datetime.now(timezone.utc).isoformat())
        )
    except RepoScannerError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/repos/scan/{team}", response_model=RepoScanResultResponse)
async def scan_team_repos(
    team: str,
    background_tasks: BackgroundTasks,
    scan_local: bool = Query(default=False, description="Scan local clones"),
    background: bool = Query(default=True, description="Run in background"),
):
    """
    Scan GitLab repos for a specific team.

    Args:
        team: Team slug (e.g., "platform", "integrations")
        scan_local: If True, scans local clones for deep metadata
        background: If True, returns immediately
    """
    # Validate team exists
    if team not in TEAM_GITLAB_PATHS:
        raise HTTPException(status_code=404, detail=f"Team not found: {team}")

    try:
        scanner = get_repo_scanner()

        if background:
            background_tasks.add_task(
                _scan_repos_background, scan_local, [team]
            )
            return RepoScanResultResponse(
                team=team,
                status="scan_started"
            )

        result = scanner.scan_team(
            team=team,
            gitlab_paths=TEAM_GITLAB_PATHS[team],
            scan_local=scan_local
        )

        return RepoScanResultResponse(**result)
    except RepoScannerError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))




@router.get("/repos/orphaned")
async def list_orphaned_repos(
    team: Optional[str] = Query(default=None, description="Filter by team"),
):
    """
    List repos that appear orphaned (no recent activity, no owner).

    Orphaned repos are candidates for cleanup or archival.
    """
    try:
        scanner = get_repo_scanner()
        repos = scanner.get_orphaned_repos(team=team)
        return {"orphaned_repos": repos, "count": len(repos)}
    except RepoScannerError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))




# ==================== Search & Dependencies Endpoints ====================

@router.get("/search")
async def search_repos(
    q: str = Query(..., min_length=1, description="Search query"),
    team: Optional[str] = Query(default=None, description="Filter by team"),
    language: Optional[str] = Query(default=None, description="Filter by language"),
    include_orphaned: bool = Query(default=False, description="Include orphaned repos"),
    limit: int = Query(default=50, ge=1, le=200, description="Max results"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
):
    """
    Full-text search across repositories.

    Searches repo names, languages, and frameworks.
    """
    try:
        from backend.services.gitlab_intelligence import get_search_service

        service = get_search_service()
        return service.search(
            query=q,
            team=team,
            language=language,
            include_orphaned=include_orphaned,
            limit=limit,
            offset=offset,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dependencies")
async def search_dependencies(
    q: Optional[str] = Query(default=None, description="Package name to search"),
    language: Optional[str] = Query(default=None, description="Filter by language"),
    limit: int = Query(default=50, ge=1, le=200, description="Max results"),
):
    """
    Search for packages/dependencies across repos.

    Returns packages matching the query with usage stats.
    """
    try:
        from backend.services.gitlab_intelligence import get_package_service

        service = get_package_service()

        if q:
            return service.search_packages(query=q, language=language, limit=limit)
        else:
            return service.get_package_stats(language=language, top_n=limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dependencies/{package}")
async def get_package_usage(
    package: str,
    team: Optional[str] = Query(default=None, description="Filter by team"),
):
    """
    Get repos using a specific package.

    Returns list of repos with version information.
    """
    try:
        from backend.services.gitlab_intelligence import get_package_service

        service = get_package_service()
        return service.get_repos_using_package(package=package, team=team)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/languages")
async def get_language_distribution(
    team: Optional[str] = Query(default=None, description="Filter by team"),
    include_orphaned: bool = Query(default=False, description="Include orphaned repos"),
):
    """
    Get distribution of programming languages across repos.
    """
    try:
        from backend.services.gitlab_intelligence import get_search_service

        service = get_search_service()
        return service.get_language_distribution(team=team, include_orphaned=include_orphaned)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/frameworks")
async def get_framework_distribution(
    team: Optional[str] = Query(default=None, description="Filter by team"),
    include_orphaned: bool = Query(default=False, description="Include orphaned repos"),
):
    """
    Get distribution of frameworks across repos.
    """
    try:
        from backend.services.gitlab_intelligence import get_search_service

        service = get_search_service()
        return service.get_framework_distribution(team=team, include_orphaned=include_orphaned)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Security Endpoints ====================

@router.get("/security")
async def get_security_summary(
    sync_first: bool = Query(default=False, description="Refresh from Snyk API before returning"),
):
    """
    Get full security vulnerability summary.

    Returns Snyk vulnerability counts by team with trends.
    Pass sync_first=true to refresh data from Snyk API before reading.
    """
    try:
        from backend.services.snyk_service import get_snyk_service

        service = get_snyk_service()
        if sync_first:
            service.refresh_data()
        return service.get_security_summary()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/security/teams")
async def get_security_by_team():
    """
    Get security metrics grouped by team.

    Sorted by severity (critical first).
    """
    try:
        from backend.services.snyk_service import get_snyk_service

        service = get_snyk_service()
        return service.get_security_by_team()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/security/critical")
async def get_critical_vulnerabilities():
    """
    Get teams with critical vulnerabilities.
    """
    try:
        from backend.services.snyk_service import get_snyk_service

        service = get_snyk_service()
        return service.get_critical_vulns()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/security/high-risk")
async def get_high_risk_teams(
    threshold: int = Query(default=5, ge=1, description="Min critical+high to be high risk"),
):
    """
    Get teams with high security risk.

    Teams with (critical + high) >= threshold are considered high risk.
    """
    try:
        from backend.services.snyk_service import get_snyk_service

        service = get_snyk_service()
        return service.get_high_risk_teams(threshold=threshold)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/security/trend")
async def get_security_trend(
    months: int = Query(default=6, ge=1, le=12, description="Months of history"),
):
    """
    Get security vulnerability trend over time.
    """
    try:
        from backend.services.snyk_service import get_snyk_service

        service = get_snyk_service()
        return service.get_security_trend(months=months)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/security/repos-without-tests")
async def get_repos_without_tests(
    team: Optional[str] = Query(default=None, description="Filter by team"),
    limit: int = Query(default=50, ge=1, le=200, description="Max results"),
):
    """
    Get repos that don't have tests.

    These represent a security/quality risk.
    """
    try:
        from backend.services.gitlab_intelligence import get_search_service

        service = get_search_service()
        return service.get_repos_without_tests(team=team, limit=limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Version Tracking Endpoints ====================

@router.get("/versions")
async def get_version_summary(
    team: Optional[str] = Query(default=None, description="Filter by team"),
):
    """
    Get language and framework version summary.

    Shows version distribution across repos with EOL flags.
    """
    try:
        from backend.services.gitlab_intelligence import get_version_service

        service = get_version_service()
        return service.get_version_summary(team=team)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/versions/languages")
async def get_language_versions(
    language: Optional[str] = Query(default=None, description="Filter by language"),
    team: Optional[str] = Query(default=None, description="Filter by team"),
):
    """
    Get detailed language version distribution.
    """
    try:
        from backend.services.gitlab_intelligence import get_version_service

        service = get_version_service()
        return service.get_language_versions(language=language, team=team)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/versions/frameworks")
async def get_framework_versions(
    framework: Optional[str] = Query(default=None, description="Filter by framework"),
    team: Optional[str] = Query(default=None, description="Filter by team"),
):
    """
    Get detailed framework version distribution.
    """
    try:
        from backend.services.gitlab_intelligence import get_version_service

        service = get_version_service()
        return service.get_framework_versions(framework=framework, team=team)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/versions/eol-risk")
async def get_eol_risk_repos(
    team: Optional[str] = Query(default=None, description="Filter by team"),
    risk_level: Optional[str] = Query(default=None, description="Filter by risk level"),
    limit: int = Query(default=50, ge=1, le=200, description="Max results"),
):
    """
    Get repos with EOL or near-EOL versions.

    Returns repos with language/framework versions that are EOL.
    """
    try:
        from backend.services.gitlab_intelligence import get_version_service

        service = get_version_service()
        return service.get_eol_risk_repos(team=team, risk_level=risk_level, limit=limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/versions/upgrades")
async def get_upgrades_needed(
    team: Optional[str] = Query(default=None, description="Filter by team"),
    limit: int = Query(default=50, ge=1, le=200, description="Max results"),
):
    """
    Get repos that need version upgrades.

    Returns repos where current version != latest version.
    """
    try:
        from backend.services.gitlab_intelligence import get_version_service

        service = get_version_service()
        return service.get_upgrades_needed(team=team, limit=limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Engineer Endpoints ====================

from backend.services.engineer_sync_service import _fetch_commit_count, _fetch_review_count


@router.get("/engineers")
async def list_engineers(
    team: Optional[str] = Query(default=None),
    days: int = Query(default=30, ge=1, le=365),
    compare: bool = Query(default=False, description="Include period-over-period deltas"),
    db: Session = Depends(get_ecosystem_session),
):
    from datetime import datetime, timedelta, timezone
    from collections import defaultdict
    from sqlalchemy import func as sqlfunc
    from backend.models_domain import MRActivity, RefMember

    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)

    # All team members from config (authoritative roster)
    members_query = db.query(RefMember)
    if team:
        members_query = members_query.filter_by(team_slug=team)
    all_members = members_query.all()
    if team and not all_members:
        return {"engineers": [], "count": 0, "period_days": days}

    # Index by lowercase username for fast lookup
    member_by_lower = {m.gitlab_username.lower(): m for m in all_members}
    team_usernames_lower = set(member_by_lower.keys())

    # SQL GROUP BY aggregation — avoids loading all MR rows into memory
    agg_query = (
        db.query(
            sqlfunc.lower(MRActivity.author_username).label("username"),
            sqlfunc.count().label("mrs_opened"),
            sqlfunc.count(MRActivity.merged_at).label("mrs_merged"),
            sqlfunc.max(MRActivity.created_at).label("last_activity"),
        )
        .filter(MRActivity.created_at >= since)
    )
    if team:
        agg_query = agg_query.filter(
            sqlfunc.lower(MRActivity.author_username).in_(team_usernames_lower)
        )
    agg_rows = agg_query.group_by(sqlfunc.lower(MRActivity.author_username)).all()

    authors: dict = {
        row.username: {
            "mrs_opened": row.mrs_opened,
            "mrs_merged": row.mrs_merged,
            "last_activity": row.last_activity,
        }
        for row in agg_rows
    }

    # Build result for all known members (include zero-MR members so nobody disappears)
    results = []
    seen_lower: set = set()
    for lower_username, member in member_by_lower.items():
        if member.departed:
            continue
        stats = authors.get(lower_username, {"mrs_opened": 0, "mrs_merged": 0, "last_activity": None})
        results.append({
            "username": member.gitlab_username,
            "name": member.name,
            "email": member.email,
            "role": member.role,
            "team": member.team_slug,
            "team_display": member.team_display,
            "team_lead": member.em_name,
            "jira_project": member.jira_project,
            "mrs_opened": stats["mrs_opened"],
            "mrs_merged": stats["mrs_merged"],
            "last_activity": stats["last_activity"],
        })
        seen_lower.add(lower_username)

    # If no team filter: also include active non-roster engineers from MR activity
    if not team:
        for lower_username, stats in authors.items():
            if lower_username in seen_lower:
                continue
            member = db.query(RefMember).filter(
                sqlfunc.lower(RefMember.gitlab_username) == lower_username
            ).first()
            if not member or member.departed:
                continue  # skip service accounts / EMs not in roster / departed
            results.append({
                "username": member.gitlab_username,
                "name": member.name,
                "email": member.email,
                "role": member.role,
                "team": member.team_slug,
                "team_display": member.team_display,
                "team_lead": member.em_name,
                "jira_project": member.jira_project,
                "mrs_opened": stats["mrs_opened"],
                "mrs_merged": stats["mrs_merged"],
                "last_activity": stats["last_activity"],
            })

    # Period-over-period deltas
    if compare:
        prev_since = since - timedelta(days=days)
        prev_agg_query = (
            db.query(
                sqlfunc.lower(MRActivity.author_username).label("username"),
                sqlfunc.count().label("mrs_opened"),
            )
            .filter(
                MRActivity.created_at >= prev_since,
                MRActivity.created_at < since,
            )
        )
        if team:
            prev_agg_query = prev_agg_query.filter(
                sqlfunc.lower(MRActivity.author_username).in_(team_usernames_lower)
            )
        prev_agg_rows = prev_agg_query.group_by(sqlfunc.lower(MRActivity.author_username)).all()
        prev_authors: dict = {row.username: row.mrs_opened for row in prev_agg_rows}

        for eng in results:
            previous = prev_authors.get(eng["username"].lower(), 0)
            current = eng["mrs_opened"]
            delta = current - previous
            pct = round(delta / previous * 100, 1) if previous > 0 else None
            eng["delta"] = {"current": current, "previous": previous, "delta": delta, "pct_change": pct}

    results.sort(key=lambda x: -x["mrs_opened"])
    return {"engineers": results, "count": len(results), "period_days": days}


@router.get("/engineers/{username}")
async def get_engineer(
    username: str,
    days: int = Query(default=90, ge=1, le=365),
    db: Session = Depends(get_ecosystem_session),
):
    """
    Fetch engineer detail from ecosystem.db cache (fast).
    Commit and review counts are fetched from GitLab in parallel.
    Use POST /engineers/{username}/sync to refresh the MR cache from GitLab.
    """
    import os
    import asyncio
    from datetime import datetime, timedelta, timezone
    from collections import defaultdict
    from backend.models_domain import RefMember, MRActivity, EngineerStats

    since = datetime.now(timezone.utc) - timedelta(days=days)

    from sqlalchemy import func as sqlfunc

    member = db.query(RefMember).filter(
        sqlfunc.lower(RefMember.gitlab_username) == username.lower()
    ).first()

    # --- Read MRs from ecosystem.db cache (instant) ---
    cached = (
        db.query(MRActivity)
        .filter(
            sqlfunc.lower(MRActivity.author_username) == username.lower(),
            MRActivity.created_at >= since,
        )
        .order_by(MRActivity.created_at.desc())
        .all()
    )
    mr_list = [
        {
            "mr_iid": m.mr_iid,
            "title": m.title,
            "state": m.state,
            "opened_at": m.created_at,
            "merged_at": m.merged_at,
            "gitlab_url": m.web_url,
            "repo_id": m.repo_id,
            "jira_tickets": m.jira_tickets,
        }
        for m in cached
    ]

    # --- Commit + review counts: serve from cache, auto-fetch on first visit ---
    stats_row = db.query(EngineerStats).filter(
        EngineerStats.username == username.lower(),
        EngineerStats.period_days == days,
    ).first()

    if stats_row is None:
        # First visit for this engineer+period — fetch live and cache for next time
        import requests as _req
        gitlab_settings = get_gitlab_settings()
        gitlab_token = gitlab_settings["token"]
        gitlab_url = gitlab_settings["url"]
        since_iso = since.strftime("%Y-%m-%dT%H:%M:%SZ")
        if gitlab_token:
            http = _req.Session()
            http.headers["PRIVATE-TOKEN"] = gitlab_token
            try:
                commit_count, review_count = await asyncio.gather(
                    asyncio.to_thread(_fetch_commit_count, gitlab_url, http, username, since_iso),
                    asyncio.to_thread(_fetch_review_count, gitlab_url, http, username, since_iso),
                )
            finally:
                http.close()
            db.add(EngineerStats(
                username=username.lower(),
                period_days=days,
                commit_count=commit_count,
                review_count=review_count,
            ))
            db.commit()
        else:
            commit_count, review_count = 0, 0
    else:
        commit_count = stats_row.commit_count
        review_count = stats_row.review_count

    # Build daily timeline with separate opened/merged counts
    daily_opened: dict = defaultdict(int)
    daily_merged: dict = defaultdict(int)
    for mr in mr_list:
        dt = mr["opened_at"]
        if dt:
            day = dt.strftime("%Y-%m-%d")
            daily_opened[day] += 1
        if mr["state"] == "merged" and mr["merged_at"]:
            mday = mr["merged_at"].strftime("%Y-%m-%d")
            daily_merged[mday] += 1
    all_dates = sorted(set(daily_opened) | set(daily_merged))
    timeline = [
        {"date": d, "mrs_opened": daily_opened[d], "mrs_merged": daily_merged[d]}
        for d in all_dates
    ]

    mrs_opened = len(mr_list)
    mrs_merged = sum(1 for m in mr_list if m["state"] == "merged")

    return {
        "username": username,
        "name": member.name if member else username,
        "email": member.email if member else None,
        "role": member.role if member else None,
        "team": member.team_slug if member else None,
        "team_display": member.team_display if member else None,
        "team_lead": member.em_name if member else None,
        "jira_project": member.jira_project if member else None,
        "period_days": days,
        "summary": {
            "mrs_opened": mrs_opened,
            "mrs_merged": mrs_merged,
            "commits": commit_count,
            "reviews": review_count,
            "avg_cycle_time_hours": None,
        },
        "timeline": timeline,
        "mrs": mr_list,
    }


@router.post("/engineers/{username}/sync")
async def sync_engineer(
    username: str,
    days: int = Query(default=90, ge=1, le=365),
    db: Session = Depends(get_ecosystem_session),
):
    """
    Re-sync MR activity for a single engineer from GitLab.
    Fetches with scope=all so all projects are covered.
    """
    import asyncio
    import requests as _req
    from datetime import datetime, timedelta, timezone
    from backend.models_domain import RefMember, EngineerStats
    from backend.services.engineer_sync_service import _fetch_mrs, _upsert_mrs, _build_jira_pattern
    from backend.core.config_loader import get_domain_config
    from backend.services.domain_registry import get_active_slug

    member = db.query(RefMember).filter(
        RefMember.gitlab_username.ilike(username)
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail=f"Engineer not found: {username}")

    gitlab_settings = get_gitlab_settings()
    gitlab_token = gitlab_settings["token"]
    gitlab_url = gitlab_settings["url"]
    if not gitlab_token:
        raise HTTPException(status_code=503, detail="GitLab credentials are not configured for the active domain")

    since = datetime.now(timezone.utc) - timedelta(days=days)
    since_iso = since.strftime("%Y-%m-%dT%H:%M:%SZ")

    cfg = get_domain_config(get_active_slug())
    jira_pattern = _build_jira_pattern(cfg.jira_project_keys)

    http = _req.Session()
    http.headers["PRIVATE-TOKEN"] = gitlab_token
    try:
        # Fetch MRs + commit/review counts in parallel (network only)
        mrs, (commit_count, review_count) = await asyncio.gather(
            asyncio.to_thread(_fetch_mrs, gitlab_url, http, member.gitlab_username, since_iso),
            asyncio.gather(
                asyncio.to_thread(_fetch_commit_count, gitlab_url, http, username, since_iso),
                asyncio.to_thread(_fetch_review_count, gitlab_url, http, username, since_iso),
            ),
        )
    finally:
        http.close()

    # Upsert MRs sequentially (DB write)
    mr_count = _upsert_mrs(db, member, mrs, jira_pattern)

    # Upsert engineer_stats cache
    stats_row = db.query(EngineerStats).filter(
        EngineerStats.username == username.lower(),
        EngineerStats.period_days == days,
    ).first()
    if stats_row:
        stats_row.commit_count = commit_count
        stats_row.review_count = review_count
        stats_row.cached_at = datetime.now(timezone.utc)
    else:
        db.add(EngineerStats(
            username=username.lower(),
            period_days=days,
            commit_count=commit_count,
            review_count=review_count,
        ))
    db.commit()

    return {"username": username, "synced": mr_count, "commits": commit_count, "reviews": review_count, "period_days": days}


def _preload_engineer_stats(gitlab_url: str, gitlab_token: str, periods=None):
    """
    Pre-warm EngineerStats cache for all active engineers across all UI periods.

    Fetches commit + review counts in parallel (thread pool), then writes all
    results to the DB in a single session. Called automatically after bulk sync.
    """
    from datetime import datetime, timedelta, timezone
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from backend.database_domain import create_ecosystem_session
    from backend.models_domain import RefMember, EngineerStats

    if periods is None:
        periods = [30, 60, 90]

    session = create_ecosystem_session()
    try:
        members = session.query(RefMember).filter(
            RefMember.departed == False,
        ).all()
        usernames = [m.gitlab_username for m in members]
    finally:
        session.close()

    if not usernames:
        logger.info("EngineerStats preload: no active engineers found")
        return

    now = datetime.now(timezone.utc)
    logger.info(
        f"EngineerStats preload: {len(usernames)} engineers × {len(periods)} periods "
        f"= {len(usernames) * len(periods)} fetches"
    )

    import requests as _req

    def fetch(username: str, days: int):
        since_iso = (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        http = _req.Session()
        http.headers["PRIVATE-TOKEN"] = gitlab_token
        try:
            commits = _fetch_commit_count(gitlab_url, http, username, since_iso)
            reviews = _fetch_review_count(gitlab_url, http, username, since_iso)
        finally:
            http.close()
        return username.lower(), days, commits, reviews

    results: dict = {}
    tasks = [(u, d) for u in usernames for d in periods]

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(fetch, u, d): (u, d) for u, d in tasks}
        done = 0
        for fut in as_completed(futures):
            done += 1
            try:
                lower_username, days, commits, reviews = fut.result()
                results[(lower_username, days)] = (commits, reviews)
            except Exception as exc:
                u, d = futures[fut]
                logger.warning(f"Preload failed for {u}/{d}d: {exc}")
            if done % 20 == 0:
                logger.info(f"EngineerStats preload progress: {done}/{len(tasks)}")

    # Write all results to DB in a single session (avoids concurrent SQLite writes)
    session = create_ecosystem_session()
    try:
        for (lower_username, days), (commits, reviews) in results.items():
            row = session.query(EngineerStats).filter(
                EngineerStats.username == lower_username,
                EngineerStats.period_days == days,
            ).first()
            if row:
                row.commit_count = commits
                row.review_count = reviews
                row.cached_at = now
            else:
                session.add(EngineerStats(
                    username=lower_username,
                    period_days=days,
                    commit_count=commits,
                    review_count=reviews,
                ))
        session.commit()
        logger.info(f"EngineerStats preload complete: {len(results)} entries cached")
    finally:
        session.close()
