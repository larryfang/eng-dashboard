import sys
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
from backend.routers import reports_router  # noqa: E402
from backend.services import executive_reporting_service  # noqa: E402
from backend.services.email_service import EmailResult  # noqa: E402


class StubEmailService:
    def __init__(self):
        self.calls = []
        self.is_configured = True
        self.provider_name = "mailgun"
        self.default_from = "Digest Bot <digest@example.com>"

    def send(self, **kwargs):
        self.calls.append(kwargs)
        return EmailResult(success=True, message_id="queued-123", provider="mailgun")


def _make_db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    DomainBase.metadata.create_all(bind=engine)
    return TestingSessionLocal()


def test_saved_view_crud_and_report_resolution(monkeypatch):
    db_session = _make_db_session()
    try:
        monkeypatch.setattr(
            reports_router,
            "render_executive_report",
            lambda db, include_pulse=True: {
                "html": "<html>report</html>",
                "markdown": "# report",
                "summary": {"teams": 2, "total_items": 7, "wip_epics": 3, "generated_at": "2026-03-06T00:00:00Z"},
            },
        )

        created = reports_router.create_saved_view(
            reports_router.SavedViewPayload(
                name="Pulse Off",
                config={"include_pulse": False, "format": "html"},
            ),
            db=db_session,
        )
        listing = reports_router.list_saved_views(view_type=None, db=db_session)
        report = reports_router.get_executive_report(view_id=created["id"], include_pulse=None, db=db_session)

        assert listing["views"][0]["name"] == "Pulse Off"
        assert report["config"]["include_pulse"] is False
        assert report["summary"]["teams"] == 2

        removed = reports_router.remove_saved_view(created["id"], db=db_session)
        assert removed == {"deleted": True}
        assert reports_router.list_saved_views(view_type=None, db=db_session)["views"] == []
    finally:
        db_session.close()


def test_run_digest_persists_run_and_uses_configured_email(monkeypatch):
    db_session = _make_db_session()
    try:
        stub_email = StubEmailService()
        monkeypatch.setattr(
            executive_reporting_service,
            "render_executive_report",
            lambda db, include_pulse=True: {
                "html": "<html><body>Digest</body></html>",
                "markdown": "# Digest",
                "summary": {"teams": 1, "total_items": 3, "wip_epics": 1, "generated_at": "2026-03-06T00:00:00Z"},
            },
        )
        monkeypatch.setattr(executive_reporting_service, "get_email_service", lambda: stub_email)

        digest = executive_reporting_service.upsert_digest(
            db_session,
            name="Weekly Executive Digest",
            saved_view_id=None,
            recipients=["cto@example.com", "vp@example.com"],
            include_pulse=True,
            frequency="weekly",
            weekday=0,
            hour_utc=8,
            active=True,
        )

        run = executive_reporting_service.run_digest(db_session, digest)
        listed = reports_router.list_digests(db=db_session)

        assert run.delivery_state == "sent"
        assert run.recipient_count == 2
        assert stub_email.calls[0]["to"] == ["cto@example.com", "vp@example.com"]
        assert stub_email.calls[0]["subject"].startswith("Weekly Executive Digest")
        assert listed["runs"][0]["delivery_state"] == "sent"
        assert listed["digests"][0]["name"] == "Weekly Executive Digest"
        assert listed["digests"][0]["next_run_at"] is not None
    finally:
        db_session.close()
