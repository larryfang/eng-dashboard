"""
GitLab Collector Service

Collects pipeline and MR metrics directly from GitLab GraphQL API.
Replaces the external gitlab-analysis/scripts/sync_gitlab_metrics.py.

This service:
1. Fetches pipelines and MRs from GitLab for all team groups
2. Computes daily DORA-style metrics
3. Stores directly in PA's GitLabMetrics table
4. Supports incremental sync (only fetches since last sync)

Usage:
    from backend.services.gitlab_intelligence import get_collector

    collector = get_collector()
    results = collector.sync_all_teams(days=30)
"""

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Optional

import requests
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.database import GitLabMetrics, GitLabMRActivity, SessionLocal
from backend.config.gitlab_teams import TEAM_GITLAB_PATHS
from backend.services.domain_credentials import get_gitlab_settings

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 60  # seconds


class GitLabCollectorError(Exception):
    """Raised when GitLab collection fails."""
    pass


class GitLabCollector:
    """
    Collects GitLab metrics directly via GraphQL API.

    Replaces the external gitlab-analysis project's sync_gitlab_metrics.py.
    """

    def __init__(self, db: Optional[Session] = None, gitlab_token: Optional[str] = None, gitlab_url: Optional[str] = None):
        self._db = db
        settings = get_gitlab_settings()
        self.gitlab_url = (gitlab_url or settings["url"] or "https://gitlab.com").rstrip("/")
        self.graphql_url = f"{self.gitlab_url}/api/graphql"
        self.gitlab_token = gitlab_token or settings["token"]
        self._stats = {
            "teams_synced": 0,
            "pipelines_fetched": 0,
            "mrs_fetched": 0,
            "days_synced": 0,
            "errors": [],
        }

    def _get_db(self) -> Session:
        """Get database session."""
        if self._db:
            return self._db
        return SessionLocal()

    def _close_db(self, db: Session):
        """Close database session if we created it."""
        if db != self._db:
            db.close()

    def _graphql_query(self, query: str, variables: Optional[dict] = None) -> dict:
        """Execute a GraphQL query against GitLab."""
        if not self.gitlab_token:
            raise GitLabCollectorError("GitLab credentials are not configured for the active domain")

        headers = {
            "Authorization": f"Bearer {self.gitlab_token}",
            "Content-Type": "application/json",
        }

        try:
            response = requests.post(
                self.graphql_url,
                json={"query": query, "variables": variables or {}},
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            result = response.json()

            if "errors" in result:
                logger.warning(f"GraphQL errors: {result['errors']}")

            return result.get("data", {})

        except requests.exceptions.Timeout:
            raise GitLabCollectorError(f"GitLab API timeout after {REQUEST_TIMEOUT}s")
        except requests.exceptions.RequestException as e:
            raise GitLabCollectorError(f"GitLab API error: {e}")

    def fetch_pipelines(self, group_path: str, since_date: str) -> list[dict]:
        """
        Fetch pipelines for all projects in a group since a given date.

        Args:
            group_path: GitLab group path (e.g., "acme/teams/platform")
            since_date: ISO date string (YYYY-MM-DD)

        Returns:
            List of pipeline dicts with status, duration, timestamps
        """
        query = """
        query($fullPath: ID!, $after: String) {
          group(fullPath: $fullPath) {
            projects(first: 50, after: $after) {
              pageInfo { hasNextPage endCursor }
              nodes {
                fullPath
                pipelines(first: 100) {
                  nodes {
                    id
                    status
                    duration
                    createdAt
                    finishedAt
                    ref
                  }
                }
              }
            }
          }
        }
        """

        all_pipelines = []
        after = None
        since_dt = datetime.fromisoformat(since_date + "T00:00:00+00:00")

        while True:
            data = self._graphql_query(query, {"fullPath": group_path, "after": after})
            group = data.get("group")

            if not group:
                logger.warning(f"Group not found: {group_path}")
                break

            projects = group.get("projects", {})

            for project in projects.get("nodes", []):
                project_path = project.get("fullPath", "")
                pipelines = project.get("pipelines", {}).get("nodes", [])

                for p in pipelines:
                    created = p.get("createdAt")
                    if created:
                        created_dt = self._parse_gitlab_datetime(created)
                        if created_dt and created_dt >= since_dt:
                            all_pipelines.append({
                                "project": project_path,
                                "status": p.get("status"),
                                "duration": p.get("duration"),
                                "created_at": created,
                                "finished_at": p.get("finishedAt"),
                                "ref": p.get("ref"),
                            })

            page_info = projects.get("pageInfo", {})
            if not page_info.get("hasNextPage"):
                break
            after = page_info.get("endCursor")

        self._stats["pipelines_fetched"] += len(all_pipelines)
        return all_pipelines

    def fetch_merge_requests(self, group_path: str, since_date: str) -> list[dict]:
        """
        Fetch merged MRs for a group since a given date.

        Args:
            group_path: GitLab group path
            since_date: ISO date string (YYYY-MM-DD)

        Returns:
            List of MR dicts with timestamps and project info
        """
        query = """
        query($fullPath: ID!, $after: String) {
          group(fullPath: $fullPath) {
            mergeRequests(state: merged, first: 100, after: $after) {
              pageInfo { hasNextPage endCursor }
              nodes {
                iid
                title
                description
                sourceBranch
                state
                webUrl
                createdAt
                mergedAt
                author { username }
                project { fullPath }
                diffStatsSummary { additions deletions fileCount }
              }
            }
          }
        }
        """

        all_mrs = []
        after = None
        since_dt = datetime.fromisoformat(since_date + "T00:00:00+00:00")

        while True:
            data = self._graphql_query(query, {"fullPath": group_path, "after": after})
            group = data.get("group")

            if not group:
                break

            mrs = group.get("mergeRequests", {})

            for mr in mrs.get("nodes", []):
                merged = mr.get("mergedAt")
                if merged:
                    merged_dt = self._parse_gitlab_datetime(merged)
                    if merged_dt and merged_dt >= since_dt:
                        diff_stats = mr.get("diffStatsSummary") or {}
                        all_mrs.append({
                            "iid": mr.get("iid"),
                            "title": mr.get("title"),
                            "description": mr.get("description"),
                            "source_branch": mr.get("sourceBranch"),
                            "state": mr.get("state"),
                            "web_url": mr.get("webUrl"),
                            "author_username": (mr.get("author") or {}).get("username", "unknown"),
                            "created_at": mr.get("createdAt"),
                            "merged_at": merged,
                            "project": mr.get("project", {}).get("fullPath", ""),
                            "lines_added": diff_stats.get("additions"),
                            "lines_removed": diff_stats.get("deletions"),
                            "files_changed": diff_stats.get("fileCount"),
                        })

            page_info = mrs.get("pageInfo", {})
            if not page_info.get("hasNextPage"):
                break
            after = page_info.get("endCursor")

        self._stats["mrs_fetched"] += len(all_mrs)
        return all_mrs

    @staticmethod
    def _parse_gitlab_datetime(dt_str: str) -> Optional[datetime]:
        """Parse GitLab datetime string to timezone-aware datetime."""
        if not dt_str:
            return None
        dt_str = dt_str.replace("Z", "+00:00")
        return datetime.fromisoformat(dt_str)

    @staticmethod
    def _extract_jira_tickets(branch: Optional[str], title: Optional[str], description: Optional[str]) -> list[str]:
        """
        Extract Jira ticket keys from MR branch, title, and description.

        Recognizes common patterns like:
        - PLAT-123, INT-456 (standard Jira keys)
        - feature/PLAT-123-description (branch names)
        """
        # Known Jira project prefixes — auto-populated from organization.yaml
        project_patterns = [
            "PLAT",
            "INT",
            "NS",
            "SF",
            "SMTHZ",  # Zoho (Zoho Zebras)
            "WFP",    # Contact Sync (Gravity)
            "NEXT",   # Connectors
            "PD",     # Partnership/AI
        ]

        pattern = r'\b(' + '|'.join(project_patterns) + r')-(\d+)\b'
        tickets = set()

        for text in [branch, title, description]:
            if text:
                matches = re.findall(pattern, text, re.IGNORECASE)
                for prefix, number in matches:
                    tickets.add(f"{prefix.upper()}-{number}")

        return sorted(tickets)

    def _compute_daily_metrics(
        self,
        pipelines: list[dict],
        mrs: list[dict],
        date: str
    ) -> dict:
        """
        Compute metrics for a single day.

        Args:
            pipelines: All pipelines in the sync period
            mrs: All MRs in the sync period
            date: The specific date to compute (YYYY-MM-DD)

        Returns:
            Dict with pipeline counts, durations, MR counts, cycle times
        """
        day_start = datetime.fromisoformat(date + "T00:00:00+00:00")
        day_end = day_start + timedelta(days=1)

        # Filter to this day
        day_pipelines = [
            p for p in pipelines
            if (created := self._parse_gitlab_datetime(p["created_at"]))
            and day_start <= created < day_end
        ]

        day_mrs = [
            mr for mr in mrs
            if (merged := self._parse_gitlab_datetime(mr["merged_at"]))
            and day_start <= merged < day_end
        ]

        # Pipeline metrics
        pipeline_runs = len(day_pipelines)
        pipeline_success = len([p for p in day_pipelines if p["status"] == "SUCCESS"])
        pipeline_failed = len([p for p in day_pipelines if p["status"] == "FAILED"])

        durations = [p["duration"] for p in day_pipelines if p["duration"]]
        avg_duration = sum(durations) / len(durations) if durations else None

        # MR metrics
        mrs_merged = len(day_mrs)

        # MR cycle times (created -> merged)
        cycle_times = []
        for mr in day_mrs:
            created = self._parse_gitlab_datetime(mr["created_at"])
            merged = self._parse_gitlab_datetime(mr["merged_at"])
            if created and merged:
                hours = (merged - created).total_seconds() / 3600
                cycle_times.append(hours)

        avg_cycle_time = median(cycle_times) if cycle_times else None

        return {
            "pipeline_runs": pipeline_runs,
            "pipeline_success": pipeline_success,
            "pipeline_failed": pipeline_failed,
            "avg_duration_seconds": avg_duration,
            "merge_requests_merged": mrs_merged,
            "avg_mr_cycle_time_hours": avg_cycle_time,
        }

    def _compute_recovery_times(self, pipelines: list[dict]) -> Optional[float]:
        """
        Compute average time to recover from failed pipelines.

        Measures time between a failed pipeline and the next successful
        pipeline on the same project/ref.

        Returns:
            Median recovery time in hours, or None if no recoveries found
        """
        # Sort pipelines by time
        sorted_pipelines = sorted(
            [p for p in pipelines if p["finished_at"]],
            key=lambda x: x["finished_at"]
        )

        recovery_times = []

        for i, p in enumerate(sorted_pipelines):
            if p["status"] == "FAILED":
                # Find next success for same project/ref
                for j in range(i + 1, len(sorted_pipelines)):
                    next_p = sorted_pipelines[j]
                    if (next_p["project"] == p["project"] and
                        next_p["ref"] == p["ref"] and
                        next_p["status"] == "SUCCESS"):

                        failed_time = self._parse_gitlab_datetime(p["finished_at"])
                        success_time = self._parse_gitlab_datetime(next_p["finished_at"])

                        if failed_time and success_time:
                            hours = (success_time - failed_time).total_seconds() / 3600
                            recovery_times.append(hours)
                        break

        return median(recovery_times) if recovery_times else None

    def _calculate_dora_level(
        self,
        deployment_freq: float,
        lead_time: Optional[float],
        cfr: float,
        mttr: Optional[float]
    ) -> str:
        """
        Calculate DORA performance level based on metrics.

        Based on DORA research thresholds:
        - Elite: Deploy multiple times/day, lead time <1h, CFR <5%, MTTR <1h
        - High: Deploy daily-weekly, lead time <1 day, CFR <10%, MTTR <1 day
        - Medium: Deploy weekly-monthly, lead time <1 week, CFR <15%, MTTR <1 day
        - Low: Deploy monthly+, lead time >1 month, CFR >15%, MTTR >1 week
        """
        score = 0

        # Deployment frequency scoring
        if deployment_freq >= 3:
            score += 4  # Multiple per day
        elif deployment_freq >= 1:
            score += 3  # Daily
        elif deployment_freq >= 0.2:
            score += 2  # Weekly
        else:
            score += 1  # Monthly or less

        # Lead time scoring
        if lead_time is not None:
            if lead_time < 1:
                score += 4
            elif lead_time < 24:
                score += 3
            elif lead_time < 168:  # 1 week
                score += 2
            else:
                score += 1

        # Change failure rate scoring
        if cfr < 0.05:
            score += 4
        elif cfr < 0.10:
            score += 3
        elif cfr < 0.15:
            score += 2
        else:
            score += 1

        # MTTR scoring
        if mttr is not None:
            if mttr < 1:
                score += 4
            elif mttr < 24:
                score += 3
            elif mttr < 168:
                score += 2
            else:
                score += 1

        # Calculate level from average score
        avg_score = score / 4

        if avg_score >= 3.5:
            return "elite"
        elif avg_score >= 2.5:
            return "high"
        elif avg_score >= 1.5:
            return "medium"
        else:
            return "low"

    def get_last_sync_date(self, db: Session, team: str) -> Optional[str]:
        """Get the last sync date for a team from the database."""
        result = db.query(func.max(GitLabMetrics.metric_date)).filter(
            GitLabMetrics.team == team
        ).scalar()

        return result.isoformat() if result else None

    def sync_team(
        self,
        team: str,
        gitlab_paths: list[str],
        days: int = 30,
        full_sync: bool = False,
        db: Optional[Session] = None
    ) -> dict:
        """
        Sync metrics for a single team.

        Args:
            team: Team slug (e.g., "platform", "integrations")
            gitlab_paths: List of GitLab group paths for this team
            days: Maximum days to sync (for full/initial sync)
            full_sync: If True, re-sync all data. If False, incremental.
            db: Optional database session

        Returns:
            Summary dict with sync statistics
        """
        logger.info(f"Syncing {team}...")

        own_session = db is None
        if own_session:
            db = SessionLocal()

        try:
            now = datetime.now(timezone.utc)

            # Determine sync start date
            if full_sync:
                since_date = (now - timedelta(days=days)).strftime("%Y-%m-%d")
                days_to_sync = days
            else:
                last_sync = self.get_last_sync_date(db, team)
                if last_sync:
                    since_date = last_sync
                    # Parse date string - handle both date and datetime formats
                    from datetime import date as date_type
                    last_sync_date = date_type.fromisoformat(last_sync[:10])  # Take first 10 chars (YYYY-MM-DD)
                    days_to_sync = (now.date() - last_sync_date).days + 1
                    if days_to_sync <= 1:
                        logger.info(f"  {team} already synced today, skipping")
                        return {"team": team, "status": "skipped", "reason": "already_synced_today"}
                else:
                    since_date = (now - timedelta(days=days)).strftime("%Y-%m-%d")
                    days_to_sync = days

            # Fetch data from all paths for this team
            all_pipelines = []
            all_mrs = []

            for path in gitlab_paths:
                logger.info(f"  Fetching from {path}...")
                try:
                    pipelines = self.fetch_pipelines(path, since_date)
                    mrs = self.fetch_merge_requests(path, since_date)
                    all_pipelines.extend(pipelines)
                    all_mrs.extend(mrs)
                except GitLabCollectorError as e:
                    logger.error(f"  Error fetching from {path}: {e}")
                    self._stats["errors"].append(f"{team}/{path}: {e}")

            if not all_pipelines and not all_mrs:
                logger.warning(f"  No data found for {team}")
                return {"team": team, "status": "no_data", "pipelines": 0, "mrs": 0}

            # Store MR activity for risk analysis and epic correlation
            mrs_stored = 0
            for mr in all_mrs:
                # Check if MR already exists
                existing_mr = db.query(GitLabMRActivity).filter(
                    GitLabMRActivity.mr_iid == mr["iid"],
                    GitLabMRActivity.repo_id == mr["project"]
                ).first()

                if not existing_mr:
                    # Calculate cycle time (created -> merged)
                    created_dt = self._parse_gitlab_datetime(mr["created_at"])
                    merged_dt = self._parse_gitlab_datetime(mr["merged_at"])
                    cycle_time = None
                    if created_dt and merged_dt:
                        cycle_time = (merged_dt - created_dt).total_seconds() / 3600

                    # Extract Jira tickets from branch/title/description
                    jira_tickets = self._extract_jira_tickets(
                        mr.get("source_branch"),
                        mr.get("title"),
                        mr.get("description")
                    )

                    new_mr = GitLabMRActivity(
                        mr_iid=mr["iid"],
                        repo_id=mr["project"],
                        title=mr["title"],
                        description=mr.get("description"),
                        source_branch=mr.get("source_branch"),
                        author_username=mr.get("author_username", "unknown"),
                        state=mr.get("state", "merged"),
                        created_at=created_dt,
                        merged_at=merged_dt,
                        web_url=mr.get("web_url"),
                        jira_tickets=json.dumps(jira_tickets) if jira_tickets else None,
                        lines_added=mr.get("lines_added"),
                        lines_removed=mr.get("lines_removed"),
                        files_changed=mr.get("files_changed"),
                        cycle_time_hours=cycle_time,
                    )
                    db.add(new_mr)
                    mrs_stored += 1

            if mrs_stored > 0:
                logger.info(f"  Stored {mrs_stored} new MRs in GitLabMRActivity")

            # Compute recovery time across all data
            recovery_time = self._compute_recovery_times(all_pipelines)

            # Compute and store daily metrics
            records_created = 0
            records_updated = 0

            for day_offset in range(days_to_sync):
                metric_date = (now - timedelta(days=day_offset)).date()
                date_str = metric_date.strftime("%Y-%m-%d")
                metrics = self._compute_daily_metrics(all_pipelines, all_mrs, date_str)

                # Add recovery time
                metrics["failed_pipeline_recovery_hours"] = recovery_time

                # Calculate DORA metrics
                deployment_freq = metrics["pipeline_success"]  # Per day
                lead_time = metrics["avg_mr_cycle_time_hours"]
                cfr = 0.0
                if metrics["pipeline_runs"] > 0:
                    cfr = metrics["pipeline_failed"] / metrics["pipeline_runs"]

                dora_level = self._calculate_dora_level(
                    deployment_freq, lead_time, cfr, recovery_time
                )

                # Upsert into database
                existing = db.query(GitLabMetrics).filter(
                    GitLabMetrics.team == team,
                    GitLabMetrics.metric_date == metric_date
                ).first()

                if existing:
                    existing.pipeline_runs = metrics["pipeline_runs"]
                    existing.pipeline_success = metrics["pipeline_success"]
                    existing.pipeline_failed = metrics["pipeline_failed"]
                    existing.avg_duration_seconds = metrics["avg_duration_seconds"]
                    existing.merge_requests_merged = metrics["merge_requests_merged"]
                    existing.avg_mr_cycle_time_hours = metrics["avg_mr_cycle_time_hours"]
                    existing.failed_pipeline_recovery_hours = metrics["failed_pipeline_recovery_hours"]
                    existing.deployment_frequency = deployment_freq
                    existing.lead_time_hours = lead_time
                    existing.change_failure_rate = cfr
                    existing.mttr_hours = recovery_time
                    existing.dora_level = dora_level
                    existing.synced_at = now
                    records_updated += 1
                else:
                    new_metric = GitLabMetrics(
                        team=team,
                        metric_date=metric_date,
                        pipeline_runs=metrics["pipeline_runs"],
                        pipeline_success=metrics["pipeline_success"],
                        pipeline_failed=metrics["pipeline_failed"],
                        avg_duration_seconds=metrics["avg_duration_seconds"],
                        merge_requests_merged=metrics["merge_requests_merged"],
                        avg_mr_cycle_time_hours=metrics["avg_mr_cycle_time_hours"],
                        failed_pipeline_recovery_hours=metrics["failed_pipeline_recovery_hours"],
                        deployment_frequency=deployment_freq,
                        lead_time_hours=lead_time,
                        change_failure_rate=cfr,
                        mttr_hours=recovery_time,
                        dora_level=dora_level,
                        synced_at=now,
                    )
                    db.add(new_metric)
                    records_created += 1

            if own_session:
                db.commit()
            else:
                db.flush()

            self._stats["teams_synced"] += 1
            self._stats["days_synced"] += days_to_sync

            logger.info(f"  Synced {days_to_sync} days: {len(all_pipelines)} pipelines, {len(all_mrs)} MRs, {mrs_stored} stored")

            return {
                "team": team,
                "status": "success",
                "days_synced": days_to_sync,
                "pipelines": len(all_pipelines),
                "mrs": len(all_mrs),
                "mrs_stored": mrs_stored,
                "records_created": records_created,
                "records_updated": records_updated,
            }

        except Exception as e:
            logger.error(f"Error syncing {team}: {e}")
            self._stats["errors"].append(f"{team}: {e}")
            if own_session:
                db.rollback()
            raise
        finally:
            if own_session:
                db.close()

    def sync_all_teams(
        self,
        days: int = 30,
        full_sync: bool = False,
        teams: Optional[list[str]] = None
    ) -> dict:
        """
        Sync metrics for all teams (or specified subset).

        Args:
            days: Maximum days to sync (for full/initial sync)
            full_sync: If True, re-sync all data
            teams: Optional list of team slugs to sync (default: all)

        Returns:
            Summary dict with per-team results and overall stats
        """
        if not self.gitlab_token:
            raise GitLabCollectorError("GitLab credentials are not configured for the active domain")

        logger.info(f"GitLab Metrics Sync ({'full' if full_sync else 'incremental'})")
        logger.info(f"  Max period: {days} days")

        # Reset stats
        self._stats = {
            "teams_synced": 0,
            "pipelines_fetched": 0,
            "mrs_fetched": 0,
            "days_synced": 0,
            "errors": [],
        }

        teams_to_sync = TEAM_GITLAB_PATHS
        if teams:
            teams_to_sync = {t: TEAM_GITLAB_PATHS[t] for t in teams if t in TEAM_GITLAB_PATHS}

        results = {}

        for team, paths in teams_to_sync.items():
            try:
                results[team] = self.sync_team(team, paths, days, full_sync)
            except Exception as e:
                results[team] = {"team": team, "status": "error", "error": str(e)}

        return {
            "results": results,
            "stats": self._stats,
            "synced_at": datetime.now(timezone.utc).isoformat(),
        }

    def health_check(self) -> dict:
        """Check if GitLab API is accessible."""
        try:
            # Simple query to verify token works
            query = "query { currentUser { username } }"
            result = self._graphql_query(query)
            username = result.get("currentUser", {}).get("username")

            return {
                "status": "healthy",
                "gitlab_url": self.gitlab_url,
                "authenticated_as": username,
            }
        except GitLabCollectorError as e:
            return {
                "status": "unhealthy",
                "error": str(e),
            }


def get_collector() -> GitLabCollector:
    """Return a collector configured for the current active domain."""
    return GitLabCollector()
