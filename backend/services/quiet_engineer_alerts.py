"""
Quiet engineer alerts — flags engineers with no MR activity in N days.

Queries ref_members for active, non-excluded engineers and checks mr_activity
for recent work. Engineers without MRs in QUIET_ENGINEER_DAYS are flagged.
"""
import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import func as sqlfunc
from sqlalchemy.orm import Session

from backend.models_domain import MRActivity, RefMember
from backend.services.datetime_utils import ensure_utc
from backend.services.notification_service import get_notifier

logger = logging.getLogger(__name__)


def check_quiet_engineers(db: Session) -> list[dict]:
    """Find active engineers with no recent MR activity.

    Returns list of {team_slug, team_name, engineer_username, engineer_name,
    days_since_last_activity}.
    """
    quiet_days = int(os.getenv("QUIET_ENGINEER_DAYS", "10"))
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=quiet_days)

    # All active, non-excluded members
    members = (
        db.query(RefMember)
        .filter(
            RefMember.departed.is_(False),
            RefMember.exclude_from_metrics.is_(False),
        )
        .all()
    )

    usernames_lower = [m.gitlab_username.lower() for m in members if m.gitlab_username]
    last_activity_rows = (
        db.query(
            sqlfunc.lower(MRActivity.author_username).label("username"),
            sqlfunc.max(MRActivity.created_at).label("last_activity"),
        )
        .filter(sqlfunc.lower(MRActivity.author_username).in_(usernames_lower))
        .group_by(sqlfunc.lower(MRActivity.author_username))
        .all()
        if usernames_lower
        else []
    )
    last_activity_by_username = {
        row.username: row.last_activity for row in last_activity_rows
    }

    quiet = []
    for m in members:
        last_mr = ensure_utc(last_activity_by_username.get(m.gitlab_username.lower()))

        if last_mr is None or last_mr < cutoff:
            days_since = quiet_days  # minimum
            if last_mr:
                days_since = (now - last_mr).days
            quiet.append({
                "team_slug": m.team_slug,
                "team_name": m.team_display or m.team_slug,
                "engineer_name": m.name,
                "engineer_username": m.gitlab_username,
                "days_since_last_activity": days_since,
            })

    return quiet


def run_quiet_engineer_alert(db: Session) -> None:
    """Batch all quiet engineers into one Telegram message."""
    quiet = check_quiet_engineers(db)
    if not quiet:
        return

    quiet_days = os.getenv("QUIET_ENGINEER_DAYS", "10")
    lines = [f"<b>Quiet Engineers ({len(quiet)} with no MRs in {quiet_days}+ days)</b>\n"]

    # Group by team
    by_team: dict[str, list] = {}
    for q in quiet:
        by_team.setdefault(q["team_name"], []).append(q)

    for team, engineers in sorted(by_team.items()):
        lines.append(f"<b>{team}</b>:")
        for e in sorted(engineers, key=lambda x: x["days_since_last_activity"], reverse=True):
            lines.append(f"  - {e['engineer_name']} ({e['days_since_last_activity']}d)")

    get_notifier().send_alert("quiet_engineers", "\n".join(lines))
