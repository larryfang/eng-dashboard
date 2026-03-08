# All-Optional Provider-Based Onboarding — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make all onboarding integrations optional and add support for GitHub, Linear, Monday.com, Asana, OpenAI, and Anthropic as provider choices.

**Architecture:** The Connections step becomes four category cards (Code Platform, Issue Tracker, AI, Security), each with a provider dropdown. Backend validate endpoint accepts any combination. Domain creation succeeds with zero integrations.

**Tech Stack:** FastAPI + Pydantic (backend), React + TypeScript (frontend), httpx/requests for provider validation, pytest for backend tests.

---

### Task 1: Backend — Expand ValidateRequest and validate endpoint for all providers

**Files:**
- Modify: `backend/routers/onboard_router.py:36-82`
- Test: `backend/tests/test_onboarding_runtime.py`

**Step 1: Write failing tests for new provider validations**

Add to `backend/tests/test_onboarding_runtime.py`:

```python
@pytest.mark.asyncio
async def test_validate_github_credentials(monkeypatch):
    def fake_get(url, headers=None, timeout=0, auth=None, params=None):
        return StubResponse(payload={"login": "octocat", "name": "The Octocat"})

    monkeypatch.setattr(onboard_router.requests, "get", fake_get)

    result = await onboard_router.validate_credentials(
        onboard_router.ValidateRequest(github_token="ghp_test123")
    )
    assert result["github"] == {"ok": True, "user": "octocat", "error": None}
    assert result["gitlab"] is None  # not provided


@pytest.mark.asyncio
async def test_validate_linear_credentials(monkeypatch):
    def fake_post(url, headers=None, json=None, timeout=0):
        return StubResponse(payload={"data": {"viewer": {"id": "u1", "name": "Alice"}}})

    monkeypatch.setattr(onboard_router.requests, "post", fake_post)

    result = await onboard_router.validate_credentials(
        onboard_router.ValidateRequest(linear_api_key="lin_api_test")
    )
    assert result["linear"] == {"ok": True, "user": "Alice", "error": None}


@pytest.mark.asyncio
async def test_validate_monday_credentials(monkeypatch):
    def fake_post(url, headers=None, json=None, timeout=0):
        return StubResponse(payload={"data": {"me": {"id": 123, "name": "Bob"}}})

    monkeypatch.setattr(onboard_router.requests, "post", fake_post)

    result = await onboard_router.validate_credentials(
        onboard_router.ValidateRequest(monday_token="monday_test")
    )
    assert result["monday"] == {"ok": True, "user": "Bob", "error": None}


@pytest.mark.asyncio
async def test_validate_asana_credentials(monkeypatch):
    def fake_get(url, headers=None, timeout=0, auth=None, params=None):
        return StubResponse(payload={"data": {"gid": "123", "name": "Carol"}})

    monkeypatch.setattr(onboard_router.requests, "get", fake_get)

    result = await onboard_router.validate_credentials(
        onboard_router.ValidateRequest(asana_token="asana_test")
    )
    assert result["asana"] == {"ok": True, "user": "Carol", "error": None}


@pytest.mark.asyncio
async def test_validate_openai_credentials(monkeypatch):
    def fake_get(url, headers=None, timeout=0, auth=None, params=None):
        return StubResponse(payload={"data": [{"id": "gpt-4o"}]})

    monkeypatch.setattr(onboard_router.requests, "get", fake_get)

    result = await onboard_router.validate_credentials(
        onboard_router.ValidateRequest(openai_api_key="sk-test123")
    )
    assert result["openai"] == {"ok": True, "user": None, "error": None}


@pytest.mark.asyncio
async def test_validate_anthropic_credentials(monkeypatch):
    def fake_post(url, headers=None, json=None, timeout=0):
        return StubResponse(ok=False, status_code=400, payload={"error": {"message": "invalid request"}})

    # Anthropic returns 400 for minimal request but that still proves the key is valid
    # if we get 401, the key is invalid
    def fake_get(url, headers=None, timeout=0, auth=None, params=None):
        return StubResponse(payload={"type": "model_list"})

    monkeypatch.setattr(onboard_router.requests, "get", fake_get)

    result = await onboard_router.validate_credentials(
        onboard_router.ValidateRequest(anthropic_api_key="sk-ant-test")
    )
    assert result["anthropic"] == {"ok": True, "user": None, "error": None}


@pytest.mark.asyncio
async def test_validate_snyk_credentials(monkeypatch):
    def fake_get(url, headers=None, timeout=0, auth=None, params=None):
        return StubResponse(payload={"data": {"attributes": {"name": "Dave"}}})

    monkeypatch.setattr(onboard_router.requests, "get", fake_get)

    result = await onboard_router.validate_credentials(
        onboard_router.ValidateRequest(snyk_token="snyk_test")
    )
    assert result["snyk"] == {"ok": True, "user": "Dave", "error": None}


@pytest.mark.asyncio
async def test_validate_empty_request_returns_all_null(monkeypatch):
    result = await onboard_router.validate_credentials(
        onboard_router.ValidateRequest()
    )
    for key in ("gitlab", "github", "jira", "linear", "monday", "asana", "openai", "anthropic", "snyk"):
        assert result[key] is None
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/larfan/Projects/eng-dashboard && python -m pytest backend/tests/test_onboarding_runtime.py -v -k "validate" --no-header`
Expected: FAIL — `ValidateRequest` missing new fields.

**Step 3: Implement the expanded ValidateRequest and validate endpoint**

Replace `ValidateRequest` and `validate_credentials` in `backend/routers/onboard_router.py:36-82`:

