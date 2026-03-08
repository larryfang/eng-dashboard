# Engineering Director Dashboard

Track your engineers' GitLab activity, Jira tickets, DORA metrics, and Port service catalog — through a React dashboard configured from a single YAML file.

**Built for:** Directors who want visibility across multiple teams without setting up complex infrastructure.
**Philosophy:** Local-first. Runs on your laptop. No cloud required.

---

## Quick Start (5 minutes)

### Prerequisites
- Python 3.11+ with [uv](https://astral.sh/uv)
- Node.js 18+ with npm
- GitLab Personal Access Token (read_api scope)
- Jira API Token

### Steps

```bash
# 1. Clone and enter the project
git clone <your-repo-url>
cd eng-dashboard

# 2. Copy example configs
cp config/organization.example.yaml config/organization.yaml
cp .env.example .env

# 3. Add your credentials to .env
#    (see Token Setup section below)

# 4. Start the dashboard
./start.sh

# 5. Open http://localhost:5174
#    Complete the setup wizard, or edit organization.yaml directly
```

The wizard will guide you through connecting Jira and GitLab, defining your teams, and adding engineers.

---

## Configuration

### organization.yaml

All org structure lives in `config/organization.yaml`. This file is safe to commit once you've removed personal details from it (credentials always stay in `.env`).

```yaml
organization:
  name: Acme Engineering
  slug: acme-eng

user:
  name: Alex Smith
  email: alex@acme.com
  role: Director of Engineering
  timezone: America/New_York

teams:
  - key: PLAT               # Jira project key
    name: Platform
    slug: platform
    lead: Jordan Lee
    headcount: 5
    gitlab_path: acme/platform
    jira_project: PLAT
    gitlab_members:
      - username: jlee
        name: Jordan Lee
        role: TL
```

See `config/organization.example.yaml` for a full annotated template.

### .env

All credentials and secrets go here. Never commit this file.

```bash
JIRA_EMAIL=your@company.com
JIRA_API_TOKEN=your_token
JIRA_URL=https://yourcompany.atlassian.net
GITLAB_TOKEN=your_token

# Optional
PORT_CLIENT_ID=...
PORT_CLIENT_SECRET=...
SNYK_TOKEN=...
```

---

## Token Setup

### Jira API Token
1. Go to https://id.atlassian.com/manage-profile/security/api-tokens
2. Create token → copy it to `JIRA_API_TOKEN` in `.env`
3. Set `JIRA_EMAIL` to your Atlassian account email
4. Set `JIRA_URL` to `https://yourcompany.atlassian.net`

### GitLab Personal Access Token
1. Go to https://gitlab.com/-/profile/personal_access_tokens
   (or `https://gitlab.yourcompany.com/-/profile/personal_access_tokens` for self-hosted)
2. Create token with scopes: `read_api`, `read_user`
3. Copy to `GITLAB_TOKEN` in `.env`

### Port.io (optional — for service catalog)
1. Go to https://app.getport.io/settings/credentials
2. Copy Client ID and Secret to `.env`

### Snyk (optional — for security metrics)
1. Go to https://app.snyk.io/account
2. Copy token to `SNYK_TOKEN` in `.env`

---

## Dashboard Pages

| Page | Description |
|------|-------------|
| **Dashboard** | Team health grid — DORA levels, MR activity, warnings |
| **Engineers** | All engineers with aggregate metrics, sortable |
| **Engineer Detail** | Individual MR timeline, commit activity, Jira links |
| **Jira** | Team ticket board with sprint filter |
| **DORA** | Deployment frequency, lead time, CFR, MTTR charts |
| **Services** | Port.io service catalog by team |

---

## API Endpoints

The backend runs on port 9002. Key endpoints:

```
GET  /api/config                  Get current organization config
POST /api/config                  Save organization config
POST /api/config/validate         Test Jira + GitLab connections

GET  /api/gitlab/teams            All configured teams
GET  /api/gitlab/metrics          DORA metrics for all teams
GET  /api/gitlab/engineers        All engineers with aggregate metrics
GET  /api/gitlab/engineers/{user} Individual engineer detail
POST /api/gitlab/sync             Sync GitLab data (incremental)

GET  /api/jira/issues             Jira issues by team/sprint
GET  /api/port/services           Port service catalog
GET  /api/port/status             Port connection status
```

---

## Development

```bash
# Backend only
uv run uvicorn backend.main:app --port 9002 --reload

# Frontend only
cd frontend && npm run dev

# Both together
./start.sh
```

### Sync GitLab data

The dashboard needs an initial sync to populate metrics:

```bash
# Quick 30-day sync
curl -X POST "http://localhost:9002/api/gitlab/sync?days=30&background=false"

# Or via the dashboard: click "Sync" button in the Teams view
```

---

## Architecture

```
eng-dashboard/
├── backend/
│   ├── main.py                     FastAPI app (port 9002)
│   ├── database.py                 SQLite models (GitLabMetrics, JiraIssue, etc.)
│   ├── core/
│   │   └── config_loader.py        Loads organization.yaml → typed config
│   ├── routers/
│   │   ├── config_router.py        GET/POST /api/config, validate
│   │   ├── gitlab_collector_router.py  GitLab sync + DORA metrics + engineers
│   │   ├── jira_indexer_router.py  Jira issue indexing
│   │   ├── jira_report_router.py   Jira reports
│   │   └── port_router.py          Port service catalog
│   └── services/
│       ├── gitlab_intelligence/    GitLab data collection + DORA calculations
│       ├── jira_api_service.py     Jira REST API client
│       └── port_service.py         Port.io service catalog
├── frontend/
│   ├── src/
│   │   ├── api/client.ts           Typed axios API client
│   │   ├── App.tsx                 Router (redirects to /setup if no config)
│   │   ├── pages/
│   │   │   ├── Setup/              7-step setup wizard
│   │   │   ├── Dashboard.tsx       Team health grid
│   │   │   ├── Engineers.tsx       Engineer list
│   │   │   ├── EngineerDetail.tsx  Individual drill-down
│   │   │   ├── Jira.tsx            Ticket board
│   │   │   ├── Dora.tsx            DORA charts
│   │   │   └── Services.tsx        Port service catalog
│   │   └── components/             Shared UI components
│   └── vite.config.ts              Proxy /api → localhost:9002
├── config/
│   ├── organization.yaml           Your config (gitignored)
│   └── organization.example.yaml   Template to copy
├── .env                            Your credentials (gitignored)
├── .env.example                    Template to copy
└── start.sh                        Start backend + frontend
```

---

## Multi-Director Setup (Domain Isolation)

Each director runs their own isolated instance. All reference and dashboard data lives in a per-domain SQLite file (`data/domains/{slug}.db`) — completely separate from every other director's data.

### Onboarding a New Director

```bash
# 1. Clone the repo
git clone <repo> ~/my-dashboard
cd ~/my-dashboard

# 2. Set up config and credentials
cp config/organization.example.yaml config/organization.yaml
cp .env.example .env

# 3. Edit organization.yaml
#    Set organization.slug (e.g. "platform"), add your teams and engineers
#    Each engineer needs: name, email, gitlab_username, role

# 4. Add API tokens to .env
#    GITLAB_TOKEN, JIRA_EMAIL, JIRA_API_TOKEN, etc.

# 5. Start
./start.sh
```

On first startup the app automatically:
- Creates `data/domains/{your-slug}.db`
- Seeds `ref_teams` and `ref_members` from your `organization.yaml`
- All dashboard data is isolated to your DB — never shared with other directors

### Re-seed After Config Changes

If you add or update engineers/teams in `organization.yaml`:

```bash
curl -X POST http://localhost:9002/api/config/domain/seed
```

### Domain DB Tables

| Table | Type | Purpose |
|-------|------|---------|
| `ref_teams` | Reference | Team config (seeded from YAML) |
| `ref_members` | Reference | Engineer roster — authoritative team membership |
| `mr_activity` | Transactional | MR history with team attribution |
| `team_metrics` | Transactional | Daily DORA/pipeline data |
| `jira_epics` | Transactional | Jira epic cache |
| `sync_status` | Control | Per-section sync state and TTL |
| `section_cache` | Control | Cached responses per section+period |

> **Key principle:** Engineer team membership is determined by `ref_members` (from your YAML), not by which repository they committed to. An engineer contributing to another team's repo still appears under their own team.

---

## License

MIT
