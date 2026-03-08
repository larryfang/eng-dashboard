import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(BACKEND) not in sys.path:
    sys.path.insert(1, str(BACKEND))

from backend.services import email_service  # noqa: E402


class StubResponse:
    def __init__(self, ok=True, status_code=200, payload=None, text="ok"):
        self.ok = ok
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


def test_email_service_autoselects_mailgun_and_sends(monkeypatch):
    monkeypatch.setenv("MAILGUN_API_KEY", "key-test")
    monkeypatch.setenv("MAILGUN_DOMAIN", "mg.example.com")
    monkeypatch.setenv("MAILGUN_FROM_EMAIL", "Digest Bot <digest@example.com>")
    monkeypatch.delenv("EMAIL_PROVIDER", raising=False)

    captured = {}

    def fake_post(url, auth, data, timeout):
        captured["url"] = url
        captured["auth"] = auth
        captured["data"] = data
        captured["timeout"] = timeout
        return StubResponse(payload={"id": "mailgun-message-id"})

    monkeypatch.setattr(email_service.requests, "post", fake_post)

    service = email_service.EmailService()
    result = service.send(
        to=["cto@example.com", "vp@example.com"],
        subject="Executive Digest",
        text="Digest body",
        html="<p>Digest body</p>",
        tags=["digest", "executive"],
    )

    assert service.provider_name == "mailgun"
    assert service.is_configured is True
    assert result.success is True
    assert result.message_id == "mailgun-message-id"
    assert captured["url"] == "https://api.mailgun.net/v3/mg.example.com/messages"
    assert captured["auth"] == ("api", "key-test")
    assert ("to", "cto@example.com") in captured["data"]
    assert ("to", "vp@example.com") in captured["data"]
    assert ("o:tag", "digest") in captured["data"]
    assert ("o:tag", "executive") in captured["data"]


def test_mailgun_validation_uses_domain_endpoint(monkeypatch):
    monkeypatch.setenv("MAILGUN_API_KEY", "key-test")
    monkeypatch.setenv("MAILGUN_DOMAIN", "mg.example.com")
    monkeypatch.setenv("MAILGUN_FROM_EMAIL", "Digest Bot <digest@example.com>")

    captured = {}

    def fake_get(url, auth, timeout):
        captured["url"] = url
        captured["auth"] = auth
        captured["timeout"] = timeout
        return StubResponse(payload={"domain": {"name": "mg.example.com"}})

    monkeypatch.setattr(email_service.requests, "get", fake_get)

    result = email_service.MailgunEmailService().validate()

    assert result.success is True
    assert result.message_id == "mg.example.com"
    assert captured["url"] == "https://api.mailgun.net/v3/domains/mg.example.com"
    assert captured["auth"] == ("api", "key-test")


def test_disabled_email_service_reports_missing_configuration(monkeypatch):
    monkeypatch.delenv("EMAIL_PROVIDER", raising=False)
    monkeypatch.delenv("MAILGUN_API_KEY", raising=False)
    monkeypatch.delenv("MAILGUN_DOMAIN", raising=False)
    monkeypatch.delenv("MAILGUN_FROM_EMAIL", raising=False)
    monkeypatch.delenv("GMAIL_EMAIL", raising=False)
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)

    service = email_service.EmailService()
    result = service.send(to="cto@example.com", subject="Digest", text="body")

    assert service.provider_name == "disabled"
    assert service.is_configured is False
    assert result.success is False
    assert "not configured" in (result.error or "").lower()
