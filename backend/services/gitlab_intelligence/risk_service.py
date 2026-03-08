"""
Knowledge Risk Service

Analyzes code ownership patterns to identify knowledge silos and bus factor risks.
All metrics are computed dynamically from GitLab MR activity data stored in PA's database.

Key Concepts:
- Bus Factor: Number of people who would need to leave for a project to stall
- Knowledge Concentration: How much code knowledge is held by a single person
- Single Owner Risk: Repos entirely dependent on one contributor

Risk Levels:
- CRITICAL: Bus factor = 1, single contributor owns >80% of code
- HIGH: Bus factor ≤ 2, top contributor owns >60% of code
- MEDIUM: Bus factor ≤ 3, top contributor owns >40% of code
- LOW: Well-distributed knowledge, multiple active contributors
"""

import logging
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy import func, desc
from sqlalchemy.orm import Session

from backend.database import GitLabRepo, GitLabEngineer, GitLabMRActivity, SessionLocal
from backend.config.gitlab_teams import TEAM_DISPLAY_NAMES, TEAM_GITLAB_PATHS, normalize_team_name

logger = logging.getLogger(__name__)


def _gitlab_path_to_team() -> dict[str, str]:
    """Build a fresh GitLab path-segment → team lookup for the active domain."""
    lookup: dict[str, str] = {}
    for team, paths in TEAM_GITLAB_PATHS.items():
        for path in paths:
            lookup[path.split("/")[-1]] = team
    return lookup


class RiskLevel:
    """Risk level constants."""
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


