"""
DORA Metrics Service

Calculates and provides DORA (DevOps Research and Assessment) metrics
for software delivery performance tracking.

Four Key DORA Metrics:
1. Deployment Frequency - How often code is deployed to production
2. Lead Time for Changes - Time from commit to production
3. Change Failure Rate - Percentage of deployments causing failures
4. Time to Restore - Time to recover from production failures

Performance Levels (from DORA research):
- Elite: Multiple deploys/day, <1 hour lead time, <5% failure rate, <1 hour MTTR
- High: Weekly-daily, <1 day lead time, <10% failure rate, <1 day MTTR
- Medium: Monthly-weekly, <1 week lead time, <15% failure rate, <1 day MTTR
- Low: Monthly+, >1 month lead time, >15% failure rate, >1 week MTTR
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.database import GitLabMetrics, DoraMetricsSnapshot, SessionLocal

logger = logging.getLogger(__name__)

# DORA performance level thresholds
DORA_LEVELS = {
    "elite": {"lead_time_hours": 24, "deploy_freq": 1.0, "failure_rate": 5},
    "high": {"lead_time_hours": 168, "deploy_freq": 0.14, "failure_rate": 10},  # 1 week, weekly
    "medium": {"lead_time_hours": 720, "deploy_freq": 0.03, "failure_rate": 15},  # 1 month, monthly
}


class DORAService:
    """
    Service for calculating and querying DORA metrics.

    Data sources:
    - GitLabMetrics table (synced from gitlab-analysis)
    - DoraMetricsSnapshot table (historical snapshots)
    """

    def __init__(self, db: Optional[Session] = None):
        self._db = db

    def _get_db(self) -> Session:
        """Get database session."""
        if self._db:
            return self._db
        return SessionLocal()

    def _close_db(self, db: Session):
        """Close database session if we created it."""
        if db != self._db:
            db.close()

    @staticmethod
    def get_dora_level(
        lead_time_hours: Optional[float],
        deploy_freq: Optional[float],
        failure_rate: Optional[float]
    ) -> str:
        """
        Determine DORA performance level based on metrics.

        Args:
            lead_time_hours: Average lead time for changes in hours
            deploy_freq: Deployments per day
            failure_rate: Failure rate as percentage (0-100)

        Returns:
            Performance level: elite, high, medium, low, or unknown
        """
        if lead_time_hours is None or deploy_freq is None or failure_rate is None:
            return "unknown"

        for level in ["elite", "high", "medium"]:
            thresholds = DORA_LEVELS[level]
            if (
                lead_time_hours <= thresholds["lead_time_hours"]
                and deploy_freq >= thresholds["deploy_freq"]
                and failure_rate <= thresholds["failure_rate"]
            ):
                return level

        return "low"

    @staticmethod
    def compute_trend(
        current: Optional[float],
        previous: Optional[float],
        lower_is_better: bool = False
    ) -> str:
        """
        Compute trend direction.

        Args:
            current: Current period value
            previous: Previous period value
            lower_is_better: True for metrics where lower is better (e.g., lead time)

        Returns:
            Trend: "improving", "stable", or "declining"
        """
        if current is None or previous is None or previous == 0:
            return "stable"

        change_pct = (current - previous) / previous * 100

        if abs(change_pct) < 5:
            return "stable"

        if lower_is_better:
            return "improving" if change_pct < 0 else "declining"
        return "improving" if change_pct > 0 else "declining"

    @staticmethod
    def compute_change_pct(
        current: Optional[float],
        previous: Optional[float]
    ) -> Optional[float]:
        """Compute percentage change between periods."""
        if current is None or previous is None or previous == 0:
            return None
        return round((current - previous) / previous * 100, 1)

    def get_metrics(
        self,
        team: Optional[str] = None,
        days: int = 30
    ) -> dict:
        """
        Get aggregated DORA metrics for a period.

        Args:
            team: Team slug to filter (None for all teams)
            days: Number of days to aggregate

        Returns:
            DORA metrics with current values, previous period, and trends
        """
        db = self._get_db()
        try:
            now = datetime.now(timezone.utc)
            current_start = now - timedelta(days=days)
            previous_start = now - timedelta(days=days * 2)
            previous_end = current_start

            # Build query for current period
            current_query = db.query(
                func.sum(GitLabMetrics.pipeline_runs).label("total_pipelines"),
                func.sum(GitLabMetrics.pipeline_success).label("total_success"),
                func.sum(GitLabMetrics.pipeline_failed).label("total_failed"),
                func.avg(GitLabMetrics.avg_duration_seconds).label("avg_duration"),
                func.sum(GitLabMetrics.merge_requests_merged).label("total_mrs"),
                func.avg(GitLabMetrics.avg_mr_cycle_time_hours).label("avg_lead_time"),
                func.avg(GitLabMetrics.failed_pipeline_recovery_hours).label("avg_recovery_time"),
            ).filter(GitLabMetrics.metric_date >= current_start.date())

            if team:
                current_query = current_query.filter(GitLabMetrics.team == team)

            current = current_query.first()

            # Build query for previous period
            previous_query = db.query(
                func.sum(GitLabMetrics.pipeline_runs).label("total_pipelines"),
                func.sum(GitLabMetrics.pipeline_success).label("total_success"),
                func.sum(GitLabMetrics.pipeline_failed).label("total_failed"),
                func.avg(GitLabMetrics.avg_duration_seconds).label("avg_duration"),
                func.sum(GitLabMetrics.merge_requests_merged).label("total_mrs"),
                func.avg(GitLabMetrics.avg_mr_cycle_time_hours).label("avg_lead_time"),
                func.avg(GitLabMetrics.failed_pipeline_recovery_hours).label("avg_recovery_time"),
            ).filter(
                GitLabMetrics.metric_date >= previous_start.date(),
                GitLabMetrics.metric_date < previous_end.date()
            )

            if team:
                previous_query = previous_query.filter(GitLabMetrics.team == team)

            previous = previous_query.first()

            # Compute derived metrics
            total_pipelines = current.total_pipelines or 0
            total_success = current.total_success or 0
            total_failed = current.total_failed or 0

            success_rate = (total_success / total_pipelines * 100) if total_pipelines > 0 else None
            failure_rate = (total_failed / total_pipelines * 100) if total_pipelines > 0 else None
            deploy_freq = total_success / days if total_success else 0

            # Previous period
            prev_total = previous.total_pipelines or 0
            prev_success = previous.total_success or 0
            prev_failed = previous.total_failed or 0
            prev_success_rate = (prev_success / prev_total * 100) if prev_total > 0 else None
            prev_failure_rate = (prev_failed / prev_total * 100) if prev_total > 0 else None
            prev_deploy_freq = prev_success / days if prev_success else 0

            lead_time = current.avg_lead_time
            prev_lead_time = previous.avg_lead_time

            recovery_time = current.avg_recovery_time
            prev_recovery_time = previous.avg_recovery_time

            avg_duration = current.avg_duration
            prev_duration = previous.avg_duration

            return {
                "period": {
                    "days": days,
                    "start": current_start.strftime("%Y-%m-%d"),
                    "end": now.strftime("%Y-%m-%d"),
                },
                "team": team or "all",
                "leadTime": {
                    "current": round(lead_time, 1) if lead_time else None,
                    "previous": round(prev_lead_time, 1) if prev_lead_time else None,
                    "unit": "hours",
                    "trend": self.compute_trend(lead_time, prev_lead_time, lower_is_better=True),
                    "change": self.compute_change_pct(lead_time, prev_lead_time),
                },
                "deploymentFrequency": {
                    "current": round(deploy_freq, 2),
                    "previous": round(prev_deploy_freq, 2),
                    "unit": "per_day",
                    "trend": self.compute_trend(deploy_freq, prev_deploy_freq),
                    "change": self.compute_change_pct(deploy_freq, prev_deploy_freq),
                },
                "changeFailureRate": {
                    "current": round(failure_rate, 1) if failure_rate else None,
                    "previous": round(prev_failure_rate, 1) if prev_failure_rate else None,
                    "unit": "percent",
                    "trend": self.compute_trend(failure_rate, prev_failure_rate, lower_is_better=True),
                    "change": self.compute_change_pct(failure_rate, prev_failure_rate),
                },
                "timeToRestore": {
                    "current": round(recovery_time, 1) if recovery_time else None,
                    "previous": round(prev_recovery_time, 1) if prev_recovery_time else None,
                    "unit": "hours",
                    "trend": self.compute_trend(recovery_time, prev_recovery_time, lower_is_better=True),
                    "change": self.compute_change_pct(recovery_time, prev_recovery_time),
                },
                "pipelineSuccessRate": {
                    "current": round(success_rate, 1) if success_rate else None,
                    "previous": round(prev_success_rate, 1) if prev_success_rate else None,
                    "unit": "percent",
                    "trend": self.compute_trend(success_rate, prev_success_rate),
                    "change": self.compute_change_pct(success_rate, prev_success_rate),
                },
                "avgPipelineDuration": {
                    "current": round(avg_duration / 60, 1) if avg_duration else None,
                    "previous": round(prev_duration / 60, 1) if prev_duration else None,
                    "unit": "minutes",
                    "trend": self.compute_trend(avg_duration, prev_duration, lower_is_better=True),
                    "change": self.compute_change_pct(avg_duration, prev_duration),
                },
                "doraLevel": self.get_dora_level(lead_time, deploy_freq, failure_rate),
            }

        finally:
            self._close_db(db)

    def get_timeseries(
        self,
        team: Optional[str] = None,
        days: int = 30
    ) -> dict:
        """
        Get daily time series data for charts.

        Args:
            team: Team slug to filter (None for all teams)
            days: Number of days of data

        Returns:
            Time series data with dates and metric arrays
        """
        db = self._get_db()
        try:
            start_date = (datetime.now(timezone.utc) - timedelta(days=days)).date()

            query = db.query(
                GitLabMetrics.metric_date,
                func.sum(GitLabMetrics.pipeline_runs).label("pipeline_runs"),
                func.sum(GitLabMetrics.pipeline_success).label("pipeline_success"),
                func.sum(GitLabMetrics.pipeline_failed).label("pipeline_failed"),
                func.avg(GitLabMetrics.avg_duration_seconds).label("avg_duration"),
                func.sum(GitLabMetrics.merge_requests_merged).label("mrs_merged"),
                func.avg(GitLabMetrics.avg_mr_cycle_time_hours).label("avg_lead_time"),
            ).filter(
                GitLabMetrics.metric_date >= start_date
            ).group_by(
                GitLabMetrics.metric_date
            ).order_by(
                GitLabMetrics.metric_date
            )

            if team:
                query = query.filter(GitLabMetrics.team == team)

            results = query.all()

            dates = []
            series = {
                "pipelineRuns": [],
                "pipelineSuccess": [],
                "pipelineFailed": [],
                "successRate": [],
                "avgDuration": [],
                "mrsMerged": [],
                "leadTime": [],
            }

            for row in results:
                dates.append(row.metric_date.isoformat())

                runs = row.pipeline_runs or 0
                success = row.pipeline_success or 0
                failed = row.pipeline_failed or 0

                series["pipelineRuns"].append(runs)
                series["pipelineSuccess"].append(success)
                series["pipelineFailed"].append(failed)
                series["successRate"].append(
                    round(success / runs * 100, 1) if runs > 0 else None
                )
                series["avgDuration"].append(
                    round(row.avg_duration / 60, 1) if row.avg_duration else None
                )
                series["mrsMerged"].append(row.mrs_merged or 0)
                series["leadTime"].append(
                    round(row.avg_lead_time, 1) if row.avg_lead_time else None
                )

            return {
                "dates": dates,
                "series": series,
                "team": team or "all",
            }

        finally:
            self._close_db(db)

    def get_teams_comparison(self, days: int = 30) -> dict:
        """
        Get per-team metrics for comparison.

        Args:
            days: Period in days

        Returns:
            List of team metrics for comparison table
        """
        db = self._get_db()
        try:
            start_date = (datetime.now(timezone.utc) - timedelta(days=days)).date()

            results = db.query(
                GitLabMetrics.team,
                func.sum(GitLabMetrics.pipeline_runs).label("total_pipelines"),
                func.sum(GitLabMetrics.pipeline_success).label("total_success"),
                func.sum(GitLabMetrics.pipeline_failed).label("total_failed"),
                func.avg(GitLabMetrics.avg_duration_seconds).label("avg_duration"),
                func.sum(GitLabMetrics.merge_requests_merged).label("total_mrs"),
                func.avg(GitLabMetrics.avg_mr_cycle_time_hours).label("avg_lead_time"),
                func.avg(GitLabMetrics.failed_pipeline_recovery_hours).label("avg_recovery_time"),
            ).filter(
                GitLabMetrics.metric_date >= start_date
            ).group_by(
                GitLabMetrics.team
            ).order_by(
                func.sum(GitLabMetrics.pipeline_runs).desc()
            ).all()

            teams = []
            for row in results:
                total = row.total_pipelines or 0
                success = row.total_success or 0
                failed = row.total_failed or 0

                success_rate = (success / total * 100) if total > 0 else None
                failure_rate = (failed / total * 100) if total > 0 else None
                deploy_freq = success / days if success else 0
                lead_time = row.avg_lead_time
                recovery_time = row.avg_recovery_time

                teams.append({
                    "name": row.team,
                    "leadTime": round(lead_time, 1) if lead_time else None,
                    "deployFreq": round(deploy_freq, 2),
                    "failureRate": round(failure_rate, 1) if failure_rate else None,
                    "restoreTime": round(recovery_time, 1) if recovery_time else None,
                    "successRate": round(success_rate, 1) if success_rate else None,
                    "avgDuration": round(row.avg_duration / 60, 1) if row.avg_duration else None,
                    "totalPipelines": total,
                    "totalMRs": row.total_mrs or 0,
                    "level": self.get_dora_level(lead_time, deploy_freq, failure_rate),
                })

            return {"teams": teams, "period": {"days": days}}

        finally:
            self._close_db(db)

    def save_snapshot(
        self,
        team: Optional[str] = None,
        days: int = 30
    ) -> DoraMetricsSnapshot:
        """
        Save current metrics as a snapshot for trend analysis.

        Args:
            team: Team to snapshot (None for all)
            days: Period for metrics calculation

        Returns:
            Created snapshot record
        """
        db = self._get_db()
        try:
            metrics = self.get_metrics(team=team, days=days)

            snapshot = DoraMetricsSnapshot(
                team=team,
                deployment_frequency=metrics["deploymentFrequency"]["current"],
                lead_time_hours=metrics["leadTime"]["current"],
                change_failure_rate=metrics["changeFailureRate"]["current"],
                mttr_hours=metrics["timeToRestore"]["current"],
                metrics_json=str(metrics),
            )

            db.add(snapshot)
            db.commit()
            db.refresh(snapshot)

            return snapshot

        finally:
            self._close_db(db)


# Convenience function
def get_dora_service(db: Optional[Session] = None) -> DORAService:
    """Get a DORA service instance."""
    return DORAService(db)