```python
class ValidateRequest(BaseModel):
    # Code platform
    gitlab_token: Optional[str] = None
    gitlab_url: Optional[str] = None
    github_token: Optional[str] = None
    github_org: Optional[str] = None
    # Issue tracker
    jira_url: Optional[str] = None
    jira_email: Optional[str] = None
    jira_token: Optional[str] = None
    linear_api_key: Optional[str] = None
    monday_token: Optional[str] = None
    asana_token: Optional[str] = None
    # AI
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    # Security
    snyk_token: Optional[str] = None


def _validate_result(ok: bool, user: str | None = None, error: str | None = None) -> dict:
    return {"ok": ok, "user": user, "error": error}


@router.post("/validate")
async def validate_credentials(body: ValidateRequest):
    results: dict = {}

    # GitLab
    if body.gitlab_token:
        gitlab_api = _gitlab_api_base(body.gitlab_url)
        try:
            r = requests.get(
                f"{gitlab_api}/user",
                headers={"PRIVATE-TOKEN": body.gitlab_token},
                timeout=10,
            )
            if r.ok:
                results["gitlab"] = _validate_result(True, user=r.json().get("username"))
            else:
                results["gitlab"] = _validate_result(False, error=f"HTTP {r.status_code}")
        except Exception as e:
            results["gitlab"] = _validate_result(False, error=str(e))
    else:
        results["gitlab"] = None

    # GitHub
    if body.github_token:
        try:
            r = requests.get(
                "https://api.github.com/user",
                headers={"Authorization": f"Bearer {body.github_token}", "Accept": "application/vnd.github+json"},
                timeout=10,
            )
            if r.ok:
                results["github"] = _validate_result(True, user=r.json().get("login"))
            else:
                results["github"] = _validate_result(False, error=f"HTTP {r.status_code}")
        except Exception as e:
            results["github"] = _validate_result(False, error=str(e))
    else:
        results["github"] = None

    # Jira
    if body.jira_url and body.jira_email and body.jira_token:
        try:
            r = requests.get(
                f"{body.jira_url.rstrip('/')}/rest/api/3/myself",
                auth=(body.jira_email, body.jira_token),
                timeout=10,
            )
            if r.ok:
                results["jira"] = _validate_result(True, user=r.json().get("displayName"))
            else:
                results["jira"] = _validate_result(False, error=f"HTTP {r.status_code}")
        except Exception as e:
            results["jira"] = _validate_result(False, error=str(e))
    else:
        results["jira"] = None

    # Linear
    if body.linear_api_key:
        try:
            r = requests.post(
                "https://api.linear.app/graphql",
                headers={"Authorization": body.linear_api_key, "Content-Type": "application/json"},
                json={"query": "{ viewer { id name } }"},
                timeout=10,
            )
            if r.ok:
                viewer = r.json().get("data", {}).get("viewer", {})
                results["linear"] = _validate_result(True, user=viewer.get("name"))
            else:
                results["linear"] = _validate_result(False, error=f"HTTP {r.status_code}")
        except Exception as e:
            results["linear"] = _validate_result(False, error=str(e))
    else:
        results["linear"] = None

    # Monday.com
    if body.monday_token:
        try:
            r = requests.post(
                "https://api.monday.com/v2",
                headers={"Authorization": body.monday_token, "Content-Type": "application/json"},
                json={"query": "{ me { id name } }"},
                timeout=10,
            )
            if r.ok:
                me = r.json().get("data", {}).get("me", {})
                results["monday"] = _validate_result(True, user=me.get("name"))
            else:
                results["monday"] = _validate_result(False, error=f"HTTP {r.status_code}")
        except Exception as e:
            results["monday"] = _validate_result(False, error=str(e))
    else:
        results["monday"] = None

    # Asana
    if body.asana_token:
        try:
            r = requests.get(
                "https://app.asana.com/api/1.0/users/me",
                headers={"Authorization": f"Bearer {body.asana_token}"},
                timeout=10,
            )
            if r.ok:
                results["asana"] = _validate_result(True, user=r.json().get("data", {}).get("name"))
            else:
                results["asana"] = _validate_result(False, error=f"HTTP {r.status_code}")
        except Exception as e:
            results["asana"] = _validate_result(False, error=str(e))
    else:
        results["asana"] = None

    # OpenAI
    if body.openai_api_key:
        try:
            r = requests.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {body.openai_api_key}"},
                timeout=10,
            )
            if r.ok:
                results["openai"] = _validate_result(True)
            else:
                results["openai"] = _validate_result(False, error=f"HTTP {r.status_code}")
        except Exception as e:
            results["openai"] = _validate_result(False, error=str(e))
    else:
        results["openai"] = None

    # Anthropic
    if body.anthropic_api_key:
        try:
            r = requests.get(
                "https://api.anthropic.com/v1/models",
                headers={
                    "x-api-key": body.anthropic_api_key,
                    "anthropic-version": "2023-06-01",
                },
                timeout=10,
            )
            if r.ok:
                results["anthropic"] = _validate_result(True)
            else:
                results["anthropic"] = _validate_result(False, error=f"HTTP {r.status_code}")
        except Exception as e:
            results["anthropic"] = _validate_result(False, error=str(e))
    else:
        results["anthropic"] = None

    # Snyk
    if body.snyk_token:
        try:
            r = requests.get(
                "https://api.snyk.io/rest/self?version=2024-04-29",
                headers={"Authorization": f"token {body.snyk_token}"},
                timeout=10,
            )
            if r.ok:
                name = r.json().get("data", {}).get("attributes", {}).get("name")
                results["snyk"] = _validate_result(True, user=name)
            else:
                results["snyk"] = _validate_result(False, error=f"HTTP {r.status_code}")
        except Exception as e:
            results["snyk"] = _validate_result(False, error=str(e))
    else:
        results["snyk"] = None

    return results
```

**Step 4: Run tests to verify they pass**

Run: `cd /Users/larfan/Projects/eng-dashboard && python -m pytest backend/tests/test_onboarding_runtime.py -v -k "validate" --no-header`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add backend/routers/onboard_router.py backend/tests/test_onboarding_runtime.py
git commit -m "feat: expand validate endpoint for all provider types (GitHub, Linear, Monday, Asana, OpenAI, Anthropic, Snyk)"
```

---

### Task 2: Backend — Add GitHub discovery endpoints

**Files:**
- Modify: `backend/routers/onboard_router.py` (append after existing endpoints, before create_domain)
- Test: `backend/tests/test_onboarding_runtime.py`

**Step 1: Write failing tests**

Add to `backend/tests/test_onboarding_runtime.py`:

```python
@pytest.mark.asyncio
async def test_discover_github_orgs(monkeypatch):
    def fake_get(url, headers=None, params=None, timeout=0):
        return StubResponse(payload=[
            {"login": "my-org", "description": "Main org"},
            {"login": "side-project", "description": ""},
        ])

    monkeypatch.setattr(onboard_router.requests, "get", fake_get)

    result = await onboard_router.discover_github_orgs(
        StubRequest(headers={"x-github-token": "ghp_test"}),
        token=None,
    )
    assert len(result["orgs"]) == 2
    assert result["orgs"][0]["login"] == "my-org"


@pytest.mark.asyncio
async def test_discover_github_teams(monkeypatch):
    def fake_get(url, headers=None, params=None, timeout=0):
        return StubResponse(payload=[
            {"slug": "platform", "name": "Platform", "description": "Core infra"},
        ])

    monkeypatch.setattr(onboard_router.requests, "get", fake_get)

    result = await onboard_router.discover_github_teams(
        StubRequest(headers={"x-github-token": "ghp_test"}),
        token=None,
        org="my-org",
    )
    assert len(result["teams"]) == 1
    assert result["teams"][0]["slug"] == "platform"


@pytest.mark.asyncio
async def test_discover_github_team_members(monkeypatch):
    def fake_get(url, headers=None, params=None, timeout=0):
        return StubResponse(payload=[
            {"login": "alice", "type": "User"},
        ])

    monkeypatch.setattr(onboard_router.requests, "get", fake_get)

    result = await onboard_router.discover_github_members(
        StubRequest(headers={"x-github-token": "ghp_test"}),
        token=None,
        org="my-org",
        team_slug="platform",
    )
    assert len(result["members"]) == 1
    assert result["members"][0]["username"] == "alice"
```

**Step 2: Run tests to confirm they fail**

Run: `cd /Users/larfan/Projects/eng-dashboard && python -m pytest backend/tests/test_onboarding_runtime.py -v -k "github" --no-header`
Expected: FAIL — functions don't exist.

**Step 3: Implement GitHub discovery endpoints**

Add to `backend/routers/onboard_router.py` (before the `# ── Create domain` section):

