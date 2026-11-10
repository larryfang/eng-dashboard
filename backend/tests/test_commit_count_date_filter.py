"""GitLab `GET /users/:id/events` filters on `after` (a date). `created_after`
is ignored, so every period returned the same all-time commit count (the same
bug was fixed in sinch-pa on 2026-11-10)."""

from __future__ import annotations

from unittest.mock import MagicMock

from backend.services import engineer_sync_service


def _resp(payload):
    r = MagicMock()
    r.json.return_value = payload
    r.raise_for_status.return_value = None
    return r


def test_commit_count_sends_the_date_filter_the_events_api_reads():
    http = MagicMock()
    http.get.side_effect = [_resp([{"id": 5}]), _resp([])]
    engineer_sync_service._fetch_commit_count("https://gl", http, "alice", "2026-10-11T00:00:00Z")
    params = http.get.call_args_list[1].kwargs["params"]
    assert "created_after" not in params
    # `after` is exclusive: the day before `since` keeps the first day in the window.
    assert params["after"] == "2026-10-10"


def test_events_after_date_helper():
    from backend.services.git_providers.gitlab_provider import events_after_date

    assert events_after_date("2026-10-11T00:00:00Z") == "2026-10-10"
    assert events_after_date("2026-03-01T12:30:00Z") == "2026-02-28"
