"""
Package Service

Provides package/dependency search and analysis capabilities.
Queries the GitLabPackage table populated by the repo scanner.

Usage:
    from backend.services.gitlab_intelligence import get_package_service

    service = get_package_service()
    results = service.search_packages("express")
    repos = service.get_repos_using_package("django")
"""

import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.database import GitLabPackage, GitLabRepo, SessionLocal

logger = logging.getLogger(__name__)


class PackageService:
    """
    Service for searching and analyzing package dependencies across repos.
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

    def search_packages(
        self,
        query: str,
        language: Optional[str] = None,
        limit: int = 50,
    ) -> dict:
        """
        Search for packages by name.

        Args:
            query: Package name or partial name to search
            language: Filter by language (Python, JavaScript, etc.)
            limit: Maximum results to return

        Returns:
            Dict with packages list and usage stats
        """
        db = self._get_db()
        try:
            # Search with LIKE for partial matches
            search_pattern = f"%{query}%"
            q = db.query(
                GitLabPackage.package,
                GitLabPackage.language,
                func.count(GitLabPackage.repo_id).label("repo_count"),
            ).filter(
                GitLabPackage.package.ilike(search_pattern)
            )

            if language:
                q = q.filter(GitLabPackage.language == language)

            q = q.group_by(
                GitLabPackage.package, GitLabPackage.language
            ).order_by(
                func.count(GitLabPackage.repo_id).desc()
            ).limit(limit)

            results = q.all()

            packages = []
            for pkg, lang, count in results:
                packages.append({
                    "package": pkg,
                    "language": lang,
                    "repo_count": count,
                })

            return {
                "query": query,
                "packages": packages,
                "total_found": len(packages),
            }
        finally:
            self._close_db(db)

    def get_repos_using_package(
        self,
        package: str,
        team: Optional[str] = None,
        include_versions: bool = True,
    ) -> dict:
        """
        Find all repos using a specific package.

        Args:
            package: Exact package name
            team: Filter by team
            include_versions: Include version information

        Returns:
            Dict with repos list and version distribution
        """
        db = self._get_db()
        try:
            q = db.query(GitLabPackage).filter(
                GitLabPackage.package == package
            )

            if team:
                q = q.filter(GitLabPackage.repo_id.like(f"{team}/%"))

            packages = q.all()

            repos = []
            version_counts = defaultdict(int)

            for pkg in packages:
                repo_info = {
                    "repo_id": pkg.repo_id,
                    "language": pkg.language,
                    "is_dev": pkg.is_dev,
                    "source_file": pkg.source_file,
                }
                if include_versions:
                    repo_info["version"] = pkg.version
                    repo_info["version_resolved"] = pkg.version_resolved
                    version_counts[pkg.version or "unspecified"] += 1

                repos.append(repo_info)

            result = {
                "package": package,
                "repos": repos,
                "repo_count": len(repos),
            }

            if include_versions:
                result["version_distribution"] = dict(version_counts)

            return result
        finally:
            self._close_db(db)

    def get_package_stats(
        self,
        language: Optional[str] = None,
        team: Optional[str] = None,
        top_n: int = 20,
    ) -> dict:
        """
        Get aggregated package usage statistics.

        Args:
            language: Filter by language
            team: Filter by team
            top_n: Number of top packages to return

        Returns:
            Dict with package usage stats
        """
        db = self._get_db()
        try:
            # Get top packages
            q = db.query(
                GitLabPackage.package,
                GitLabPackage.language,
                func.count(GitLabPackage.repo_id).label("repo_count"),
            )

            if language:
                q = q.filter(GitLabPackage.language == language)

            if team:
                q = q.filter(GitLabPackage.repo_id.like(f"{team}/%"))

            top_packages = q.group_by(
                GitLabPackage.package, GitLabPackage.language
            ).order_by(
                func.count(GitLabPackage.repo_id).desc()
            ).limit(top_n).all()

            # Get language distribution
            lang_q = db.query(
                GitLabPackage.language,
                func.count(func.distinct(GitLabPackage.package)).label("package_count"),
                func.count(GitLabPackage.repo_id).label("total_usages"),
            )

            if team:
                lang_q = lang_q.filter(GitLabPackage.repo_id.like(f"{team}/%"))

            lang_stats = lang_q.group_by(GitLabPackage.language).all()

            # Get internal vs external breakdown
            internal_count = db.query(func.count(GitLabPackage.id)).filter(
                GitLabPackage.is_internal == True
            ).scalar() or 0

            total_count = db.query(func.count(GitLabPackage.id)).scalar() or 0

            return {
                "top_packages": [
                    {"package": p, "language": l, "repo_count": c}
                    for p, l, c in top_packages
                ],
                "by_language": [
                    {"language": l, "unique_packages": pc, "total_usages": tu}
                    for l, pc, tu in lang_stats
                ],
                "internal_packages": internal_count,
                "external_packages": total_count - internal_count,
                "total_packages": total_count,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
        finally:
            self._close_db(db)

    def get_outdated_packages(
        self,
        team: Optional[str] = None,
        limit: int = 50,
    ) -> dict:
        """
        Find packages with outdated versions (where version_resolved != latest).

        Note: This requires version data to be populated by the scanner.
        """
        db = self._get_db()
        try:
            # For now, return packages where we have version info
            # Full outdated detection would require a package version registry
            q = db.query(GitLabPackage).filter(
                GitLabPackage.version.isnot(None)
            )

            if team:
                q = q.filter(GitLabPackage.repo_id.like(f"{team}/%"))

            packages = q.order_by(GitLabPackage.package).limit(limit).all()

            # Group by package
            package_versions = defaultdict(list)
            for pkg in packages:
                package_versions[pkg.package].append({
                    "repo_id": pkg.repo_id,
                    "version": pkg.version,
                    "language": pkg.language,
                })

            return {
                "packages_with_versions": len(package_versions),
                "packages": dict(package_versions),
                "note": "Full outdated detection requires version registry integration",
            }
        finally:
            self._close_db(db)


# Singleton instance
_package_service: Optional[PackageService] = None


def get_package_service() -> PackageService:
    """Get or create the package service instance."""
    global _package_service
    if _package_service is None:
        _package_service = PackageService()
    return _package_service