```python
# ── GitHub discovery ──────────────────────────────────────────────────────────

GITHUB_API = "https://api.github.com"


@router.get("/discover/github-orgs")
async def discover_github_orgs(
    request: Request,
    token: Optional[str] = Query(default=None, description="GitHub personal access token"),
):
    """List GitHub organizations for the authenticated user."""
    token = request.headers.get("x-github-token") or token
    if not token:
        raise HTTPException(status_code=400, detail="GitHub token is required")

    try:
        r = requests.get(
            f"{GITHUB_API}/user/orgs",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
            params={"per_page": 100},
            timeout=15,
        )
        if not r.ok:
            raise HTTPException(status_code=r.status_code, detail=f"GitHub org list failed: HTTP {r.status_code}")
        orgs = [{"login": o["login"], "description": o.get("description", "")} for o in r.json()]
        return {"orgs": orgs}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/discover/github-teams")
async def discover_github_teams(
    request: Request,
    token: Optional[str] = Query(default=None),
    org: str = Query(..., description="GitHub organization login"),
):
    """List teams under a GitHub organization."""
    token = request.headers.get("x-github-token") or token
    if not token:
        raise HTTPException(status_code=400, detail="GitHub token is required")

    try:
        r = requests.get(
            f"{GITHUB_API}/orgs/{org}/teams",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
            params={"per_page": 100},
            timeout=15,
        )
        if not r.ok:
            raise HTTPException(status_code=r.status_code, detail=f"GitHub teams failed: HTTP {r.status_code}")
        teams = [
            {"slug": t["slug"], "name": t["name"], "description": t.get("description", "")}
            for t in r.json()
        ]
        return {"teams": teams}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/discover/github-members")
async def discover_github_members(
    request: Request,
    token: Optional[str] = Query(default=None),
    org: str = Query(..., description="GitHub organization login"),
    team_slug: str = Query(..., description="GitHub team slug"),
):
    """List members of a GitHub team."""
    token = request.headers.get("x-github-token") or token
    if not token:
        raise HTTPException(status_code=400, detail="GitHub token is required")

    try:
        r = requests.get(
            f"{GITHUB_API}/orgs/{org}/teams/{team_slug}/members",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
            params={"per_page": 100},
            timeout=15,
        )
        if not r.ok:
            raise HTTPException(status_code=r.status_code, detail=f"GitHub team members failed: HTTP {r.status_code}")
        members = [
            {"username": m["login"], "name": m["login"], "role": "engineer"}
            for m in r.json()
            if m.get("type") == "User"
        ]
        return {"members": members}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

**Step 4: Run tests to verify they pass**

Run: `cd /Users/larfan/Projects/eng-dashboard && python -m pytest backend/tests/test_onboarding_runtime.py -v -k "github" --no-header`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add backend/routers/onboard_router.py backend/tests/test_onboarding_runtime.py
git commit -m "feat: add GitHub discovery endpoints for orgs, teams, and members"
```

---

### Task 3: Backend — Add credential getters for new providers

**Files:**
- Modify: `backend/services/domain_credentials.py` (append after `get_snyk_settings`)
- Test: `backend/tests/test_onboarding_runtime.py`

**Step 1: Write failing tests**

Add to `backend/tests/test_onboarding_runtime.py`:

```python
import json

from backend.services import domain_credentials


def test_get_github_settings_reads_from_secrets(tmp_path, monkeypatch):
    secrets_file = tmp_path / "test-domain.secrets.json"
    secrets_file.write_text(json.dumps({"github": {"token": "ghp_123", "org": "acme"}}))
    monkeypatch.setattr(domain_credentials, "DOMAIN_DATA_DIR", tmp_path)
    monkeypatch.setattr(domain_credentials, "_slug", lambda s: "test-domain")

    result = domain_credentials.get_github_settings("test-domain")
    assert result["token"] == "ghp_123"
    assert result["org"] == "acme"


def test_get_linear_settings_reads_from_secrets(tmp_path, monkeypatch):
    secrets_file = tmp_path / "test-domain.secrets.json"
    secrets_file.write_text(json.dumps({"linear": {"api_key": "lin_abc"}}))
    monkeypatch.setattr(domain_credentials, "DOMAIN_DATA_DIR", tmp_path)
    monkeypatch.setattr(domain_credentials, "_slug", lambda s: "test-domain")

    result = domain_credentials.get_linear_settings("test-domain")
    assert result["api_key"] == "lin_abc"


def test_get_monday_settings_reads_from_secrets(tmp_path, monkeypatch):
    secrets_file = tmp_path / "test-domain.secrets.json"
    secrets_file.write_text(json.dumps({"monday": {"token": "mon_xyz"}}))
    monkeypatch.setattr(domain_credentials, "DOMAIN_DATA_DIR", tmp_path)
    monkeypatch.setattr(domain_credentials, "_slug", lambda s: "test-domain")

    result = domain_credentials.get_monday_settings("test-domain")
    assert result["token"] == "mon_xyz"


def test_get_asana_settings_reads_from_secrets(tmp_path, monkeypatch):
    secrets_file = tmp_path / "test-domain.secrets.json"
    secrets_file.write_text(json.dumps({"asana": {"token": "asana_abc"}}))
    monkeypatch.setattr(domain_credentials, "DOMAIN_DATA_DIR", tmp_path)
    monkeypatch.setattr(domain_credentials, "_slug", lambda s: "test-domain")

    result = domain_credentials.get_asana_settings("test-domain")
    assert result["token"] == "asana_abc"
```

**Step 2: Run tests to confirm failure**

Run: `cd /Users/larfan/Projects/eng-dashboard && python -m pytest backend/tests/test_onboarding_runtime.py -v -k "settings" --no-header`
Expected: FAIL — functions don't exist.

**Step 3: Implement getters**

Add to end of `backend/services/domain_credentials.py`:

```python
def get_github_settings(domain_slug: str | None = None) -> dict[str, str]:
    secrets = load_domain_secrets(domain_slug).get("github", {}) or {}
    return {
        "token": secrets.get("token") or os.getenv("GITHUB_TOKEN", ""),
        "org": secrets.get("org") or "",
    }


def get_linear_settings(domain_slug: str | None = None) -> dict[str, str]:
    secrets = load_domain_secrets(domain_slug).get("linear", {}) or {}
    return {
        "api_key": secrets.get("api_key") or os.getenv("LINEAR_API_KEY", ""),
    }


def get_monday_settings(domain_slug: str | None = None) -> dict[str, str]:
    secrets = load_domain_secrets(domain_slug).get("monday", {}) or {}
    return {
        "token": secrets.get("token") or os.getenv("MONDAY_TOKEN", ""),
    }


def get_asana_settings(domain_slug: str | None = None) -> dict[str, str]:
    secrets = load_domain_secrets(domain_slug).get("asana", {}) or {}
    return {
        "token": secrets.get("token") or os.getenv("ASANA_TOKEN", ""),
    }
```

**Step 4: Run tests**

Run: `cd /Users/larfan/Projects/eng-dashboard && python -m pytest backend/tests/test_onboarding_runtime.py -v -k "settings" --no-header`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add backend/services/domain_credentials.py backend/tests/test_onboarding_runtime.py
git commit -m "feat: add credential getters for GitHub, Linear, Monday.com, Asana"
```

---

### Task 4: Backend — Make domain creation all-optional

**Files:**
- Modify: `backend/routers/onboard_router.py:261-398` (DomainCreateRequest + create_domain)
- Test: `backend/tests/test_onboarding_runtime.py`

**Step 1: Write failing test**

Add to `backend/tests/test_onboarding_runtime.py`:

```python
@pytest.mark.asyncio
async def test_create_domain_without_gitlab_succeeds(monkeypatch, tmp_path):
    """Domain creation should succeed with zero integrations."""
    import yaml
    from backend.routers import onboard_router as orouter

    config_dir = tmp_path / "config" / "domains"
    config_dir.mkdir(parents=True)
    monkeypatch.setattr(orouter, "CONFIG_DOMAINS_DIR", config_dir)

    data_dir = tmp_path / "data" / "domains"
    data_dir.mkdir(parents=True)

    from backend.services import domain_credentials as dc
    monkeypatch.setattr(dc, "DOMAIN_DATA_DIR", data_dir)

    # Stub out DB init, seeding, domain switching
    monkeypatch.setattr("backend.database_domain.init_domain_db", lambda slug: None)
    monkeypatch.setattr("backend.database_domain.get_domain_engine", lambda slug: None)

    class FakeSession:
        def close(self): pass
    monkeypatch.setattr("sqlalchemy.orm.sessionmaker", lambda bind=None: lambda: FakeSession())

    monkeypatch.setattr("backend.services.domain_seeder.seed_reference_data", lambda db, domain_slug=None: {"teams": 0, "members": 0})

    fake_config = type("Cfg", (), {"name": "No-Git Org", "slug": "no-git", "teams": []})()
    monkeypatch.setattr("backend.core.config_loader.reload_domain_config", lambda slug: fake_config)
    monkeypatch.setattr("backend.services.domain_registry.switch_domain", lambda slug: None)

    body = orouter.DomainCreateRequest(
        organization={"name": "No-Git Org", "slug": "no-git", "description": "Testing zero integrations"},
        user={"name": "Test", "email": "t@t.com", "role": "EM", "timezone": "UTC"},
        teams=[{"key": "T1", "name": "Team One", "slug": "team-one", "gitlab_path": "", "gitlab_members": []}],
    )

    result = await orouter.create_domain(body)
    assert result["ok"] is True
    assert result["slug"] == "no-git"
