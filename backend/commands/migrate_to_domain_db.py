"""
One-time migration: eng_dashboard.db → ecosystem.db

Copies gitlab_mr_activity and gitlab_metrics into the new domain tables.
Safe to re-run (skips existing rows).

Usage:
    uv run python backend/commands/migrate_to_domain_db.py
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Project root on sys.path so "backend.*" imports resolve uniformly.
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from datetime import datetime, date
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from backend.database_domain import get_ecosystem_engine, DomainBase
from backend.models_domain import MRActivity, TeamMetrics, RefMember

OLD_DB = str(PROJECT_ROOT / "eng_dashboard.db")

_DT_FORMATS = [
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S",
]


def parse_dt(value) -> datetime | None:
    """Convert string timestamps stored in old DB into datetime objects."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        for fmt in _DT_FORMATS:
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
        raise ValueError(f"Cannot parse datetime: {value!r}")
    return value  # pass through if already date/datetime


def parse_date(value) -> date | None:
    """Convert string dates stored in old DB into date objects."""
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        # Try date-only first, then full datetime
        for fmt in ["%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"]:
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
        raise ValueError(f"Cannot parse date: {value!r}")
    return value


def resolve_team(username: str, domain_session) -> str:
    """Look up canonical team from ref_members (config is authoritative)."""
    m = domain_session.query(RefMember).filter(
        RefMember.gitlab_username.ilike(username)
    ).first()
    return m.team_slug if m else "unknown"


def migrate():
    old_engine = create_engine(
        f"sqlite:///{OLD_DB}",
        connect_args={"check_same_thread": False},
    )
    OldSession = sessionmaker(bind=old_engine)

    # Create tables directly using the already-imported DomainBase metadata.
    # We do NOT call init_domain_db() here because that function uses
    # `from backend.models_domain import ...` which would cause a double-import
    # and SQLAlchemy "Table already defined" error.
    domain_engine = get_ecosystem_engine()
    DomainBase.metadata.create_all(bind=domain_engine)
    DomainSession = sessionmaker(bind=domain_engine)

    with OldSession() as old_db, DomainSession() as new_db:
        # Check what tables exist in old DB
        tables = [
            r[0]
            for r in old_db.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            ).fetchall()
        ]
        print(f"Tables in eng_dashboard.db: {sorted(tables)}")

        # --- MR Activity ---
        if "gitlab_mr_activity" in tables:
            rows = old_db.execute(
                text("SELECT * FROM gitlab_mr_activity")
            ).fetchall()
            print(f"Migrating {len(rows)} MR activity rows...")
            migrated = 0
            skipped = 0
            for r in rows:
                existing = new_db.query(MRActivity).filter_by(
                    repo_id=str(r.repo_id), mr_iid=r.mr_iid
                ).first()
                if existing:
                    skipped += 1
                    continue
                author_team = resolve_team(r.author_username, new_db)
                new_db.add(MRActivity(
                    mr_iid=r.mr_iid,
                    repo_id=str(r.repo_id),
                    title=r.title,
                    description=getattr(r, "description", None),
                    source_branch=getattr(r, "source_branch", None),
                    author_username=r.author_username,
                    author_team=author_team,
                    state=r.state,
                    created_at=parse_dt(r.created_at),
                    merged_at=parse_dt(getattr(r, "merged_at", None)),
                    web_url=getattr(r, "web_url", None),
                    jira_tickets=getattr(r, "jira_tickets", None),
                    epic_keys=getattr(r, "epic_keys", None),
                    lines_added=getattr(r, "lines_added", None),
                    lines_removed=getattr(r, "lines_removed", None),
                    files_changed=getattr(r, "files_changed", None),
                    cycle_time_hours=getattr(r, "cycle_time_hours", None),
                    synced_at=parse_dt(getattr(r, "synced_at", None)),
                ))
                migrated += 1
            new_db.commit()
            print(
                f"MR activity: {migrated} new rows migrated, {skipped} already present."
            )
        else:
            print("WARNING: gitlab_mr_activity table not found in eng_dashboard.db")

        # --- Team Metrics ---
        if "gitlab_metrics" in tables:
            rows = old_db.execute(
                text("SELECT * FROM gitlab_metrics")
            ).fetchall()
            print(f"Migrating {len(rows)} team metrics rows...")
            migrated = 0
            skipped = 0
            for r in rows:
                existing = new_db.query(TeamMetrics).filter_by(
                    team=r.team, metric_date=r.metric_date
                ).first()
                if existing:
                    skipped += 1
                    continue
                # gitlab_metrics uses `merge_requests_merged`; mrs_merged is the domain column
                mrs_merged_val = getattr(r, "merge_requests_merged", None)
                if mrs_merged_val is None:
                    mrs_merged_val = getattr(r, "mrs_merged", 0)
                new_db.add(TeamMetrics(
                    team=r.team,
                    metric_date=parse_date(r.metric_date),
                    pipeline_runs=getattr(r, "pipeline_runs", 0) or 0,
                    pipeline_success=getattr(r, "pipeline_success", 0) or 0,
                    pipeline_failed=getattr(r, "pipeline_failed", 0) or 0,
                    avg_duration_seconds=getattr(r, "avg_duration_seconds", None),
                    mrs_merged=mrs_merged_val or 0,
                    avg_cycle_time_hours=getattr(r, "avg_mr_cycle_time_hours", None),
                    deployment_frequency=getattr(r, "deployment_frequency", None),
                    lead_time_hours=getattr(r, "lead_time_hours", None),
                    change_failure_rate=getattr(r, "change_failure_rate", None),
                    mttr_hours=getattr(r, "mttr_hours", None),
                    dora_level=getattr(r, "dora_level", None),
                    synced_at=parse_dt(getattr(r, "synced_at", None)),
                ))
                migrated += 1
            new_db.commit()
            print(
                f"Team metrics: {migrated} new rows migrated, {skipped} already present."
            )
        else:
            print("WARNING: gitlab_metrics table not found in eng_dashboard.db")

    print("\nMigration complete.")


if __name__ == "__main__":
    migrate()
