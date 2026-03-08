"""
Jira epic health alerts — flags stalled epics with no recent updates.

Queries jira_epics for items not updated within ALERT_JIRA_STALE_DAYS
whose status is not in a terminal state (Done/Closed/Cancelled/Resolved).
"""
import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from backend.models_domain import JiraEpic
from backend.services.datetime_utils import ensure_utc, utcnow_naive
from backend.services.notification_service import get_notifier

logger = logging.getLogger(__name__)

_DONE_STATUSES = {"Done", "Closed", "Cancelled", "Resolved"}


def check_stalled_epics(db: Session) -> list[dict]:
    """Find epics not updated within ALERT_JIRA_STALE_DAYS.

    Returns list of {team_name, project, epic_key, epic_name, days_stalled, jira_url}.
    """
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
        stalled.append({
            "team_name": e.team or "Unknown",
            "project": e.project,
            "epic_key": e.key,
            "epic_name": e.summary or "",
            "days_stalled": days_stalled,
            "jira_url": f"{site_url}/browse/{e.key}",
        })

    return stalled


def run_epic_health_alert(db: Session) -> None:
    """Group stalled epics by team, send single Telegram alert."""
    stalled = check_stalled_epics(db)
    if not stalled:
        return

    stale_days = os.getenv("ALERT_JIRA_STALE_DAYS", "7")
    lines = [
        f"<b>Stalled Epics ({len(stalled)} with no updates in {stale_days}+ days)</b>\n"
    ]

    # Group by team
    by_team: dict[str, list] = {}
    for s in stalled:
        by_team.setdefault(s["team_name"], []).append(s)

    for team, epics in sorted(by_team.items()):
        lines.append(f"<b>{team}</b>:")
        for e in sorted(epics, key=lambda x: x["days_stalled"], reverse=True):
            name = e["epic_name"]
            if len(name) > 50:
                name = name[:50] + "..."
            lines.append(
                f'  - <a href="{e["jira_url"]}">{e["epic_key"]}</a> '
                f"{name} ({e['days_stalled']}d)"
            )

    get_notifier().send_alert("jira_epics", "\n".join(lines))