```

**Step 2: Run test to verify failure**

Run: `cd /Users/larfan/Projects/eng-dashboard && python -m pytest backend/tests/test_onboarding_runtime.py::test_create_domain_without_gitlab_succeeds -v --no-header`
Expected: FAIL — `422: GitLab credentials are required`

**Step 3: Update DomainCreateRequest and create_domain**

In `backend/routers/onboard_router.py`, modify `DomainCreateRequest` and the `create_domain` function:

1. Add new optional fields to `DomainCreateRequest`:

```python
class DomainCreateRequest(BaseModel):
    organization: dict
    user: dict
    teams: list
    # Code platform (pick one or none)
    gitlab: Optional[dict] = None
    github: Optional[dict] = None
    # Issue tracker (pick one or none)
    jira: Optional[dict] = None
    linear: Optional[dict] = None
    monday: Optional[dict] = None
    asana: Optional[dict] = None
    # AI
    llm: Optional[dict] = None
    # Other
    optional: Optional[dict] = None  # Port, Snyk (legacy field name kept for compat)
```

2. In `create_domain`, remove the GitLab requirement check at line 285-286:

```python
# DELETE these lines:
# if not body.gitlab or not body.gitlab.get("token"):
#     raise HTTPException(status_code=422, detail="GitLab credentials are required to create a usable domain")
```

3. Add new provider sections to the secrets and config builders in `create_domain`:

After the existing `if body.gitlab:` block for integrations, add:
```python
    if body.github and body.github.get("token"):
        github_config: dict = {}
        if body.github.get("org"):
            github_config["org"] = body.github["org"]
        integrations["code_platform"] = {
            "provider": "github",
            "config": github_config,
        }
```

After the existing Jira integrations block, add:
```python
    if body.linear and body.linear.get("api_key"):
        integrations["issue_tracker"] = {"provider": "linear", "config": {}}
    if body.monday and body.monday.get("token"):
        integrations["issue_tracker"] = {"provider": "monday", "config": {}}
    if body.asana and body.asana.get("token"):
        integrations["issue_tracker"] = {"provider": "asana", "config": {}}
```

After the existing LLM block, add AI integrations:
```python
    if body.llm:
        if body.llm.get("openai_api_key"):
            integrations["ai"] = {"provider": "openai", "config": {}}
        elif body.llm.get("anthropic_api_key"):
            integrations["ai"] = {"provider": "anthropic", "config": {}}
```

In the secrets builder section, add after existing blocks:
```python
    if body.github and body.github.get("token"):
        secret_payload["github"] = {
            "token": body.github.get("token", ""),
            "org": body.github.get("org", ""),
        }
    if body.linear and body.linear.get("api_key"):
        secret_payload["linear"] = {"api_key": body.linear["api_key"]}
    if body.monday and body.monday.get("token"):
        secret_payload["monday"] = {"token": body.monday["token"]}
    if body.asana and body.asana.get("token"):
        secret_payload["asana"] = {"token": body.asana["token"]}
    if body.llm:
        llm_secrets: dict = {}
        if body.llm.get("openai_api_key"):
            llm_secrets["openai_api_key"] = body.llm["openai_api_key"]
        if body.llm.get("anthropic_api_key"):
            llm_secrets["anthropic_api_key"] = body.llm["anthropic_api_key"]
        if llm_secrets:
            secret_payload["llm"] = llm_secrets
```

**Step 4: Run tests**

Run: `cd /Users/larfan/Projects/eng-dashboard && python -m pytest backend/tests/test_onboarding_runtime.py -v --no-header`
Expected: ALL PASS (including the existing test which still sends GitLab creds)

**Step 5: Commit**

```bash
git add backend/routers/onboard_router.py backend/tests/test_onboarding_runtime.py
git commit -m "feat: make domain creation all-optional — no provider required"
```

---

### Task 5: Frontend — Refactor Connections step with category-based provider selector

**Files:**
- Modify: `frontend/src/pages/Setup.tsx` (major rewrite of connections step)

This is the largest task. The approach:

1. Add new interfaces and state for provider selection
2. Replace the connections step rendering
3. Update validation logic, canContinueConnections, review step, and createDomain payload

**Step 1: Add new types and state**

Add these interfaces near the top of `Setup.tsx` (after existing interfaces around line 60):

```typescript
type CodePlatform = 'none' | 'gitlab' | 'github'
type IssueTracker = 'none' | 'jira' | 'linear' | 'monday' | 'asana'
type AiProvider = 'none' | 'openai' | 'anthropic'
type SecurityProvider = 'none' | 'snyk'

interface GitHubForm {
  token: string
  org: string
}

interface LinearForm {
  apiKey: string
}

interface MondayForm {
  token: string
}

interface AsanaForm {
  token: string
}

