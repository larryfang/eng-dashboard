# Sync team_metrics, jira_epics, dora Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Wire `team_metrics`, `jira_epics`, and `dora` sections in `sync_router.py` so triggering `POST /api/sync/{section}` actually fetches and persists data into `ecosystem.db`.

**Architecture:**
- `jira_epics` sync: Calls `JiraAPIService.search_epics()` → upserts into `jira_epics` table in ecosystem.db using the existing `JiraEpic` ORM model.
- `team_metrics` + `dora` sync: Reads `mr_activity` already in ecosystem.db, computes per-team-per-day metrics (deployment_frequency, lead_time_hours, cycle_time, dora_level), and upserts into `team_metrics`.
- Both new services follow the exact same pattern as `engineer_sync_service.py`.

**Tech Stack:** Python, SQLAlchemy, FastAPI BackgroundTasks, existing `JiraAPIService`, existing `JiraEpic` + `TeamMetrics` ORM models.

---

## Key Reference

### Existing pattern (engineer_sync_service.py → sync_router.py)
```python
# sync_router.py wiring pattern:
def _sync_engineers_bg(days: int, force_full: bool) -> None:
    engine = get_ecosystem_engine()
    _Session = _sessionmaker(bind=engine)
    db = _Session()
    try:
        count = sync_engineers(db, days, force_full=force_full)
        mark_sync_complete(db, "engineers", days, count)
    except Exception as e:
        # mark error on row
    finally:
        db.close()

# Triggered by:
if section == "engineers":
    background_tasks.add_task(_sync_engineers_bg, days, force_full)
```

### ORM models to write to (backend/models_domain.py)
```python
class TeamMetrics(DomainBase):
    __tablename__ = "team_metrics"
    team, metric_date            # UniqueConstraint("team", "metric_date")
    mrs_merged, avg_cycle_time_hours
    deployment_frequency         # merged MRs/week for that date's window
    lead_time_hours              # avg open→merge hours
    change_failure_rate          # 0.0 placeholder (no pipeline data)
    mttr_hours                   # 0.0 placeholder
    dora_level                   # "Elite"/"High"/"Medium"/"Low"

class JiraEpic(DomainBase):
    __tablename__ = "jira_epics"
    key                          # unique
    project, team, summary, status, status_category
    priority, assignee, url
    progress_percent, child_issues_total, child_issues_done
    updated_date, due_date
```

### DORA level thresholds (based on merged MR frequency as deployment proxy)
```python
def _dora_level(deploy_freq_per_week: float, lead_time_hours: float) -> str:
    if deploy_freq_per_week >= 5 and lead_time_hours < 24:
        return "Elite"
    if deploy_freq_per_week >= 1 and lead_time_hours < 168:  # 7 days
        return "High"
    if deploy_freq_per_week >= 0.25 and lead_time_hours < 720:  # 30 days
        return "Medium"
    return "Low"
```

---

## Task 1: jira_epics sync service

**Files:**
- Create: `backend/services/jira_epics_sync_service.py`

**Step 1: Create the service file**

```python
"""
Jira Epics Sync Service

Fetches epics from Jira REST API and upserts into jira_epics table
in ecosystem.db. Called by sync_router for the 'jira_epics' section.
"""
import logging
from datetime import datetime, timezone
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def sync_jira_epics(db: Session) -> int:
    """
    Fetch all epics from configured Jira projects and upsert into jira_epics.

    Returns:
        Number of epics upserted.
    """
    from backend.services.jira_api_service import JiraAPIService
    from backend.core.config_loader import get_config
    from backend.models_domain import JiraEpic

    jira = JiraAPIService()
    if not jira.is_configured:
        raise RuntimeError("Jira not configured — set JIRA_URL, JIRA_EMAIL, JIRA_API_TOKEN")

    cfg = get_config()
    project_to_team = cfg.project_to_team_map   # {project_key: team_name}
    projects = list(project_to_team.keys())
    if not projects:
        raise RuntimeError("No Jira projects configured in organization.yaml")

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

        # Parse dates
        updated_raw = f.get("updated")
        due_raw = f.get("duedate")
        updated_dt = _parse_dt(updated_raw)
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
    return upserted


def _parse_dt(s: str | None):
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None
```

