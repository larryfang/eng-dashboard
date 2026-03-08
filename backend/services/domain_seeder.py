"""
Domain Seeder — seeds ref_teams and ref_members from organization.yaml.

Called during application startup (lifespan) and available as a POST endpoint
for manual re-seeding after config changes.
"""
import json
import logging
from typing import Dict, Any

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def seed_reference_data(db: Session, domain_slug: str | None = None) -> Dict[str, Any]:
    """
    Upsert ref_teams and ref_members from the domain's organization config.

    Strategy:
    - Look up existing row by slug (teams) or gitlab_username (members)
    - Update all fields if found; insert new row if not found
    - Returns counts of teams and members written

    Args:
        db: SQLAlchemy Session bound to the domain DB
        domain_slug: Domain slug to load config for. If None, falls back to
                     the legacy get_config() singleton (backward compat).

    Returns:
        Dict with keys "teams" and "members" containing integer counts
    """
    # Use backend.models_domain to match database_domain.py's import path,
    # preventing SQLAlchemy "table already defined" errors from double-import.
    from backend.models_domain import RefTeam, RefMember

    if domain_slug:
        from backend.core.config_loader import get_domain_config
        config = get_domain_config(domain_slug)
    else:
        from backend.core.config_loader import get_config
        config = get_config()

    team_count = 0
    member_count = 0

    for team in config.teams:
        # slug is always set (Team.__post_init__ derives it if missing)
        slug = team.slug or team.key.lower().replace(" ", "_")

        # Upsert ref_teams
        existing_team = db.query(RefTeam).filter(RefTeam.slug == slug).first()
        if existing_team is None:
            existing_team = RefTeam(slug=slug)
            db.add(existing_team)
            logger.debug(f"Inserting team: {slug}")
        else:
            logger.debug(f"Updating team: {slug}")

        existing_team.key = team.key
        existing_team.name = team.name
        existing_team.scrum_name = team.scrum_name
        existing_team.jira_project = team.jira_project
        existing_team.gitlab_path = team.gitlab_path
        existing_team.headcount = team.headcount or 0
        existing_team.em_name = team.lead
        existing_team.em_email = team.lead_email
        existing_team.products = json.dumps(team.products) if team.products else None

        team_count += 1

        # Upsert ref_members (gitlab_members only)
        for member in team.gitlab_members:
            username = member.username
            existing_member = (
                db.query(RefMember)
                .filter(RefMember.gitlab_username == username)
                .first()
            )
            if existing_member is None:
                existing_member = RefMember(gitlab_username=username)
                db.add(existing_member)
                logger.debug(f"Inserting member: {username} ({slug})")
            else:
                logger.debug(f"Updating member: {username} ({slug})")

            existing_member.name = member.name
            existing_member.email = member.email
            existing_member.role = member.role or "engineer"
            existing_member.team_slug = slug
            existing_member.team_display = team.name
            existing_member.em_name = team.lead
            existing_member.em_email = team.lead_email
            existing_member.jira_project = team.jira_project
            existing_member.jira_account_id = member.jira_account_id
            existing_member.gitlab_path = team.gitlab_path
            existing_member.exclude_from_metrics = member.exclude_from_metrics
            existing_member.departed = member.departed

            member_count += 1

    db.commit()
    logger.info(f"Seeded {team_count} teams and {member_count} members into domain DB")
    return {"teams": team_count, "members": member_count}