interface AiForm {
  openaiKey: string
  anthropicKey: string
}
```

Update the `ValidationResult` interface to cover all providers:

```typescript
interface ValidationResult {
  gitlab?: { ok: boolean; user?: string; error?: string } | null
  github?: { ok: boolean; user?: string; error?: string } | null
  jira?: { ok: boolean; user?: string; error?: string } | null
  linear?: { ok: boolean; user?: string; error?: string } | null
  monday?: { ok: boolean; user?: string; error?: string } | null
  asana?: { ok: boolean; user?: string; error?: string } | null
  openai?: { ok: boolean; user?: string; error?: string } | null
  anthropic?: { ok: boolean; user?: string; error?: string } | null
  snyk?: { ok: boolean; user?: string; error?: string } | null
}
```

Add state variables inside the `Setup` component (after the existing state around line 534):

```typescript
const [codePlatform, setCodePlatform] = useState<CodePlatform>('none')
const [issueTracker, setIssueTracker] = useState<IssueTracker>('none')
const [aiProvider, setAiProvider] = useState<AiProvider>('none')
const [securityProvider, setSecurityProvider] = useState<SecurityProvider>('none')
const [github, setGithub] = useState<GitHubForm>({ token: '', org: '' })
const [linear, setLinear] = useState<LinearForm>({ apiKey: '' })
const [monday, setMonday] = useState<MondayForm>({ token: '' })
const [asana, setAsana] = useState<AsanaForm>({ token: '' })
const [ai, setAi] = useState<AiForm>({ openaiKey: '', anthropicKey: '' })
```

**Step 2: Update canContinueConnections**

Replace the `canContinueConnections` logic (line 624-629) with:

```typescript
// All connections are optional — user can always continue.
// We just warn if nothing is configured.
const hasAnyConnection = Boolean(
  (codePlatform === 'gitlab' && gitlab.token.trim()) ||
  (codePlatform === 'github' && github.token.trim()) ||
  (issueTracker === 'jira' && jira.url.trim() && jira.email.trim() && jira.token.trim()) ||
  (issueTracker === 'linear' && linear.apiKey.trim()) ||
  (issueTracker === 'monday' && monday.token.trim()) ||
  (issueTracker === 'asana' && asana.token.trim()) ||
  (aiProvider === 'openai' && ai.openaiKey.trim()) ||
  (aiProvider === 'anthropic' && ai.anthropicKey.trim()) ||
  (securityProvider === 'snyk' && optional.snykToken.trim())
)
const canContinueConnections = true  // always true now
```

**Step 3: Update validateConnections**

Replace the `validateConnections` function (line 698-736) to send all selected providers:

```typescript
const validateConnections = async () => {
  setValidating(true)
  setCreateError(null)
  setValidation(null)
  try {
    const payload: Record<string, string> = {}

    // Code platform
    if (codePlatform === 'gitlab' && gitlab.token.trim()) {
      payload.gitlab_token = gitlab.token
      payload.gitlab_url = gitlab.url.trim()
    }
    if (codePlatform === 'github' && github.token.trim()) {
      payload.github_token = github.token
      if (github.org.trim()) payload.github_org = github.org.trim()
    }

    // Issue tracker
    if (issueTracker === 'jira' && jira.url.trim() && jira.email.trim() && jira.token.trim()) {
      payload.jira_url = jira.url.trim()
      payload.jira_email = jira.email.trim()
      payload.jira_token = jira.token
    }
    if (issueTracker === 'linear' && linear.apiKey.trim()) {
      payload.linear_api_key = linear.apiKey
    }
    if (issueTracker === 'monday' && monday.token.trim()) {
      payload.monday_token = monday.token
    }
    if (issueTracker === 'asana' && asana.token.trim()) {
      payload.asana_token = asana.token
    }

    // AI
    if (aiProvider === 'openai' && ai.openaiKey.trim()) {
      payload.openai_api_key = ai.openaiKey
    }
    if (aiProvider === 'anthropic' && ai.anthropicKey.trim()) {
      payload.anthropic_api_key = ai.anthropicKey
    }

    // Security
    if (securityProvider === 'snyk' && optional.snykToken.trim()) {
      payload.snyk_token = optional.snykToken
    }

    if (Object.keys(payload).length === 0) {
      setValidation({})
      return
    }

    const response = await axios.post('/api/onboard/validate', payload)
    setValidation(response.data)

    // Auto-discover if platform validated
    const followUps: Promise<unknown>[] = []
    if (response.data?.gitlab?.ok && gitlab.baseGroup.trim()) {
      followUps.push(discoverGitLabGroups(true))
    }
    if (response.data?.github?.ok && github.org.trim()) {
      followUps.push(discoverGitHubTeams(true))
    }
    if (response.data?.jira?.ok) {
      followUps.push(discoverJiraProjects(true))
    }
    if (followUps.length > 0) {
      await Promise.all(followUps)
    }
  } catch (error: any) {
    setValidation({
      gitlab: codePlatform === 'gitlab' ? {
        ok: false,
        error: error.response?.data?.detail ?? 'Connection validation failed',
      } : null,
    })
  } finally {
    setValidating(false)
  }
}
```

**Step 4: Add GitHub team discovery function**

Add after `discoverJiraProjects` (around line 696):

```typescript
const [discoveredGithubTeams, setDiscoveredGithubTeams] = useState<Array<{slug: string; name: string; description: string}>>([])
const [discoveringGithubTeams, setDiscoveringGithubTeams] = useState(false)
const [githubTeamsError, setGithubTeamsError] = useState<string | null>(null)

