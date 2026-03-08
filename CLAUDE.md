# eng-dashboard — Engineering Director Dashboard

## Project Overview

React + FastAPI dashboard for tracking GitLab activity, Jira tickets, DORA metrics, and Port service catalog across engineering teams.

- **Frontend**: React/Vite on port 5173
- **Backend**: FastAPI on port 9001
- **Package manager**: uv (backend), npm (frontend)

## Architecture

### Two-Database Design

| DB | Path | Purpose |
|----|------|---------|
| `eng_dashboard.db` | `data/eng_dashboard.db` | Legacy personal data |
| `ecosystem.db` | `data/domains/ecosystem.db` | Dashboard data (domain-isolated) |

All dashboard endpoints read from `ecosystem.db`. The `data/domains/` directory is gitignored except for `.gitkeep`.

### Domain Isolation

Each director gets their own isolated DB at `data/domains/{slug}.db`. The slug comes from `organization.yaml → organization.slug`.

### Reference Data (Authoritative)

Team membership is determined by `ref_members` table (seeded from `organization.yaml`), NOT by which GitLab repo an engineer committed to. An engineer contributing to another team's repo still appears under their own team.

## Key Implementation Rules

### Individual Engineer View — ALWAYS Query GitLab API Directly

For `GET /api/gitlab/engineers/{username}`, **ALWAYS** fetch live from the GitLab REST API. Do NOT rely on the cached `mr_activity` table — it only covers repos that were explicitly synced and will miss MRs from other projects.

```python
resp = requests.get(
    f"{gitlab_url}/api/v4/merge_requests",
    params={
        "author_username": username,
        "created_after": since_iso,
        "state": "all",
        "scope": "all",   # REQUIRED — without this returns 0 results
        "per_page": 100,
        "page": page,
        "order_by": "created_at",
        "sort": "desc",
    },
    headers={"PRIVATE-TOKEN": gitlab_token},
    timeout=20,
)
```

- `scope=all` is **REQUIRED** — omitting it makes the GitLab API return 0 results
- Use `PRIVATE-TOKEN` header with `GITLAB_TOKEN` env var
- The list view (`/engineers`) may remain limited by what's in the DB cache

### Engineer List View — Case-Insensitive Username Matching

GitLab usernames can be stored with mixed case in `mr_activity` (e.g., `Liam.Herbert`). Always use SQL-level `func.lower()` for matching, not Python-side string manipulation:

```python
from sqlalchemy import func as sqlfunc
query = query.filter(
    sqlfunc.lower(MRActivity.author_username).in_(team_usernames_lower)
)
```

### Show All Roster Members (Even Zero-MR)

The engineer list must show all members from `ref_members`, even those with 0 MRs in the current period. This prevents engineers from "disappearing" due to data gaps:

```python
# Build result for ALL known members
for lower_username, member in member_by_lower.items():
    if member.departed: continue
    stats = authors.get(lower_username, {"mrs_opened": 0, "mrs_merged": 0, "last_activity": None})
    results.append({...})
```

### Dashboard MR Counts — Use ecosystem.db, Not DORA Metrics

The Dashboard period selector (30d/60d/90d) must use `mr_activity` from `ecosystem.db`. The old `gitlab_metrics` table only spans 30 days and will show identical data across all periods.

Use `GET /api/gitlab/team-summary?days=N` which reads from `ecosystem.db.mr_activity`.

## Import Pattern

**ALL files within `backend/` MUST use the `backend.` prefix:**
```python
from backend.database_domain import get_ecosystem_session   # ✅
from database_domain import get_ecosystem_session            # ❌ NEVER bare imports
```

The backend runs from the project root (`uvicorn backend.main:app`), so `backend.` is the only valid import path. Bare imports cause dual module identity — Python loads the same file under two names, and SQLAlchemy tries to register tables twice.

## Key Files