**Step 2: Verify it's importable**

```bash
cd /path/to/eng-dashboard
uv run python -c "from backend.services.jira_epics_sync_service import sync_jira_epics; print('OK')"
```
Expected: `OK`

---

## Task 2: team_metrics + dora sync service

**Files:**
- Create: `backend/services/team_metrics_sync_service.py`

**Step 1: Create the service file**

```python
"""
Team Metrics Sync Service

Computes per-team daily DORA metrics from mr_activity in ecosystem.db
and upserts into team_metrics table.

Called by sync_router for both 'team_metrics' and 'dora' sections.

Data sources:
  - mr_activity.created_at / merged_at / author_team — from ecosystem.db
  - No external API calls needed

Metrics computed:
  - mrs_merged: count of merged MRs per team per day
  - avg_cycle_time_hours: avg hours from created_at to merged_at
  - deployment_frequency: merged MRs/week (rolling window ending on metric_date)
  - lead_time_hours: same as avg_cycle_time_hours (proxy)
  - dora_level: Elite/High/Medium/Low from frequency + lead_time thresholds
"""
import logging
from datetime import datetime, timedelta, timezone, date
from collections import defaultdict
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def sync_team_metrics(db: Session, days: int) -> int:
    """
    Compute team metrics from mr_activity and upsert into team_metrics.

    Args:
        db: ecosystem.db session
        days: Number of days back to compute

    Returns:
        Number of rows written (upserted).
    """
    from backend.models_domain import MRActivity, TeamMetrics, RefTeam

    since = datetime.now(timezone.utc) - timedelta(days=days)

    # Fetch all relevant MR activity
    rows = (
        db.query(MRActivity)
        .filter(MRActivity.created_at >= since)
        .all()
    )
    logger.info(f"Computing team metrics from {len(rows)} MR rows (days={days})")

    # Group by team and date
    # daily_merged[team][date] = list of cycle_time_hours for merged MRs
    daily_merged: dict = defaultdict(lambda: defaultdict(list))
    # all_opened[team][date] = count of opened MRs (for context)
    daily_opened: dict = defaultdict(lambda: defaultdict(int))

    for r in rows:
        if not r.author_team:
            continue
        day = r.created_at.date() if r.created_at else None
        if not day:
            continue
        daily_opened[r.author_team][day] += 1
        if r.state == "merged" and r.merged_at and r.created_at:
            cycle_hours = (r.merged_at - r.created_at).total_seconds() / 3600
            merge_day = r.merged_at.date()
            daily_merged[r.author_team][merge_day].append(max(0.0, cycle_hours))

    # Get all teams from ref_teams
    teams = db.query(RefTeam).all()
    team_slugs = [t.slug for t in teams]
    if not team_slugs:
        # Fall back to teams seen in mr_activity
        team_slugs = list(set(daily_merged.keys()) | set(daily_opened.keys()))

    now = datetime.now(timezone.utc)
    written = 0

    for team_slug in team_slugs:
        # Collect all dates that had any MR activity for this team
        dates_with_activity: set = set()
        dates_with_activity.update(daily_opened.get(team_slug, {}).keys())
        dates_with_activity.update(daily_merged.get(team_slug, {}).keys())

        if not dates_with_activity:
            # Still write a summary row for today so the team shows up
            dates_with_activity = {date.today()}

        for metric_date in dates_with_activity:
            cycle_times = daily_merged.get(team_slug, {}).get(metric_date, [])
            mrs_merged_count = len(cycle_times)
            avg_cycle = (sum(cycle_times) / len(cycle_times)) if cycle_times else None

            # Deployment frequency = merged MRs in the 7-day window ending on metric_date
            week_start = metric_date - timedelta(days=6)
            week_merged = sum(
                len(daily_merged.get(team_slug, {}).get(
                    week_start + timedelta(days=i), []
                ))
                for i in range(7)
            )
            deploy_freq = week_merged / 7 * 7  # MRs/week (sum of 7 days)

            dora = _dora_level(deploy_freq, avg_cycle or 999)

            existing = (
                db.query(TeamMetrics)
                .filter_by(team=team_slug, metric_date=metric_date)
                .first()
            )
            if existing:
                existing.mrs_merged = mrs_merged_count
                existing.avg_cycle_time_hours = avg_cycle
                existing.deployment_frequency = deploy_freq
                existing.lead_time_hours = avg_cycle
                existing.change_failure_rate = 0.0
                existing.mttr_hours = 0.0
                existing.dora_level = dora
                existing.synced_at = now
            else:
                db.add(TeamMetrics(
                    team=team_slug,
                    metric_date=metric_date,
                    mrs_merged=mrs_merged_count,
                    avg_cycle_time_hours=avg_cycle,
                    deployment_frequency=deploy_freq,
                    lead_time_hours=avg_cycle,
                    change_failure_rate=0.0,
                    mttr_hours=0.0,
                    dora_level=dora,
                    synced_at=now,
                ))
            written += 1

    db.commit()
    logger.info(f"team_metrics sync complete: {written} rows written")
    return written


def _dora_level(deploy_freq_per_week: float, lead_time_hours: float) -> str:
    """
    Classify DORA level from deployment frequency (MRs/week) and lead time.

    Thresholds based on MR merge frequency as a deployment proxy:
      Elite:  ≥5/week  AND  lead time < 24h
      High:   ≥1/week  AND  lead time < 168h (7 days)
      Medium: ≥1/month AND  lead time < 720h (30 days)
      Low:    anything worse
    """
    if deploy_freq_per_week >= 5 and lead_time_hours < 24:
        return "Elite"
    if deploy_freq_per_week >= 1 and lead_time_hours < 168:
        return "High"
    if deploy_freq_per_week >= 0.25 and lead_time_hours < 720:
        return "Medium"
    return "Low"
```