const discoverGitHubTeams = async (silent = false) => {
  if (!github.token.trim() || !github.org.trim()) {
    if (!silent) setGithubTeamsError('GitHub token and organization are required to discover teams.')
    return
  }
  setDiscoveringGithubTeams(true)
  if (!silent) setGithubTeamsError(null)
  try {
    const response = await axios.get('/api/onboard/discover/github-teams', {
      params: { org: github.org.trim() },
      headers: { 'X-GitHub-Token': github.token },
    })
    setDiscoveredGithubTeams(response.data.teams ?? [])
    if (!silent && (response.data.teams ?? []).length === 0) {
      setGithubTeamsError('No teams found in this organization.')
    }
  } catch (error: any) {
    setGithubTeamsError(error.response?.data?.detail ?? 'GitHub team discovery failed')
  } finally {
    setDiscoveringGithubTeams(false)
  }
}
```

**Step 5: Replace the connections step rendering**

Replace the entire `{step === 'connections' ? ( ... ) : null}` block (lines 1111-1310 approx) with a new layout containing four category cards. Each card has:
- A title row with icon and provider selector dropdown
- Provider-specific fields that appear when a provider is selected
- Collapse/expand behavior

The new connections rendering should have this structure:

```tsx
{step === 'connections' ? (
  <div>
    <div className="mb-8 flex items-start gap-4">
      <div className="rounded-3xl bg-cyan-500/10 p-3 text-cyan-300">
        <KeyRound size={22} />
      </div>
      <div>
        <p className="text-[11px] uppercase tracking-[0.24em] text-slate-500">Runtime credentials</p>
        <h2 className="mt-2 text-2xl font-semibold text-white">Connect your tools — all optional.</h2>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-400">
          Pick the providers you use. Every integration is optional — the dashboard works in
          degraded mode without them. You can always add more from Settings later.
        </p>
      </div>
    </div>

    <div className="grid gap-6 xl:grid-cols-[1.2fr_0.8fr]">
      <div className="space-y-6">
        {/* ─── Code Platform ─── */}
        <div className="rounded-3xl border border-slate-800 bg-slate-950/70 p-5">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <FolderGit2 className="text-cyan-300" size={18} />
              <div>
                <p className="text-sm font-semibold text-white">Code Platform</p>
                <p className="text-xs text-slate-500">Engineer activity, MR metrics, and team discovery.</p>
              </div>
            </div>
            <select
              className="setup-input !w-auto !py-2 !px-3 !text-xs"
              value={codePlatform}
              onChange={e => setCodePlatform(e.target.value as CodePlatform)}
            >
              <option value="none">None</option>
              <option value="gitlab">GitLab</option>
              <option value="github">GitHub</option>
            </select>
          </div>

          {codePlatform === 'gitlab' ? (
            <div className="mt-5 grid gap-4 md:grid-cols-2">
              <label className="space-y-2 text-sm text-slate-300 md:col-span-2">
                <span className="text-xs uppercase tracking-[0.18em] text-slate-500">Base URL</span>
                <input className="setup-input" value={gitlab.url} placeholder="https://gitlab.com"
                  onChange={e => setGitlab(c => ({ ...c, url: e.target.value }))} />
              </label>
              <label className="space-y-2 text-sm text-slate-300 md:col-span-2">
                <span className="text-xs uppercase tracking-[0.18em] text-slate-500">Personal access token</span>
                <input className="setup-input font-mono text-xs" type="password" value={gitlab.token} placeholder="glpat-..."
                  onChange={e => setGitlab(c => ({ ...c, token: e.target.value }))} />
              </label>
              <label className="space-y-2 text-sm text-slate-300 md:col-span-2">
                <span className="text-xs uppercase tracking-[0.18em] text-slate-500">Base group for discovery</span>
                <input className="setup-input font-mono text-xs" value={gitlab.baseGroup} placeholder="acme/teams"
                  onChange={e => setGitlab(c => ({ ...c, baseGroup: e.target.value }))} />
              </label>
            </div>
          ) : codePlatform === 'github' ? (
            <div className="mt-5 grid gap-4 md:grid-cols-2">
              <label className="space-y-2 text-sm text-slate-300 md:col-span-2">
                <span className="text-xs uppercase tracking-[0.18em] text-slate-500">Personal access token</span>
                <input className="setup-input font-mono text-xs" type="password" value={github.token} placeholder="ghp_..."
                  onChange={e => setGithub(c => ({ ...c, token: e.target.value }))} />
              </label>
              <label className="space-y-2 text-sm text-slate-300 md:col-span-2">
                <span className="text-xs uppercase tracking-[0.18em] text-slate-500">Organization</span>
                <input className="setup-input font-mono text-xs" value={github.org} placeholder="my-org"
                  onChange={e => setGithub(c => ({ ...c, org: e.target.value }))} />
              </label>
            </div>
          ) : null}
        </div>

        {/* ─── Issue Tracker ─── */}
        <div className="rounded-3xl border border-slate-800 bg-slate-950/70 p-5">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <ShieldCheck className="text-amber-300" size={18} />
              <div>
                <p className="text-sm font-semibold text-white">Issue Tracker</p>
                <p className="text-xs text-slate-500">Epic health, project drill-through, and roadmap views.</p>
              </div>
            </div>
            <select
              className="setup-input !w-auto !py-2 !px-3 !text-xs"
              value={issueTracker}
              onChange={e => setIssueTracker(e.target.value as IssueTracker)}
            >
              <option value="none">None</option>
              <option value="jira">Jira</option>
              <option value="linear">Linear</option>
              <option value="monday">Monday.com</option>
              <option value="asana">Asana</option>
            </select>
          </div>

          {issueTracker === 'jira' ? (
            <div className="mt-5 grid gap-4 md:grid-cols-2">
              <label className="space-y-2 text-sm text-slate-300 md:col-span-2">
                <span className="text-xs uppercase tracking-[0.18em] text-slate-500">Jira URL</span>
                <input className="setup-input" value={jira.url} placeholder="https://your-org.atlassian.net"
                  onChange={e => setJira(c => ({ ...c, url: e.target.value }))} />
              </label>
              <label className="space-y-2 text-sm text-slate-300">
                <span className="text-xs uppercase tracking-[0.18em] text-slate-500">Email</span>
                <input className="setup-input" value={jira.email} placeholder="you@company.com"
                  onChange={e => setJira(c => ({ ...c, email: e.target.value }))} />
              </label>
              <label className="space-y-2 text-sm text-slate-300">
                <span className="text-xs uppercase tracking-[0.18em] text-slate-500">API token</span>
                <input className="setup-input font-mono text-xs" type="password" value={jira.token} placeholder="ATATT3x..."
                  onChange={e => setJira(c => ({ ...c, token: e.target.value }))} />
              </label>
            </div>
          ) : issueTracker === 'linear' ? (
            <div className="mt-5">
              <label className="space-y-2 text-sm text-slate-300">
                <span className="text-xs uppercase tracking-[0.18em] text-slate-500">API key</span>
                <input className="setup-input font-mono text-xs" type="password" value={linear.apiKey} placeholder="lin_api_..."
                  onChange={e => setLinear(c => ({ ...c, apiKey: e.target.value }))} />
              </label>
            </div>
          ) : issueTracker === 'monday' ? (
            <div className="mt-5">
              <label className="space-y-2 text-sm text-slate-300">
                <span className="text-xs uppercase tracking-[0.18em] text-slate-500">API token</span>
                <input className="setup-input font-mono text-xs" type="password" value={monday.token} placeholder="eyJhbG..."
                  onChange={e => setMonday(c => ({ ...c, token: e.target.value }))} />
              </label>
            </div>
          ) : issueTracker === 'asana' ? (
            <div className="mt-5">
              <label className="space-y-2 text-sm text-slate-300">
                <span className="text-xs uppercase tracking-[0.18em] text-slate-500">Personal access token</span>
                <input className="setup-input font-mono text-xs" type="password" value={asana.token} placeholder="1/12345..."
                  onChange={e => setAsana(c => ({ ...c, token: e.target.value }))} />
              </label>
            </div>
          ) : null}
        </div>

        {/* ─── AI Provider ─── */}
        <div className="rounded-3xl border border-slate-800 bg-slate-950/70 p-5">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <Sparkles className="text-violet-300" size={18} />
              <div>
                <p className="text-sm font-semibold text-white">AI Provider</p>
                <p className="text-xs text-slate-500">Powers AI summaries and analysis features.</p>
              </div>
            </div>
            <select
              className="setup-input !w-auto !py-2 !px-3 !text-xs"
              value={aiProvider}
              onChange={e => setAiProvider(e.target.value as AiProvider)}
            >
              <option value="none">None</option>
              <option value="openai">OpenAI</option>
              <option value="anthropic">Anthropic</option>
            </select>
          </div>

          {aiProvider === 'openai' ? (
            <div className="mt-5">
              <label className="space-y-2 text-sm text-slate-300">
                <span className="text-xs uppercase tracking-[0.18em] text-slate-500">API key</span>
                <input className="setup-input font-mono text-xs" type="password" value={ai.openaiKey} placeholder="sk-..."
                  onChange={e => setAi(c => ({ ...c, openaiKey: e.target.value }))} />
              </label>
            </div>
          ) : aiProvider === 'anthropic' ? (
            <div className="mt-5">
              <label className="space-y-2 text-sm text-slate-300">
                <span className="text-xs uppercase tracking-[0.18em] text-slate-500">API key</span>
                <input className="setup-input font-mono text-xs" type="password" value={ai.anthropicKey} placeholder="sk-ant-..."
                  onChange={e => setAi(c => ({ ...c, anthropicKey: e.target.value }))} />
              </label>
            </div>
          ) : null}
        </div>

        {/* ─── Security ─── */}
        <div className="rounded-3xl border border-slate-800 bg-slate-950/70 p-5">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <ShieldCheck className="text-emerald-300" size={18} />
              <div>
                <p className="text-sm font-semibold text-white">Security</p>
                <p className="text-xs text-slate-500">Vulnerability scanning and security dashboard.</p>
              </div>
            </div>
            <select
              className="setup-input !w-auto !py-2 !px-3 !text-xs"
              value={securityProvider}
              onChange={e => setSecurityProvider(e.target.value as SecurityProvider)}
            >
              <option value="none">None</option>
              <option value="snyk">Snyk</option>
            </select>
          </div>

          {securityProvider === 'snyk' ? (
            <div className="mt-5">
              <label className="space-y-2 text-sm text-slate-300">
                <span className="text-xs uppercase tracking-[0.18em] text-slate-500">Auth token</span>
                <input className="setup-input font-mono text-xs" type="password" value={optional.snykToken} placeholder="snyk token..."
                  onChange={e => setOptional(c => ({ ...c, snykToken: e.target.value }))} />
              </label>
            </div>
          ) : null}
        </div>

        {/* ─── Port (DORA) — keep in Optional section ─── */}
        <div className="rounded-3xl border border-slate-800 bg-slate-950/70 p-5">
          <button
            type="button"
            onClick={() => setAdvancedOpen(open => !open)}
            className="flex w-full items-center justify-between gap-3 text-left"
          >
            <div>
              <p className="text-sm font-semibold text-white">Port (DORA metrics)</p>
              <p className="mt-1 text-xs text-slate-500">Enables service catalog and Port-backed DORA data.</p>
            </div>
            <ChevronRight size={16} className={`text-slate-500 transition-transform ${advancedOpen ? 'rotate-90' : ''}`} />
          </button>

          {advancedOpen ? (
            <div className="mt-5 grid gap-4 md:grid-cols-2">
              <label className="space-y-2 text-sm text-slate-300">
                <span className="text-xs uppercase tracking-[0.18em] text-slate-500">Port client ID</span>
                <input className="setup-input" value={optional.portClientId}
                  onChange={e => setOptional(c => ({ ...c, portClientId: e.target.value }))} />
              </label>
              <label className="space-y-2 text-sm text-slate-300">
                <span className="text-xs uppercase tracking-[0.18em] text-slate-500">Port client secret</span>
                <input className="setup-input" type="password" value={optional.portClientSecret}
                  onChange={e => setOptional(c => ({ ...c, portClientSecret: e.target.value }))} />
              </label>
              <label className="space-y-2 text-sm text-slate-300 md:col-span-2">
                <span className="text-xs uppercase tracking-[0.18em] text-slate-500">Port base URL</span>
                <input className="setup-input" value={optional.portBaseUrl}
                  onChange={e => setOptional(c => ({ ...c, portBaseUrl: e.target.value }))} />
              </label>
            </div>
          ) : null}
        </div>
      </div>

      {/* ─── Sidebar: validation badges + actions ─── */}
      <div className="space-y-4">
        {codePlatform !== 'none' ? <ValidationBadge label={codePlatform === 'gitlab' ? 'GitLab' : 'GitHub'} result={validation?.[codePlatform]} /> : null}
        {issueTracker !== 'none' ? <ValidationBadge label={issueTracker.charAt(0).toUpperCase() + issueTracker.slice(1)} result={validation?.[issueTracker]} /> : null}
        {aiProvider !== 'none' ? <ValidationBadge label={aiProvider === 'openai' ? 'OpenAI' : 'Anthropic'} result={validation?.[aiProvider]} /> : null}
        {securityProvider !== 'none' ? <ValidationBadge label="Snyk" result={validation?.snyk} /> : null}

        {!hasAnyConnection ? (
          <div className="rounded-2xl border border-amber-500/25 bg-amber-500/10 px-4 py-3 text-xs leading-5 text-amber-200">
            No integrations selected. The dashboard will have limited data until you add connections from Settings.
          </div>
        ) : null}

        <button
          type="button"
          onClick={validateConnections}
          disabled={validating || !hasAnyConnection}
          className="inline-flex w-full items-center justify-center gap-2 rounded-2xl bg-cyan-400 px-4 py-3 text-sm font-semibold text-slate-950 transition-colors hover:bg-cyan-300 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
        >
          {validating ? <Loader2 size={16} className="animate-spin" /> : <ShieldCheck size={16} />}
          Validate connections
        </button>

        {codePlatform === 'gitlab' && validation?.gitlab?.ok && gitlab.baseGroup.trim() ? (
          <button type="button" onClick={() => void discoverGitLabGroups(false)}
            disabled={discoveringGroups}
            className="inline-flex w-full items-center justify-center gap-2 rounded-2xl border border-slate-700 px-4 py-3 text-sm font-medium text-slate-200 transition-colors hover:border-slate-500 hover:text-white disabled:cursor-not-allowed disabled:opacity-50">
            {discoveringGroups ? <Loader2 size={16} className="animate-spin" /> : <FolderGit2 size={16} />}
            Discover GitLab teams
          </button>
        ) : null}

        {codePlatform === 'github' && validation?.github?.ok && github.org.trim() ? (
          <button type="button" onClick={() => void discoverGitHubTeams(false)}
            disabled={discoveringGithubTeams}
            className="inline-flex w-full items-center justify-center gap-2 rounded-2xl border border-slate-700 px-4 py-3 text-sm font-medium text-slate-200 transition-colors hover:border-slate-500 hover:text-white disabled:cursor-not-allowed disabled:opacity-50">
            {discoveringGithubTeams ? <Loader2 size={16} className="animate-spin" /> : <FolderGit2 size={16} />}
            Discover GitHub teams
          </button>
        ) : null}

        {issueTracker === 'jira' && validation?.jira?.ok ? (
          <button type="button" onClick={() => void discoverJiraProjects(false)}
            disabled={discoveringProjects}
            className="inline-flex w-full items-center justify-center gap-2 rounded-2xl border border-slate-700 px-4 py-3 text-sm font-medium text-slate-200 transition-colors hover:border-slate-500 hover:text-white disabled:cursor-not-allowed disabled:opacity-50">
            {discoveringProjects ? <Loader2 size={16} className="animate-spin" /> : <RefreshCcw size={16} />}
            Discover Jira projects
          </button>
        ) : null}

        {groupsError ? (
          <div className="rounded-2xl border border-rose-500/25 bg-rose-500/10 px-4 py-3 text-xs leading-5 text-rose-200">{groupsError}</div>
        ) : null}
        {githubTeamsError ? (
          <div className="rounded-2xl border border-rose-500/25 bg-rose-500/10 px-4 py-3 text-xs leading-5 text-rose-200">{githubTeamsError}</div>
        ) : null}
        {projectsError ? (
          <div className="rounded-2xl border border-rose-500/25 bg-rose-500/10 px-4 py-3 text-xs leading-5 text-rose-200">{projectsError}</div>
        ) : null}
      </div>
    </div>
  </div>
) : null}
```

**Step 6: Update the createDomain payload**

Replace the `createDomain` function's payload builder (lines 899-955) to send all selected providers:

```typescript
const payload: Record<string, unknown> = {
  organization: {
    name: org.name.trim(),
    slug: org.slug.trim(),
    description: org.description.trim(),
  },
  user: {
    name: user.name.trim(),
    email: user.email.trim(),
    role: user.role.trim(),
    timezone: user.timezone.trim(),
  },
  teams: teams.map(team => ({
    key: team.jiraKey.trim() || team.slug.toUpperCase().replace(/-/g, '_'),
    name: team.name.trim(),
    slug: team.slug.trim(),
    scrum_name: team.scrumName.trim() || team.name.trim(),
    lead: team.lead.trim(),
    lead_email: team.leadEmail.trim(),
    headcount: team.members.length,
    jira_project: team.jiraKey.trim() || undefined,
    gitlab_path: team.gitlabPath.trim(),
    gitlab_members: team.members.map(member => ({
      username: member.username.trim(),
      name: member.name.trim(),
      role: member.role,
      email: member.email.trim() || undefined,
    })),
  })),
}

