"""
Background sync scheduler.

asyncio-based polling loop that checks sync_status.next_sync_at and
triggers syncs when sections go stale. No new dependencies required.

Sync order (dependency-aware):
  1. engineers
  2. team_metrics + dora  (parallel — both depend on mr_activity)
  3. jira_epics
  4. repos + port          (parallel — independent)
"""
import asyncio
import logging
from datetime import date, datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ── Module-level state ────────────────────────────────────────────────────────

_task: Optional[asyncio.Task] = None
_paused = False
_active_syncs: set[str] = set()
_retry_counts: dict[str, int] = {}

# Alert scheduling state
_last_quiet_check: Optional[date] = None
_last_epic_check: Optional[date] = None

MAX_RETRIES = 3
RETRY_BACKOFF_MINUTES = [5, 15, 45]
POLL_INTERVAL_SECONDS = 60


def get_scheduler_state() -> dict:
    """Return current scheduler state for the /schedule endpoint."""
    return {
        "running": _task is not None and not _task.done(),
        "paused": _paused,
        "active_syncs": list(_active_syncs),
        "retry_counts": dict(_retry_counts),
    }


def pause():
    """Pause the scheduler (syncs in flight will complete)."""
    global _paused
    _paused = True
    logger.info("Scheduler paused")


def resume():
    """Resume the scheduler."""
    global _paused
    _paused = False
    logger.info("Scheduler resumed")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_section_due(section: str, period_days: int = 30) -> bool:
    """Check if a section needs syncing based on sync_status table."""
    from backend.database_domain import get_ecosystem_engine
    from backend.models_domain import SyncStatus
    from sqlalchemy.orm import sessionmaker

    engine = get_ecosystem_engine()
    db = sessionmaker(bind=engine)()
    try:
        row = db.query(SyncStatus).filter_by(
            section=section, period_days=period_days
        ).first()
        if not row:
            return True  # Never synced
        if row.status == "syncing":
            return False  # Already running
        if row.last_synced_at is None:
            return True
        now = datetime.utcnow()  # naive UTC to match SQLite's naive datetimes
        if row.next_sync_at and row.next_sync_at < now:
            return True
        return False
    finally:
        db.close()


async def _run_section(section: str, fn, *args) -> bool:
    """Run a single section sync with lock tracking and retry logic."""
    if section in _active_syncs:
        return True  # Already running

    _active_syncs.add(section)
    try:
        await asyncio.to_thread(fn, *args)
        _retry_counts.pop(section, None)
        return True
    except Exception as e:
        retries = _retry_counts.get(section, 0)
        _retry_counts[section] = retries + 1
        if retries < MAX_RETRIES:
            backoff = RETRY_BACKOFF_MINUTES[min(retries, len(RETRY_BACKOFF_MINUTES) - 1)]
            logger.warning(f"Scheduler: {section} failed (attempt {retries + 1}/{MAX_RETRIES}), "
                          f"retry in {backoff}m: {e}")
        else:
            logger.error(f"Scheduler: {section} failed {MAX_RETRIES} times, waiting for next TTL window: {e}")
            _retry_counts.pop(section, None)
        return False
    finally:
        _active_syncs.discard(section)


# ── Alert helpers (run in thread via asyncio.to_thread) ──────────────────────

def _fire_trend_alert():
    from backend.database_domain import create_ecosystem_session
    from backend.services.team_trend_alerts import run_trend_alert
    db = create_ecosystem_session()
    try:
        run_trend_alert(db)
    finally:
        db.close()


def _fire_quiet_engineer_alert():
    from backend.database_domain import create_ecosystem_session
    from backend.services.quiet_engineer_alerts import run_quiet_engineer_alert
    db = create_ecosystem_session()
    try:
        run_quiet_engineer_alert(db)
    finally:
        db.close()


def _fire_epic_health_alert():
    from backend.database_domain import create_ecosystem_session
    from backend.services.jira_epic_health import run_epic_health_alert
    db = create_ecosystem_session()
    try:
        run_epic_health_alert(db)
    finally:
        db.close()


def _run_due_executive_digests():
    from backend.database_domain import create_ecosystem_session
    from backend.services.executive_reporting_service import run_due_digests

    db = create_ecosystem_session()
    try:
        return run_due_digests(db)
    finally:
        db.close()


# ── Main sync cycle ──────────────────────────────────────────────────────────

