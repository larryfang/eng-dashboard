"""
Epic-MR Correlator Service

Links Jira epics to GitLab merge requests for velocity and progress tracking.

Correlation Methods:
1. Branch name parsing (e.g., "EEH-123-feature-name")
2. Commit message extraction (e.g., "[EEH-123] Add feature")
3. MR title parsing (e.g., "EEH-123: Implement feature")
4. MR description references

Enables:
- "What MRs contributed to epic EEH-123?"
- "Which engineers worked on epic MA-456?"
- "Calculate epic velocity from MR throughput"
"""

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.database import (
    GitLabMRActivity,
    JiraEpicCache,
    EpicMRCorrelation,
    SessionLocal,
)
from backend.config.gitlab_teams import get_team_from_jira_key, JIRA_PREFIX_TO_TEAM

logger = logging.getLogger(__name__)

# Jira ticket pattern: PROJECT-123
JIRA_TICKET_PATTERN = re.compile(r'([A-Z]{2,10}-\d+)')


class EpicMRCorrelator:
    """
    Correlates Jira epics with GitLab merge requests.

    Uses multiple extraction methods to link MRs to tickets:
    1. Branch names (most reliable)
    2. Commit messages
    3. MR titles
    4. MR descriptions
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

    def extract_tickets_from_mr(
        self,
        branch: Optional[str],
        title: Optional[str],
        description: Optional[str]
    ) -> list[tuple[str, str, float]]:
        """
        Extract Jira ticket keys from MR metadata.

        Returns:
            List of (ticket_key, extraction_method, confidence) tuples
        """
        results = []
        seen_tickets = set()

        # Branch name is most reliable (developers often include ticket in branch)
        if branch:
            matches = JIRA_TICKET_PATTERN.findall(branch)
            for ticket in matches:
                if ticket not in seen_tickets:
                    results.append((ticket, "branch_name", 0.95))
                    seen_tickets.add(ticket)

        # MR title is second most reliable
        if title:
            matches = JIRA_TICKET_PATTERN.findall(title)
            for ticket in matches:
                if ticket not in seen_tickets:
                    results.append((ticket, "mr_title", 0.90))
                    seen_tickets.add(ticket)

        # Description may have more references but lower confidence
        if description:
            matches = JIRA_TICKET_PATTERN.findall(description)
            for ticket in matches:
                if ticket not in seen_tickets:
                    results.append((ticket, "mr_description", 0.75))
                    seen_tickets.add(ticket)

        return results

    def correlate_mr_to_epics(
        self,
        mr: GitLabMRActivity,
        db: Session
    ) -> list[EpicMRCorrelation]:
        """
        Create correlations for a single MR to its epics.

        Args:
            mr: The merge request to correlate
            db: Database session

        Returns:
            List of created EpicMRCorrelation records
        """
        correlations = []

        # Extract tickets from MR
        tickets = self.extract_tickets_from_mr(
            mr.source_branch,
            mr.title,
            mr.description
        )

        if not tickets:
            return []

        for ticket_key, method, confidence in tickets:
            # Look up the epic for this ticket
            # First check if the ticket is an epic itself
            epic = db.query(JiraEpicCache).filter(
                JiraEpicCache.epic_key == ticket_key
            ).first()

            epic_key = ticket_key if epic else None

            # If not an epic, try to find parent epic (would need jira_ticket_epics table)
            # For now, we'll just use the ticket directly

            # Get team from ticket prefix
            team = get_team_from_jira_key(ticket_key)

            correlation = EpicMRCorrelation(
                epic_key=epic_key or ticket_key,  # Use ticket if no epic found
                ticket_key=ticket_key,
                mr_id=mr.id,
                author_username=mr.author_username,
                team=team,
                lines_changed=(mr.lines_added or 0) + (mr.lines_removed or 0),
                files_changed=mr.files_changed,
                merged_at=mr.merged_at,
                correlation_method=method,
                confidence=confidence,
            )

            correlations.append(correlation)

        return correlations

    def build_correlations(
        self,
        days: int = 90,
        team: Optional[str] = None
    ) -> dict:
        """
        Build correlations for recent MRs.

        Args:
            days: Number of days to look back
            team: Filter by team (optional)

        Returns:
            Summary of correlation results
        """
        db = self._get_db()
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)

            # Get merged MRs with Jira tickets
            query = db.query(GitLabMRActivity).filter(
                GitLabMRActivity.merged_at >= cutoff,
                GitLabMRActivity.state == "merged",
                GitLabMRActivity.jira_tickets.isnot(None)
            )

            if team:
                query = query.filter(GitLabMRActivity.repo_id.like(f"{team}/%"))

            mrs = query.all()

            created = 0
            skipped = 0

            for mr in mrs:
                # Check if already correlated
                existing = db.query(EpicMRCorrelation).filter(
                    EpicMRCorrelation.mr_id == mr.id
                ).first()

                if existing:
                    skipped += 1
                    continue

                correlations = self.correlate_mr_to_epics(mr, db)
                for corr in correlations:
                    db.add(corr)
                    created += 1

            db.commit()

            return {
                "mrs_processed": len(mrs),
                "correlations_created": created,
                "skipped_existing": skipped,
                "period_days": days,
            }

        finally:
            self._close_db(db)

    def get_epic_mrs(
        self,
        epic_key: str,
        include_child_tickets: bool = True
    ) -> dict:
        """
        Get all MRs linked to an epic.

        Args:
            epic_key: Jira epic key (e.g., "EEH-123")
            include_child_tickets: Also include MRs for child tickets

        Returns:
            Epic with linked MRs and contributor stats
        """
        db = self._get_db()
        try:
            # Get correlations for this epic
            query = db.query(EpicMRCorrelation).filter(
                EpicMRCorrelation.epic_key == epic_key
            )

            correlations = query.all()

            # Get MR details
            mr_ids = [c.mr_id for c in correlations if c.mr_id]
            mrs = db.query(GitLabMRActivity).filter(
                GitLabMRActivity.id.in_(mr_ids)
            ).all() if mr_ids else []

            # Aggregate by contributor
            contributors = {}
            total_lines = 0
            total_files = 0

            for corr in correlations:
                author = corr.author_username
                if author not in contributors:
                    contributors[author] = {
                        "username": author,
                        "mr_count": 0,
                        "lines_changed": 0,
                        "files_changed": 0,
                    }
                contributors[author]["mr_count"] += 1
                contributors[author]["lines_changed"] += corr.lines_changed or 0
                contributors[author]["files_changed"] += corr.files_changed or 0
                total_lines += corr.lines_changed or 0
                total_files += corr.files_changed or 0

            # Sort contributors by contribution
            sorted_contributors = sorted(
                contributors.values(),
                key=lambda x: x["lines_changed"],
                reverse=True
            )

            return {
                "epic_key": epic_key,
                "total_mrs": len(correlations),
                "total_lines_changed": total_lines,
                "total_files_changed": total_files,
                "contributors": sorted_contributors,
                "mrs": [
                    {
                        "iid": mr.mr_iid,
                        "title": mr.title,
                        "author": mr.author_username,
                        "merged_at": mr.merged_at.isoformat() if mr.merged_at else None,
                        "web_url": mr.web_url,
                    }
                    for mr in mrs
                ],
            }

        finally:
            self._close_db(db)

    def get_engineer_epics(
        self,
        username: str,
        days: int = 90
    ) -> dict:
        """
        Get all epics an engineer has contributed to.

        Args:
            username: GitLab username
            days: Days to look back

        Returns:
            Engineer contribution summary
        """
        db = self._get_db()
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)

            correlations = db.query(EpicMRCorrelation).filter(
                EpicMRCorrelation.author_username == username,
                EpicMRCorrelation.merged_at >= cutoff
            ).all()

            # Aggregate by epic
            epics = {}
            for corr in correlations:
                epic = corr.epic_key
                if epic not in epics:
                    epics[epic] = {
                        "epic_key": epic,
                        "team": corr.team,
                        "mr_count": 0,
                        "lines_changed": 0,
                        "files_changed": 0,
                        "first_contribution": corr.merged_at,
                        "last_contribution": corr.merged_at,
                    }
                epics[epic]["mr_count"] += 1
                epics[epic]["lines_changed"] += corr.lines_changed or 0
                epics[epic]["files_changed"] += corr.files_changed or 0

                if corr.merged_at:
                    if epics[epic]["first_contribution"] is None or corr.merged_at < epics[epic]["first_contribution"]:
                        epics[epic]["first_contribution"] = corr.merged_at
                    if epics[epic]["last_contribution"] is None or corr.merged_at > epics[epic]["last_contribution"]:
                        epics[epic]["last_contribution"] = corr.merged_at

            # Sort by contribution
            sorted_epics = sorted(
                epics.values(),
                key=lambda x: x["mr_count"],
                reverse=True
            )

            return {
                "username": username,
                "period_days": days,
                "total_epics": len(sorted_epics),
                "total_mrs": sum(e["mr_count"] for e in sorted_epics),
                "total_lines_changed": sum(e["lines_changed"] for e in sorted_epics),
                "epics": [
                    {
                        **e,
                        "first_contribution": e["first_contribution"].isoformat() if e["first_contribution"] else None,
                        "last_contribution": e["last_contribution"].isoformat() if e["last_contribution"] else None,
                    }
                    for e in sorted_epics
                ],
            }

        finally:
            self._close_db(db)

    def calculate_epic_velocity(
        self,
        epic_key: str
    ) -> dict:
        """
        Calculate velocity metrics for an epic based on MR activity.

        Args:
            epic_key: Jira epic key

        Returns:
            Velocity metrics
        """
        db = self._get_db()
        try:
            correlations = db.query(EpicMRCorrelation).filter(
                EpicMRCorrelation.epic_key == epic_key
            ).order_by(EpicMRCorrelation.merged_at).all()

            if not correlations:
                return {
                    "epic_key": epic_key,
                    "error": "No MR activity found",
                }

            # Calculate time-based metrics
            first_mr = min(c.merged_at for c in correlations if c.merged_at)
            last_mr = max(c.merged_at for c in correlations if c.merged_at)
            duration_days = (last_mr - first_mr).days if first_mr and last_mr else 0

            total_mrs = len(correlations)
            total_lines = sum(c.lines_changed or 0 for c in correlations)

            # MRs per week
            mrs_per_week = (total_mrs / duration_days * 7) if duration_days > 0 else 0

            # Lines per week
            lines_per_week = (total_lines / duration_days * 7) if duration_days > 0 else 0

            # Unique contributors
            contributors = set(c.author_username for c in correlations)

            return {
                "epic_key": epic_key,
                "duration_days": duration_days,
                "first_mr": first_mr.isoformat() if first_mr else None,
                "last_mr": last_mr.isoformat() if last_mr else None,
                "total_mrs": total_mrs,
                "total_lines_changed": total_lines,
                "mrs_per_week": round(mrs_per_week, 2),
                "lines_per_week": round(lines_per_week, 1),
                "unique_contributors": len(contributors),
                "contributors": list(contributors),
            }

        finally:
            self._close_db(db)


def get_epic_mr_correlator(db: Optional[Session] = None) -> EpicMRCorrelator:
    """Get an Epic-MR Correlator instance."""
    return EpicMRCorrelator(db)
