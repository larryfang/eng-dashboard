"""
Unified search endpoint.

GET /api/search?q={query}&limit=5&type={filter}

Searches across engineers, teams, MRs, Jira epics, and Port services
using simple ILIKE matching. Data volume is small enough that FTS5 is
not needed.
"""

import logging
from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.database_domain import get_ecosystem_session
from backend.models_domain import RefMember, RefTeam, MRActivity, JiraEpic, PortService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/search", tags=["Search"])


def _like(field, term: str):
    """Case-insensitive LIKE helper."""
    return field.ilike(f"%{term}%")


@router.get("")
def global_search(
    q: str = Query(..., min_length=2, description="Search query"),
    limit: int = Query(5, ge=1, le=20),
    type: str | None = Query(None, description="Filter to a single type: engineer, team, mr, epic, service"),
    db: Session = Depends(get_ecosystem_session),
):
    pattern = q.strip()
    results: dict[str, list] = {}
    total = 0

    # --- Engineers ---
    if type is None or type == "engineer":
        rows = (
            db.query(RefMember)
            .filter(
                RefMember.departed != True,  # noqa: E712
                or_(
                    _like(RefMember.name, pattern),
                    _like(RefMember.gitlab_username, pattern),
                    _like(RefMember.email, pattern),
                    _like(RefMember.team_display, pattern),
                    _like(RefMember.team_slug, pattern),
                ),
            )
            .limit(limit)
            .all()
        )
        results["engineers"] = [
            {
                "type": "engineer",
                "id": r.gitlab_username,
                "title": r.name,
                "subtitle": r.team_display or r.team_slug,
                "url": f"/engineers/{r.gitlab_username}",
            }
            for r in rows
        ]
        total += len(results["engineers"])

    # --- Teams ---
    if type is None or type == "team":
        rows = (
            db.query(RefTeam)
            .filter(
                or_(
                    _like(RefTeam.name, pattern),
                    _like(RefTeam.scrum_name, pattern),
                    _like(RefTeam.slug, pattern),
                    _like(RefTeam.key, pattern),
                    _like(RefTeam.jira_project, pattern),
                    _like(RefTeam.products, pattern),
                ),
            )
            .limit(limit)
            .all()
        )
        results["teams"] = [
            {
                "type": "team",
                "id": r.slug,
                "title": r.name,
                "subtitle": r.scrum_name or r.slug,
                "url": f"/engineers?team={r.slug}",
            }
            for r in rows
        ]
        total += len(results["teams"])

    # --- Merge Requests ---
    if type is None or type == "mr":
        rows = (
            db.query(MRActivity)
            .filter(
                or_(
                    _like(MRActivity.title, pattern),
                    _like(MRActivity.source_branch, pattern),
                    _like(MRActivity.author_username, pattern),
                    _like(MRActivity.jira_tickets, pattern),
                    _like(MRActivity.epic_keys, pattern),
                ),
            )
            .order_by(MRActivity.created_at.desc())
            .limit(limit)
            .all()
        )
        results["mrs"] = [
            {
                "type": "mr",
                "id": f"{r.repo_id}!{r.mr_iid}",
                "title": r.title,
                "subtitle": f"{r.author_username} · {r.state}",
                "url": None,
                "external_url": r.web_url,
            }
            for r in rows
        ]
        total += len(results["mrs"])

    # --- Jira Epics ---
    if type is None or type == "epic":
        rows = (
            db.query(JiraEpic)
            .filter(
                or_(
                    _like(JiraEpic.key, pattern),
                    _like(JiraEpic.summary, pattern),
                    _like(JiraEpic.project, pattern),
                    _like(JiraEpic.assignee, pattern),
                ),
            )
            .limit(limit)
            .all()
        )
        results["epics"] = [
            {
                "type": "epic",
                "id": r.key,
                "title": f"{r.key}: {r.summary}",
                "subtitle": f"{r.project} · {r.status or 'Unknown'}",
                "url": None,
                "external_url": r.url,
            }
            for r in rows
        ]
        total += len(results["epics"])

    # --- Port Services ---
    if type is None or type == "service":
        # Cross-reference: if query matches a team name/scrum_name/slug,
        # also include services owned by that team's port_team_id
        matching_port_ids: list[str] = []
        try:
            from backend.core.config_loader import get_config
            cfg = get_config()
            for team in cfg.teams:
                searchable = " ".join(filter(None, [
                    team.name, team.scrum_name, team.slug, team.key,
                    *team.aliases, *(team.products or []),
                ]))
                if pattern.lower() in searchable.lower() and team.port_team_id:
                    matching_port_ids.append(team.port_team_id)
        except Exception:
            pass  # config not loaded yet — skip team cross-ref

        svc_filters = [
            _like(PortService.title, pattern),
            _like(PortService.id, pattern),
            _like(PortService.description, pattern),
            _like(PortService.language, pattern),
            _like(PortService.language_version, pattern),
            _like(PortService.system, pattern),
            _like(PortService.team, pattern),
        ]
        if matching_port_ids:
            svc_filters.append(PortService.team.in_(matching_port_ids))

        rows = (
            db.query(PortService)
            .filter(or_(*svc_filters))
            .limit(limit)
            .all()
        )
        results["services"] = [
            {
                "type": "service",
                "id": r.id,
                "title": r.title,
                "subtitle": " · ".join(s for s in [r.language_version or r.language, r.system, r.team] if s),
                "url": None,
                "external_url": r.url,
            }
            for r in rows
        ]
        total += len(results["services"])

    return {"query": q, "results": results, "total": total}
