"""
Sync control endpoints.

GET  /api/sync/status               - status of all sections
GET  /api/sync/status/{section}     - status of one section
POST /api/sync/{section}?days=30    - trigger real sync for section
GET  /api/sync/schedule             - scheduler state + next run times
POST /api/sync/schedule/pause       - pause the background scheduler
POST /api/sync/schedule/resume      - resume the background scheduler
"""
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.database_domain import get_ecosystem_session
from backend.models_domain import SyncRunHistory, SyncStatus
from backend.services import sync_tasks

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sync", tags=["Sync"])

SECTIONS = ["engineers", "team_metrics", "jira_epics", "repos", "dora"]


def _get_or_create_status(db: Session, section: str, period_days: int) -> SyncStatus:
    row = db.query(SyncStatus).filter_by(section=section, period_days=period_days).first()
    if not row:
        row = SyncStatus(section=section, period_days=period_days, status="idle")
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def _status_dict(row: SyncStatus) -> dict:
    now = datetime.now(timezone.utc).replace(tzinfo=None)  # naive UTC to match SQLite storage
    is_stale = (
        row.last_synced_at is None
        or (row.next_sync_at is not None and row.next_sync_at < now)
    )
    return {
        "section": row.section,
        "period_days": row.period_days,
        "status": row.status,
        "last_synced_at": row.last_synced_at.isoformat() if row.last_synced_at else None,
        "next_sync_at": row.next_sync_at.isoformat() if row.next_sync_at else None,
        "records_synced": row.records_synced,
        "duration_seconds": row.duration_seconds,
        "is_stale": is_stale,
        "error": row.error_message,
    }


# ── Status endpoints ──────────────────────────────────────────────────────────

def _default_status(section: str, period_days: int) -> dict:
    """Return a default idle status dict without touching the DB."""
    return {
        "section": section,
        "period_days": period_days,
        "status": "idle",
        "last_synced_at": None,
        "next_sync_at": None,
        "records_synced": 0,
        "duration_seconds": None,
        "is_stale": True,
        "error": None,
    }


@router.get("/status")
async def get_all_sync_status(db: Session = Depends(get_ecosystem_session)):
    # Batch-load all existing sync status rows in one query
    all_rows = db.query(SyncStatus).all()
    by_key = {(r.section, r.period_days): r for r in all_rows}

    result = {}
    for section in SECTIONS:
        result[section] = {}
        for period in [30, 60, 90]:
            row = by_key.get((section, period))
            result[section][str(period)] = _status_dict(row) if row else _default_status(section, period)
    return result


@router.get("/status/{section}")
async def get_section_sync_status(
    section: str,
    days: int = Query(default=30),
    db: Session = Depends(get_ecosystem_session),
):
    if section not in SECTIONS:
        raise HTTPException(status_code=400, detail=f"Unknown section: {section}")
    row = db.query(SyncStatus).filter_by(section=section, period_days=days).first()
    return _status_dict(row) if row else _default_status(section, days)


# ── Manual sync trigger ───────────────────────────────────────────────────────

@router.post("/{section}")
async def trigger_sync(
    section: str,
    background_tasks: BackgroundTasks,
    days: int = Query(default=30),
    force_full: bool = Query(default=False, description="Clean and rebuild from scratch"),
    db: Session = Depends(get_ecosystem_session),
):
    """Trigger a sync for the given section. Engineers sync fetches from GitLab API."""
    SYNC_HANDLERS = {
        "engineers": lambda: background_tasks.add_task(sync_tasks.sync_engineers, days, force_full, "manual"),
        "jira_epics": lambda: background_tasks.add_task(sync_tasks.sync_jira_epics, "manual"),
        "team_metrics": lambda: background_tasks.add_task(sync_tasks.sync_team_metrics, days, "manual"),
        "dora": lambda: background_tasks.add_task(sync_tasks.sync_dora, days, "manual"),
    }

    handler = SYNC_HANDLERS.get(section)
    if handler is None:
        raise HTTPException(status_code=400, detail=f"Unknown sync section: {section}")

    # Validate section before creating any DB rows
    row = _get_or_create_status(db, section, days)
    row.status = "syncing"
    db.commit()

    handler()

    return {"status": "syncing", "section": section, "period_days": days, "force_full": force_full}


# ── Scheduler control ─────────────────────────────────────────────────────────

@router.get("/schedule")
async def get_sync_schedule(db: Session = Depends(get_ecosystem_session)):
    """Return scheduler state + next run times for each section."""
    from backend.services.scheduler import get_scheduler_state

    state = get_scheduler_state()

    # Enrich with per-section next_sync_at from DB
    sections = {}
    for section in SECTIONS:
        row = _get_or_create_status(db, section, 30)
        sections[section] = {
            **_status_dict(row),
            "is_active": section in state.get("active_syncs", []),
            "retry_count": state.get("retry_counts", {}).get(section, 0),
        }

    return {
        "scheduler": state,
        "sections": sections,
    }


@router.get("/history")
async def get_sync_history(
    section: str | None = Query(default=None),
    limit: int = Query(default=30, ge=1, le=200),
    db: Session = Depends(get_ecosystem_session),
):
    query = db.query(SyncRunHistory)
    if section:
        query = query.filter(SyncRunHistory.section == section)
    rows = query.order_by(SyncRunHistory.started_at.desc()).limit(limit).all()
    return {
        "runs": [
            {
                "id": row.id,
                "section": row.section,
                "period_days": row.period_days,
                "trigger_source": row.trigger_source,
                "status": row.status,
                "records_synced": row.records_synced,
                "error": row.error_message,
                "started_at": row.started_at.isoformat() if row.started_at else None,
                "finished_at": row.finished_at.isoformat() if row.finished_at else None,
                "duration_seconds": row.duration_seconds,
            }
            for row in rows
        ]
    }


@router.post("/schedule/pause")
async def pause_scheduler():
    """Pause the background sync scheduler."""
    from backend.services.scheduler import pause
    pause()
    return {"status": "paused"}


@router.post("/schedule/resume")
async def resume_scheduler():
    """Resume the background sync scheduler."""
    from backend.services.scheduler import resume
    resume()
    return {"status": "running"}
