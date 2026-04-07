"""
Epic health alerts — flags stalled epics with no recent updates.

Primary path: queries the jira_epics table for items not updated within
ALERT_JIRA_STALE_DAYS whose status is not in a terminal state.

Plugin path: when an IssueTrackerPlugin is provided, delegates to
its get_stale_epics() method instead of querying the DB directly.
"""
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy.orm import Session

from backend.models_domain import JiraEpic
from backend.services.datetime_utils import ensure_utc, utcnow_naive

if TYPE_CHECKING:
    from backend.issue_tracker.base import IssueTrackerPlugin

logger = logging.getLogger(__name__)

_DONE_STATUSES = {"Done", "Closed", "Cancelled", "Resolved"}


def _check_stalled_epics_db(db: Session) -> list[dict]:
    """Find stalled epics from the local DB cache (jira_epics table)."""
    stale_days = int(os.getenv("ALERT_JIRA_STALE_DAYS", "7"))
    site_url = os.getenv("ATLASSIAN_SITE_URL", "")
    now = datetime.now(timezone.utc)
    cutoff = utcnow_naive() - timedelta(days=stale_days)

    epics = (
        db.query(JiraEpic)
        .filter(
            JiraEpic.updated_date < cutoff,
            ~JiraEpic.status.in_(_DONE_STATUSES),
        )
        .all()
    )

    stalled = []
    for e in epics:
        days_stalled = stale_days
        updated_date = ensure_utc(e.updated_date)
        if updated_date:
            days_stalled = (now - updated_date).days

        # Prefer the stored URL; fall back to constructing from site_url
        url = e.url or (f"{site_url}/browse/{e.key}" if site_url else "")

        stalled.append({
            "team_name": e.team or "Unknown",
            "project": e.project,
            "epic_key": e.key,
            "epic_name": e.summary or "",
            "days_stalled": days_stalled,
            "url": url,
        })

    return stalled


def _check_stalled_epics_plugin(
    issue_tracker: "IssueTrackerPlugin",
) -> list[dict]:
    """Find stalled epics via the issue tracker plugin."""
    stale_days = int(os.getenv("ALERT_JIRA_STALE_DAYS", "7"))
    stale_epics = issue_tracker.get_stale_epics(team_keys=[], days=stale_days)

    return [
        {
            "team_name": epic.team or "Unknown",
            "project": epic.project,
            "epic_key": epic.key,
            "epic_name": epic.summary or "",
            "days_stalled": epic.days_since_update,
            "url": epic.url,
        }
        for epic in stale_epics
    ]


def check_stalled_epics(
    db: Session,
    issue_tracker: Optional["IssueTrackerPlugin"] = None,
) -> list[dict]:
    """Find epics not updated within ALERT_JIRA_STALE_DAYS.

    When *issue_tracker* is provided, delegates to the plugin's
    ``get_stale_epics()`` method.  Otherwise queries the local
    ``jira_epics`` DB table (the default for scheduled alerts).

    Returns list of dicts with keys:
        team_name, project, epic_key, epic_name, days_stalled, url
    """
    if issue_tracker is not None:
        return _check_stalled_epics_plugin(issue_tracker)
    return _check_stalled_epics_db(db)


def run_epic_health_alert(
    db: Session,
    issue_tracker: Optional["IssueTrackerPlugin"] = None,
) -> list[dict]:
    """Check for stalled epics and return flagged list."""
    return check_stalled_epics(db, issue_tracker=issue_tracker)
