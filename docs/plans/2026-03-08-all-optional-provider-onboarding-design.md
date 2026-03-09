# All-Optional Provider-Based Onboarding

**Date**: 2026-03-08
**Status**: Approved

## Problem

The onboarding wizard requires GitLab credentials to create a domain. Users who use GitHub, or who want to start with just an issue tracker, are blocked. All integrations should be optional — the dashboard should work in degraded mode when providers are missing.

## Design

### Connections Step: Four Category Cards

Each category is a collapsible card with a provider dropdown at the top. Selecting a provider reveals that provider's specific fields. All categories are optional.

#### 1. Code Platform (GitLab | GitHub)

| Provider | Fields | Validation |
|----------|--------|------------|
| GitLab | Base URL, Personal access token, Base group | `GET {url}/api/v4/user` with `PRIVATE-TOKEN` header |
| GitHub | Personal access token, Organization | `GET https://api.github.com/user` with `Authorization: Bearer` header |

#### 2. Issue Tracker (Jira | Linear | Monday.com | Asana)

| Provider | Fields | Validation |
|----------|--------|------------|
| Jira | Site URL, Email, API token | `GET {url}/rest/api/3/myself` with basic auth |
| Linear | API key | GraphQL `POST https://api.linear.app/graphql` with `{ viewer { id name } }` |
| Monday.com | API token | GraphQL `POST https://api.monday.com/v2` with `{ me { id name } }` |
| Asana | Personal access token | `GET https://app.asana.com/api/1.0/users/me` with Bearer token |

#### 3. AI Provider (OpenAI | Anthropic)

| Provider | Fields | Validation |
|----------|--------|------------|
| OpenAI | API key | `GET https://api.openai.com/v1/models` with Bearer token (list models, confirms key works) |
| Anthropic | API key | `POST https://api.anthropic.com/v1/messages` minimal request with `x-api-key` header |

#### 4. Security (Snyk)

| Provider | Fields | Validation |
|----------|--------|------------|
| Snyk | Auth token | `GET https://api.snyk.io/rest/self?version=2024-04-29` with Bearer token |

### Backend: `POST /api/onboard/validate`

Accepts a flat object with any combination of provider credentials. Validates each provider that has credentials present. Returns:

```json
{
  "gitlab": {"ok": true, "user": "jsmith", "error": null},
  "github": {"ok": true, "user": "jsmith", "error": null},
  "jira": null,
  "linear": {"ok": false, "user": null, "error": "Invalid API key"},
  "monday": null,
  "asana": null,
  "openai": {"ok": true, "user": null, "error": null},
  "anthropic": null,
  "snyk": null
}
```

`null` means not attempted (no credentials provided).

### Backend: `POST /api/onboard/create`

Remove the GitLab requirement. Accept any combination of providers. Domain creation succeeds with zero integrations — the dashboard just shows empty states.

Secrets stored in `data/domains/{slug}.secrets.json`:

```json
{
  "gitlab": {"token": "...", "url": "...", "base_group": "..."},
  "github": {"token": "...", "org": "..."},
  "jira": {"url": "...", "email": "...", "token": "..."},
  "linear": {"api_key": "..."},
  "monday": {"token": "..."},
  "asana": {"token": "..."},
  "llm": {"openai_api_key": "...", "anthropic_api_key": "..."},
  "snyk": {"token": "..."}
}
```

### Backend: GitHub Discovery Endpoints

- `GET /api/onboard/discover/github-orgs` — list orgs for a token
- `GET /api/onboard/discover/github-teams?org=X` — list teams under an org

### Frontend: Connections Step

- Four collapsible cards replace the current GitLab/Jira/Optional layout.
- Each card has a provider `<select>` at the top. "None" is always the default.
- Selecting a provider reveals that provider's fields.
- "Validate connections" button tests all providers that have credentials filled in.
- Validation badges shown per provider in a sidebar panel.
- `canContinueConnections` is always `true` (everything optional).
- A warning banner appears if zero integrations are configured: "No integrations configured. You can add them later from Settings."

### Frontend: Teams Step

- If GitLab is configured: auto-discovery via existing GitLab group endpoints.
- If GitHub is configured: auto-discovery via new GitHub team endpoints.
- If neither: manual team entry only, with a hint explaining why discovery is unavailable.

### Config YAML

Integrations section in `config/domains/{slug}.yaml` gains new provider entries:

```yaml
integrations:
  code_platform:
    provider: github  # or gitlab
    config:
      org: my-org
  issue_tracker:
    provider: linear  # or jira, monday, asana
    config: {}
  security:
    provider: snyk
    config: {}
  ai:
    provider: openai  # or anthropic
    config: {}
```

### Domain Credentials

Add getter functions in `domain_credentials.py`:
- `get_github_settings()` — token, org
- `get_linear_settings()` — api_key
- `get_monday_settings()` — token
- `get_asana_settings()` — token

Existing getters (`get_gitlab_settings`, `get_jira_settings`, `get_snyk_settings`, `get_llm_settings`) unchanged.
