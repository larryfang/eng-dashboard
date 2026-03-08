"""
Jira Indexer Router

API endpoints for Jira issue indexing:
- GET  /api/jira/index/status — sync status + stats from ecosystem.db
- POST /api/jira/index/sync   — trigger manual sync (writes to ecosystem.db)
- GET  /api/jira/index/epics  — list epics from ecosystem.db
- GET  /api/jira/index/epics/{key}/contributors — MR contributor detail
"""

import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/jira/index", tags=["jira-index"])


def get_ecosystem_db():
    from backend.database_domain import create_ecosystem_session
    db = create_ecosystem_session()
    try:
        yield db
    finally:
        db.close()


@router.get("/status")
async def get_status(eco_db: Session = Depends(get_ecosystem_db)):
    """Epic counts by status category from ecosystem.db."""
    try:
        from sqlalchemy import text
        rows = eco_db.execute(text("""
            SELECT status_category, COUNT(*) as cnt
            FROM jira_epics
            GROUP BY status_category
        """)).fetchall()
        total = sum(r.cnt for r in rows)
        by_status = {r.status_category or "Unknown": r.cnt for r in rows}
        return {"total_epics": total, "by_status": by_status}
    except Exception as e:
        logger.error(f"Error getting Jira status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync")
async def trigger_sync(
    background_tasks: BackgroundTasks,
    force_full: bool = Query(False, description="Force full re-sync"),
):
    """
    Sync Jira epics into ecosystem.db (jira_epics + jira_child_epic).
    Delegates to jira_epics_sync_service — same path as POST /api/sync/jira_epics.
    Runs in background.
    """
    try:
        from backend.services.jira_api_service import JiraAPIService
        jira = JiraAPIService()
        if not jira.is_configured:
            raise HTTPException(
                status_code=503,
                detail="Jira credentials are not configured for the active domain",
            )

        def _run_sync():
            from backend.database_domain import create_ecosystem_session
            from backend.services.jira_epics_sync_service import sync_jira_epics
            db = create_ecosystem_session()
            try:
                count = sync_jira_epics(db)
                logger.info(f"Jira sync via /jira/index/sync complete — {count} epics")
            except Exception as exc:
                logger.error(f"Jira sync failed: {exc}", exc_info=True)
            finally:
                db.close()

        background_tasks.add_task(_run_sync)
        return {"status": "started", "message": "Jira epic sync started in background"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting Jira sync: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/epics")
async def list_epics(
    team: Optional[str] = Query(None, description="Filter by team key (e.g. EEH, MA)"),
    status: Optional[str] = Query(None, description="Filter by status category: 'In Progress', 'To Do', 'Done'"),
    limit: int = Query(200, ge=1, le=1000),
    eco_db: Session = Depends(get_ecosystem_db),
):
    """
    List epics from the ecosystem.db jira_epics table.

    Reads from the DB — no live Jira API call. Run POST /api/sync/jira_epics
    to populate. Returns issues grouped-friendly for a kanban view.
    """
    try:
        from sqlalchemy import text

        conditions = []
        params: dict = {"limit": limit}
        if team:
            conditions.append("project = :team")
            params["team"] = team
        if status:
            conditions.append("status_category = :status")
            params["status"] = status

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        rows = eco_db.execute(
            text(f"""
                SELECT key, project, team, summary, status, status_category,
                       priority, assignee, url, progress_percent,
                       child_issues_total, child_issues_done,
                       updated_date, due_date
                FROM jira_epics
                {where}
                ORDER BY updated_date DESC
                LIMIT :limit
            """),
            params,
        ).fetchall()

        epics = [
            {
                "key": r.key,
                "project": r.project,
                "team": r.team,
                "summary": r.summary,
                "status": r.status,
                "status_category": r.status_category,
                "priority": r.priority,
                "assignee": r.assignee,
                "url": r.url,
                "progress_percent": r.progress_percent,
                "child_issues_total": r.child_issues_total,
                "child_issues_done": r.child_issues_done,
                "updated_date": str(r.updated_date) if r.updated_date else None,
                "due_date": str(r.due_date) if r.due_date else None,
            }
            for r in rows
        ]

        return {"epics": epics, "count": len(epics), "team_filter": team}
    except Exception as e:
        logger.error(f"Error listing epics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/epics/{epic_key}/contributors")
async def get_epic_contributors(
    epic_key: str,
    eco_db: Session = Depends(get_ecosystem_db),
):
    """
    Get engineer contributions to a specific epic via linked MRs.

    Searches mr_activity for MRs referencing:
    1. The epic key directly (in epic_keys or jira_tickets)
    2. Any child ticket of this epic (from jira_child_epic mapping)

    Child ticket expansion is the key mechanism — engineers typically use
    child ticket keys (e.g., MA-3281) in their branches, not the epic key itself.
    """
    try:
        from sqlalchemy import text as sqla_text
        from collections import defaultdict
        from backend.models_domain import JiraChildEpic

        # Expand search to child ticket keys so we find MRs that reference
        # child stories/tasks (e.g., MA-3281) rather than the epic (MA-3098)
        child_rows = eco_db.query(JiraChildEpic).filter(
            JiraChildEpic.epic_key == epic_key
        ).all()
        child_keys = [r.child_key for r in child_rows]

        # Build parameterized LIKE conditions for epic + all child tickets
        all_keys = [epic_key] + child_keys
        conditions = []
        params: dict = {}
        for i, key in enumerate(all_keys):
            p = f"p{i}"
            params[p] = f"%{key}%"
            conditions.append(f"(ma.epic_keys LIKE :{p} OR ma.jira_tickets LIKE :{p})")

        where_clause = " OR ".join(conditions)

        rows = eco_db.execute(sqla_text(f"""
            SELECT
                ma.author_username,
                ma.title,
                ma.source_branch,
                ma.state,
                ma.created_at,
                ma.merged_at,
                ma.cycle_time_hours,
                ma.web_url,
                ma.lines_added,
                ma.lines_removed,
                ma.files_changed,
                rm.name      AS author_name,
                rm.team_display,
                rm.team_slug
            FROM mr_activity ma
            LEFT JOIN ref_members rm
                ON LOWER(rm.gitlab_username) = LOWER(ma.author_username)
            WHERE {where_clause}
            ORDER BY ma.created_at DESC
        """), params).fetchall()

        authors: dict = defaultdict(lambda: {
            "mrs": [], "name": None, "team_display": None, "team_slug": None
        })

        for row in rows:
            u = row.author_username
            authors[u]["name"] = row.author_name or row.author_username
            authors[u]["team_display"] = row.team_display or row.team_slug or ""
            authors[u]["team_slug"] = row.team_slug or ""
            def _to_iso(v) -> str | None:
                """Coerce datetime or string to ISO format string."""
                if v is None:
                    return None
                return v if isinstance(v, str) else v.isoformat()

            authors[u]["mrs"].append({
                "title": row.title,
                "branch": row.source_branch,
                "state": row.state,
                "created_at": _to_iso(row.created_at),
                "merged_at": _to_iso(row.merged_at),
                "cycle_time_hours": row.cycle_time_hours,
                "web_url": row.web_url,
                "lines_added": row.lines_added,
                "lines_removed": row.lines_removed,
                "files_changed": row.files_changed,
            })

        from datetime import datetime, timezone

        contributors = []
        for username, data in sorted(authors.items()):
            mrs = data["mrs"]
            merged = [m for m in mrs if m["state"] == "merged"]
            open_mrs = [m for m in mrs if m["state"] == "opened"]
            cycle_times = [m["cycle_time_hours"] for m in merged if m["cycle_time_hours"]]
            branches = sorted({m["branch"] for m in mrs if m["branch"]})

            # Calendar span: first MR created → last activity (merged_at or created_at)
            dates_created = [
                datetime.fromisoformat(m["created_at"].replace("Z", "+00:00"))
                for m in mrs if m["created_at"]
            ]
            dates_ended = [
                datetime.fromisoformat((m["merged_at"] or m["created_at"]).replace("Z", "+00:00"))
                for m in mrs if m["created_at"]
            ]
            calendar_days: float | None = None
            if dates_created and dates_ended:
                span = max(dates_ended) - min(dates_created)
                calendar_days = round(span.total_seconds() / 86400, 1)

            contributors.append({
                "username": username,
                "name": data["name"],
                "team_display": data["team_display"],
                "mr_count": len(mrs),
                "merged_count": len(merged),
                "open_count": len(open_mrs),
                "branches": branches,
                "avg_cycle_hours": round(sum(cycle_times) / len(cycle_times), 1) if cycle_times else None,
                "avg_cycle_days": round(sum(cycle_times) / len(cycle_times) / 24, 1) if cycle_times else None,
                "total_cycle_hours": round(sum(cycle_times), 1) if cycle_times else None,
                "calendar_days": calendar_days,
                "first_activity": min(dates_created).date().isoformat() if dates_created else None,
                "last_activity": max(dates_ended).date().isoformat() if dates_ended else None,
                "mrs": mrs,
            })

        # Sort by most MRs first
        contributors.sort(key=lambda c: c["mr_count"], reverse=True)

        return {
            "epic_key": epic_key,
            "contributors": contributors,
            "mr_count": len(rows),
            "engineer_count": len(contributors),
        }
    except Exception as e:
        logger.error(f"Error getting epic contributors for {epic_key}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

