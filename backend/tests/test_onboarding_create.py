"""
Tests for POST /api/onboard/create — the setup wizard's "Create Domain" endpoint.

This is the most critical flow in the app: a new user completing the wizard
must result in a working domain with config, secrets, seeded DB, and a
readable dashboard.
"""

import json
import shutil
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.routers.onboard_router import create_domain, DomainCreateRequest  # noqa: E402
from backend.services import domain_registry  # noqa: E402


CONFIG_DOMAINS_DIR = ROOT / "config" / "domains"
DATA_DOMAINS_DIR = ROOT / "data" / "domains"


def _cleanup_domain(slug: str):
    """Remove all artifacts for a test domain."""
    yaml_path = CONFIG_DOMAINS_DIR / f"{slug}.yaml"
    db_path = DATA_DOMAINS_DIR / f"{slug}.db"
    secrets_path = DATA_DOMAINS_DIR / f"{slug}.secrets.json"
    active_path = ROOT / "data" / "active_domain.txt"

    for p in [yaml_path, db_path, secrets_path]:
        p.unlink(missing_ok=True)
    for suffix in ["-shm", "-wal"]:
        (DATA_DOMAINS_DIR / f"{slug}.db{suffix}").unlink(missing_ok=True)

    if active_path.exists():
        content = active_path.read_text().strip()
        if content == slug:
            active_path.unlink(missing_ok=True)


def _minimal_payload(slug: str = "test-wizard", **overrides) -> dict:
    """Build a minimal valid wizard payload."""
    base = {
        "organization": {"name": "Test Org", "slug": slug, "description": "Integration test"},
        "user": {"name": "Test User", "email": "test@example.com", "role": "Director", "timezone": "UTC"},
        "teams": [
            {
                "key": "ALPHA",
                "name": "Alpha Team",
                "slug": "alpha",
                "lead": "alice",
                "headcount": 3,
                "jira_project": "ALPHA",
                "git_provider": "github",
                "members": [
                    {"username": "alice", "name": "Alice Anderson", "role": "TL"},
                    {"username": "bob", "name": "Bob Baker", "role": "engineer"},
                ],
            },
        ],
    }
    base.update(overrides)
    return base


@pytest.fixture(autouse=True)
def clean_test_domains():
    """Ensure test domains are cleaned up before and after each test."""
    slugs = ["test-wizard", "test-wizard-gh", "test-wizard-dup", "test-wizard-gitlab"]
    for s in slugs:
        _cleanup_domain(s)
    yield
    for s in slugs:
        _cleanup_domain(s)


@pytest.fixture(autouse=True)
def patch_initial_sync(monkeypatch):
    """Prevent the background sync from actually running during tests.

    create_domain wraps the sync call in try/except, so we just need to make
    run_initial_sync a no-op coroutine. The event loop's create_task will
    schedule it but it completes instantly.
    """
    async def noop():
        pass

    try:
        from backend.services import scheduler
        monkeypatch.setattr(scheduler, "run_initial_sync", noop)
    except (ImportError, AttributeError):
        pass


# ── Core happy path ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_domain_writes_yaml_config():
    """The wizard must write a valid YAML config to config/domains/{slug}.yaml."""
    payload = _minimal_payload()
    body = DomainCreateRequest(**payload)
    result = await create_domain(body)

    assert result["ok"] is True
    assert result["slug"] == "test-wizard"

    config_path = CONFIG_DOMAINS_DIR / "test-wizard.yaml"
    assert config_path.exists(), "YAML config was not written"

    config = yaml.safe_load(config_path.read_text())
    assert config["organization"]["name"] == "Test Org"
    assert config["organization"]["slug"] == "test-wizard"
    assert len(config["teams"]) == 1
    assert config["teams"][0]["name"] == "Alpha Team"
    assert config["teams"][0]["members"][0]["username"] == "alice"


@pytest.mark.asyncio
async def test_create_domain_initializes_and_seeds_db():
    """The wizard must create and seed the SQLite domain DB."""
    payload = _minimal_payload()
    body = DomainCreateRequest(**payload)
    result = await create_domain(body)

    assert result["ok"] is True

    seed = result.get("seeded", {})
    assert seed.get("teams", 0) >= 1, "No teams were seeded"
    assert seed.get("members", 0) >= 2, "Not all members were seeded"

    from backend.database_domain import get_domain_engine
    from sqlalchemy import text
    from sqlalchemy.orm import Session

    engine = get_domain_engine("test-wizard")
    with Session(bind=engine) as db:
        count = db.execute(text("SELECT COUNT(*) FROM ref_teams")).scalar()
        assert count >= 1, "ref_teams table is empty after create"


