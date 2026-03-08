"""
Engineer sync service.

Fetches MR activity for all engineers in ref_members from the GitLab REST API
using scope=all + author_username — exactly like the individual engineer view.

This ensures the Engineers list and period selector show accurate data
regardless of which repos were explicitly configured for sync.
"""

import json
import logging
import re
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session

from backend.services.datetime_utils import parse_dt
from backend.services.domain_credentials import get_gitlab_settings

logger = logging.getLogger(__name__)

MAX_PAGES = 50  # Safety cap for all paginated GitLab API calls


def _build_jira_pattern(project_keys: list[str]) -> re.Pattern:
    """Build a Jira ticket regex from a list of project keys."""
    if not project_keys:
        # Fallback: match any PROJECT-NNN style key
        return re.compile(r'\b([A-Z]{2,8})-(\d+)\b')
    escaped = "|".join(re.escape(k) for k in sorted(project_keys, key=len, reverse=True))
    return re.compile(rf'\b({escaped})-(\d+)\b')


def _extract_jira_tickets(branch: str | None, title: str | None, pattern: re.Pattern) -> str | None:
    """Extract Jira ticket keys from branch name and MR title. Returns JSON or None."""
    tickets: set[str] = set()
    for text in (branch or "", title or ""):
        for match in pattern.finditer(text):
            tickets.add(match.group(0))
    return json.dumps(sorted(tickets)) if tickets else None


def sync_engineers(db: Session, days: int, force_full: bool = False) -> int:
    """
    Sync MR activity for all active engineers from GitLab API.

    Uses author_username + scope=all to find MRs across ALL projects,
    not just the repos configured for each team.

    GitLab API fetches are parallelised with a thread pool (max 6 workers).
    DB writes remain sequential to respect SQLite's single-writer constraint.

    Args:
        db: SQLAlchemy session for ecosystem.db
        days: How many days back to fetch
        force_full: If True, delete existing rows for all members first,
                    then re-insert. Use to fix stale/incorrect data.

    Returns:
        Number of rows written (inserted + updated)
    """
    from backend.models_domain import RefMember, MRActivity
    from backend.core.config_loader import get_domain_config
    from backend.services.domain_registry import get_active_slug

    gitlab_settings = get_gitlab_settings()
    gitlab_token = gitlab_settings["token"]
    gitlab_url = gitlab_settings["url"]
    if not gitlab_token:
        raise RuntimeError("GitLab credentials are not configured for the active domain")

    # Build Jira ticket pattern from the active domain's project keys
    cfg = get_domain_config(get_active_slug())
    jira_pattern = _build_jira_pattern(cfg.jira_project_keys)
    logger.info(f"Jira pattern for domain '{get_active_slug()}': {cfg.jira_project_keys}")

    since = datetime.now(timezone.utc) - timedelta(days=days)
    since_iso = since.strftime("%Y-%m-%dT%H:%M:%SZ")

    members = db.query(RefMember).filter(RefMember.departed == False).all()
    logger.info(f"Syncing {len(members)} engineers for last {days} days (force_full={force_full})")

    if force_full:
        # Clean slate: remove all existing MR rows for these members
        usernames = [m.gitlab_username for m in members]
        deleted = (
            db.query(MRActivity)
            .filter(MRActivity.author_username.in_(usernames))
            .delete(synchronize_session=False)
        )
        db.commit()
        logger.info(f"force_full: deleted {deleted} existing mr_activity rows")

    # Shared HTTP session — token set once, reused for all requests
    http = requests.Session()
    http.headers["PRIVATE-TOKEN"] = gitlab_token

    # Fetch MRs in parallel (API calls only; no DB access here)
    member_mrs: dict[str, list] = {}

    def _fetch_for_member(member):
        return member.gitlab_username, _fetch_mrs(gitlab_url, http, member.gitlab_username, since_iso)

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(_fetch_for_member, m): m for m in members}
        for future in as_completed(futures):
            m = futures[future]
            try:
                username, mrs = future.result()
                member_mrs[username] = mrs
            except Exception as e:
                logger.warning(f"  {m.gitlab_username}: fetch failed — {e}")

    http.close()

    # Upsert sequentially — SQLite is a single writer
    total_written = 0
    for member in members:
        mrs = member_mrs.get(member.gitlab_username, [])
        try:
            count = _upsert_mrs(db, member, mrs, jira_pattern)
            total_written += count
            logger.info(f"  {member.gitlab_username}: {count} MRs synced")
        except Exception as e:
            logger.warning(f"  {member.gitlab_username}: upsert failed — {e}")
            try:
                db.rollback()
            except Exception:
                pass

    return total_written


def _fetch_mrs(gitlab_url: str, http: requests.Session, username: str, since_iso: str) -> list:
    """Fetch all MRs for a given author across all projects (scope=all)."""
    mrs: list = []
    page = 1
    while page <= MAX_PAGES:
        resp = http.get(
            f"{gitlab_url}/api/v4/merge_requests",
            params={
                "author_username": username,
                "created_after": since_iso,
                "state": "all",
                "scope": "all",
                "per_page": 100,
                "page": page,
                "order_by": "created_at",
                "sort": "desc",
            },
            timeout=30,
        )
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        mrs.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return mrs