class KnowledgeRiskService:
    """
    Service for analyzing knowledge risk and bus factor.

    All metrics are computed dynamically from GitLab MR activity data.
    No external JSON files required.
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

    def _calculate_repo_risk(
        self,
        author_counts: dict[str, int],
        total_contributions: int
    ) -> tuple[int, float, str]:
        """
        Calculate risk metrics for a single repo.

        Args:
            author_counts: Dict of author -> contribution count
            total_contributions: Total contributions across all authors

        Returns:
            Tuple of (bus_factor, top_contributor_percentage, risk_level)
        """
        if not author_counts or total_contributions == 0:
            return (0, 0.0, RiskLevel.UNKNOWN)

        # Sort by contribution count
        sorted_authors = sorted(
            author_counts.items(),
            key=lambda x: x[1],
            reverse=True
        )

        # Calculate percentages
        percentages = [
            (author, count / total_contributions * 100)
            for author, count in sorted_authors
        ]

        # Bus factor = contributors with >= 10% contribution
        bus_factor = len([p for _, p in percentages if p >= 10])
        top_contributor_pct = percentages[0][1] if percentages else 0

        # Determine risk level
        if bus_factor == 1 and top_contributor_pct > 80:
            risk_level = RiskLevel.CRITICAL
        elif bus_factor <= 2 and top_contributor_pct > 60:
            risk_level = RiskLevel.HIGH
        elif bus_factor <= 3 and top_contributor_pct > 40:
            risk_level = RiskLevel.MEDIUM
        else:
            risk_level = RiskLevel.LOW

        return (bus_factor, top_contributor_pct, risk_level)

    def _get_repo_contributions(
        self,
        db: Session,
        days: int = 180
    ) -> dict[str, dict]:
        """
        Get contribution stats for all repos.

        Returns dict of repo_id -> {
            'authors': {author: count},
            'total': int,
            'team': str
        }
        """
        since_date = datetime.now(timezone.utc) - timedelta(days=days)

        # Get all merged MRs in the time period
        mrs = db.query(
            GitLabMRActivity.repo_id,
            GitLabMRActivity.author_username,
            func.count(GitLabMRActivity.id).label('count')
        ).filter(
            GitLabMRActivity.state == "merged",
            GitLabMRActivity.merged_at >= since_date
        ).group_by(
            GitLabMRActivity.repo_id,
            GitLabMRActivity.author_username
        ).all()

        # Aggregate by repo
        repo_stats = defaultdict(lambda: {'authors': {}, 'total': 0, 'team': None})

        path_to_team = _gitlab_path_to_team()

        for repo_id, author, count in mrs:
            repo_stats[repo_id]['authors'][author] = count
            repo_stats[repo_id]['total'] += count

            # Extract team from repo_id
            # Format: org/group/teams/{team_folder}/{repo}
            if '/' in repo_id:
                parts = repo_id.split('/')
                # Look for team in path (after "teams/" segment)
                if 'teams' in parts:
                    team_idx = parts.index('teams')
                    if team_idx + 1 < len(parts):
                        gitlab_folder = parts[team_idx + 1]
                        # Map GitLab folder name to canonical team key
                        team = path_to_team.get(gitlab_folder, gitlab_folder)
                        repo_stats[repo_id]['team'] = team
                else:
                    # Fallback: use first segment
                    repo_stats[repo_id]['team'] = parts[0]

        return dict(repo_stats)

    def get_risk_summary(self, days: int = 180) -> dict:
        """
        Get complete knowledge risk summary.

        Returns team risk scores, bottleneck engineers, and critical repos.

        Args:
            days: Look back period for MR activity (default 180 days)
        """
        db = self._get_db()
        try:
            repo_contributions = self._get_repo_contributions(db, days)

            if not repo_contributions:
                return {
                    "data": {
                        "message": "No MR activity data available. Run GitLab sync first.",
                        "teams": [],
                    },
                    "source": "computed",
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }

            # Calculate risk for each repo
            team_stats = defaultdict(lambda: {
                'repos': [],
                'critical': 0,
                'high': 0,
                'medium': 0,
                'low': 0,
            })

            all_repos_risk = []

            for repo_id, stats in repo_contributions.items():
                bus_factor, top_pct, risk_level = self._calculate_repo_risk(
                    stats['authors'],
                    stats['total']
                )

                team = stats.get('team', 'unknown')
                repo_info = {
                    'repo_id': repo_id,
                    'team': team,
                    'bus_factor': bus_factor,
                    'top_contributor_pct': round(top_pct, 1),
                    'risk_level': risk_level,
                    'total_mrs': stats['total'],
                    'contributors': len(stats['authors']),
                }

                all_repos_risk.append(repo_info)
                team_stats[team]['repos'].append(repo_info)

                level_key = risk_level.lower()
                if level_key in team_stats[team]:
                    team_stats[team][level_key] += 1

            # Build team summary
            teams = []
            for team, data in team_stats.items():
                total = len(data['repos'])
                # Score based on risk distribution
                score = (
                    data['critical'] * 100 +
                    data['high'] * 50 +
                    data['medium'] * 20 +
                    data['low'] * 5
                ) / total if total > 0 else 0

                # Determine team level
                if data['critical'] > 0:
                    level = RiskLevel.CRITICAL
                elif data['high'] > 0:
                    level = RiskLevel.HIGH
                elif data['medium'] > 0:
                    level = RiskLevel.MEDIUM
                else:
                    level = RiskLevel.LOW

                teams.append({
                    'team': team,
                    'display_name': TEAM_DISPLAY_NAMES.get(team, team),
                    'score': round(score, 1),
                    'level': level,
                    'repos_analyzed': total,
                    'critical_repos': data['critical'],
                    'high_risk_repos': data['high'],
                })

            teams.sort(key=lambda x: x['score'], reverse=True)

            # Count totals
            total_critical = sum(t['critical_repos'] for t in teams)
            total_high = sum(t['high_risk_repos'] for t in teams)

            return {
                "data": {
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "period_days": days,
                    "total_repos_analyzed": len(all_repos_risk),
                    "critical_risk_repos": total_critical,
                    "high_risk_repos": total_high,
                    "teams": teams,
                },
                "source": "computed",
            }

        finally:
            self._close_db(db)

    def get_team_risk(self, team: Optional[str] = None, days: int = 180) -> dict:
        """
        Get risk scores by team.

        Args:
            team: Team slug to filter (optional)
            days: Look back period for MR activity

        Returns:
            Risk assessment per team with severity levels
        """
        summary = self.get_risk_summary(days)

        if "error" in summary:
            return summary

        teams = summary.get("data", {}).get("teams", [])

        if team:
            normalized = normalize_team_name(team)
            if not normalized:
                return {"error": f"Team '{team}' not recognized"}

            for t in teams:
                if t['team'] == normalized or t['team'] == team.lower():
                    return {"data": t}

            return {"error": f"Team '{team}' not found in risk data"}

        return {
            "data": {
                "generated_at": summary.get("data", {}).get("generated_at"),
                "teams": teams,
            }
        }

    def get_critical_repos(
        self,
        team: Optional[str] = None,
        days: int = 180,
        limit: int = 50
    ) -> dict:
        """
        Get repos with critical bus factor risk.

        Critical = single contributor owns >80% of code.

        Args:
            team: Filter by team slug
            days: Look back period
            limit: Maximum repos to return

        Returns:
            List of critical risk repos
        """
        db = self._get_db()
        try:
            repo_contributions = self._get_repo_contributions(db, days)
            critical_repos = []

            for repo_id, stats in repo_contributions.items():
                bus_factor, top_pct, risk_level = self._calculate_repo_risk(
                    stats['authors'],
                    stats['total']
                )

                if risk_level != RiskLevel.CRITICAL:
                    continue

                repo_team = stats.get('team', 'unknown')

                # Filter by team if specified
                if team:
                    normalized = normalize_team_name(team) or team.lower()
                    if repo_team != normalized:
                        continue

                # Get top contributor
                top_author = max(stats['authors'].items(), key=lambda x: x[1])[0] if stats['authors'] else None

                critical_repos.append({
                    'repo_id': repo_id,
                    'repo': repo_id.split('/')[-1] if '/' in repo_id else repo_id,
                    'team': repo_team,
                    'bus_factor': bus_factor,
                    'top_contributor': top_author,
                    'top_contributor_pct': round(top_pct, 1),
                    'total_mrs': stats['total'],
                })

            # Sort by top contributor percentage descending
            critical_repos.sort(key=lambda x: x['top_contributor_pct'], reverse=True)
            critical_repos = critical_repos[:limit]

            # Group by team
            by_team = defaultdict(int)
            for repo in critical_repos:
                by_team[repo['team']] += 1

            return {
                "data": {
                    "total": len(critical_repos),
                    "by_team": dict(by_team),
                    "repos": critical_repos,
                }
            }

        finally:
            self._close_db(db)

    def get_high_risk_repos(
        self,
        team: Optional[str] = None,
        days: int = 180
    ) -> dict:
        """
        Get repos with high (but not critical) bus factor risk.

        High = top contributor owns 40-80% of code, bus factor ≤ 2.

        Args:
            team: Filter by team slug
            days: Look back period

        Returns:
            List of high risk repos
        """
        db = self._get_db()
        try:
            repo_contributions = self._get_repo_contributions(db, days)
            high_risk_repos = []

            for repo_id, stats in repo_contributions.items():
                bus_factor, top_pct, risk_level = self._calculate_repo_risk(
                    stats['authors'],
                    stats['total']
                )

                if risk_level != RiskLevel.HIGH:
                    continue

                repo_team = stats.get('team', 'unknown')

                # Filter by team if specified
                if team:
                    normalized = normalize_team_name(team) or team.lower()
                    if repo_team != normalized:
                        continue

                top_author = max(stats['authors'].items(), key=lambda x: x[1])[0] if stats['authors'] else None

                high_risk_repos.append({
                    'repo_id': repo_id,
                    'repo': repo_id.split('/')[-1] if '/' in repo_id else repo_id,
                    'team': repo_team,
                    'bus_factor': bus_factor,
                    'top_contributor': top_author,
                    'top_contributor_pct': round(top_pct, 1),
                    'total_mrs': stats['total'],
                })

            high_risk_repos.sort(key=lambda x: x['top_contributor_pct'], reverse=True)

            return {
                "data": {
                    "total": len(high_risk_repos),
                    "repos": high_risk_repos,
                }
            }

        finally:
            self._close_db(db)

    def get_bottleneck_engineers(
        self,
        team: Optional[str] = None,
        days: int = 180,
        min_critical_repos: int = 2
    ) -> dict:
        """
        Get engineers who are knowledge bottlenecks.

        Bottleneck = owns multiple critical repos (knowledge hoarding signal).

        Args:
            team: Filter by team slug
            days: Look back period
            min_critical_repos: Minimum critical repos to be considered a bottleneck

        Returns:
            List of bottleneck engineers with their repos
        """
        db = self._get_db()
        try:
            repo_contributions = self._get_repo_contributions(db, days)

            # Find engineers who are top contributors on critical repos
            engineer_critical_repos = defaultdict(list)

            for repo_id, stats in repo_contributions.items():
                bus_factor, top_pct, risk_level = self._calculate_repo_risk(
                    stats['authors'],
                    stats['total']
                )

                if risk_level != RiskLevel.CRITICAL:
                    continue

                repo_team = stats.get('team', 'unknown')

                # Filter by team if specified
                if team:
                    normalized = normalize_team_name(team) or team.lower()
                    if repo_team != normalized:
                        continue

                # Get top contributor (the bottleneck)
                if stats['authors']:
                    top_author = max(stats['authors'].items(), key=lambda x: x[1])[0]
                    engineer_critical_repos[top_author].append({
                        'repo_id': repo_id,
                        'repo': repo_id.split('/')[-1] if '/' in repo_id else repo_id,
                        'team': repo_team,
                        'ownership_pct': round(top_pct, 1),
                    })

            # Filter to engineers with multiple critical repos
            bottlenecks = []
            for engineer, repos in engineer_critical_repos.items():
                if len(repos) >= min_critical_repos:
                    bottlenecks.append({
                        'username': engineer,
                        'critical_repos_owned': len(repos),
                        'repos': repos,
                    })

            # Sort by number of critical repos
            bottlenecks.sort(key=lambda x: x['critical_repos_owned'], reverse=True)

            return {
                "data": {
                    "total": len(bottlenecks),
                    "engineers": bottlenecks,
                }
            }

        finally:
            self._close_db(db)

    def get_single_owner_repos(
        self,
        team: Optional[str] = None,
        days: int = 180
    ) -> dict:
        """
        Get repos with only a single contributor.

        These are entirely dependent on one engineer - maximum risk.

        Args:
            team: Filter by team slug
            days: Look back period

        Returns:
            List of single-owner repos grouped by owner
        """
        db = self._get_db()
        try:
            repo_contributions = self._get_repo_contributions(db, days)
            single_owner_repos = []

            for repo_id, stats in repo_contributions.items():
                if len(stats['authors']) != 1:
                    continue

                repo_team = stats.get('team', 'unknown')

                # Filter by team if specified
                if team:
                    normalized = normalize_team_name(team) or team.lower()
                    if repo_team != normalized:
                        continue

                owner = list(stats['authors'].keys())[0]
                mr_count = stats['total']

                single_owner_repos.append({
                    'repo_id': repo_id,
                    'repo': repo_id.split('/')[-1] if '/' in repo_id else repo_id,
                    'team': repo_team,
                    'owner': owner,
                    'total_mrs': mr_count,
                })

            # Group by owner
            by_owner = defaultdict(lambda: {'repos': [], 'count': 0})
            for repo in single_owner_repos:
                owner = repo['owner']
                by_owner[owner]['repos'].append({
                    'repo': repo['repo'],
                    'team': repo['team'],
                    'mrs': repo['total_mrs'],
                })
                by_owner[owner]['count'] += 1

            return {
                "data": {
                    "total": len(single_owner_repos),
                    "by_owner": dict(by_owner),
                    "repos": single_owner_repos,
                }
            }

        finally:
            self._close_db(db)

    def get_summary_stats(self, days: int = 180) -> dict:
        """
        Get high-level risk statistics for dashboards.

        Returns aggregated risk metrics.
        """
        summary = self.get_risk_summary(days)

        if "error" in summary:
            return summary

        data = summary.get("data", {})
        teams = data.get("teams", [])

        # Count teams by risk level
        risk_levels = {
            RiskLevel.CRITICAL: 0,
            RiskLevel.HIGH: 0,
            RiskLevel.MEDIUM: 0,
            RiskLevel.LOW: 0,
        }
        for team in teams:
            level = team.get("level", RiskLevel.UNKNOWN)
            if level in risk_levels:
                risk_levels[level] += 1

        # Get bottleneck count
        bottlenecks = self.get_bottleneck_engineers(days=days)
        bottleneck_count = bottlenecks.get("data", {}).get("total", 0)

        # Get single owner count
        single_owner = self.get_single_owner_repos(days=days)
        single_owner_count = single_owner.get("data", {}).get("total", 0)

        return {
            "data": {
                "generated_at": data.get("generated_at"),
                "period_days": days,
                "total_repos_analyzed": data.get("total_repos_analyzed", 0),
                "critical_risk_repos": data.get("critical_risk_repos", 0),
                "high_risk_repos": data.get("high_risk_repos", 0),
                "bottleneck_engineers": bottleneck_count,
                "single_owner_repos": single_owner_count,
                "teams_by_risk_level": risk_levels,
            }
        }

    def get_repo_risk(self, repo_id: str, days: int = 180) -> dict:
        """
        Get risk details for a specific repository.

        Args:
            repo_id: Repository ID (team/repo format)
            days: Look back period for MR activity

        Returns:
            Risk details including bus factor and top contributors
        """
        db = self._get_db()
        try:
            since_date = datetime.now(timezone.utc) - timedelta(days=days)

            # Get MR activity for this repo
            mrs = db.query(
                GitLabMRActivity.author_username,
                func.count(GitLabMRActivity.id).label('count')
            ).filter(
                GitLabMRActivity.repo_id == repo_id,
                GitLabMRActivity.state == "merged",
                GitLabMRActivity.merged_at >= since_date
            ).group_by(
                GitLabMRActivity.author_username
            ).order_by(
                desc('count')
            ).all()

            if not mrs:
                # Check if repo exists
                repo = db.query(GitLabRepo).filter(
                    GitLabRepo.repo_id == repo_id
                ).first()

                if not repo:
                    return {"error": f"Repository '{repo_id}' not found"}

                return {
                    "data": {
                        "repo_id": repo_id,
                        "name": repo.name,
                        "team": repo.team,
                        "bus_factor": 0,
                        "risk_level": RiskLevel.UNKNOWN,
                        "total_mrs": 0,
                        "message": "No merge request activity in the specified period",
                    }
                }

            # Calculate stats
            author_counts = {author: count for author, count in mrs}
            total_mrs = sum(author_counts.values())
            bus_factor, top_pct, risk_level = self._calculate_repo_risk(
                author_counts,
                total_mrs
            )

            # Build contributor list
            contributors = []
            for author, count in mrs:
                contributors.append({
                    "username": author,
                    "mrs": count,
                    "percentage": round(count / total_mrs * 100, 1),
                })

            # Get repo info
            repo = db.query(GitLabRepo).filter(
                GitLabRepo.repo_id == repo_id
            ).first()

            return {
                "data": {
                    "repo_id": repo_id,
                    "name": repo.name if repo else repo_id.split('/')[-1],
                    "team": repo.team if repo else repo_id.split('/')[0],
                    "bus_factor": bus_factor,
                    "risk_level": risk_level,
                    "top_contributor_pct": round(top_pct, 1),
                    "total_mrs": total_mrs,
                    "period_days": days,
                    "top_contributors": contributors[:10],
                }
            }

        finally:
            self._close_db(db)

    def update_repo_risk_scores(self, days: int = 180) -> dict:
        """
        Update stored risk scores for all repos in the database.

        This updates the bus_factor and knowledge_risk columns in GitLabRepo.

        Args:
            days: Look back period for MR activity

        Returns:
            Summary of updated repos
        """
        db = self._get_db()
        try:
            repo_contributions = self._get_repo_contributions(db, days)

            updated = 0
            for repo_id, stats in repo_contributions.items():
                bus_factor, top_pct, risk_level = self._calculate_repo_risk(
                    stats['authors'],
                    stats['total']
                )

                # Update the repo record
                repo = db.query(GitLabRepo).filter(
                    GitLabRepo.repo_id == repo_id
                ).first()

                if repo:
                    repo.bus_factor = bus_factor
                    repo.knowledge_risk = risk_level.lower()
                    updated += 1

            db.commit()

            return {
                "status": "success",
                "repos_updated": updated,
                "period_days": days,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }

        except Exception as e:
            db.rollback()
            logger.error(f"Failed to update repo risk scores: {e}")
            return {"error": str(e)}

        finally:
            self._close_db(db)


def get_risk_service(db: Optional[Session] = None) -> KnowledgeRiskService:
    """Get a risk service instance."""
    return KnowledgeRiskService(db)