| File | Purpose |
|------|---------|
| `backend/database_domain.py` | Domain engine factory — `get_ecosystem_session()`, `init_domain_db()` |
| `backend/models_domain.py` | ORM models for all 7 domain DB tables |
| `backend/services/domain_seeder.py` | Seeds `ref_teams` + `ref_members` from YAML on startup |
| `backend/routers/gitlab_collector_router.py` | GitLab sync, DORA metrics, engineer endpoints |
| `backend/routers/sync_router.py` | Sync status GET/POST endpoints |
| `config/organization.yaml` | Team + engineer roster (source of truth) |

## Domain DB Tables

| Table | Type | Purpose |
|-------|------|---------|
| `ref_teams` | Reference | Team config from YAML |
| `ref_members` | Reference | Engineer roster — authoritative team membership |
| `mr_activity` | Transactional | MR history with team attribution |
| `team_metrics` | Transactional | Daily DORA/pipeline data |
| `jira_epics` | Transactional | Jira epic cache |
| `sync_status` | Control | Per-section sync state and TTL |
| `section_cache` | Control | Cached responses per section+period |

## Common Mistakes

| ❌ Don't | ✅ Do |
|---------|------|
| Query `mr_activity` for individual engineer detail | Query GitLab REST API directly with `scope=all` |
| Omit `scope=all` in GitLab MR API calls | Always include `scope=all` — required for cross-project search |
| Use Python-side string case conversion for username matching | Use `sqlfunc.lower()` in SQLAlchemy queries |
| Read DORA metrics for Dashboard MR counts | Read from `ecosystem.db.mr_activity` via `/api/gitlab/team-summary` |
| Use bare imports like `from models_domain import ...` | Always use `backend.` prefix — `from backend.models_domain import ...` |
| Show only engineers with MR activity in list view | Always include all `ref_members` (0-MR members included) |

## Notification System

Alerts are pushed directly to Telegram via the Bot API.

### Architecture

- **`backend/services/notification_service.py`** — `TelegramNotifier` singleton that sends HTML-formatted messages via httpx to the Telegram Bot API. Includes per-alert-type cooldown (in-memory dict, keyed by `alert_type`, minimum gap of `ALERT_COOLDOWN_MINUTES`).
- **`backend/services/team_trend_alerts.py`** — Compares current vs prior 7-day MR counts per team from `mr_activity`. Flags teams with drop >= `ALERT_DORA_DEGRADATION_PCT`%.
- **`backend/services/quiet_engineer_alerts.py`** — Checks `ref_members` (active, non-departed, non-excluded) against `mr_activity` for recent work. Flags engineers with no MRs in `QUIET_ENGINEER_DAYS`.
- **`backend/services/jira_epic_health.py`** — Queries `jira_epics` for items not updated within `ALERT_JIRA_STALE_DAYS` whose status is not Done/Closed/Cancelled/Resolved.

### Alert Schedule (wired in `scheduler.py`)

| Alert | Trigger | Frequency |
|-------|---------|-----------|
| Team MR trends | After successful engineer sync | Per sync cycle (~1h) with 4h cooldown |
| Quiet engineers | Daily | Once per calendar day |
| Stalled epics | Weekly Monday | Once per Monday |

All alerts run via `asyncio.to_thread()` and are wrapped in try/except — they never crash the scheduler.

### Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `TELEGRAM_BOT_TOKEN` | — | Telegram Bot API token (from @BotFather) |
| `TELEGRAM_CHAT_ID` | — | Target chat/group ID |
| `ALERT_COOLDOWN_MINUTES` | 240 | Minimum gap between same alert type |
| `ALERT_DORA_DEGRADATION_PCT` | 20 | MR drop % threshold for trend alerts |
| `QUIET_ENGINEER_DAYS` | 10 | Days of inactivity before flagging |
| `ALERT_JIRA_STALE_DAYS` | 7 | Days since last epic update before flagging |