@pytest.mark.asyncio
async def test_create_domain_seeds_ref_tables():
    """After create, ref_teams and ref_members in the DB must match the YAML."""
    payload = _minimal_payload()
    body = DomainCreateRequest(**payload)
    await create_domain(body)

    from backend.database_domain import get_domain_engine
    from backend.models_domain import RefTeam, RefMember
    from sqlalchemy.orm import Session

    engine = get_domain_engine("test-wizard")
    with Session(bind=engine) as db:
        teams = db.query(RefTeam).all()
        members = db.query(RefMember).all()

    team_slugs = [t.slug for t in teams]
    member_usernames = [m.gitlab_username for m in members]

    assert "alpha" in team_slugs
    assert "alice" in member_usernames
    assert "bob" in member_usernames


@pytest.mark.asyncio
async def test_create_domain_switches_active_domain():
    """After create, the new domain must be the active domain."""
    payload = _minimal_payload()
    body = DomainCreateRequest(**payload)
    await create_domain(body)

    active = domain_registry.get_active_slug()
    assert active == "test-wizard"


# ── Secrets handling ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_domain_saves_github_secrets():
    """GitHub token and org must be persisted to secrets.json."""
    payload = _minimal_payload(
        slug="test-wizard-gh",
        github={"token": "ghp_test_token_123", "org": "acme-corp"},
    )
    body = DomainCreateRequest(**payload)
    result = await create_domain(body)
    assert result["ok"] is True

    secrets_path = DATA_DOMAINS_DIR / "test-wizard-gh.secrets.json"
    assert secrets_path.exists(), "Secrets file was not written"

    secrets = json.loads(secrets_path.read_text())
    assert secrets["github"]["token"] == "ghp_test_token_123"
    assert secrets["github"]["org"] == "acme-corp"


@pytest.mark.asyncio
async def test_create_domain_saves_gitlab_and_jira_secrets():
    """GitLab and Jira credentials must be persisted to secrets.json."""
    payload = _minimal_payload(
        slug="test-wizard-gitlab",
        gitlab={"token": "glpat-test", "url": "https://gitlab.example.com", "base_group": "acme"},
        jira={"url": "https://acme.atlassian.net", "email": "eng@acme.com", "token": "jira-tok-123"},
    )
    body = DomainCreateRequest(**payload)
    result = await create_domain(body)
    assert result["ok"] is True

    secrets_path = DATA_DOMAINS_DIR / "test-wizard-gitlab.secrets.json"
    secrets = json.loads(secrets_path.read_text())

    assert secrets["gitlab"]["token"] == "glpat-test"
    assert secrets["gitlab"]["url"] == "https://gitlab.example.com"
    assert secrets["jira"]["email"] == "eng@acme.com"
    assert secrets["jira"]["token"] == "jira-tok-123"


@pytest.mark.asyncio
async def test_create_domain_saves_llm_secrets():
    """LLM API keys must be persisted to secrets.json."""
    payload = _minimal_payload(
        llm={"openai_api_key": "sk-test-123", "anthropic_api_key": "sk-ant-test-456"},
    )
    body = DomainCreateRequest(**payload)
    result = await create_domain(body)
    assert result["ok"] is True

    secrets_path = DATA_DOMAINS_DIR / "test-wizard.secrets.json"
    secrets = json.loads(secrets_path.read_text())
    assert secrets["llm"]["openai_api_key"] == "sk-test-123"
    assert secrets["llm"]["anthropic_api_key"] == "sk-ant-test-456"


@pytest.mark.asyncio
async def test_create_domain_no_secrets_file_when_no_credentials():
    """If no credentials are provided, no secrets.json should be written."""
    payload = _minimal_payload()
    body = DomainCreateRequest(**payload)
    await create_domain(body)

    secrets_path = DATA_DOMAINS_DIR / "test-wizard.secrets.json"
    if secrets_path.exists():
        secrets = json.loads(secrets_path.read_text())
        assert secrets == {} or all(not v for v in secrets.values()), \
            "Secrets file written with real values when no credentials provided"