**Step 2: Verify import**

```bash
uv run python -c "from backend.services.team_metrics_sync_service import sync_team_metrics; print('OK')"
```
Expected: `OK`

---

## Task 3: Wire all three into sync_router.py

**Files:**
- Modify: `backend/routers/sync_router.py`

**Step 1: Add three background task functions after the existing `_sync_engineers_bg`**

After line 103 (`finally: db.close()`), add:

```python

def _sync_jira_epics_bg() -> None:
    """Background task: fetch Jira epics and upsert into ecosystem.db."""
    from backend.database_domain import get_ecosystem_engine
    from sqlalchemy.orm import sessionmaker as _sessionmaker
    from backend.services.jira_epics_sync_service import sync_jira_epics

    engine = get_ecosystem_engine()
    _Session = _sessionmaker(bind=engine)
    db = _Session()
    try:
        count = sync_jira_epics(db)
        mark_sync_complete(db, "jira_epics", 0, count)
        logger.info(f"Jira epics sync done: {count} epics upserted")
    except Exception as e:
        logger.error(f"Jira epics sync failed: {e}")
        row = _get_or_create_status(db, "jira_epics", 0)
        row.status = "error"
        row.error_message = str(e)
        try:
            db.commit()
        except Exception:
            pass
    finally:
        db.close()


def _sync_team_metrics_bg(days: int) -> None:
    """Background task: compute team metrics from mr_activity into ecosystem.db."""
    from backend.database_domain import get_ecosystem_engine
    from sqlalchemy.orm import sessionmaker as _sessionmaker
    from backend.services.team_metrics_sync_service import sync_team_metrics

    engine = get_ecosystem_engine()
    _Session = _sessionmaker(bind=engine)
    db = _Session()
    try:
        count = sync_team_metrics(db, days)
        mark_sync_complete(db, "team_metrics", days, count)
        logger.info(f"Team metrics sync done: {count} rows written (days={days})")
    except Exception as e:
        logger.error(f"Team metrics sync failed: {e}")
        row = _get_or_create_status(db, "team_metrics", days)
        row.status = "error"
        row.error_message = str(e)
        try:
            db.commit()
        except Exception:
            pass
    finally:
        db.close()


def _sync_dora_bg(days: int) -> None:
    """Background task: same computation as team_metrics — computes dora_level per team."""
    from backend.database_domain import get_ecosystem_engine
    from sqlalchemy.orm import sessionmaker as _sessionmaker
    from backend.services.team_metrics_sync_service import sync_team_metrics

    engine = get_ecosystem_engine()
    _Session = _sessionmaker(bind=engine)
    db = _Session()
    try:
        count = sync_team_metrics(db, days)
        mark_sync_complete(db, "dora", days, count)
        logger.info(f"DORA sync done: {count} rows written (days={days})")
    except Exception as e:
        logger.error(f"DORA sync failed: {e}")
        row = _get_or_create_status(db, "dora", days)
        row.status = "error"
        row.error_message = str(e)
        try:
            db.commit()
        except Exception:
            pass
    finally:
        db.close()
```

