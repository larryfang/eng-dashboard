# Contributing to eng-dashboard

## Quick Start

1. Clone the repository
2. Copy `.env.example` to `.env` and fill in credentials
3. Install dependencies:
   ```bash
   # Backend (Python 3.11+)
   uv sync

   # Frontend (Node.js 18+)
   cd frontend && npm install
   ```
4. Start the backend:
   ```bash
   uv run uvicorn backend.main:app --port 9002 --reload
   ```
5. Start the frontend:
   ```bash
   cd frontend && npm run dev
   ```
6. Open http://localhost:5174 and complete the setup wizard

## Running Tests

```bash
# All backend tests
uv run pytest backend/tests/ -x --tb=short

# With coverage
uv run pytest backend/tests/ --cov=backend --cov-report=term-missing
```

## Architecture

- **Backend:** FastAPI (Python) on port 9002
- **Frontend:** React + Vite on port 5174
- **Database:** SQLite (domain-isolated at `data/domains/{slug}.db`)
- **Config:** `config/organization.yaml` → `config/domains/{slug}.yaml`

## Plugin System

eng-dashboard uses a plugin architecture for git providers, issue trackers, and code platforms.

### Adding a New Provider

1. Create your plugin class implementing the appropriate ABC:
   - `GitProvider` for git platforms (see `backend/services/git_providers/base.py`)
   - `IssueTrackerPlugin` for issue trackers (see `backend/issue_tracker/base.py`)
   - `CodePlatformPlugin` for code platforms (see `backend/code_platform/base.py`)

2. Register it with the `@register` decorator:
   ```python
   from backend.plugins.registry import register
   from backend.services.git_providers.base import GitProvider

   @register("git_provider", "bitbucket")
   class BitbucketProvider(GitProvider):
       ...
   ```

3. Add credential loading in `backend/services/domain_credentials.py`

4. Update the factory to handle instantiation (`backend/services/git_providers/factory.py` or `backend/issue_tracker/factory.py`)

5. Write tests in `backend/tests/`

### External Plugins (pip-installable)

External plugins can register themselves via setuptools entry points:

```toml
# In your plugin's pyproject.toml
[project.entry-points."eng_dashboard.plugins"]
my_plugin = "my_package.plugin"
```

The plugin module just needs to import and use `@register` -- it will be auto-discovered on startup.

## Code Style

- **Backend imports:** Always use `backend.` prefix (absolute imports). Never relative imports.
- **Python:** Follow PEP 8. Type hints encouraged.
- **Tests:** Use pytest with monkeypatch for mocking.

## API Endpoints

| Namespace | Purpose | Status |
|-----------|---------|--------|
| `/api/code/*` | Provider-agnostic git/code metrics | New |
| `/api/issues/*` | Provider-agnostic issue tracking | New |
| `/api/providers/*` | Provider capabilities & feature flags | New |
| `/api/gitlab/*` | GitLab-specific (legacy, still works) | Stable |
| `/api/jira/*` | Jira-specific (legacy, still works) | Stable |
| `/api/config/*` | Organization configuration | Stable |
| `/api/sync/*` | Sync status and triggers | Stable |
