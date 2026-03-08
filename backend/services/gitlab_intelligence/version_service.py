"""
Version Service

Tracks language and framework versions across repositories with EOL risk assessment.
Enables queries like "Which repos are on Python 3.8?" or "Find EOL risk repos".

Usage:
    from backend.services.gitlab_intelligence import get_version_service

    service = get_version_service()
    summary = service.get_version_summary()
    eol_repos = service.get_eol_risk_repos()
"""

import logging
from collections import defaultdict
from datetime import datetime, timezone, date
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.database import GitLabVersion, GitLabRepo, SessionLocal

logger = logging.getLogger(__name__)


# Known EOL dates for common languages/frameworks
# Format: (name, version_prefix) -> eol_date
EOL_DATES = {
    # Python versions
    ("Python", "3.7"): date(2023, 6, 27),
    ("Python", "3.8"): date(2024, 10, 31),
    ("Python", "3.9"): date(2025, 10, 31),
    ("Python", "3.10"): date(2026, 10, 31),
    ("Python", "3.11"): date(2027, 10, 31),
    ("Python", "3.12"): date(2028, 10, 31),
    # Node.js versions (LTS)
    ("Node", "16"): date(2023, 9, 11),
    ("Node", "18"): date(2025, 4, 30),
    ("Node", "20"): date(2026, 4, 30),
    ("Node", "22"): date(2027, 4, 30),
    ("Node.js", "16"): date(2023, 9, 11),
    ("Node.js", "18"): date(2025, 4, 30),
    ("Node.js", "20"): date(2026, 4, 30),
    ("Node.js", "22"): date(2027, 4, 30),
    # Java versions (LTS)
    ("Java", "8"): date(2030, 12, 31),  # Extended support
    ("Java", "11"): date(2026, 9, 30),
    ("Java", "17"): date(2029, 9, 30),
    ("Java", "21"): date(2031, 9, 30),
    # Spring Boot
    ("Spring Boot", "2.7"): date(2023, 11, 24),
    ("Spring Boot", "3.0"): date(2023, 11, 24),
    ("Spring Boot", "3.1"): date(2024, 5, 18),
    ("Spring Boot", "3.2"): date(2024, 11, 21),
    ("Spring Boot", "3.3"): date(2025, 5, 22),
}


def get_eol_date(name: str, version: str) -> Optional[date]:
    """Get EOL date for a language/framework version."""
    # Try exact match first
    key = (name, version)
    if key in EOL_DATES:
        return EOL_DATES[key]

    # Try major version match
    major_version = version.split(".")[0] if version else None
    if major_version:
        key = (name, major_version)
        if key in EOL_DATES:
            return EOL_DATES[key]

    # Try major.minor match
    if "." in version:
        parts = version.split(".")
        if len(parts) >= 2:
            major_minor = f"{parts[0]}.{parts[1]}"
            key = (name, major_minor)
            if key in EOL_DATES:
                return EOL_DATES[key]

    return None


def is_eol(name: str, version: str) -> tuple[bool, Optional[date]]:
    """Check if a version is EOL."""
    eol_date = get_eol_date(name, version)
    if eol_date is None:
        return False, None
    return date.today() > eol_date, eol_date