**Step 2: Wire into `trigger_sync` handler**

In the `trigger_sync` function, replace:
```python
    if section == "engineers":
        background_tasks.add_task(_sync_engineers_bg, days, force_full)

    return {"status": "syncing", ...}
```

With:
```python
    if section == "engineers":
        background_tasks.add_task(_sync_engineers_bg, days, force_full)
    elif section == "jira_epics":
        background_tasks.add_task(_sync_jira_epics_bg)
    elif section == "team_metrics":
        background_tasks.add_task(_sync_team_metrics_bg, days)
    elif section == "dora":
        background_tasks.add_task(_sync_dora_bg, days)

    return {"status": "syncing", ...}
```

**Step 3: Verify by triggering a sync and checking status**

```bash
# Trigger all three
curl -s -X POST "http://localhost:9001/api/sync/jira_epics" | python3 -m json.tool
curl -s -X POST "http://localhost:9001/api/sync/team_metrics?days=30" | python3 -m json.tool
curl -s -X POST "http://localhost:9001/api/sync/dora?days=30" | python3 -m json.tool

# Wait 20s, then check status
sleep 20 && curl -s "http://localhost:9001/api/sync/status" | python3 -m json.tool
```

Expected: `jira_epics`, `team_metrics`, `dora` all show `"status": "success"` and `records_synced > 0`.

**Step 4: Verify data landed in ecosystem.db**

```bash
uv run python -c "
from backend.database_domain import get_ecosystem_engine
from sqlalchemy.orm import sessionmaker
from backend.models_domain import JiraEpic, TeamMetrics
db = sessionmaker(bind=get_ecosystem_engine())()
print('JiraEpics:', db.query(JiraEpic).count())
print('TeamMetrics:', db.query(TeamMetrics).count())
"
```
Expected: both counts > 0.

---

## Notes

- `jira_epics` uses `period_days=0` in `sync_status` (not period-specific — all epics are fetched).
- `team_metrics` and `dora` share the same computation. They're separate sections only so the UI can trigger/track them independently.
- `change_failure_rate` and `mttr_hours` default to `0.0` — real values require GitLab pipeline failure data (future enhancement).
- The `dora` section in the Dora page (`/api/gitlab/metrics`) still reads from the existing `get_dora_service()` / sinch_pa.db. The new `team_metrics` table is available for future period-aware DORA endpoints.
