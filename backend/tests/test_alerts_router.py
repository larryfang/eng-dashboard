import copy
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(BACKEND) not in sys.path:
    sys.path.insert(1, str(BACKEND))

from backend.database_domain import DomainBase  # noqa: E402
from backend.models_domain import AlertTriageState  # noqa: E402
from backend.routers import alerts_router  # noqa: E402


TEAM_TRENDS = [
    {
        "team_slug": "marketing",
        "team_name": "Marketing",
        "current_mrs": 2,
        "prior_mrs": 5,
        "drop_pct": 60.0,
    }
]

QUIET_ENGINEERS = [
    {
        "team_slug": "marketing",
        "team_name": "Marketing",
        "engineer_username": "jdoe",
        "engineer_name": "Jane Doe",
        "days_since_last_activity": 12,
    }
]

STALLED_EPICS = [
    {
        "team_name": "Platform",
        "project": "PLAT",
        "epic_key": "PLAT-101",
        "epic_name": "Improve onboarding",
        "days_stalled": 15,
        "jira_url": "https://jira.example/browse/PLAT-101",
    }
]


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    DomainBase.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


def _install_alert_sources(monkeypatch):
    monkeypatch.setattr(
        alerts_router,
        "check_team_trends",
        lambda db: copy.deepcopy(TEAM_TRENDS),
    )
    monkeypatch.setattr(
        alerts_router,
        "check_quiet_engineers",
        lambda db: copy.deepcopy(QUIET_ENGINEERS),
    )
    monkeypatch.setattr(
        alerts_router,
        "check_stalled_epics",
        lambda db: copy.deepcopy(STALLED_EPICS),
    )


def test_alerts_summary_merges_persisted_triage(monkeypatch, db_session):
    _install_alert_sources(monkeypatch)
    db_session.add(
        AlertTriageState(
            alert_key="quiet_engineer:jdoe",
            alert_type="quiet_engineer",
            entity_type="engineer",
            entity_key="jdoe",
            status="acknowledged",
            owner="Alice",
            note="Checking in with the manager",
        )
    )
    db_session.commit()

    response = alerts_router.alerts_summary(db=db_session)

    assert response["summary"]["teams_flagged"] == 1
    assert response["summary"]["quiet_engineer_count"] == 1
    assert response["summary"]["stalled_epic_count"] == 1
    assert response["summary"]["open_count"] == 2
    assert response["summary"]["acknowledged_count"] == 1

    alerts_by_key = {alert["alert_key"]: alert for alert in response["alerts"]}
    quiet = alerts_by_key["quiet_engineer:jdoe"]
    assert quiet["status"] == "acknowledged"
    assert quiet["owner"] == "Alice"
    assert quiet["note"] == "Checking in with the manager"
    assert quiet["route"] == "/engineers/jdoe"
    assert quiet["metadata"]["team_slug"] == "marketing"

    stalled = alerts_by_key["stalled_epic:PLAT-101"]
    assert stalled["route_metadata"]["params"]["team"] == "PLAT"
    assert response["quiet_engineers"][0]["alert_key"] == "quiet_engineer:jdoe"
    assert response["team_trends"][0]["alert_key"] == "team_trend:marketing"


def test_update_alert_triage_persists_state(monkeypatch, db_session):
    _install_alert_sources(monkeypatch)

    response = alerts_router.update_alert_triage(
        alerts_router.AlertTriageUpdateRequest(
            alert_key="stalled_epic:PLAT-101",
            status="resolved",
            owner="Program Ops",
            note="Waiting on product decision",
        ),
        db=db_session,
    )

    alert = response["alert"]
    assert alert["alert_key"] == "stalled_epic:PLAT-101"
    assert alert["status"] == "resolved"
    assert alert["owner"] == "Program Ops"
    assert alert["note"] == "Waiting on product decision"
    assert alert["resolved_at"] is not None

    row = db_session.query(AlertTriageState).filter_by(alert_key="stalled_epic:PLAT-101").one()
    assert row.alert_type == "stalled_epic"
    assert row.entity_type == "epic"
    assert row.entity_key == "PLAT-101"
    assert row.status == "resolved"


def test_update_alert_triage_rejects_unknown_alert(monkeypatch, db_session):
    _install_alert_sources(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        alerts_router.update_alert_triage(
            alerts_router.AlertTriageUpdateRequest(
                alert_key="quiet_engineer:missing",
                status="acknowledged",
            ),
            db=db_session,
        )

    assert exc.value.status_code == 404
