# Engineering Director Dashboard

Track your engineers' code activity, issue tracker progress, DORA metrics, and service catalog -- through a React dashboard configured from a single YAML file.

Supports **GitLab** or **GitHub** as your code platform, and **Jira**, **GitHub Issues**, or **Linear** as your issue tracker. All integrations are optional -- connect only what you use.

**Built for:** Engineering Directors, VPs, and Managers who want visibility across teams without complex infrastructure.
**Philosophy:** Local-first. Runs on your laptop. No cloud required.

---

## Quick Start (5 minutes)

### Prerequisites

- Python 3.11+ with [uv](https://astral.sh/uv)
- Node.js 18+ with npm

All integrations are optional. Connect whichever providers you use:

| Integration | What you need |
|-------------|---------------|
| **GitLab** | Personal Access Token (`read_api`, `read_user` scopes) |
| **GitHub** | Personal Access Token (repo, read:org scopes) |
| **Jira** | API Token + email |
| **Snyk** | API Token (optional -- security metrics) |
| **Port.io** | Client ID + Secret (optional -- service catalog) |
| **AI Summaries** | OpenAI or Anthropic API key (optional) |

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

The setup wizard will guide you through selecting your providers, defining teams, and adding engineers.

### Verify Your Setup

After starting, run the health check script:

```bash
./check.sh
```

This validates Python deps, frontend compilation, and backend imports.

---

## Feature x Provider Matrix

Not every feature requires every provider. Here's what works with what:

| Feature | GitLab | GitHub | Jira | GitHub Issues | No Provider |
|---------|--------|--------|------|---------------|-------------|
| Dashboard MR counts | Yes | Yes | -- | -- | Empty |
| Engineer list + activity | Yes | Yes | -- | -- | Roster only |
| Individual engineer detail | Yes | Yes | -- | -- | Empty |
| MR Activity feed | Yes | Yes | -- | -- | Empty |
| DORA metrics | Yes | Partial | -- | -- | Empty |
| Epic/ticket tracking | -- | -- | Yes | Yes | Empty |
| Security vulnerabilities | -- | -- | -- | -- | Needs Snyk |
| Service catalog | -- | -- | -- | -- | Needs Port.io |
| AI team pulse summaries | -- | -- | -- | -- | Needs LLM key |
| Alerts (quiet engineers) | Yes | Yes | -- | -- | Disabled |
| Alerts (stalled epics) | -- | -- | Yes | Yes | Disabled |

---

## Configuration

### organization.yaml

All org structure lives in `config/organization.yaml`. Credentials stay in `.env` -- never in YAML.

```yaml
organization:
  name: Acme Engineering
  slug: acme-eng

user:
  name: Alex Smith
  email: alex@acme.com
  role: Director of Engineering
  timezone: America/New_York

integrations:
  code_platform:
    provider: gitlab              # gitlab | github
  issue_tracker:
    provider: jira                # jira | github

teams:
  - key: PLAT
    name: Platform
    slug: platform
    lead: Jordan Lee
    headcount: 5
    git_provider: gitlab          # gitlab | github (per-team override)
    gitlab_path: acme/platform    # for GitLab teams
    jira_project: PLAT
    members:                      # preferred field (gitlab_members also works)
      - username: jlee
        name: Jordan Lee
        role: TL

  - key: NOVA
    name: Nova
    slug: nova
    git_provider: github          # this team uses GitHub
    jira_project: NOVA
    members:
      - username: alice-gh        # GitHub username
        name: Alice Anderson
        role: TL
```

See `config/organization.example.yaml` for the full annotated template.

### .env

All credentials and secrets go here. Never commit this file.

```bash
# Code platform (pick one or both)
GITLAB_TOKEN=your_token
GITLAB_URL=https://gitlab.com          # default; change for self-hosted
GITHUB_TOKEN=ghp_your_token
GITHUB_ORG=your-org

# Issue tracker (pick one)
JIRA_EMAIL=your@company.com
JIRA_API_TOKEN=your_token
JIRA_URL=https://yourcompany.atlassian.net

# Optional integrations
PORT_CLIENT_ID=...
PORT_CLIENT_SECRET=...
SNYK_TOKEN=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...

# AI summaries (optional -- pick one or both)
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
```

---

## Token Setup

### GitLab Personal Access Token

1. Go to `https://gitlab.com/-/profile/personal_access_tokens` (or your self-hosted URL)
2. Create token with scopes: `read_api`, `read_user`
3. Copy to `GITLAB_TOKEN` in `.env`

### GitHub Personal Access Token

1. Go to https://github.com/settings/tokens
2. Create a **fine-grained token** with `repo`, `read:org` permissions
3. Copy to `GITHUB_TOKEN` in `.env`
4. Set `GITHUB_ORG` to your organization name

### Jira API Token

1. Go to https://id.atlassian.com/manage-profile/security/api-tokens
2. Create token, copy to `JIRA_API_TOKEN` in `.env`
3. Set `JIRA_EMAIL` to your Atlassian account email
4. Set `JIRA_URL` to `https://yourcompany.atlassian.net`

### Port.io (optional -- service catalog)

1. Go to https://app.getport.io/settings/credentials
2. Copy Client ID and Secret to `.env`

### Snyk (optional -- security metrics)

1. Go to https://app.snyk.io/account
2. Copy token to `SNYK_TOKEN` in `.env`

### AI Summaries (optional)

Install the LLM extras to enable AI-powered team pulse summaries:

```bash
uv sync --extra llm
```

Then add one or both keys to `.env`:

```bash
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
```

When both are set, Anthropic is primary with OpenAI as fallback.

---

## Dashboard Pages

| Page | Description |
|------|-------------|
| **Dashboard** | Team health grid -- DORA levels, MR activity, trend sparklines, warnings |
| **Engineers** | All engineers with aggregate metrics, sortable, filterable by team |
| **Engineer Detail** | Individual MR timeline, commit activity, ticket links |
| **Jira** | Kanban-style epic board with contributor drill-down |
| **Activity** | MR activity feed with compare mode (current vs previous period) |
| **DORA** | Deployment frequency, lead time, CFR, MTTR per team |
| **Alerts** | Operational alerts for quiet engineers, stalled epics, trend drops |
| **Reports** | Executive reports with saved views and scheduled email digests |
| **Services** | Port.io service catalog by domain/team |
| **Settings** | Provider health, scheduler, LLM config, sync history |

---

## API Endpoints

The backend runs on port 9002. Provider-agnostic endpoints:

```
GET  /api/config                     Organization config
POST /api/config/validate            Test provider connections

GET  /api/code/engineers             All engineers with metrics
GET  /api/code/engineers/{user}      Individual engineer detail
POST /api/code/engineers/{user}/sync Re-sync single engineer
GET  /api/code/team-summary          MR counts per team
GET  /api/code/team-trend            MR trend over time
GET  /api/code/activity              MR activity feed
GET  /api/code/metrics               DORA metrics
GET  /api/code/health                Code platform health check
GET  /api/code/security              Snyk vulnerability summary
GET  /api/code/security/teams        Snyk by team
GET  /api/code/security/critical     Critical vulnerabilities

GET  /api/jira/index/epics           Jira/GitHub epics
GET  /api/port/services              Port service catalog
GET  /api/sync/status                Sync status for all sections
GET  /api/providers/capabilities     Which providers are configured
```

Legacy `/api/gitlab/*` endpoints remain for backward compatibility.

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

### Running Tests

```bash
# Backend tests (107 tests)
uv run pytest

# Frontend lint + type-check
cd frontend && npm run lint && npx tsc --noEmit

# Full health check
./check.sh
```

### Initial Data Sync

The dashboard needs an initial sync to populate metrics:

```bash
# Via API (30-day sync)
curl -X POST "http://localhost:9002/api/gitlab/sync?days=30&background=false"

# Or via the dashboard: click "Sync" in the Settings page
```

---

## Docker

```bash
# Build and run
docker compose up -d

# Or build manually
docker build -t eng-dashboard .
docker run -p 9002:9002 -v ./data:/app/data -v ./config:/app/config --env-file .env eng-dashboard
```

The Docker image serves both frontend and backend on port 9002.

---

## Architecture

```
eng-dashboard/
├── backend/
│   ├── main.py                     FastAPI app (port 9002)
│   ├── database_domain.py          Domain DB engine factory
│   ├── models_domain.py            ORM models for domain tables
│   ├── core/
│   │   └── config_loader.py        Loads organization.yaml → typed config
│   ├── routers/
│   │   ├── config_router.py        GET/POST /api/config, validate
│   │   ├── code_router.py          Provider-agnostic /api/code/* endpoints
│   │   ├── gitlab_collector_router.py  GitLab sync + DORA + engineers
│   │   ├── jira_indexer_router.py  Jira epic indexing
│   │   ├── port_router.py          Port service catalog
│   │   ├── providers_router.py     Provider capabilities
│   │   └── sync_router.py          Sync status and scheduling
│   ├── services/
│   │   ├── git_providers/          GitProvider ABC + GitLab/GitHub implementations
│   │   ├── gitlab_intelligence/    GitLab GraphQL + DORA calculations
│   │   ├── snyk_service.py         Snyk vulnerability metrics
│   │   ├── jira_api_service.py     Jira REST API client
│   │   └── port_service.py         Port.io service catalog
│   ├── issue_tracker/              IssueTrackerPlugin ABC + Jira/GitHub
│   ├── code_platform/              CodePlatformPlugin ABC
│   └── plugins/llm/                LLMProvider ABC + OpenAI/Anthropic
├── frontend/
│   ├── src/
│   │   ├── api/client.ts           Typed axios API client
│   │   ├── App.tsx                 Router (redirects to /setup if not configured)
│   │   └── pages/                  Dashboard, Engineers, Jira, DORA, etc.
│   └── vite.config.ts              Proxy /api → localhost:9002
├── config/
│   ├── organization.yaml           Your config (gitignored)
│   └── organization.example.yaml   Template to copy
├── .env                            Your credentials (gitignored)
├── .env.example                    Template to copy
├── start.sh                        Start backend + frontend
├── check.sh                        Verify setup health
├── Dockerfile                      Multi-stage Docker build
└── docker-compose.yml              Docker Compose config
```

---

## Multi-Director Setup (Domain Isolation)

Each director runs their own isolated instance. All data lives in a per-domain SQLite file (`data/domains/{slug}.db`).

```bash
# 1. Clone, configure, start -- same as Quick Start
# 2. Each director's organization.slug determines their DB file
# 3. No data is shared between directors
```

On first startup the app automatically:
- Creates `data/domains/{your-slug}.db`
- Seeds `ref_teams` and `ref_members` from your `organization.yaml`
- All dashboard data is isolated to your domain DB

### Re-seed After Config Changes

```bash
curl -X POST http://localhost:9002/api/config/domain/seed
```

> **Key principle:** Engineer team membership is determined by `ref_members` (from your YAML), not by which repository they committed to. An engineer contributing to another team's repo still appears under their own team.

---

## License

MIT
