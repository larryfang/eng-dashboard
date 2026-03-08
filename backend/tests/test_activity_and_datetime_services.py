import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(BACKEND) not in sys.path:
    sys.path.insert(1, str(BACKEND))

from backend.database_domain import DomainBase  # noqa: E402
from backend.models_domain import JiraEpic, MRActivity, RefMember, RefTeam, TeamMetrics  # noqa: E402
from backend.routers import gitlab_collector_router  # noqa: E402
from backend.services.jira_epic_health import check_stalled_epics  # noqa: E402
from backend.services.quiet_engineer_alerts import check_quiet_engineers  # noqa: E402
from backend.services.team_metrics_sync_service import sync_team_metrics  # noqa: E402


def _make_db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    DomainBase.metadata.create_all(bind=engine)
    return testing_session()


def _utc_naive_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@pytest.mark.asyncio
async def test_merge_request_activity_handles_team_alias_and_naive_datetimes():
    db_session = _make_db_session()
    try:
        created_at = _utc_naive_now() - timedelta(days=2)
        merged_at = created_at + timedelta(hours=6)
        db_session.add(
            MRActivity(
                mr_iid=7,
                repo_id="repo-1",
                title="Fix cart flow",
                author_username="alice",
                author_team="platform",
                state="merged",
                created_at=created_at,
                merged_at=merged_at,
                web_url="https://gitlab.example/repo-1/-/merge_requests/7",
            )
        )
        db_session.commit()

        payload = await gitlab_collector_router.get_merge_request_activity(
            team="Platform",
            engineer=None,
            epic=None,
            days=30,
            compare=False,
            limit=20,
            db=db_session,
        )

        assert payload["count"] == 1
        assert payload["mrs"][0]["team"] == "platform"
        assert payload["mrs"][0]["created_at"].endswith("+00:00")
    finally:
        db_session.close()


@pytest.mark.asyncio
async def test_merge_request_activity_filters_active_state():
    db_session = _make_db_session()
    try:
        now = _utc_naive_now()
        db_session.add_all([
            MRActivity(
                mr_iid=21,
                repo_id="repo-4",
                title="Keep checkout open",
                author_username="alice",
                author_team="platform",
                state="opened",
                created_at=now - timedelta(days=1),
                web_url="https://gitlab.example/repo-4/-/merge_requests/21",
            ),
            MRActivity(
                mr_iid=22,
                repo_id="repo-4",
                title="Already merged",
                author_username="alice",
                author_team="platform",
                state="merged",
                created_at=now - timedelta(days=2),
                merged_at=now - timedelta(days=1),
                web_url="https://gitlab.example/repo-4/-/merge_requests/22",
            ),
        ])
        db_session.commit()

        payload = await gitlab_collector_router.get_merge_request_activity(
            team="Platform",
            engineer=None,
            epic=None,
            state="active",
            days=30,
            compare=False,
            limit=20,
            db=db_session,
        )

        assert payload["count"] == 1
        assert payload["filters"]["state"] == "opened"
        assert payload["mrs"][0]["state"] == "opened"
        assert payload["mrs"][0]["mr_iid"] == 21
    finally:
        db_session.close()


def test_sync_team_metrics_handles_naive_sqlite_datetimes():
    db_session = _make_db_session()
    try:
        created_at = _utc_naive_now() - timedelta(days=1, hours=3)
        merged_at = created_at + timedelta(hours=5)
        db_session.add(RefTeam(key="PLAT", slug="platform", name="Platform"))
        db_session.add(
            MRActivity(
                mr_iid=11,
                repo_id="repo-2",
                title="Add payment retries",
                author_username="bob",
                author_team="platform",
                state="merged",
                created_at=created_at,
                merged_at=merged_at,
                web_url="https://gitlab.example/repo-2/-/merge_requests/11",
            )
        )
        db_session.commit()

        written = sync_team_metrics(db_session, 30)
        rows = db_session.query(TeamMetrics).filter_by(team="platform").all()

        assert written >= 1
        assert rows
        assert rows[0].deployment_frequency is not None
    finally:
        db_session.close()


def test_quiet_engineers_handles_naive_last_activity():
    db_session = _make_db_session()
    try:
        db_session.add(
            RefMember(
                gitlab_username="quiet.dev",
                name="Quiet Dev",
                team_slug="platform",
                team_display="Platform",
                exclude_from_metrics=False,
                departed=False,
            )
        )
        db_session.add(
            MRActivity(
                mr_iid=18,
                repo_id="repo-3",
                title="Old change",
                author_username="quiet.dev",
                author_team="platform",
                state="opened",
                created_at=_utc_naive_now() - timedelta(days=20),
            )
        )
        db_session.commit()

        results = check_quiet_engineers(db_session)

        assert results
        assert results[0]["engineer_username"] == "quiet.dev"
        assert results[0]["days_since_last_activity"] >= 10
    finally:
        db_session.close()


def test_stalled_epics_handles_naive_updated_date():
    db_session = _make_db_session()
    try:
        db_session.add(
            JiraEpic(
                key="PLAT-101",
                project="PLAT",
                team="Platform",
                summary="Checkout refresh",
                status="In Progress",
                updated_date=_utc_naive_now() - timedelta(days=15),
            )
        )
        db_session.commit()

        results = check_stalled_epics(db_session)

        assert results
        assert results[0]["epic_key"] == "PLAT-101"
        assert results[0]["days_stalled"] >= 7
    finally:
        db_session.close()
