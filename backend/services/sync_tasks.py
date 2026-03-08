"""
Shared sync task functions.

Used by both manual sync (sync_router.py) and the background scheduler.
Each function creates its own DB session, runs the sync, then marks status.
"""
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import sessionmaker as _sessionmaker

logger = logging.getLogger(__name__)

# ── Sync TTLs (hours) ────────────────────────────────────────────────────────
# How often each section re-syncs. Adjust these to trade freshness vs API load.
SYNC_TTL_HOURS: dict[str, int] = {
    "engineers": 1,       # MR activity — changes frequently
    "team_metrics": 6,    # Aggregated from MR data
    "dora": 6,            # Shares data with team_metrics
    "jira_epics": 2,      # Jira epic cache
    "repos": 24,          # Repo list — rarely changes
}
DEFAULT_TTL_HOURS = 6     # Fallback for unlisted sections


def _get_session():
    """Create a standalone DB session for background work."""
    from backend.database_domain import get_ecosystem_engine
    engine = get_ecosystem_engine()
    return _sessionmaker(bind=engine)()


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _get_or_create_status(db, section: str, period_days: int):
    from backend.models_domain import SyncStatus
    row = db.query(SyncStatus).filter_by(section=section, period_days=period_days).first()
    if not row:
        row = SyncStatus(section=section, period_days=period_days, status="idle")
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def _start_sync_run(db, section: str, period_days: int, trigger_source: str):
    from backend.models_domain import SyncRunHistory

    row = _get_or_create_status(db, section, period_days)
    row.status = "syncing"
    row.error_message = None
    db.commit()

    run = SyncRunHistory(
        section=section,
        period_days=period_days,
        trigger_source=trigger_source,
        status="syncing",
        started_at=datetime.now(timezone.utc),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def mark_sync_complete(db, section: str, period_days: int, records: int, run_history=None) -> None:
    """Mark a section sync as successfully completed."""
    row = _get_or_create_status(db, section, period_days)
    now = datetime.now(timezone.utc)
    ttl = SYNC_TTL_HOURS.get(section, DEFAULT_TTL_HOURS)
    row.status = "success"
    row.last_synced_at = now
    row.next_sync_at = now + timedelta(hours=ttl)
    row.records_synced = records
    row.error_message = None
    if run_history is not None:
        run_history.status = "success"
        run_history.records_synced = records
        run_history.finished_at = now
        started_at = _as_utc(run_history.started_at) or now
        run_history.duration_seconds = max(0.0, (now - started_at).total_seconds())
        row.duration_seconds = run_history.duration_seconds
    db.commit()


def _mark_error(db, section: str, period_days: int, error: str, run_history=None) -> None:
    """Mark a section sync as failed."""
    row = _get_or_create_status(db, section, period_days)
    row.status = "error"
    row.error_message = error
    if run_history is not None:
        now = datetime.now(timezone.utc)
        run_history.status = "error"
        run_history.error_message = error
        run_history.finished_at = now
        started_at = _as_utc(run_history.started_at) or now
        run_history.duration_seconds = max(0.0, (now - started_at).total_seconds())
        row.duration_seconds = run_history.duration_seconds
    try:
        db.commit()
    except Exception:
        pass


def sync_engineers(days: int, force_full: bool = False, trigger_source: str = "manual") -> None:
    """Fetch MRs for all engineers from GitLab and upsert into ecosystem.db."""
    from backend.services.engineer_sync_service import sync_engineers as _do_sync, preload_engineer_stats

    db = _get_session()
    run_history = _start_sync_run(db, "engineers", days, trigger_source)
    try:
        count = _do_sync(db, days, force_full=force_full)
        mark_sync_complete(db, "engineers", days, count, run_history)
        logger.info(f"Engineer sync done: {count} MRs (days={days}, force_full={force_full})")

        for preload_days in sorted({days, 30, 60, 90, 365}):
            stats_count = preload_engineer_stats(db, preload_days)
            logger.info(f"Engineer stats preloaded: {stats_count} engineers (days={preload_days})")
    except Exception as e:
        logger.error(f"Engineer sync failed: {e}")
        _mark_error(db, "engineers", days, str(e), run_history)
        raise
    finally:
        db.close()


def sync_jira_epics(trigger_source: str = "manual") -> None:
    """Fetch Jira epics and upsert into ecosystem.db."""
    from backend.services.jira_epics_sync_service import sync_jira_epics as _do_sync

    db = _get_session()
    run_history = _start_sync_run(db, "jira_epics", 0, trigger_source)
    try:
        count = _do_sync(db)
        mark_sync_complete(db, "jira_epics", 0, count, run_history)
        logger.info(f"Jira epics sync done: {count} epics")
    except Exception as e:
        logger.error(f"Jira epics sync failed: {e}")
        _mark_error(db, "jira_epics", 0, str(e), run_history)
        raise
    finally:
        db.close()


def sync_team_metrics(days: int, trigger_source: str = "manual") -> None:
    """Compute team metrics from mr_activity into ecosystem.db."""
    from backend.services.team_metrics_sync_service import sync_team_metrics as _do_sync

    db = _get_session()
    run_history = _start_sync_run(db, "team_metrics", days, trigger_source)
    try:
        count = _do_sync(db, days)
        mark_sync_complete(db, "team_metrics", days, count, run_history)
        logger.info(f"Team metrics sync done: {count} rows (days={days})")
    except Exception as e:
        logger.error(f"Team metrics sync failed: {e}")
        _mark_error(db, "team_metrics", days, str(e), run_history)
        raise
    finally:
        db.close()


def _sync_domain_dora_metrics(db, days: int) -> int:
    from backend.models_domain import TeamMetrics
    from backend.services.gitlab_intelligence import get_dora_service

    today = datetime.now(timezone.utc).date()
    now = datetime.now(timezone.utc)
    comparison = get_dora_service().get_teams_comparison(days)
    written = 0

    for item in comparison.get("teams", []):
        team = item.get("name")
        if not team:
            continue

        latest = (
            db.query(TeamMetrics)
            .filter(TeamMetrics.team == team)
            .order_by(TeamMetrics.metric_date.desc())
            .first()
        )
        current = (
            db.query(TeamMetrics)
            .filter_by(team=team, metric_date=today)
            .first()
        )

        if current is None:
            current = TeamMetrics(
                team=team,
                metric_date=today,
                mrs_merged=latest.mrs_merged if latest else 0,
                avg_cycle_time_hours=latest.avg_cycle_time_hours if latest else None,
                synced_at=now,
            )
            db.add(current)

        current.deployment_frequency = item.get("deployFreq")
        current.lead_time_hours = item.get("leadTime")
        current.change_failure_rate = item.get("failureRate")
        current.mttr_hours = item.get("restoreTime")
        current.dora_level = str(item.get("level") or "unknown").title()
        current.synced_at = now
        written += 1

    db.commit()
    return written


def sync_dora(days: int, trigger_source: str = "manual") -> None:
    """Persist real DORA aggregates from GitLab metrics into the domain store."""
    db = _get_session()
    run_history = _start_sync_run(db, "dora", days, trigger_source)
    try:
        count = _sync_domain_dora_metrics(db, days)
        mark_sync_complete(db, "dora", days, count, run_history)
        logger.info(f"DORA sync persisted: {count} team rows (days={days})")
    except Exception as e:
        logger.error(f"DORA sync failed: {e}")
        _mark_error(db, "dora", days, str(e), run_history)
        raise
    finally:
        db.close()
