"""
Epics Sync Service

Provider-agnostic entry point for syncing epics into jira_epics table
in ecosystem.db. Routes to Jira or GitHub sync implementations.

For Jira: directly calls the existing sync_jira_epics() logic.
For GitHub: uses the issue_tracker plugin interface.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from backend.services.datetime_utils import parse_dt

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Provider-agnostic entry point
# ---------------------------------------------------------------------------

def sync_epics(db: Session, provider: Optional[str] = None) -> int:
    """
    Sync epics from the configured issue tracker.

    Routes to provider-specific sync implementation.
    For Jira, this calls the existing sync_jira_epics().
    For GitHub, this calls _sync_github_epics() using the plugin interface.

    Args:
        db: SQLAlchemy session for ecosystem.db.
        provider: "jira", "github", or None (auto-detect from domain config).

    Returns:
        Number of epics upserted.
    """
    if provider is None:
        try:
            from backend.issue_tracker.factory import _get_configured_provider
            provider = _get_configured_provider()
        except RuntimeError:
            provider = "jira"  # Legacy fallback

    if provider == "jira":
        return sync_jira_epics(db)

    if provider in ("github", "github-issues"):
        return _sync_github_epics(db)

    raise ValueError(f"Unsupported issue tracker for epic sync: {provider}")


# ---------------------------------------------------------------------------
# GitHub sync via plugin interface
# ---------------------------------------------------------------------------

def _sync_github_epics(db: Session) -> int:
    """
    Sync epics from GitHub Issues using the issue_tracker plugin interface.

    Reuses the JiraEpic ORM table — column names are Jira-flavoured but the
    data is provider-agnostic enough (key, project, team, status, etc.).

    Returns:
        Number of epics upserted.
    """
    from backend.issue_tracker.factory import create_issue_tracker
    from backend.core.config_loader import get_domain_config
    from backend.services.domain_registry import get_active_slug
    from backend.models_domain import JiraEpic  # Reuse table for now

    plugin = create_issue_tracker("github")
    cfg = get_domain_config(get_active_slug())

    # Get team keys from config
    team_keys = [t.key for t in cfg.teams]
    epics = plugin.search_epics(team_keys, exclude_done=False)

    now = datetime.now(timezone.utc)
    upserted = 0

    for epic in epics:
        existing = db.query(JiraEpic).filter_by(key=epic.key).first()
        if existing:
            existing.team = epic.team
            existing.summary = epic.summary
            existing.status = epic.status
            existing.priority = epic.priority
            existing.assignee = epic.assignee or ""
            existing.url = epic.url
            existing.updated_date = epic.updated
            existing.synced_at = now
        else:
            db.add(JiraEpic(
                key=epic.key,
                project=epic.project,
                team=epic.team,
                summary=epic.summary,
                status=epic.status,
                priority=epic.priority,
                assignee=epic.assignee or "",
                url=epic.url,
                updated_date=epic.updated,
                synced_at=now,
            ))
        upserted += 1

    db.commit()
    logger.info(f"GitHub epics sync complete: {upserted} upserted")
    return upserted


# ---------------------------------------------------------------------------
# Jira-specific sync (original implementation, unchanged)
# ---------------------------------------------------------------------------

def sync_jira_epics(db: Session) -> int:
    """
    Fetch all epics from configured Jira projects and upsert into jira_epics.
    Also populates jira_child_epic mapping for MR-to-epic correlation.

    Returns:
        Number of epics upserted.
    """
    from backend.services.jira_api_service import JiraAPIService
    from backend.core.config_loader import get_domain_config
    from backend.services.domain_registry import get_active_slug
    from backend.models_domain import JiraEpic

    jira = JiraAPIService()
    if not jira.is_configured:
        raise RuntimeError("Jira credentials are not configured for the active domain")

    cfg = get_domain_config(get_active_slug())
    project_to_team = cfg.project_to_team_map   # {project_key: team_name}
    projects = list(project_to_team.keys())
    if not projects:
        raise RuntimeError(f"No Jira projects configured for domain '{get_active_slug()}'")

    fields = [
        "summary", "status", "assignee", "priority", "updated",
        "created", "duedate", "issuetype", "project",
        "aggregateprogress", "subtasks",
    ]
    epics = jira.search_epics(projects=projects, exclude_done=False, fields=fields)
    logger.info(f"Fetched {len(epics)} epics from Jira")

    now = datetime.now(timezone.utc)
    upserted = 0
    for epic in epics:
        f = epic.get("fields", {})
        key = epic.get("key", "")
        if not key:
            continue

        project_key = (f.get("project") or {}).get("key", key.split("-")[0])
        team = project_to_team.get(project_key, "")
        status_obj = f.get("status") or {}
        status = status_obj.get("name", "")
        status_cat = (status_obj.get("statusCategory") or {}).get("name", "")
        assignee_obj = f.get("assignee") or {}
        assignee = assignee_obj.get("displayName") or assignee_obj.get("name") or ""
        priority = (f.get("priority") or {}).get("name", "")
        progress_obj = f.get("aggregateprogress") or {}
        total = progress_obj.get("total", 0)
        done_pct = (progress_obj.get("progress", 0) / total * 100) if total else None
        child_total = len(f.get("subtasks") or []) or total or 0
        child_done = progress_obj.get("progress", 0) if total else 0
        jira_url = f"{jira.jira_url}/browse/{key}" if jira.jira_url else None

        updated_raw = f.get("updated")
        due_raw = f.get("duedate")
        updated_dt = parse_dt(updated_raw)
        due_date = datetime.strptime(due_raw, "%Y-%m-%d").date() if due_raw else None

        existing = db.query(JiraEpic).filter_by(key=key).first()
        if existing:
            existing.team = team
            existing.summary = f.get("summary", "")
            existing.status = status
            existing.status_category = status_cat
            existing.priority = priority
            existing.assignee = assignee
            existing.url = jira_url
            existing.progress_percent = done_pct
            existing.child_issues_total = child_total
            existing.child_issues_done = child_done
            existing.updated_date = updated_dt
            existing.due_date = due_date
            existing.synced_at = now
        else:
            db.add(JiraEpic(
                key=key,
                project=project_key,
                team=team,
                summary=f.get("summary", ""),
                status=status,
                status_category=status_cat,
                priority=priority,
                assignee=assignee,
                url=jira_url,
                progress_percent=done_pct,
                child_issues_total=child_total,
                child_issues_done=child_done,
                updated_date=updated_dt,
                due_date=due_date,
                synced_at=now,
            ))
        upserted += 1

    db.commit()
    logger.info(f"Jira epics sync complete: {upserted} upserted")

    # Populate child ticket → epic mapping for MR correlation
    all_epic_keys: list[str] = [e["key"] for e in epics if e.get("key")]
    child_count = _sync_child_tickets(db, jira, all_epic_keys, projects)
    logger.info(f"Jira child ticket sync complete: {child_count} mappings upserted")

    return upserted


def _sync_child_tickets(db: Session, jira, epic_keys: list[str], projects: list[str]) -> int:
    """
    Fetch child issues for all synced epics and populate jira_child_epic.

    Uses 'parent' field (next-gen Jira) and 'Epic Link' / customfield_10014
    (classic Jira) to map child ticket keys → parent epic key.

    Also counts done vs total child tickets per epic and writes back
    child_issues_done, child_issues_total, and progress_percent on each
    JiraEpic row. Jira's aggregateprogress is time-based (returns 0 when no
    time estimates are set); counting child statuses is the correct approach.

    Scoped to configured projects to avoid cross-org slowness.
    Batches epic keys into groups of 30 to keep JQL queries manageable.
    Returns number of child mappings upserted.
    """
    from collections import defaultdict
    from backend.models_domain import JiraChildEpic, JiraEpic

    if not epic_keys:
        return 0

    BATCH_SIZE = 30
    total = 0
    now = datetime.now(timezone.utc)
    epic_set = set(epic_keys)
    quoted_projects = ", ".join(f'"{p}"' for p in projects)
    # Track child counts per epic across all batches
    epic_stats: dict[str, dict] = defaultdict(lambda: {"total": 0, "done": 0})

    for i in range(0, len(epic_keys), BATCH_SIZE):
        batch = epic_keys[i:i + BATCH_SIZE]
        quoted = ", ".join(f'"{k}"' for k in batch)
        # Project filter is critical for performance — avoids searching all of Jira
        jql = f'project in ({quoted_projects}) AND ("Epic Link" in ({quoted}) OR parent in ({quoted}))'

        issues = jira.search_all_issues(
            jql,
            fields=["parent", "customfield_10014", "status"],
            max_total=2000,
        )
        logger.info(f"Child ticket batch {i // BATCH_SIZE + 1}: fetched {len(issues)} issues")

        for issue in issues:
            child_key = issue.get("key", "")
            if not child_key:
                continue

            fields = issue.get("fields", {})

            # Next-gen: parent field
            parent_obj = fields.get("parent") or {}
            epic_key = parent_obj.get("key") if parent_obj.get("key") in epic_set else None

            # Classic: Epic Link (customfield_10014)
            if not epic_key:
                epic_link = fields.get("customfield_10014")
                if epic_link and isinstance(epic_link, str) and epic_link in epic_set:
                    epic_key = epic_link

            if epic_key:
                existing = db.query(JiraChildEpic).filter_by(child_key=child_key).first()
                if existing:
                    existing.epic_key = epic_key
                    existing.synced_at = now
                else:
                    db.add(JiraChildEpic(child_key=child_key, epic_key=epic_key, synced_at=now))
                total += 1

                # Count child ticket statuses for progress calculation
                status_cat = ((fields.get("status") or {}).get("statusCategory") or {}).get("name", "")
                epic_stats[epic_key]["total"] += 1
                if status_cat == "Done":
                    epic_stats[epic_key]["done"] += 1

    db.commit()

    # Write back child counts and progress % to each epic row
    for epic_key, stats in epic_stats.items():
        tot = stats["total"]
        done = stats["done"]
        epic_row = db.query(JiraEpic).filter_by(key=epic_key).first()
        if epic_row:
            epic_row.child_issues_total = tot
            epic_row.child_issues_done = done
            epic_row.progress_percent = round(done / tot * 100, 1) if tot else None
    db.commit()

    return total

