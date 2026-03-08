"""
Team Metrics Sync Service

Computes per-team daily DORA metrics from mr_activity in ecosystem.db
and upserts into team_metrics table.

Called by sync_router for both 'team_metrics' and 'dora' sections.

Data sources:
  - mr_activity.created_at / merged_at / author_team — from ecosystem.db
  - No external API calls needed

Metrics computed:
  - mrs_merged: count of merged MRs per team per day
  - avg_cycle_time_hours: avg hours from created_at to merged_at
  - deployment_frequency: merged MRs/week (rolling 7-day window ending on metric_date)
  - lead_time_hours: same as avg_cycle_time_hours (proxy until pipeline data available)
  - dora_level: Elite/High/Medium/Low from frequency + lead_time thresholds
"""
import logging
from datetime import datetime, timedelta, timezone, date
from collections import defaultdict
from sqlalchemy import or_
from sqlalchemy.orm import Session
from backend.services.datetime_utils import ensure_utc, utcnow_naive

logger = logging.getLogger(__name__)


def sync_team_metrics(db: Session, days: int) -> int:
    """
    Compute team metrics from mr_activity and upsert into team_metrics.

    Args:
        db: ecosystem.db session
        days: Number of days back to compute

    Returns:
        Number of rows written (upserted).
    """
    from backend.models_domain import MRActivity, TeamMetrics, RefTeam

    since = datetime.now(timezone.utc) - timedelta(days=days)
    since_db = utcnow_naive() - timedelta(days=days)

    rows = (
        db.query(MRActivity)
        .filter(
            or_(
                MRActivity.created_at >= since_db,
                MRActivity.merged_at >= since_db,
            )
        )
        .all()
    )
    logger.info(f"Computing team metrics from {len(rows)} MR rows (days={days})")

    # daily_merged[team][date] = list of cycle_time_hours for merged MRs on that day
    daily_merged: dict = defaultdict(lambda: defaultdict(list))
    daily_opened: dict = defaultdict(lambda: defaultdict(int))

    for r in rows:
        if not r.author_team:
            continue
        created_at = ensure_utc(r.created_at)
        merged_at = ensure_utc(r.merged_at)
        if created_at and created_at >= since:
            daily_opened[r.author_team][created_at.date()] += 1
        if r.state == "merged" and merged_at and merged_at >= since and created_at:
            cycle_hours = (merged_at - created_at).total_seconds() / 3600
            merge_day = merged_at.date()
            daily_merged[r.author_team][merge_day].append(max(0.0, cycle_hours))

    teams = db.query(RefTeam).all()
    team_slugs = [t.slug for t in teams]
    if not team_slugs:
        team_slugs = list(set(daily_merged.keys()) | set(daily_opened.keys()))

    now = datetime.now(timezone.utc)
    written = 0

    for team_slug in team_slugs:
        dates_with_activity: set = set()
        dates_with_activity.update(daily_opened.get(team_slug, {}).keys())
        dates_with_activity.update(daily_merged.get(team_slug, {}).keys())

        if not dates_with_activity:
            dates_with_activity = {datetime.now(timezone.utc).date()}

        for metric_date in dates_with_activity:
            cycle_times = daily_merged.get(team_slug, {}).get(metric_date, [])
            mrs_merged_count = len(cycle_times)
            avg_cycle = (sum(cycle_times) / len(cycle_times)) if cycle_times else None

            # Deployment frequency = total merged MRs in the 7-day window ending on metric_date
            week_start = metric_date - timedelta(days=6)
            deploy_freq = sum(
                len(daily_merged.get(team_slug, {}).get(week_start + timedelta(days=i), []))
                for i in range(7)
            )

            dora = _dora_level(deploy_freq, avg_cycle or 999)

            existing = (
                db.query(TeamMetrics)
                .filter_by(team=team_slug, metric_date=metric_date)
                .first()
            )
            if existing:
                existing.mrs_merged = mrs_merged_count
                existing.avg_cycle_time_hours = avg_cycle
                existing.deployment_frequency = deploy_freq
                existing.lead_time_hours = avg_cycle
                existing.change_failure_rate = None
                existing.mttr_hours = None
                existing.dora_level = dora
                existing.synced_at = now
            else:
                db.add(TeamMetrics(
                    team=team_slug,
                    metric_date=metric_date,
                    mrs_merged=mrs_merged_count,
                    avg_cycle_time_hours=avg_cycle,
                    deployment_frequency=deploy_freq,
                    lead_time_hours=avg_cycle,
                    change_failure_rate=None,
                    mttr_hours=None,
                    dora_level=dora,
                    synced_at=now,
                ))
            written += 1

    db.commit()
    logger.info(f"team_metrics sync complete: {written} rows written")
    return written


def _dora_level(deploy_freq_per_week: float, lead_time_hours: float) -> str:
    """
    Classify DORA level from deployment frequency (MRs/week) and lead time.

    Thresholds use MR merge frequency as a deployment proxy:
      Elite:  ≥5/week  AND  lead time < 24h
      High:   ≥1/week  AND  lead time < 168h (7 days)
      Medium: ≥1/month AND  lead time < 720h (30 days)
      Low:    anything worse
    """
    if deploy_freq_per_week >= 5 and lead_time_hours < 24:
        return "Elite"
    if deploy_freq_per_week >= 1 and lead_time_hours < 168:
        return "High"
    if deploy_freq_per_week >= 0.25 and lead_time_hours < 720:
        return "Medium"
    return "Low"
