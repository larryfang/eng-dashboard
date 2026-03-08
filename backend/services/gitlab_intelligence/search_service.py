"""
Search Service

Provides full-text search across GitLab repository data.
Uses LIKE queries on GitLabRepo fields for flexible searching.

Usage:
    from backend.services.gitlab_intelligence import get_search_service

    service = get_search_service()
    results = service.search("shopify")
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.database import GitLabRepo, GitLabPackage, SessionLocal

logger = logging.getLogger(__name__)


class SearchService:
    """
    Full-text search service for GitLab repository data.
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

    def search(
        self,
        query: str,
        team: Optional[str] = None,
        language: Optional[str] = None,
        include_orphaned: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        """
        Search across repos by name, languages, and frameworks.

        Args:
            query: Search term
            team: Filter by team
            language: Filter by primary language
            include_orphaned: Include archived/orphaned repos
            limit: Max results
            offset: Pagination offset

        Returns:
            Dict with repos and search metadata
        """
        db = self._get_db()
        try:
            search_pattern = f"%{query}%"

            # Build query
            q = db.query(GitLabRepo).filter(
                or_(
                    GitLabRepo.name.ilike(search_pattern),
                    GitLabRepo.repo_id.ilike(search_pattern),
                    GitLabRepo.languages.ilike(search_pattern),
                    GitLabRepo.frameworks.ilike(search_pattern),
                    GitLabRepo.primary_language.ilike(search_pattern),
                )
            )

            if team:
                q = q.filter(GitLabRepo.team == team)

            if language:
                q = q.filter(GitLabRepo.primary_language == language)

            if not include_orphaned:
                q = q.filter(GitLabRepo.is_orphaned == False)

            # Get total count before pagination
            total = q.count()

            # Apply pagination and ordering
            repos = q.order_by(
                GitLabRepo.last_commit_date.desc()
            ).offset(offset).limit(limit).all()

            results = []
            for r in repos:
                # Parse JSON fields
                frameworks = []
                if r.frameworks:
                    try:
                        frameworks = json.loads(r.frameworks)
                    except (json.JSONDecodeError, TypeError):
                        frameworks = []

                languages = []
                if r.languages:
                    try:
                        languages = json.loads(r.languages)
                    except (json.JSONDecodeError, TypeError):
                        languages = []

                results.append({
                    "repo_id": r.repo_id,
                    "name": r.name,
                    "team": r.team,
                    "team_display": r.team_display,
                    "primary_language": r.primary_language,
                    "languages": languages,
                    "frameworks": frameworks,
                    "has_tests": r.has_tests,
                    "has_ci": r.has_ci,
                    "is_orphaned": r.is_orphaned,
                    "bus_factor": r.bus_factor,
                    "knowledge_risk": r.knowledge_risk,
                    "last_activity": r.last_commit_date.isoformat() if r.last_commit_date else None,
                    "days_since_commit": r.days_since_commit,
                })

            return {
                "query": query,
                "repos": results,
                "total": total,
                "limit": limit,
                "offset": offset,
                "filters": {
                    "team": team,
                    "language": language,
                    "include_orphaned": include_orphaned,
                },
            }
        finally:
            self._close_db(db)

    def get_language_distribution(
        self,
        team: Optional[str] = None,
        include_orphaned: bool = False,
    ) -> dict:
        """
        Get distribution of primary languages across repos.

        Args:
            team: Filter by team
            include_orphaned: Include orphaned repos

        Returns:
            Dict with language counts
        """
        db = self._get_db()
        try:
            from sqlalchemy import func

            q = db.query(
                GitLabRepo.primary_language,
                func.count(GitLabRepo.id).label("count"),
            )

            if team:
                q = q.filter(GitLabRepo.team == team)

            if not include_orphaned:
                q = q.filter(GitLabRepo.is_orphaned == False)

            results = q.filter(
                GitLabRepo.primary_language.isnot(None)
            ).group_by(
                GitLabRepo.primary_language
            ).order_by(
                func.count(GitLabRepo.id).desc()
            ).all()

            languages = [
                {"language": lang, "repo_count": count}
                for lang, count in results
            ]

            total_repos = sum(r["repo_count"] for r in languages)

            return {
                "languages": languages,
                "total_repos": total_repos,
                "unique_languages": len(languages),
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
        finally:
            self._close_db(db)

    def get_framework_distribution(
        self,
        team: Optional[str] = None,
        include_orphaned: bool = False,
    ) -> dict:
        """
        Get distribution of frameworks across repos.

        Note: Frameworks are stored as JSON arrays, so this does client-side aggregation.

        Args:
            team: Filter by team
            include_orphaned: Include orphaned repos

        Returns:
            Dict with framework counts
        """
        db = self._get_db()
        try:
            q = db.query(GitLabRepo).filter(
                GitLabRepo.frameworks.isnot(None)
            )

            if team:
                q = q.filter(GitLabRepo.team == team)

            if not include_orphaned:
                q = q.filter(GitLabRepo.is_orphaned == False)

            repos = q.all()

            # Aggregate frameworks
            framework_counts = {}
            for r in repos:
                try:
                    frameworks = json.loads(r.frameworks) if r.frameworks else []
                    for fw in frameworks:
                        # Handle both string and dict formats
                        if isinstance(fw, str):
                            name = fw
                        elif isinstance(fw, dict):
                            name = fw.get("framework", fw.get("name", str(fw)))
                        else:
                            continue
                        framework_counts[name] = framework_counts.get(name, 0) + 1
                except (json.JSONDecodeError, TypeError):
                    continue

            # Sort by count
            sorted_frameworks = sorted(
                framework_counts.items(),
                key=lambda x: x[1],
                reverse=True
            )

            return {
                "frameworks": [
                    {"framework": fw, "repo_count": count}
                    for fw, count in sorted_frameworks
                ],
                "total_repos_with_frameworks": len(repos),
                "unique_frameworks": len(framework_counts),
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
        finally:
            self._close_db(db)

    def get_repos_without_tests(
        self,
        team: Optional[str] = None,
        include_orphaned: bool = False,
        limit: int = 50,
    ) -> dict:
        """
        Find repos that don't have tests.

        Args:
            team: Filter by team
            include_orphaned: Include orphaned repos
            limit: Max results

        Returns:
            Dict with repos lacking tests
        """
        db = self._get_db()
        try:
            q = db.query(GitLabRepo).filter(
                GitLabRepo.has_tests == False
            )

            if team:
                q = q.filter(GitLabRepo.team == team)

            if not include_orphaned:
                q = q.filter(GitLabRepo.is_orphaned == False)

            # Get total count
            total = q.count()

            repos = q.order_by(
                GitLabRepo.last_commit_date.desc()
            ).limit(limit).all()

            return {
                "repos": [
                    {
                        "repo_id": r.repo_id,
                        "name": r.name,
                        "team": r.team,
                        "primary_language": r.primary_language,
                        "has_ci": r.has_ci,
                        "last_activity": r.last_commit_date.isoformat() if r.last_commit_date else None,
                    }
                    for r in repos
                ],
                "total": total,
                "limit": limit,
            }
        finally:
            self._close_db(db)


# Singleton instance
_search_service: Optional[SearchService] = None


def get_search_service() -> SearchService:
    """Get or create the search service instance."""
    global _search_service
    if _search_service is None:
        _search_service = SearchService()
    return _search_service