def _upsert_mrs(db: Session, member, mrs: list, jira_pattern: re.Pattern) -> int:
    """Upsert MR rows for one engineer. Returns count written. Must run sequentially."""
    from backend.models_domain import MRActivity

    count = 0
    for mr_data in mrs:
        repo_id = str(mr_data.get("project_id", ""))
        mr_iid = mr_data.get("iid")
        if not repo_id or mr_iid is None:
            continue

        created_at = parse_dt(mr_data.get("created_at"))
        merged_at = parse_dt(mr_data.get("merged_at"))
        state = mr_data.get("state", "")

        branch = mr_data.get("source_branch")
        title = mr_data.get("title", "")
        jira_tickets = _extract_jira_tickets(branch, title, jira_pattern)

        existing = db.query(MRActivity).filter_by(repo_id=repo_id, mr_iid=mr_iid).first()
        if existing:
            existing.state = state
            existing.merged_at = merged_at
            existing.author_team = member.team_slug   # Fix any stale team attribution
            existing.synced_at = datetime.now(timezone.utc)
            # Backfill jira_tickets if not already extracted
            if existing.jira_tickets is None and jira_tickets:
                existing.jira_tickets = jira_tickets
        else:
            db.add(MRActivity(
                mr_iid=mr_iid,
                repo_id=repo_id,
                title=title,
                source_branch=branch,
                author_username=member.gitlab_username,
                author_team=member.team_slug,
                state=state,
                created_at=created_at,
                merged_at=merged_at,
                web_url=mr_data.get("web_url"),
                jira_tickets=jira_tickets,
                synced_at=datetime.now(timezone.utc),
            ))
        count += 1

    db.commit()
    return count


def _fetch_commit_count(gitlab_url: str, http: requests.Session, username: str, since_iso: str) -> int:
    """Fetch commit count for an engineer via GitLab push events."""
    try:
        resp = http.get(
            f"{gitlab_url}/api/v4/users",
            params={"username": username},
            timeout=10,
        )
        resp.raise_for_status()
        users = resp.json()
        if not users:
            return 0
        user_id = users[0]["id"]

        count = 0
        page = 1
        while page <= MAX_PAGES:
            ev_resp = http.get(
                f"{gitlab_url}/api/v4/users/{user_id}/events",
                params={"action": "pushed", "created_after": since_iso, "per_page": 100, "page": page},
                timeout=20,
            )
            ev_resp.raise_for_status()
            events = ev_resp.json()
            if not events:
                break
            for ev in events:
                count += ev.get("push_data", {}).get("commit_count", 0)
            if len(events) < 100:
                break
            page += 1
        return count
    except Exception as e:
        logger.warning(f"Commit count fetch failed for {username}: {e}")
        return 0


def _fetch_review_count(gitlab_url: str, http: requests.Session, username: str, since_iso: str) -> int:
    """Fetch review count (MRs where user is a reviewer)."""
    try:
        count = 0
        page = 1
        while page <= MAX_PAGES:
            resp = http.get(
                f"{gitlab_url}/api/v4/merge_requests",
                params={
                    "reviewer_username": username,
                    "created_after": since_iso,
                    "state": "all",
                    "scope": "all",
                    "per_page": 100,
                    "page": page,
                },
                timeout=20,
            )
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                break
            count += len(batch)
            if len(batch) < 100:
                break
            page += 1
        return count
    except Exception as e:
        logger.warning(f"Review count fetch failed for {username}: {e}")
        return 0


def preload_engineer_stats(db: Session, days: int) -> int:
    """
    Pre-populate engineer_stats (commit + review counts) for all active engineers.

    Called after sync_engineers() so that individual engineer pages load
    instantly without triggering a per-user live GitLab fetch.

    API fetches are parallelised (max 6 workers). DB writes are batched into
    a single commit at the end to avoid repeated SQLite round-trips.

    Returns:
        Number of engineers whose stats were written.
    """
    from backend.models_domain import RefMember, EngineerStats

    gitlab_settings = get_gitlab_settings()
    gitlab_token = gitlab_settings["token"]
    gitlab_url = gitlab_settings["url"]
    if not gitlab_token:
        logger.warning("GitLab credentials are not configured for the active domain — skipping engineer stats preload")
        return 0

    since = datetime.now(timezone.utc) - timedelta(days=days)
    since_iso = since.strftime("%Y-%m-%dT%H:%M:%SZ")

    members = db.query(RefMember).filter(RefMember.departed == False).all()
    logger.info(f"Preloading stats for {len(members)} engineers (days={days})")

    http = requests.Session()
    http.headers["PRIVATE-TOKEN"] = gitlab_token

    # Fetch commit + review counts in parallel
    fetch_results: dict[str, tuple[int, int]] = {}

    def _fetch_for_member(member):
        username = member.gitlab_username
        commits = _fetch_commit_count(gitlab_url, http, username, since_iso)
        reviews = _fetch_review_count(gitlab_url, http, username, since_iso)
        return username, commits, reviews

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(_fetch_for_member, m): m for m in members}
        for future in as_completed(futures):
            m = futures[future]
            try:
                username, commits, reviews = future.result()
                fetch_results[username] = (commits, reviews)
                logger.info(f"  {username}: commits={commits}, reviews={reviews}")
            except Exception as e:
                logger.warning(f"  {m.gitlab_username}: stats preload failed — {e}")

    http.close()

    # Write all results sequentially, single commit at end
    now = datetime.now(timezone.utc)
    written = 0
    for member in members:
        username = member.gitlab_username
        if username not in fetch_results:
            continue
        commit_count, review_count = fetch_results[username]
        stats_row = db.query(EngineerStats).filter_by(
            username=username.lower(), period_days=days
        ).first()
        if stats_row:
            stats_row.commit_count = commit_count
            stats_row.review_count = review_count
            stats_row.cached_at = now
        else:
            db.add(EngineerStats(
                username=username.lower(),
                period_days=days,
                commit_count=commit_count,
                review_count=review_count,
            ))
        written += 1

    db.commit()
    return written