class VersionService:
    """
    Service for tracking and analyzing language/framework versions.
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

    def get_version_summary(
        self,
        team: Optional[str] = None,
    ) -> dict:
        """
        Get overall version statistics.

        Args:
            team: Filter by team

        Returns:
            Dict with language/framework version stats
        """
        db = self._get_db()
        try:
            # Get language versions
            lang_q = db.query(
                GitLabVersion.name,
                GitLabVersion.current_version,
                func.count(GitLabVersion.id).label("count"),
            ).filter(
                GitLabVersion.type == "language"
            )

            if team:
                lang_q = lang_q.filter(GitLabVersion.team == team)

            lang_results = lang_q.group_by(
                GitLabVersion.name, GitLabVersion.current_version
            ).order_by(
                GitLabVersion.name, func.count(GitLabVersion.id).desc()
            ).all()

            # Get framework versions
            fw_q = db.query(
                GitLabVersion.name,
                GitLabVersion.current_version,
                func.count(GitLabVersion.id).label("count"),
            ).filter(
                GitLabVersion.type == "framework"
            )

            if team:
                fw_q = fw_q.filter(GitLabVersion.team == team)

            fw_results = fw_q.group_by(
                GitLabVersion.name, GitLabVersion.current_version
            ).order_by(
                GitLabVersion.name, func.count(GitLabVersion.id).desc()
            ).all()

            # Get EOL stats
            eol_q = db.query(func.count(GitLabVersion.id)).filter(
                GitLabVersion.is_eol == True
            )
            if team:
                eol_q = eol_q.filter(GitLabVersion.team == team)
            eol_count = eol_q.scalar() or 0

            # Aggregate by language/framework
            languages = defaultdict(list)
            for name, version, count in lang_results:
                eol_flag, eol_date_val = is_eol(name, version)
                languages[name].append({
                    "version": version,
                    "repo_count": count,
                    "is_eol": eol_flag,
                    "eol_date": eol_date_val.isoformat() if eol_date_val else None,
                })

            frameworks = defaultdict(list)
            for name, version, count in fw_results:
                eol_flag, eol_date_val = is_eol(name, version)
                frameworks[name].append({
                    "version": version,
                    "repo_count": count,
                    "is_eol": eol_flag,
                    "eol_date": eol_date_val.isoformat() if eol_date_val else None,
                })

            return {
                "languages": dict(languages),
                "frameworks": dict(frameworks),
                "eol_count": eol_count,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
        finally:
            self._close_db(db)

    def get_language_versions(
        self,
        language: Optional[str] = None,
        team: Optional[str] = None,
    ) -> dict:
        """
        Get detailed language version distribution.

        Args:
            language: Filter by specific language
            team: Filter by team

        Returns:
            Dict with version distribution per language
        """
        db = self._get_db()
        try:
            q = db.query(
                GitLabVersion.name,
                GitLabVersion.current_version,
                GitLabVersion.repo_id,
                GitLabVersion.team,
                GitLabVersion.is_eol,
            ).filter(
                GitLabVersion.type == "language"
            )

            if language:
                q = q.filter(GitLabVersion.name == language)

            if team:
                q = q.filter(GitLabVersion.team == team)

            results = q.all()

            # Group by language and version
            languages = defaultdict(lambda: defaultdict(list))
            for name, version, repo_id, t, eol in results:
                languages[name][version].append({
                    "repo_id": repo_id,
                    "team": t,
                    "is_eol": eol,
                })

            # Format output
            output = {}
            for lang, versions in languages.items():
                output[lang] = {
                    "versions": {
                        v: {
                            "repo_count": len(repos),
                            "repos": repos,
                        }
                        for v, repos in versions.items()
                    },
                    "total_repos": sum(len(repos) for repos in versions.values()),
                }

            return {
                "languages": output,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
        finally:
            self._close_db(db)

    def get_framework_versions(
        self,
        framework: Optional[str] = None,
        team: Optional[str] = None,
    ) -> dict:
        """
        Get detailed framework version distribution.

        Args:
            framework: Filter by specific framework
            team: Filter by team

        Returns:
            Dict with version distribution per framework
        """
        db = self._get_db()
        try:
            q = db.query(
                GitLabVersion.name,
                GitLabVersion.current_version,
                GitLabVersion.repo_id,
                GitLabVersion.team,
                GitLabVersion.is_eol,
            ).filter(
                GitLabVersion.type == "framework"
            )

            if framework:
                q = q.filter(GitLabVersion.name == framework)

            if team:
                q = q.filter(GitLabVersion.team == team)

            results = q.all()

            # Group by framework and version
            frameworks = defaultdict(lambda: defaultdict(list))
            for name, version, repo_id, t, eol in results:
                frameworks[name][version].append({
                    "repo_id": repo_id,
                    "team": t,
                    "is_eol": eol,
                })

            # Format output
            output = {}
            for fw, versions in frameworks.items():
                output[fw] = {
                    "versions": {
                        v: {
                            "repo_count": len(repos),
                            "repos": repos,
                        }
                        for v, repos in versions.items()
                    },
                    "total_repos": sum(len(repos) for repos in versions.values()),
                }

            return {
                "frameworks": output,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
        finally:
            self._close_db(db)

    def get_eol_risk_repos(
        self,
        team: Optional[str] = None,
        risk_level: Optional[str] = None,
        limit: int = 50,
    ) -> dict:
        """
        Find repos with EOL or near-EOL language/framework versions.

        Args:
            team: Filter by team
            risk_level: Filter by risk level (low, medium, high, critical)
            limit: Max results

        Returns:
            Dict with repos at EOL risk
        """
        db = self._get_db()
        try:
            q = db.query(GitLabVersion).filter(
                GitLabVersion.is_eol == True
            )

            if team:
                q = q.filter(GitLabVersion.team == team)

            if risk_level:
                q = q.filter(GitLabVersion.risk_level == risk_level)

            results = q.order_by(
                GitLabVersion.risk_level.desc(),
                GitLabVersion.name,
            ).limit(limit).all()

            repos = []
            for v in results:
                repos.append({
                    "repo_id": v.repo_id,
                    "team": v.team,
                    "type": v.type,
                    "name": v.name,
                    "current_version": v.current_version,
                    "latest_version": v.latest_version,
                    "risk_level": v.risk_level,
                    "eol_date": v.eol_date.isoformat() if v.eol_date else None,
                })

            # Get count by risk level
            risk_counts = {}
            for level in ["critical", "high", "medium", "low"]:
                count_q = db.query(func.count(GitLabVersion.id)).filter(
                    GitLabVersion.is_eol == True,
                    GitLabVersion.risk_level == level,
                )
                if team:
                    count_q = count_q.filter(GitLabVersion.team == team)
                risk_counts[level] = count_q.scalar() or 0

            return {
                "eol_repos": repos,
                "total": len(repos),
                "by_risk_level": risk_counts,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
        finally:
            self._close_db(db)

    def get_upgrades_needed(
        self,
        team: Optional[str] = None,
        limit: int = 50,
    ) -> dict:
        """
        Find repos that need version upgrades (not at latest version).

        Args:
            team: Filter by team
            limit: Max results

        Returns:
            Dict with repos needing upgrades
        """
        db = self._get_db()
        try:
            # Find repos where current != latest and latest is known
            q = db.query(GitLabVersion).filter(
                GitLabVersion.latest_version.isnot(None),
                GitLabVersion.current_version != GitLabVersion.latest_version,
            )

            if team:
                q = q.filter(GitLabVersion.team == team)

            results = q.order_by(
                GitLabVersion.name,
                GitLabVersion.current_version,
            ).limit(limit).all()

            repos = []
            for v in results:
                repos.append({
                    "repo_id": v.repo_id,
                    "team": v.team,
                    "type": v.type,
                    "name": v.name,
                    "current_version": v.current_version,
                    "latest_version": v.latest_version,
                    "version_status": v.version_status,
                })

            # Group by what needs upgrading
            upgrades_by_name = defaultdict(list)
            for r in repos:
                upgrades_by_name[r["name"]].append(r)

            return {
                "repos_needing_upgrades": repos,
                "total": len(repos),
                "by_name": {k: len(v) for k, v in upgrades_by_name.items()},
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
        finally:
            self._close_db(db)


# Singleton instance
_version_service: Optional[VersionService] = None


def get_version_service() -> VersionService:
    """Get or create the version service instance."""
    global _version_service
    if _version_service is None:
        _version_service = VersionService()
    return _version_service
