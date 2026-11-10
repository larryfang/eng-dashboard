"""A Snyk org whose read failed is unknown, not zero (same fix as sinch-pa,
2026-11-10). A timeout on one org wrote 0 critical for its team with
success=True; the next good run then looked like a jump in vulnerabilities."""

from __future__ import annotations

import csv

import pytest
import requests

from backend.services import snyk_service


@pytest.fixture
def svc(monkeypatch, tmp_path):
    monkeypatch.setattr(snyk_service, "_get_token", lambda: "t")
    s = snyk_service.SnykService.__new__(snyk_service.SnykService)
    s.current_report_path = tmp_path / "snyk_severity_report.csv"
    s.timeseries_path = tmp_path / "snyk_monthly_by_team.csv"
    monkeypatch.setattr(s, "_list_orgs", lambda token: [{"id": "1", "name": "org-a"}, {"id": "2", "name": "org-b"}])
    return s


def test_a_failed_org_keeps_its_earlier_counts_and_the_run_is_not_success(svc, monkeypatch):
    monkeypatch.setattr(svc, "_get_severity_counts", lambda token, ids: {"critical": 3, "high": 7, "medium": 1, "low": 0})
    assert svc.refresh_data()["success"] is True

    def flaky(token, ids):
        if ids == ["2"]:
            raise requests.exceptions.ConnectionError("timeout")
        return {"critical": 4, "high": 7, "medium": 1, "low": 0}

    monkeypatch.setattr(svc, "_get_severity_counts", flaky)
    result = svc.refresh_data()

    assert result["success"] is False
    assert "org-b" in result["error"]
    with open(svc.current_report_path) as f:
        rows = {r["org"]: r for r in csv.DictReader(f)}
    assert rows["org-a"]["critical"] == "4"
    assert rows["org-b"]["critical"] == "3"
    with open(svc.timeseries_path) as f:
        month = {r["Team"]: r for r in csv.DictReader(f)}
    assert month["org-b"]["Critical"] == "3"


def test_a_project_error_fails_the_org_instead_of_counting_as_no_issues(svc, monkeypatch):
    monkeypatch.setattr(svc, "_list_projects", lambda token, org_id: ["p1"])
    monkeypatch.setattr(snyk_service.time, "sleep", lambda s: None)

    def boom(method, url, headers, **kwargs):
        resp = requests.Response()
        resp.status_code = 403
        raise requests.exceptions.HTTPError("403", response=resp)

    monkeypatch.setattr(svc, "_snyk_request", boom)
    with pytest.raises(requests.exceptions.HTTPError):
        svc._get_severity_counts("t", ["1"])


def test_total_row_is_the_sum_of_fresh_and_kept_rows(svc, monkeypatch):
    monkeypatch.setattr(svc, "_get_severity_counts", lambda token, ids: {"critical": 3, "high": 7, "medium": 1, "low": 0})
    svc.refresh_data()

    def flaky(token, ids):
        if ids == ["2"]:
            raise requests.exceptions.ConnectionError("timeout")
        return {"critical": 4, "high": 7, "medium": 1, "low": 0}

    monkeypatch.setattr(svc, "_get_severity_counts", flaky)
    result = svc.refresh_data()
    assert result["totals"]["critical"] == 4 + 3  # fresh org-a + kept org-b
    assert result["failed_orgs"] == ["org-b"]


def test_a_failed_org_with_no_earlier_row_is_left_out_not_written_as_zero(svc, monkeypatch):
    def flaky(token, ids):
        if ids == ["2"]:
            raise requests.exceptions.ConnectionError("timeout")
        return {"critical": 4, "high": 7, "medium": 1, "low": 0}

    monkeypatch.setattr(svc, "_get_severity_counts", flaky)
    result = svc.refresh_data()
    assert result["success"] is False and result["failed_orgs"] == ["org-b"]
    import csv as _csv

    path = getattr(svc, "current_report_path", None) or svc._report_path
    with open(path) as f:
        orgs = [r["org"] for r in _csv.DictReader(f)]
    assert "org-b" not in orgs


def test_a_project_that_is_gone_404_is_skipped_and_the_org_still_counts(svc, monkeypatch):
    monkeypatch.setattr(svc, "_list_projects", lambda token, org_id: ["gone", "p2"])
    import time as _t

    monkeypatch.setattr(_t, "sleep", lambda s: None)

    def req(method, url, headers, **kwargs):
        if "/gone/" in url:
            resp = requests.Response()
            resp.status_code = 404
            raise requests.exceptions.HTTPError("404", response=resp)

        class R:
            def json(self):
                return {"issues": [{"issueData": {"severity": "critical"}}]}

        return R()

    monkeypatch.setattr(svc, "_snyk_request", req)
    assert svc._get_severity_counts("t", ["1"])["critical"] == 1


def test_security_endpoint_reports_a_failed_refresh(monkeypatch):
    """`/security?sync_first=true` discarded the refresh result, so a failed
    refresh looked like fresh data."""
    import asyncio

    from backend.routers import gitlab_collector_router as router

    class Fake:
        def refresh_data(self):
            return {"success": False, "error": "Snyk read failed for 1 of 2 orgs: org-b", "failed_orgs": ["org-b"]}

        def get_security_summary(self):
            return {"teams": []}

    monkeypatch.setattr(snyk_service, "get_snyk_service", lambda: Fake())
    out = asyncio.run(router.get_security_summary(sync_first=True))
    assert out["refresh"] == {"success": False, "error": "Snyk read failed for 1 of 2 orgs: org-b", "failed_orgs": ["org-b"]}
    assert "refresh" not in asyncio.run(router.get_security_summary(sync_first=False))