# ── Validation / edge cases ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_domain_rejects_empty_slug():
    """Missing or empty slug must return 422."""
    payload = _minimal_payload()
    payload["organization"]["slug"] = ""
    body = DomainCreateRequest(**payload)

    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await create_domain(body)
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_create_domain_rejects_invalid_slug():
    """Slugs with special characters must return 422."""
    payload = _minimal_payload()
    payload["organization"]["slug"] = "test wizard!"
    body = DomainCreateRequest(**payload)

    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await create_domain(body)
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_create_domain_rejects_duplicate():
    """Creating the same slug twice (with teams) must return 409."""
    payload = _minimal_payload(slug="test-wizard-dup")
    body = DomainCreateRequest(**payload)
    result = await create_domain(body)
    assert result["ok"] is True

    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await create_domain(body)
    assert exc_info.value.status_code == 409


# ── YAML integrations section ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_domain_writes_integrations_for_github_and_jira():
    """Integrations section must correctly reflect chosen providers."""
    payload = _minimal_payload(
        slug="test-wizard-gh",
        github={"token": "ghp_test", "org": "acme"},
        jira={"url": "https://acme.atlassian.net", "email": "eng@acme.com", "token": "tok"},
    )
    body = DomainCreateRequest(**payload)
    await create_domain(body)

    config_path = CONFIG_DOMAINS_DIR / "test-wizard-gh.yaml"
    config = yaml.safe_load(config_path.read_text())

    integrations = config.get("integrations", {})
    assert integrations["code_platform"]["provider"] == "github"
    assert integrations["issue_tracker"]["provider"] == "jira"


@pytest.mark.asyncio
async def test_create_domain_writes_integrations_for_gitlab_only():
    """GitLab-only setup must set code_platform to gitlab."""
    payload = _minimal_payload(
        slug="test-wizard-gitlab",
        gitlab={"token": "glpat-test", "url": "https://gitlab.com"},
    )
    body = DomainCreateRequest(**payload)
    await create_domain(body)

    config_path = CONFIG_DOMAINS_DIR / "test-wizard-gitlab.yaml"
    config = yaml.safe_load(config_path.read_text())

    integrations = config.get("integrations", {})
    assert integrations["code_platform"]["provider"] == "gitlab"
    assert "issue_tracker" not in integrations


# ── Round-trip: create → config readable ─────────────────────────────────────

@pytest.mark.asyncio
async def test_round_trip_create_then_read_config():
    """After wizard create, GET /api/config must return the new domain's config."""
    payload = _minimal_payload()
    body = DomainCreateRequest(**payload)
    result = await create_domain(body)
    assert result["ok"] is True

    from backend.core.config_loader import get_domain_config
    cfg = get_domain_config("test-wizard")
    assert cfg.name == "Test Org"
    assert len(cfg.teams) == 1
    assert cfg.teams[0].name == "Alpha Team"
    assert len(cfg.teams[0].gitlab_members) == 2


@pytest.mark.asyncio
async def test_round_trip_create_then_query_db():
    """After create, querying the domain DB must return seeded teams and members."""
    payload = _minimal_payload()
    body = DomainCreateRequest(**payload)
    await create_domain(body)

    from backend.database_domain import get_domain_engine
    from backend.models_domain import RefTeam, RefMember
    from sqlalchemy.orm import Session

    engine = get_domain_engine("test-wizard")
    with Session(bind=engine) as db:
        team = db.query(RefTeam).filter_by(slug="alpha").first()
        assert team is not None, "Team 'alpha' not found in DB after create"
        assert team.name == "Alpha Team"
        assert team.key == "ALPHA"

        members = db.query(RefMember).filter_by(team_slug="alpha").all()
        usernames = {m.gitlab_username for m in members}
        assert "alice" in usernames, "Member 'alice' not found in DB after create"
        assert "bob" in usernames, "Member 'bob' not found in DB after create"
        assert len(members) == 2


@pytest.mark.asyncio
async def test_round_trip_credentials_readable_after_create():
    """After create, domain_credentials must return the saved secrets."""
    payload = _minimal_payload(
        slug="test-wizard-gh",
        github={"token": "ghp_roundtrip", "org": "test-org"},
    )
    body = DomainCreateRequest(**payload)
    await create_domain(body)

    from backend.services.domain_credentials import get_github_settings
    settings = get_github_settings("test-wizard-gh")
    assert settings["token"] == "ghp_roundtrip"
    assert settings["org"] == "test-org"
