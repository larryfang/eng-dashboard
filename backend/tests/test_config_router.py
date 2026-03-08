import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(BACKEND) not in sys.path:
    sys.path.insert(1, str(BACKEND))

from backend.routers import config_router  # noqa: E402
from backend.services.email_service import EmailResult  # noqa: E402


class StubEmailService:
    is_configured = True
    provider_name = "mailgun"
    default_from = "Digest Bot <digest@example.com>"

    def validate(self):
        return EmailResult(success=True, message_id="mg.example.com", provider="mailgun")


@pytest.mark.asyncio
async def test_validate_connections_includes_email_provider(monkeypatch):
    monkeypatch.delenv("JIRA_URL", raising=False)
    monkeypatch.delenv("JIRA_EMAIL", raising=False)
    monkeypatch.delenv("JIRA_API_TOKEN", raising=False)
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    monkeypatch.delenv("PORT_CLIENT_ID", raising=False)
    monkeypatch.delenv("PORT_CLIENT_SECRET", raising=False)
    monkeypatch.setattr("backend.services.email_service.get_email_service", lambda: StubEmailService())

    payload = await config_router.validate_connections()

    assert payload["jira"]["ok"] is False
    assert payload["gitlab"]["ok"] is False
    assert payload["port"] is None
    assert payload["email"] == {
        "ok": True,
        "user": "Digest Bot <digest@example.com>",
        "error": None,
        "provider": "mailgun",
    }
