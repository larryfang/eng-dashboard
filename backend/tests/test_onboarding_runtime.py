import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(BACKEND) not in sys.path:
    sys.path.insert(1, str(BACKEND))

from backend.config import gitlab_teams  # noqa: E402
from backend.core import config_loader  # noqa: E402
from backend.routers import onboard_router  # noqa: E402
from backend.services import domain_registry  # noqa: E402


class StubResponse:
    def __init__(self, ok=True, status_code=200, payload=None):
        self.ok = ok
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class StubRequest:
    def __init__(self, headers=None):
        self.headers = headers or {}


@pytest.mark.asyncio
async def test_validate_credentials_uses_custom_gitlab_url(monkeypatch):
    calls = []

    def fake_get(url, headers=None, timeout=0, auth=None, params=None):
        calls.append(url)
        return StubResponse(payload={"username": "bot-user"})

    monkeypatch.setattr(onboard_router.requests, "get", fake_get)

    result = await onboard_router.validate_credentials(
        onboard_router.ValidateRequest(
            gitlab_token="glpat-test",
            gitlab_url="https://gitlab.example.internal",
        )
    )

    assert result["gitlab"] == {"ok": True, "user": "bot-user", "error": None}
    assert calls[0] == "https://gitlab.example.internal/api/v4/user"


@pytest.mark.asyncio
async def test_discover_gitlab_members_uses_members_all_endpoint(monkeypatch):
    calls = []

    def fake_get(url, headers=None, params=None, timeout=0):
        calls.append(url)
        page = (params or {}).get("page", 1)
        if page == 1:
            return StubResponse(payload=[{"username": "alice", "name": "Alice", "access_level": 40}])
        return StubResponse(payload=[])

    monkeypatch.setattr(onboard_router.requests, "get", fake_get)

    result = await onboard_router.discover_gitlab_members(
        StubRequest(),
        token="glpat-test",
        gitlab_url="https://gitlab.example.internal",
        group_path="acme/platform/team-alpha",
    )

    assert result == {"members": [{"username": "alice", "name": "Alice", "role": "TL"}]}
    assert calls[0] == "https://gitlab.example.internal/api/v4/groups/acme%2Fplatform%2Fteam-alpha/members/all"


def test_get_config_tracks_active_domain_and_refreshes_gitlab_team_cache(tmp_path, monkeypatch):
    domains_dir = tmp_path / "domains"
    domains_dir.mkdir(parents=True, exist_ok=True)
    active_file = tmp_path / "active_domain.txt"

    alpha = {
        "organization": {"name": "Alpha Domain", "slug": "alpha"},
        "teams": [
            {
                "key": "ALPHA",
                "name": "Alpha",
                "slug": "alpha",
                "jira_project": "ALPHA",
                "gitlab_path": "acme/platform/alpha",
            }
        ],
    }
    beta = {
        "organization": {"name": "Beta Domain", "slug": "beta"},
        "teams": [
            {
                "key": "BETA",
                "name": "Beta",
                "slug": "beta",
                "jira_project": "BETA",
                "gitlab_path": "acme/platform/beta",
            }
        ],
    }

    (domains_dir / "alpha.yaml").write_text(yaml.safe_dump(alpha), encoding="utf-8")
    (domains_dir / "beta.yaml").write_text(yaml.safe_dump(beta), encoding="utf-8")

    monkeypatch.setattr(config_loader, "_CONFIG_DOMAINS_DIR", domains_dir)
    monkeypatch.setattr(config_loader, "_loaders", {})
    monkeypatch.setattr(config_loader, "_config_loader", None)
    monkeypatch.setattr(domain_registry, "_ACTIVE_FILE", active_file)
    monkeypatch.setattr(domain_registry, "_active_slug", None)
    gitlab_teams._reset_for_testing()

    domain_registry.switch_domain("alpha")
    alpha_config = config_loader.get_config()
    assert alpha_config.slug == "alpha"
    assert gitlab_teams.TEAM_GITLAB_PATHS["alpha"] == ["acme/platform/alpha"]

    domain_registry.switch_domain("beta")
    beta_config = config_loader.get_config()
    assert beta_config.slug == "beta"
    assert gitlab_teams.TEAM_GITLAB_PATHS["beta"] == ["acme/platform/beta"]
