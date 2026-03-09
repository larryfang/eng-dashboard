"""Smoke tests — verify the app imports and all routes register without crashing."""

import pytest


def test_app_imports_cleanly():
    from backend.main import app
    assert app is not None


def test_critical_routes_registered():
    from backend.main import app
    routes = {r.path for r in app.routes}
    for path in [
        "/health",
        "/api/gitlab/engineers",
        "/api/gitlab/security",
        "/api/code/engineers",
        "/api/jira/index/epics",
        "/api/providers/capabilities",
        "/api/sync/status",
        "/api/config",
    ]:
        assert path in routes, f"Missing route: {path}"


def test_snyk_service_importable():
    from backend.services.snyk_service import get_snyk_service
    service = get_snyk_service()
    assert hasattr(service, "get_security_summary")
    assert hasattr(service, "get_security_by_team")
    assert hasattr(service, "get_critical_vulns")
    assert hasattr(service, "get_high_risk_teams")
    assert hasattr(service, "get_security_trend")
    assert hasattr(service, "refresh_data")


def test_snyk_service_returns_empty_when_no_data():
    from backend.services.snyk_service import SnykService
    service = SnykService()
    summary = service.get_security_summary()
    assert "summary" in summary
    assert "teams" in summary
    assert summary["summary"]["total_teams"] == 0


def test_provider_factories_importable():
    from backend.services.git_providers.factory import create_provider
    from backend.issue_tracker.factory import create_issue_tracker
    assert callable(create_provider)
    assert callable(create_issue_tracker)
