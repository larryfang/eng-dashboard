import sys
import pytest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(BACKEND) not in sys.path:
    sys.path.insert(1, str(BACKEND))

from backend.database_domain import DomainBase  # noqa: E402
from backend.models_domain import SyncRunHistory  # noqa: E402
from backend.routers import sync_router  # noqa: E402
from backend.services import sync_tasks  # noqa: E402


def _make_db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    DomainBase.metadata.create_all(bind=engine)
    return TestingSessionLocal()


@pytest.mark.asyncio
async def test_start_and_complete_sync_run_records_audit_row():
    db_session = _make_db_session()
    try:
        run = sync_tasks._start_sync_run(db_session, "engineers", 30, "manual")
        sync_tasks.mark_sync_complete(db_session, "engineers", 30, 42, run)

        history = db_session.query(SyncRunHistory).filter_by(section="engineers").one()
        status = await sync_router.get_section_sync_status(section="engineers", days=30, db=db_session)

        assert history.trigger_source == "manual"
        assert history.status == "success"
        assert history.records_synced == 42
        assert history.finished_at is not None
        assert status["status"] == "success"
        assert status["records_synced"] == 42
        assert status["duration_seconds"] is not None
    finally:
        db_session.close()


@pytest.mark.asyncio
async def test_sync_history_endpoint_returns_latest_runs_first():
    db_session = _make_db_session()
    try:
        older = SyncRunHistory(
            section="team_metrics",
            period_days=30,
            trigger_source="scheduler",
            status="success",
            records_synced=12,
            started_at=datetime.now(timezone.utc) - timedelta(hours=3),
            finished_at=datetime.now(timezone.utc) - timedelta(hours=3, minutes=-2),
            duration_seconds=120,
        )
        newer = SyncRunHistory(
            section="team_metrics",
            period_days=30,
            trigger_source="manual",
            status="error",
            records_synced=0,
            error_message="boom",
            started_at=datetime.now(timezone.utc) - timedelta(hours=1),
            finished_at=datetime.now(timezone.utc) - timedelta(hours=1, minutes=-1),
            duration_seconds=60,
        )
        db_session.add_all([older, newer])
        db_session.commit()

        payload = await sync_router.get_sync_history(section="team_metrics", limit=10, db=db_session)

        assert [run["trigger_source"] for run in payload["runs"]] == ["manual", "scheduler"]
        assert payload["runs"][0]["error"] == "boom"
        assert payload["runs"][1]["records_synced"] == 12
    finally:
        db_session.close()