async def _run_sync_cycle(days: int = 30):
    """Execute one full sync cycle in dependency order."""
    global _last_quiet_check, _last_epic_check

    from backend.services.sync_tasks import (
        sync_engineers, sync_team_metrics, sync_dora, sync_jira_epics,
    )

    # Phase 1: engineers (everything depends on MR data)
    engineer_synced = False
    if _is_section_due("engineers", days):
        engineer_synced = await _run_section("engineers", sync_engineers, days, False, "scheduler")

    # Fire trend alert after successful GitLab sync
    if engineer_synced:
        try:
            await asyncio.to_thread(_fire_trend_alert)
        except Exception as e:
            logger.warning("Post-sync trend alert failed: %s", e)

    if _paused:
        return

    # Phase 2: team_metrics then dora (sequential — both write to same table)
    if _is_section_due("team_metrics", days):
        await _run_section("team_metrics", sync_team_metrics, days, "scheduler")
    if _is_section_due("dora", days):
        await _run_section("dora", sync_dora, days, "scheduler")

    if _paused:
        return

    # Phase 3: jira_epics
    if _is_section_due("jira_epics", 0):
        await _run_section("jira_epics", sync_jira_epics, "scheduler")

    # ── Proactive alerts ─────────────────────────────────────────────────────

    today = datetime.now(timezone.utc).date()

    # Daily: quiet engineer check
    if _last_quiet_check != today:
        try:
            await asyncio.to_thread(_fire_quiet_engineer_alert)
            _last_quiet_check = today
        except Exception as e:
            logger.warning("Quiet engineer alert failed: %s", e)

    # Weekly Monday: epic health check
    if datetime.now(timezone.utc).weekday() == 0 and _last_epic_check != today:
        try:
            await asyncio.to_thread(_fire_epic_health_alert)
            _last_epic_check = today
        except Exception as e:
            logger.warning("Epic health alert failed: %s", e)

    try:
        await asyncio.to_thread(_run_due_executive_digests)
    except Exception as e:
        logger.warning("Executive digest scheduler failed: %s", e)


# ── Initial sync ─────────────────────────────────────────────────────────────

async def run_initial_sync(days: int = 30):
    """Run initial sync for sections that have never been synced."""
    logger.info("Scheduler: running initial sync for never-synced sections")
    await _run_sync_cycle(days)
    logger.info("Scheduler: initial sync complete")


# ── Poll loop ─────────────────────────────────────────────────────────────────

async def _poll_loop():
    """Main scheduler loop — polls every POLL_INTERVAL_SECONDS."""
    logger.info("Scheduler: started (polling every %ds)", POLL_INTERVAL_SECONDS)
    while True:
        try:
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            if _paused:
                continue
            await _run_sync_cycle()
        except asyncio.CancelledError:
            logger.info("Scheduler: shutting down")
            break
        except Exception as e:
            logger.error(f"Scheduler: unexpected error in poll loop: {e}")
            await asyncio.sleep(POLL_INTERVAL_SECONDS)


# ── Start / stop ──────────────────────────────────────────────────────────────

async def _initial_sync_wrapper():
    """Run initial sync in background without blocking server startup."""
    try:
        await run_initial_sync()
    except Exception as e:
        logger.warning(f"Scheduler: initial sync had errors (will retry): {e}")


async def start():
    """Start the background scheduler. Safe to call multiple times."""
    global _task
    if _task and not _task.done():
        return

    # Check if any section has never been synced — run initial sync first
    from backend.database_domain import get_ecosystem_engine
    from backend.models_domain import SyncStatus
    from sqlalchemy.orm import sessionmaker
    from backend.core.config_loader import list_domain_slugs

    if not list_domain_slugs():
        logger.info("Scheduler: no domains configured, skipping initial sync")
    else:
        engine = get_ecosystem_engine()
        db = sessionmaker(bind=engine)()
        try:
            # Only check the default 30d period — idle 60d/90d rows shouldn't block startup
            never_synced = db.query(SyncStatus).filter(
                SyncStatus.last_synced_at.is_(None),
                SyncStatus.period_days.in_([0, 30]),
            ).count()
            has_any = db.query(SyncStatus).filter(
                SyncStatus.period_days.in_([0, 30]),
            ).count()
        finally:
            db.close()

        if has_any == 0 or never_synced > 0:
            # Run initial sync in background — don't block server startup
            asyncio.create_task(_initial_sync_wrapper())

    _task = asyncio.create_task(_poll_loop())
    logger.info("Scheduler: background task created")


async def stop():
    """Stop the background scheduler."""
    global _task
    if _task and not _task.done():
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
    _task = None
    logger.info("Scheduler: stopped")