// Code platform
if (codePlatform === 'gitlab' && gitlab.token.trim()) {
  payload.gitlab = {
    token: gitlab.token,
    url: gitlab.url.trim(),
    base_group: gitlab.baseGroup.trim(),
  }
}
if (codePlatform === 'github' && github.token.trim()) {
  payload.github = {
    token: github.token,
    org: github.org.trim(),
  }
}

// Issue tracker
if (issueTracker === 'jira' && jira.url.trim() && jira.email.trim() && jira.token.trim()) {
  payload.jira = {
    url: jira.url.trim(),
    email: jira.email.trim(),
    token: jira.token,
  }
}
if (issueTracker === 'linear' && linear.apiKey.trim()) {
  payload.linear = { api_key: linear.apiKey }
}
if (issueTracker === 'monday' && monday.token.trim()) {
  payload.monday = { token: monday.token }
}
if (issueTracker === 'asana' && asana.token.trim()) {
  payload.asana = { token: asana.token }
}

// AI
if (aiProvider !== 'none') {
  payload.llm = {
    openai_api_key: aiProvider === 'openai' ? ai.openaiKey.trim() : '',
    anthropic_api_key: aiProvider === 'anthropic' ? ai.anthropicKey.trim() : '',
  }
}

// Port + Snyk
if (optional.portClientId.trim() || optional.portClientSecret.trim() || optional.snykToken.trim()) {
  payload.optional = {
    port_client_id: optional.portClientId.trim(),
    port_client_secret: optional.portClientSecret.trim(),
    port_base_url: optional.portBaseUrl.trim(),
    snyk_token: optional.snykToken.trim(),
  }
}
```

**Step 7: Update the Review step**

Replace the hardcoded GitLab/Jira summary in the review step (lines 1480-1489) to dynamically show configured providers:

```tsx
<div>
  <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Code platform</p>
  <p className="mt-2 text-sm text-white">
    {codePlatform === 'gitlab' ? `GitLab — ${validation?.gitlab?.user || 'Validated'}` :
     codePlatform === 'github' ? `GitHub — ${validation?.github?.user || 'Validated'}` :
     'None'}
  </p>
  <p className="mt-1 font-mono text-xs text-slate-500">
    {codePlatform === 'gitlab' ? (gitlab.baseGroup || gitlab.url) :
     codePlatform === 'github' ? github.org :
     'Not configured'}
  </p>
