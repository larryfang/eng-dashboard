"""
Team trend alerts — flags teams with significant week-over-week MR drops.

Compares MR counts from the current 7-day window vs the prior 7-day window
per team. Teams exceeding ALERT_DORA_DEGRADATION_PCT drop get flagged.
"""
import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import func as sqlfunc
from sqlalchemy.orm import Session

from backend.models_domain import MRActivity, RefTeam

logger = logging.getLogger(__name__)


def check_team_trends(db: Session) -> list[dict]:
    """Compare current vs prior week MR counts per team.

    Returns list of {team_slug, team_name, current_mrs, prior_mrs, drop_pct} for teams
    with drop >= ALERT_DORA_DEGRADATION_PCT%.
    """
    threshold = int(os.getenv("ALERT_DORA_DEGRADATION_PCT", "20"))
    now = datetime.now(timezone.utc)
    current_start = now - timedelta(days=7)
    prior_start = now - timedelta(days=14)

    # Current week MR counts by author_team
    current = dict(
        db.query(MRActivity.author_team, sqlfunc.count(MRActivity.id))
        .filter(MRActivity.created_at >= current_start)
        .group_by(MRActivity.author_team)
        .all()
    )

    # Prior week MR counts
    prior = dict(
        db.query(MRActivity.author_team, sqlfunc.count(MRActivity.id))
        .filter(
            MRActivity.created_at >= prior_start,
            MRActivity.created_at < current_start,
        )
        .group_by(MRActivity.author_team)
        .all()
    )

    # Team display names from ref_teams
    teams = {t.slug: t.name for t in db.query(RefTeam).all()}

    flagged = []
    for slug, name in teams.items():
        cur = current.get(slug, 0)
        prev = prior.get(slug, 0)
        if prev == 0:
            continue  # Can't calculate drop percentage from zero
        drop_pct = round((prev - cur) / prev * 100, 1)
        if drop_pct >= threshold:
            flagged.append({
                "team_slug": slug,
                "team_name": name,
                "current_mrs": cur,
                "prior_mrs": prev,
                "drop_pct": drop_pct,
            })

    return flagged


def run_trend_alert(db: Session) -> list[dict]:
    """Check team trends and return flagged teams."""
    return check_team_trends(db)