</div>
<div>
  <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Issue tracker</p>
  <p className="mt-2 text-sm text-white">
    {issueTracker === 'jira' ? `Jira — ${validation?.jira?.user || 'Validated'}` :
     issueTracker === 'linear' ? `Linear — ${validation?.linear?.user || 'Validated'}` :
     issueTracker === 'monday' ? `Monday — ${validation?.monday?.user || 'Validated'}` :
     issueTracker === 'asana' ? `Asana — ${validation?.asana?.user || 'Validated'}` :
     'None'}
  </p>
  <p className="mt-1 text-xs text-slate-500">
    {issueTracker === 'jira' ? jira.url :
     issueTracker !== 'none' ? 'Connected' :
     'Not configured'}
  </p>
</div>
```

**Step 8: Update reviewWarnings**

Replace `reviewWarnings` useMemo (lines 604-619) to reflect all providers:

```typescript
const reviewWarnings = useMemo(() => {
  const warnings: string[] = []
  if (codePlatform === 'none') {
    warnings.push('No code platform connected. Engineer activity and MR metrics will be unavailable.')
  }
  if (issueTracker === 'none') {
    warnings.push('No issue tracker connected. Epic health and roadmap views will be unavailable.')
  }
  if (teamsWithoutMembers.length > 0) {
    warnings.push(`${teamsWithoutMembers.length} team${teamsWithoutMembers.length === 1 ? '' : 's'} still have no members.`)
  }
  if (aiProvider === 'none') {
    warnings.push('No AI provider connected. AI summaries and analysis will be unavailable.')
  }
  return warnings
}, [codePlatform, issueTracker, aiProvider, teamsWithoutMembers.length])
```

**Step 9: Update Teams step hints**

In the Teams step, update the hint about GitLab path requirement at line 1400:

```tsx
<p className="mt-1 text-xs text-slate-500">
  Every team needs a name and slug. {codePlatform !== 'none' ? 'A code platform path enables auto-discovery.' : 'Add teams manually since no code platform is connected.'}
</p>
```

Also update `incompleteTeams` (line 596) to no longer require gitlabPath:

```typescript
const incompleteTeams = useMemo(
  () => teams.filter(team => !team.name.trim() || !team.slug.trim()),
  [teams],
)
```

**Step 10: Update STEPS hint text**

Update the connections step hint in `STEPS` array (line 117):

```typescript
{ key: 'connections', label: 'Connections', hint: 'Connect your tools (all optional)' },
```

**Step 11: Build and verify**

Run: `cd /Users/larfan/Projects/eng-dashboard/frontend && npm run build`
Expected: Build succeeds with no TypeScript errors.

**Step 12: Commit**

```bash
git add frontend/src/pages/Setup.tsx
git commit -m "feat: refactor onboarding connections to category-based all-optional provider selector"
```

---

### Task 6: Frontend — Add GitHub team discovery to the Teams step

**Files:**
- Modify: `frontend/src/pages/Setup.tsx` (Teams step section)

**Step 1: Add GitHub teams to the discovery panel**

In the Teams step, alongside the existing GitLab group discovery panel, add GitHub team discovery. When `codePlatform === 'github'`, show discovered GitHub teams instead of GitLab groups. When `codePlatform === 'none'`, show only the manual team entry.

Add a function to build teams from GitHub discovery:

```typescript
const buildTeamFromGithubTeam = (team: {slug: string; name: string; description: string}): TeamForm => ({
  jiraKey: '',
  name: team.name || titleFromSlug(team.slug),
  slug: team.slug,
  scrumName: team.name || titleFromSlug(team.slug),
  lead: '',
  leadEmail: '',
  gitlabPath: github.org ? `${github.org}/${team.slug}` : team.slug,
  members: [],
})
```

Update the Teams step discovery panel to conditionally show either GitLab groups, GitHub teams, or a manual-only message based on `codePlatform`.

**Step 2: Add GitHub member discovery**

Add a function to discover members for GitHub teams:

```typescript
const discoverGithubMembersForTeam = async (teamIndex: number) => {
  const team = teams[teamIndex]
  const key = teamKey(team, teamIndex)
  if (!team?.gitlabPath || !github.org.trim()) return

  setMemberLoading(c => ({ ...c, [key]: true }))
  setMemberErrors(c => { const n = { ...c }; delete n[key]; return n })

  try {
    const teamSlug = team.gitlabPath.split('/').pop() || team.slug
    const response = await axios.get('/api/onboard/discover/github-members', {
      params: { org: github.org.trim(), team_slug: teamSlug },
      headers: { 'X-GitHub-Token': github.token },
    })
    const members: Member[] = (response.data.members ?? []).map((m: any) => ({
      username: m.username || '', name: m.name || m.username || '', email: '', role: 'engineer' as MemberRole,
    }))
    updateTeam(teamIndex, { ...team, members })
  } catch (error: any) {
    setMemberErrors(c => ({ ...c, [key]: error.response?.data?.detail ?? 'GitHub member discovery failed' }))
  } finally {
    setMemberLoading(c => ({ ...c, [key]: false }))
  }
}
```

Update the `TeamEditor`'s "Discover members" button to call the right discovery function based on `codePlatform`.

**Step 3: Build and verify**

Run: `cd /Users/larfan/Projects/eng-dashboard/frontend && npm run build`
Expected: Build succeeds.

**Step 4: Commit**

```bash
git add frontend/src/pages/Setup.tsx
git commit -m "feat: add GitHub team and member discovery to Teams step"
```

---

### Task 7: Full integration test — verify build and backend tests pass

**Step 1: Run all backend tests**

Run: `cd /Users/larfan/Projects/eng-dashboard && python -m pytest backend/tests/ -v --no-header`
Expected: ALL PASS

**Step 2: Run frontend build**

Run: `cd /Users/larfan/Projects/eng-dashboard/frontend && npm run build`
Expected: Build succeeds.

**Step 3: Commit design doc and plan**

```bash
git add docs/plans/2026-03-08-all-optional-provider-onboarding-design.md docs/plans/2026-03-08-all-optional-provider-onboarding.md
git commit -m "docs: add design and implementation plan for all-optional provider onboarding"
```
