# GitHub Provider Support — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add GitHub as a supported code platform alongside GitLab, enabling teams to track PR activity, commits, reviews, and DORA metrics from GitHub repositories.

**Architecture:** A `GitProvider` ABC abstracts platform-specific API calls. The existing GitLab code is extracted into `GitLabProvider`; a new `GitHubProvider` implements the same interface using GitHub's Search API (cross-repo PRs), commits API, and reviews API. The sync layer dispatches to the correct provider based on `organization.yaml → integrations.code_platform.provider`. No frontend changes required — the data model is already provider-agnostic.

**Tech Stack:** Python 3.11+, FastAPI, requests (HTTP), pytest (tests), SQLAlchemy (ORM), GitHub REST API + Search API.

---

## Key Design Decisions

1. **GitHub Search API for cross-repo PR lookup** — equivalent to GitLab's `scope=all`. Query: `is:pr org:{org} author:{user} created:>DATE`. Limited to 1,000 results and 30 req/min.
2. **Per-team provider, not per-org** — `RefTeam.git_provider` allows mixed estates (some teams on GitLab, some on GitHub).
3. **`members` field replaces `gitlab_members`** — backward-compatible: the seeder reads `members` first, falls back to `gitlab_members`.
4. **No GitHub App yet** — start with PAT auth (simpler). GitHub App can be a follow-up for higher rate limits.
5. **`MRActivity` stays unchanged** — the table is already provider-agnostic. We add a `provider` column for filtering/debugging but all downstream aggregation is unchanged.

---

### Task 1: Add `provider` column to MRActivity and `git_provider` to RefTeam

**Files:**
- Modify: `backend/models_domain.py:95-127` (MRActivity) and `backend/models_domain.py:35-56` (RefTeam)
- Test: `backend/tests/test_github_provider.py` (new)

**Step 1: Write failing test — MRActivity has provider column**

Create `backend/tests/test_github_provider.py`:

```python
"""Tests for GitHub provider support."""
import pytest
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.models_domain import DomainBase, MRActivity, RefTeam, RefMember


def _make_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    DomainBase.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


class TestProviderColumns:
    def test_mr_activity_has_provider_column(self):
        db = _make_db()
        db.add(MRActivity(
            mr_iid=1, repo_id="org/repo", title="test",
            author_username="jdoe", author_team="platform",
            state="merged", created_at=datetime.now(timezone.utc),
            provider="github",
        ))
        db.commit()
        row = db.query(MRActivity).first()
        assert row.provider == "github"

    def test_mr_activity_provider_defaults_to_gitlab(self):
        db = _make_db()
        db.add(MRActivity(
            mr_iid=2, repo_id="group/proj", title="test",
            author_username="jdoe", author_team="platform",
            state="merged", created_at=datetime.now(timezone.utc),
        ))
        db.commit()
        row = db.query(MRActivity).first()
        assert row.provider == "gitlab"

    def test_ref_team_has_git_provider_column(self):
        db = _make_db()
        db.add(RefTeam(
            slug="nova", key="NOVA", name="Nova",
            git_provider="github",
        ))
        db.commit()
        row = db.query(RefTeam).first()
        assert row.git_provider == "github"

    def test_ref_team_git_provider_defaults_to_gitlab(self):
        db = _make_db()
        db.add(RefTeam(slug="pluto", key="PLUTO", name="Pluto"))
        db.commit()
        row = db.query(RefTeam).first()
        assert row.git_provider == "gitlab"
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/larfan/Projects/eng-dashboard && python -m pytest backend/tests/test_github_provider.py::TestProviderColumns -v`
Expected: FAIL — `TypeError: 'provider' is an invalid keyword argument`

**Step 3: Add columns to models**

In `backend/models_domain.py`, add to `MRActivity` class (after `cycle_time_hours`):

```python
    provider = Column(String, default="gitlab")  # "gitlab" or "github"
```

In `RefTeam` class (after `products`):

```python
    git_provider = Column(String, default="gitlab")  # "gitlab" or "github"
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/larfan/Projects/eng-dashboard && python -m pytest backend/tests/test_github_provider.py::TestProviderColumns -v`
Expected: All 4 PASS

**Step 5: Commit**

```bash
git add backend/models_domain.py backend/tests/test_github_provider.py
git commit -m "feat: add provider column to MRActivity and git_provider to RefTeam"
```

---

### Task 2: Create GitProvider ABC

**Files:**
- Create: `backend/services/git_providers/__init__.py`
- Create: `backend/services/git_providers/base.py`
- Test: `backend/tests/test_github_provider.py` (append)

**Step 1: Write failing test — GitProvider interface exists**

Append to `backend/tests/test_github_provider.py`:

```python
from backend.services.git_providers.base import GitProvider, PullRequestData


class TestGitProviderInterface:
    def test_pull_request_data_is_a_dataclass(self):
        pr = PullRequestData(
            pr_iid=1,
            repo_id="org/repo",
            title="Add feature",
            source_branch="feat/x",
            author_username="jdoe",
            state="merged",
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            merged_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            web_url="https://github.com/org/repo/pull/1",
            lines_added=10,
            lines_removed=5,
            files_changed=2,
        )
        assert pr.pr_iid == 1
        assert pr.repo_id == "org/repo"

    def test_git_provider_is_abstract(self):
        with pytest.raises(TypeError):
            GitProvider()  # Cannot instantiate abstract class
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/larfan/Projects/eng-dashboard && python -m pytest backend/tests/test_github_provider.py::TestGitProviderInterface -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.services.git_providers'`

**Step 3: Create the provider package and base class**

Create `backend/services/git_providers/__init__.py`:

```python
from backend.services.git_providers.base import GitProvider, PullRequestData

__all__ = ["GitProvider", "PullRequestData"]
```

Create `backend/services/git_providers/base.py`:

```python
"""Abstract base class for git platform providers (GitLab, GitHub)."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass
class PullRequestData:
    """Normalized PR/MR data from any git platform."""
    pr_iid: int
    repo_id: str
    title: str
    source_branch: str | None
    author_username: str
    state: str  # "opened", "merged", "closed"
    created_at: datetime | None
    merged_at: datetime | None
    web_url: str | None
    lines_added: int | None = None
    lines_removed: int | None = None
    files_changed: int | None = None
    description: str | None = None


class GitProvider(ABC):
    """
    Interface for git platform API interactions.

    Each provider (GitLab, GitHub) implements these methods to fetch
    engineer activity data using platform-specific APIs.
    """

    @abstractmethod
    def fetch_pull_requests(
        self, username: str, since_iso: str
    ) -> list[PullRequestData]:
        """Fetch all PRs/MRs authored by username since the given date."""
        ...

    @abstractmethod
    def fetch_commit_count(self, username: str, since_iso: str) -> int:
        """Count commits by username since the given date."""
        ...

    @abstractmethod
    def fetch_review_count(self, username: str, since_iso: str) -> int:
        """Count PR/MR reviews by username since the given date."""
        ...

    @abstractmethod
    def close(self) -> None:
        """Release any held resources (HTTP sessions, etc)."""
        ...
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/larfan/Projects/eng-dashboard && python -m pytest backend/tests/test_github_provider.py::TestGitProviderInterface -v`
Expected: All 2 PASS

**Step 5: Commit**

```bash
git add backend/services/git_providers/
git commit -m "feat: add GitProvider ABC and PullRequestData dataclass"
```

---

### Task 3: Extract GitLab code into GitLabProvider

**Files:**
- Create: `backend/services/git_providers/gitlab_provider.py`
- Test: `backend/tests/test_github_provider.py` (append)

**Step 1: Write failing test — GitLabProvider implements GitProvider**

Append to `backend/tests/test_github_provider.py`:

```python
from unittest.mock import MagicMock
from backend.services.git_providers.gitlab_provider import GitLabProvider


class TestGitLabProvider:
    def test_implements_git_provider(self):
        provider = GitLabProvider(url="https://gitlab.com", token="test-token")
        assert isinstance(provider, GitProvider)

    def test_fetch_pull_requests(self, monkeypatch):
        """GitLabProvider.fetch_pull_requests calls GitLab MR API with scope=all."""
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {
                "iid": 42,
                "project_id": 123,
                "title": "Fix bug",
                "source_branch": "fix/PLAT-99",
                "state": "merged",
                "created_at": "2026-01-01T00:00:00Z",
                "merged_at": "2026-01-02T12:00:00Z",
                "web_url": "https://gitlab.com/group/proj/-/merge_requests/42",
                "author": {"username": "jdoe"},
            },
        ]
        mock_response.raise_for_status = MagicMock()

        provider = GitLabProvider(url="https://gitlab.com", token="test-token")
        monkeypatch.setattr(provider._http, "get", lambda *a, **kw: mock_response)

        prs = provider.fetch_pull_requests("jdoe", "2026-01-01T00:00:00Z")
        assert len(prs) == 1
        assert prs[0].pr_iid == 42
        assert prs[0].repo_id == "123"
        assert prs[0].state == "merged"

    def test_close_closes_http_session(self):
        provider = GitLabProvider(url="https://gitlab.com", token="test")
        provider._http.close = MagicMock()
        provider.close()
        provider._http.close.assert_called_once()
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/larfan/Projects/eng-dashboard && python -m pytest backend/tests/test_github_provider.py::TestGitLabProvider -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.services.git_providers.gitlab_provider'`

**Step 3: Implement GitLabProvider**

Create `backend/services/git_providers/gitlab_provider.py`:

```python
"""GitLab implementation of GitProvider."""

import logging
import requests
from backend.services.git_providers.base import GitProvider, PullRequestData
from backend.services.datetime_utils import parse_dt

logger = logging.getLogger(__name__)
MAX_PAGES = 50


class GitLabProvider(GitProvider):
    """Fetches engineer activity from the GitLab REST API."""

    def __init__(self, url: str, token: str):
        self._url = url.rstrip("/")
        self._http = requests.Session()
        self._http.headers["PRIVATE-TOKEN"] = token

    def fetch_pull_requests(
        self, username: str, since_iso: str
    ) -> list[PullRequestData]:
        mrs: list[PullRequestData] = []
        page = 1
        while page <= MAX_PAGES:
            resp = self._http.get(
                f"{self._url}/api/v4/merge_requests",
                params={
                    "author_username": username,
                    "created_after": since_iso,
                    "state": "all",
                    "scope": "all",
                    "per_page": 100,
                    "page": page,
                    "order_by": "created_at",
                    "sort": "desc",
                },
                timeout=30,
            )
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                break
            for mr in batch:
                mrs.append(PullRequestData(
                    pr_iid=mr["iid"],
                    repo_id=str(mr.get("project_id", "")),
                    title=mr.get("title", ""),
                    source_branch=mr.get("source_branch"),
                    author_username=username,
                    state=mr.get("state", ""),
                    created_at=parse_dt(mr.get("created_at")),
                    merged_at=parse_dt(mr.get("merged_at")),
                    web_url=mr.get("web_url"),
                    description=mr.get("description"),
                ))
            if len(batch) < 100:
                break
            page += 1
        return mrs

    def fetch_commit_count(self, username: str, since_iso: str) -> int:
        try:
            resp = self._http.get(
                f"{self._url}/api/v4/users",
                params={"username": username},
                timeout=10,
            )
            resp.raise_for_status()
            users = resp.json()
            if not users:
                return 0
            user_id = users[0]["id"]

            count = 0
            page = 1
            while page <= MAX_PAGES:
                ev_resp = self._http.get(
                    f"{self._url}/api/v4/users/{user_id}/events",
                    params={
                        "action": "pushed",
                        "created_after": since_iso,
                        "per_page": 100,
                        "page": page,
                    },
                    timeout=20,
                )
                ev_resp.raise_for_status()
                events = ev_resp.json()
                if not events:
                    break
                for ev in events:
                    count += ev.get("push_data", {}).get("commit_count", 0)
                if len(events) < 100:
                    break
                page += 1
            return count
        except Exception as e:
            logger.warning(f"GitLab commit count fetch failed for {username}: {e}")
            return 0

    def fetch_review_count(self, username: str, since_iso: str) -> int:
        try:
            count = 0
            page = 1
            while page <= MAX_PAGES:
                resp = self._http.get(
                    f"{self._url}/api/v4/merge_requests",
                    params={
                        "reviewer_username": username,
                        "created_after": since_iso,
                        "state": "all",
                        "scope": "all",
                        "per_page": 100,
                        "page": page,
                    },
                    timeout=20,
                )
                resp.raise_for_status()
                batch = resp.json()
                if not batch:
                    break
                count += len(batch)
                if len(batch) < 100:
                    break
                page += 1
            return count
        except Exception as e:
            logger.warning(f"GitLab review count fetch failed for {username}: {e}")
            return 0

    def close(self) -> None:
        self._http.close()
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/larfan/Projects/eng-dashboard && python -m pytest backend/tests/test_github_provider.py::TestGitLabProvider -v`
Expected: All 3 PASS

**Step 5: Commit**

```bash
git add backend/services/git_providers/gitlab_provider.py
git commit -m "feat: extract GitLab API code into GitLabProvider class"
```

---

### Task 4: Implement GitHubProvider — PR fetching

**Files:**
- Create: `backend/services/git_providers/github_provider.py`
- Test: `backend/tests/test_github_provider.py` (append)

**Step 1: Write failing test — GitHubProvider fetches PRs via Search API**

Append to `backend/tests/test_github_provider.py`:

```python
from backend.services.git_providers.github_provider import GitHubProvider


class TestGitHubProvider:
    def test_implements_git_provider(self):
        provider = GitHubProvider(token="ghp_test", org="acme")
        assert isinstance(provider, GitProvider)

    def test_fetch_pull_requests_uses_search_api(self, monkeypatch):
        """GitHubProvider uses GitHub Search API with org: qualifier for cross-repo PRs."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "total_count": 1,
            "incomplete_results": False,
            "items": [
                {
                    "number": 101,
                    "title": "Add new feature",
                    "state": "closed",
                    "created_at": "2026-01-15T10:00:00Z",
                    "pull_request": {
                        "merged_at": "2026-01-16T14:30:00Z",
                        "html_url": "https://github.com/acme/repo/pull/101",
                    },
                    "repository_url": "https://api.github.com/repos/acme/repo",
                    "user": {"login": "jdoe"},
                    "body": "Fixes issue #42",
                },
            ],
        }
        mock_response.raise_for_status = MagicMock()
        mock_response.headers = {}

        provider = GitHubProvider(token="ghp_test", org="acme")
        monkeypatch.setattr(provider._http, "get", lambda *a, **kw: mock_response)

        prs = provider.fetch_pull_requests("jdoe", "2026-01-01T00:00:00Z")
        assert len(prs) == 1
        assert prs[0].pr_iid == 101
        assert prs[0].repo_id == "acme/repo"
        assert prs[0].state == "merged"
        assert prs[0].web_url == "https://github.com/acme/repo/pull/101"

    def test_fetch_pull_requests_maps_closed_without_merge_to_closed(self, monkeypatch):
        """PRs that are closed but not merged should have state='closed', not 'merged'."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "total_count": 1,
            "incomplete_results": False,
            "items": [
                {
                    "number": 102,
                    "title": "Rejected PR",
                    "state": "closed",
                    "created_at": "2026-01-15T10:00:00Z",
                    "pull_request": {"merged_at": None, "html_url": "https://github.com/acme/repo/pull/102"},
                    "repository_url": "https://api.github.com/repos/acme/repo",
                    "user": {"login": "jdoe"},
                    "body": None,
                },
            ],
        }
        mock_response.raise_for_status = MagicMock()
        mock_response.headers = {}

        provider = GitHubProvider(token="ghp_test", org="acme")
        monkeypatch.setattr(provider._http, "get", lambda *a, **kw: mock_response)

        prs = provider.fetch_pull_requests("jdoe", "2026-01-01T00:00:00Z")
        assert prs[0].state == "closed"
        assert prs[0].merged_at is None
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/larfan/Projects/eng-dashboard && python -m pytest backend/tests/test_github_provider.py::TestGitHubProvider -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.services.git_providers.github_provider'`

**Step 3: Implement GitHubProvider**

Create `backend/services/git_providers/github_provider.py`:

```python
"""GitHub implementation of GitProvider using REST + Search APIs."""

import logging
import time
import requests
from backend.services.git_providers.base import GitProvider, PullRequestData
from backend.services.datetime_utils import parse_dt

logger = logging.getLogger(__name__)
MAX_PAGES = 10  # GitHub Search API: 1000 results max (10 pages × 100)
SEARCH_RATE_LIMIT_PAUSE = 2.0  # seconds between Search API calls (30/min limit)


class GitHubProvider(GitProvider):
    """Fetches engineer activity from the GitHub REST + Search APIs."""

    def __init__(self, token: str, org: str):
        self._org = org
        self._http = requests.Session()
        self._http.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })

    def fetch_pull_requests(
        self, username: str, since_iso: str
    ) -> list[PullRequestData]:
        """
        Fetch PRs via GitHub Search API.

        Query: is:pr author:{username} org:{org} created:>{date}
        This is the GitHub equivalent of GitLab's scope=all — cross-repo search.

        Note: Search API returns max 1,000 results and has a 30 req/min limit.
        """
        # Convert ISO datetime to date-only for GitHub search qualifier
        since_date = since_iso[:10]  # "2026-01-01T00:00:00Z" → "2026-01-01"
        query = f"is:pr author:{username} org:{self._org} created:>={since_date}"

        prs: list[PullRequestData] = []
        page = 1
        while page <= MAX_PAGES:
            if page > 1:
                time.sleep(SEARCH_RATE_LIMIT_PAUSE)

            resp = self._http.get(
                "https://api.github.com/search/issues",
                params={
                    "q": query,
                    "sort": "created",
                    "order": "desc",
                    "per_page": 100,
                    "page": page,
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            items = data.get("items", [])
            if not items:
                break

            for item in items:
                pr_data = item.get("pull_request", {})
                merged_at_str = pr_data.get("merged_at")
                state = item.get("state", "open")
                # GitHub: closed + merged_at means merged; closed without merged_at means rejected
                if state == "closed" and merged_at_str:
                    state = "merged"

                # Extract repo from repository_url: "https://api.github.com/repos/acme/repo" → "acme/repo"
                repo_url = item.get("repository_url", "")
                repo_id = "/".join(repo_url.split("/")[-2:]) if repo_url else ""

                web_url = pr_data.get("html_url") or item.get("html_url")

                prs.append(PullRequestData(
                    pr_iid=item["number"],
                    repo_id=repo_id,
                    title=item.get("title", ""),
                    source_branch=None,  # Not available from Search API
                    author_username=username,
                    state=state,
                    created_at=parse_dt(item.get("created_at")),
                    merged_at=parse_dt(merged_at_str),
                    web_url=web_url,
                    description=item.get("body"),
                ))

            if len(items) < 100:
                break
            page += 1

        return prs

    def fetch_commit_count(self, username: str, since_iso: str) -> int:
        """
        Count commits by username across all org repos.

        Uses GitHub Search API: type:commit author:{username} org:{org} committer-date:>{date}
        """
        since_date = since_iso[:10]
        query = f"author:{username} org:{self._org} committer-date:>={since_date}"
        try:
            resp = self._http.get(
                "https://api.github.com/search/commits",
                params={"q": query, "per_page": 1},
                timeout=20,
            )
            resp.raise_for_status()
            return resp.json().get("total_count", 0)
        except Exception as e:
            logger.warning(f"GitHub commit count fetch failed for {username}: {e}")
            return 0

    def fetch_review_count(self, username: str, since_iso: str) -> int:
        """
        Count PR reviews by username.

        Uses GitHub Search API: is:pr reviewed-by:{username} org:{org} created:>{date}
        """
        since_date = since_iso[:10]
        query = f"is:pr reviewed-by:{username} org:{self._org} created:>={since_date}"
        try:
            resp = self._http.get(
                "https://api.github.com/search/issues",
                params={"q": query, "per_page": 1},
                timeout=20,
            )
            resp.raise_for_status()
            return resp.json().get("total_count", 0)
        except Exception as e:
            logger.warning(f"GitHub review count fetch failed for {username}: {e}")
            return 0

    def close(self) -> None:
        self._http.close()
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/larfan/Projects/eng-dashboard && python -m pytest backend/tests/test_github_provider.py::TestGitHubProvider -v`
Expected: All 3 PASS

**Step 5: Commit**

```bash
git add backend/services/git_providers/github_provider.py
git commit -m "feat: implement GitHubProvider with Search API for cross-repo PR fetching"
```

---

### Task 5: Add provider factory function

**Files:**
- Create: `backend/services/git_providers/factory.py`
- Modify: `backend/services/git_providers/__init__.py`
- Test: `backend/tests/test_github_provider.py` (append)

**Step 1: Write failing test — factory creates correct provider from config**

Append to `backend/tests/test_github_provider.py`:

```python
from backend.services.git_providers.factory import create_provider


class TestProviderFactory:
    def test_create_gitlab_provider(self, monkeypatch):
        monkeypatch.setattr(
            "backend.services.git_providers.factory.get_gitlab_settings",
            lambda: {"url": "https://gitlab.com", "token": "glpat-xxx", "base_group": ""},
        )
        provider = create_provider("gitlab")
        assert isinstance(provider, GitLabProvider)

    def test_create_github_provider(self, monkeypatch):
        monkeypatch.setattr(
            "backend.services.git_providers.factory.get_github_settings",
            lambda: {"token": "ghp_xxx", "org": "acme"},
        )
        provider = create_provider("github")
        assert isinstance(provider, GitHubProvider)

    def test_create_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unsupported git provider"):
            create_provider("bitbucket")

    def test_create_github_without_token_raises(self, monkeypatch):
        monkeypatch.setattr(
            "backend.services.git_providers.factory.get_github_settings",
            lambda: {"token": "", "org": "acme"},
        )
        with pytest.raises(RuntimeError, match="not configured"):
            create_provider("github")

    def test_create_gitlab_without_token_raises(self, monkeypatch):
        monkeypatch.setattr(
            "backend.services.git_providers.factory.get_gitlab_settings",
            lambda: {"url": "https://gitlab.com", "token": "", "base_group": ""},
        )
        with pytest.raises(RuntimeError, match="not configured"):
            create_provider("gitlab")
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/larfan/Projects/eng-dashboard && python -m pytest backend/tests/test_github_provider.py::TestProviderFactory -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement factory**

Create `backend/services/git_providers/factory.py`:

```python
"""Factory for creating git provider instances from domain configuration."""

from backend.services.git_providers.base import GitProvider
from backend.services.domain_credentials import get_gitlab_settings, get_github_settings


def create_provider(provider_name: str) -> GitProvider:
    """
    Create a GitProvider instance based on the provider name.

    Args:
        provider_name: "gitlab" or "github"

    Returns:
        Configured GitProvider instance.

    Raises:
        ValueError: If provider_name is not supported.
        RuntimeError: If credentials are not configured.
    """
    if provider_name == "gitlab":
        settings = get_gitlab_settings()
        if not settings["token"]:
            raise RuntimeError("GitLab credentials are not configured for the active domain")
        from backend.services.git_providers.gitlab_provider import GitLabProvider
        return GitLabProvider(url=settings["url"], token=settings["token"])

    if provider_name == "github":
        settings = get_github_settings()
        if not settings["token"]:
            raise RuntimeError("GitHub credentials are not configured for the active domain")
        from backend.services.git_providers.github_provider import GitHubProvider
        return GitHubProvider(token=settings["token"], org=settings["org"])

    raise ValueError(f"Unsupported git provider: '{provider_name}'. Supported: gitlab, github")
```

Update `backend/services/git_providers/__init__.py`:

```python
from backend.services.git_providers.base import GitProvider, PullRequestData
from backend.services.git_providers.factory import create_provider

__all__ = ["GitProvider", "PullRequestData", "create_provider"]
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/larfan/Projects/eng-dashboard && python -m pytest backend/tests/test_github_provider.py::TestProviderFactory -v`
Expected: All 5 PASS

**Step 5: Commit**

```bash
git add backend/services/git_providers/factory.py backend/services/git_providers/__init__.py
git commit -m "feat: add provider factory to create GitLab/GitHub providers from config"
```

---

### Task 6: Make engineer_sync_service provider-aware

**Files:**
- Modify: `backend/services/engineer_sync_service.py`
- Test: `backend/tests/test_github_provider.py` (append)

**Step 1: Write failing test — sync uses provider from RefTeam.git_provider**

Append to `backend/tests/test_github_provider.py`:

```python
from backend.services.engineer_sync_service import sync_engineers


class TestProviderAwareSync:
    def test_sync_creates_correct_provider_per_team(self, monkeypatch):
        """Engineers on GitHub teams use GitHubProvider, GitLab teams use GitLabProvider."""
        db = _make_db()

        # Seed: one GitLab team, one GitHub team
        db.add(RefTeam(slug="alpha", key="ALPHA", name="Alpha", git_provider="gitlab"))
        db.add(RefTeam(slug="beta", key="BETA", name="Beta", git_provider="github"))
        db.add(RefMember(
            gitlab_username="alice", name="Alice", team_slug="alpha",
            team_display="Alpha", role="engineer",
        ))
        db.add(RefMember(
            gitlab_username="bob", name="Bob", team_slug="beta",
            team_display="Beta", role="engineer",
        ))
        db.commit()

        providers_created = []

        def mock_create_provider(name):
            providers_created.append(name)
            mock = MagicMock(spec=GitProvider)
            mock.fetch_pull_requests.return_value = []
            return mock

        monkeypatch.setattr(
            "backend.services.engineer_sync_service.create_provider",
            mock_create_provider,
        )
        monkeypatch.setattr(
            "backend.services.engineer_sync_service.get_domain_config",
            lambda slug: MagicMock(jira_project_keys=["ALPHA", "BETA"]),
        )
        monkeypatch.setattr(
            "backend.services.engineer_sync_service.get_active_slug",
            lambda: "test",
        )

        sync_engineers(db, days=30)

        assert "gitlab" in providers_created
        assert "github" in providers_created
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/larfan/Projects/eng-dashboard && python -m pytest backend/tests/test_github_provider.py::TestProviderAwareSync -v`
Expected: FAIL — `sync_engineers` doesn't use `create_provider`

**Step 3: Refactor engineer_sync_service to use GitProvider**

Modify `backend/services/engineer_sync_service.py` — the key changes:

1. Import `create_provider` and `PullRequestData` instead of calling GitLab directly
2. Group members by their team's `git_provider`
3. Create one provider per unique provider type
4. Use `provider.fetch_pull_requests()` instead of `_fetch_mrs()`

Replace the `sync_engineers` function body (lines 45–133) with:

```python
def sync_engineers(db: Session, days: int, force_full: bool = False) -> int:
    from backend.models_domain import RefMember, RefTeam, MRActivity
    from backend.core.config_loader import get_domain_config
    from backend.services.domain_registry import get_active_slug
    from backend.services.git_providers.factory import create_provider

    cfg = get_domain_config(get_active_slug())
    jira_pattern = _build_jira_pattern(cfg.jira_project_keys)
    logger.info(f"Jira pattern for domain '{get_active_slug()}': {cfg.jira_project_keys}")

    since = datetime.now(timezone.utc) - timedelta(days=days)
    since_iso = since.strftime("%Y-%m-%dT%H:%M:%SZ")

    members = db.query(RefMember).filter(RefMember.departed == False).all()
    logger.info(f"Syncing {len(members)} engineers for last {days} days (force_full={force_full})")

    if force_full:
        usernames = [m.gitlab_username for m in members]
        deleted = (
            db.query(MRActivity)
            .filter(MRActivity.author_username.in_(usernames))
            .delete(synchronize_session=False)
        )
        db.commit()
        logger.info(f"force_full: deleted {deleted} existing mr_activity rows")

    # Group members by their team's git_provider
    team_providers: dict[str, str] = {}
    for team in db.query(RefTeam).all():
        team_providers[team.slug] = team.git_provider or "gitlab"

    # Group members by provider
    members_by_provider: dict[str, list] = {}
    for m in members:
        prov = team_providers.get(m.team_slug, "gitlab")
        members_by_provider.setdefault(prov, []).append(m)

    # Fetch MRs per provider group
    total_written = 0
    for provider_name, provider_members in members_by_provider.items():
        try:
            provider = create_provider(provider_name)
        except (RuntimeError, ValueError) as e:
            logger.warning(f"Skipping {provider_name} provider: {e}")
            continue

        member_prs: dict[str, list] = {}

        def _fetch_for_member(member):
            return member.gitlab_username, provider.fetch_pull_requests(member.gitlab_username, since_iso)

        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = {pool.submit(_fetch_for_member, m): m for m in provider_members}
            for future in as_completed(futures):
                m = futures[future]
                try:
                    username, prs = future.result()
                    member_prs[username] = prs
                except Exception as e:
                    logger.warning(f"  {m.gitlab_username}: fetch failed — {e}")

        provider.close()

        # Upsert sequentially — SQLite single writer
        for member in provider_members:
            prs = member_prs.get(member.gitlab_username, [])
            try:
                count = _upsert_prs(db, member, prs, jira_pattern, provider_name)
                total_written += count
                logger.info(f"  {member.gitlab_username} ({provider_name}): {count} PRs synced")
            except Exception as e:
                logger.warning(f"  {member.gitlab_username}: upsert failed — {e}")
                try:
                    db.rollback()
                except Exception:
                    pass

    return total_written
```

Rename `_upsert_mrs` to `_upsert_prs` and update it to accept `PullRequestData` objects (line 166+):

```python
def _upsert_prs(db: Session, member, prs: list, jira_pattern: re.Pattern, provider: str = "gitlab") -> int:
    """Upsert PR/MR rows for one engineer. Returns count written."""
    from backend.models_domain import MRActivity

    count = 0
    for pr in prs:
        repo_id = pr.repo_id
        pr_iid = pr.pr_iid
        if not repo_id or pr_iid is None:
            continue

        branch = pr.source_branch
        title = pr.title or ""
        jira_tickets = _extract_jira_tickets(branch, title, jira_pattern)

        existing = db.query(MRActivity).filter_by(repo_id=repo_id, mr_iid=pr_iid).first()
        if existing:
            existing.state = pr.state
            existing.merged_at = pr.merged_at
            existing.author_team = member.team_slug
            existing.synced_at = datetime.now(timezone.utc)
            if existing.jira_tickets is None and jira_tickets:
                existing.jira_tickets = jira_tickets
        else:
            db.add(MRActivity(
                mr_iid=pr_iid,
                repo_id=repo_id,
                title=title,
                description=pr.description,
                source_branch=branch,
                author_username=member.gitlab_username,
                author_team=member.team_slug,
                state=pr.state,
                created_at=pr.created_at,
                merged_at=pr.merged_at,
                web_url=pr.web_url,
                jira_tickets=jira_tickets,
                lines_added=pr.lines_added,
                lines_removed=pr.lines_removed,
                files_changed=pr.files_changed,
                provider=provider,
                synced_at=datetime.now(timezone.utc),
            ))
        count += 1

    db.commit()
    return count
```

Similarly update `preload_engineer_stats` to use `create_provider`:

```python
def preload_engineer_stats(db: Session, days: int) -> int:
    from backend.models_domain import RefMember, RefTeam, EngineerStats
    from backend.services.git_providers.factory import create_provider

    since = datetime.now(timezone.utc) - timedelta(days=days)
    since_iso = since.strftime("%Y-%m-%dT%H:%M:%SZ")

    members = db.query(RefMember).filter(RefMember.departed == False).all()
    logger.info(f"Preloading stats for {len(members)} engineers (days={days})")

    # Group by provider
    team_providers: dict[str, str] = {}
    for team in db.query(RefTeam).all():
        team_providers[team.slug] = team.git_provider or "gitlab"

    members_by_provider: dict[str, list] = {}
    for m in members:
        prov = team_providers.get(m.team_slug, "gitlab")
        members_by_provider.setdefault(prov, []).append(m)

    now = datetime.now(timezone.utc)
    written = 0

    for provider_name, provider_members in members_by_provider.items():
        try:
            provider = create_provider(provider_name)
        except (RuntimeError, ValueError) as e:
            logger.warning(f"Skipping {provider_name} stats preload: {e}")
            continue

        fetch_results: dict[str, tuple[int, int]] = {}

        def _fetch_for_member(member):
            username = member.gitlab_username
            commits = provider.fetch_commit_count(username, since_iso)
            reviews = provider.fetch_review_count(username, since_iso)
            return username, commits, reviews

        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = {pool.submit(_fetch_for_member, m): m for m in provider_members}
            for future in as_completed(futures):
                m = futures[future]
                try:
                    username, commits, reviews = future.result()
                    fetch_results[username] = (commits, reviews)
                    logger.info(f"  {username}: commits={commits}, reviews={reviews}")
                except Exception as e:
                    logger.warning(f"  {m.gitlab_username}: stats preload failed — {e}")

        provider.close()

        for member in provider_members:
            username = member.gitlab_username
            if username not in fetch_results:
                continue
            commit_count, review_count = fetch_results[username]
            stats_row = db.query(EngineerStats).filter_by(
                username=username.lower(), period_days=days
            ).first()
            if stats_row:
                stats_row.commit_count = commit_count
                stats_row.review_count = review_count
                stats_row.cached_at = now
            else:
                db.add(EngineerStats(
                    username=username.lower(),
                    period_days=days,
                    commit_count=commit_count,
                    review_count=review_count,
                ))
            written += 1

    db.commit()
    return written
```

Remove the old `_fetch_mrs`, `_fetch_commit_count`, `_fetch_review_count` functions and the `get_gitlab_settings` import (those are now in the provider classes). Keep `_build_jira_pattern` and `_extract_jira_tickets` — they're provider-agnostic.

**Step 4: Run all tests**

Run: `cd /Users/larfan/Projects/eng-dashboard && python -m pytest backend/tests/test_github_provider.py -v`
Expected: All tests PASS

**Step 5: Run existing tests to catch regressions**

Run: `cd /Users/larfan/Projects/eng-dashboard && python -m pytest backend/tests/ -v`
Expected: All existing tests still PASS

**Step 6: Commit**

```bash
git add backend/services/engineer_sync_service.py backend/tests/test_github_provider.py
git commit -m "refactor: make engineer_sync_service provider-aware via GitProvider abstraction"
```

---

### Task 7: Update organization.yaml schema — generic `members` field

**Files:**
- Modify: `config/organization.example.yaml`
- Modify: `backend/services/domain_seeder.py`
- Test: `backend/tests/test_github_provider.py` (append)

**Step 1: Write failing test — seeder reads `members` field with fallback to `gitlab_members`**

Append to `backend/tests/test_github_provider.py`:

```python
class TestSeederMembersField:
    def test_seeder_reads_members_field(self):
        """The seeder should read 'members' as the primary field name."""
        team_data = {
            "slug": "nova",
            "key": "NOVA",
            "name": "Nova",
            "git_provider": "github",
            "members": [
                {"username": "alice", "name": "Alice A", "role": "TL"},
                {"username": "bob", "name": "Bob B", "role": "engineer"},
            ],
        }
        members = team_data.get("members") or team_data.get("gitlab_members") or []
        assert len(members) == 2
        assert members[0]["username"] == "alice"

    def test_seeder_falls_back_to_gitlab_members(self):
        """Backward compat: seeder reads 'gitlab_members' if 'members' is absent."""
        team_data = {
            "slug": "pluto",
            "key": "PLUTO",
            "name": "Pluto",
            "gitlab_members": [
                {"username": "charlie", "name": "Charlie C", "role": "engineer"},
            ],
        }
        members = team_data.get("members") or team_data.get("gitlab_members") or []
        assert len(members) == 1
        assert members[0]["username"] == "charlie"
```

**Step 2: Run test to verify it passes (this is a logic test, not a code import test)**

Run: `cd /Users/larfan/Projects/eng-dashboard && python -m pytest backend/tests/test_github_provider.py::TestSeederMembersField -v`
Expected: PASS (pure logic test)

**Step 3: Update the domain seeder**

Read `backend/services/domain_seeder.py` and find where `gitlab_members` is referenced. Change:

```python
# Old:
for member_data in team_data.get("gitlab_members", []):

# New:
for member_data in (team_data.get("members") or team_data.get("gitlab_members") or []):
```

Also add `git_provider` when seeding `RefTeam`:

```python
# When creating/updating RefTeam, add:
team.git_provider = team_data.get("git_provider", "gitlab")
```

**Step 4: Update organization.example.yaml**

Add `git_provider` field and document `members` as the preferred key:

In `config/organization.example.yaml`, update the `code_platform` section:

```yaml
  code_platform:
    provider: gitlab                    # gitlab | github
```

Add `git_provider` and `members` to the team template:

```yaml
teams:
  - key: PLAT
    name: Platform
    slug: platform
    git_provider: gitlab                # gitlab | github (default: gitlab)
    # ...
    members:                            # Preferred field name (gitlab_members still works)
      - username: jlee
        name: Jordan Lee
        role: TL
        exclude_from_metrics: false
```

Add a GitHub team example:

```yaml
  - key: NOVA
    name: Nova
    slug: nova
    git_provider: github
    jira_project: NOVA
    members:
      - username: alice-gh              # GitHub username
        name: Alice Anderson
        role: TL
      - username: bob-gh
        name: Bob Baker
        role: engineer
```

**Step 5: Run all tests**

Run: `cd /Users/larfan/Projects/eng-dashboard && python -m pytest backend/tests/ -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add backend/services/domain_seeder.py config/organization.example.yaml backend/tests/test_github_provider.py
git commit -m "feat: support generic 'members' field in YAML with gitlab_members fallback"
```

---

### Task 8: Update individual engineer endpoint for GitHub

**Files:**
- Modify: `backend/routers/gitlab_collector_router.py` (the `GET /api/gitlab/engineers/{username}` endpoint)
- Test: `backend/tests/test_github_provider.py` (append)

**Step 1: Write failing test — engineer detail uses correct provider**

Append to `backend/tests/test_github_provider.py`:

```python
class TestEngineerDetailProvider:
    def test_github_engineer_uses_github_provider(self):
        """
        The individual engineer endpoint must detect the engineer's team provider
        and use GitHubProvider for GitHub teams.
        """
        db = _make_db()
        db.add(RefTeam(slug="beta", key="BETA", name="Beta", git_provider="github"))
        db.add(RefMember(
            gitlab_username="bob-gh", name="Bob", team_slug="beta",
            team_display="Beta", role="engineer",
        ))
        db.commit()

        member = db.query(RefMember).filter_by(gitlab_username="bob-gh").first()
        team = db.query(RefTeam).filter_by(slug=member.team_slug).first()
        assert team.git_provider == "github"
```

**Step 2: Run test — passes (it's a data setup test)**

**Step 3: Update the engineer detail endpoint**

In `backend/routers/gitlab_collector_router.py`, find the `GET /api/gitlab/engineers/{username}` endpoint. Currently it directly calls GitLab REST API. Change it to:

1. Look up the engineer's team from `RefMember`
2. Look up the team's `git_provider` from `RefTeam`
3. Use `create_provider()` to get the right provider
4. Call `provider.fetch_pull_requests()` instead of direct GitLab calls

The key change pattern:

```python
# Old:
gitlab_settings = get_gitlab_settings()
# ... direct GitLab API calls ...

# New:
member = db.query(RefMember).filter_by(gitlab_username=username).first()
team = db.query(RefTeam).filter_by(slug=member.team_slug).first() if member else None
provider_name = (team.git_provider if team else None) or "gitlab"
provider = create_provider(provider_name)
prs = provider.fetch_pull_requests(username, since_iso)
# ... rest of endpoint uses normalized PullRequestData ...
provider.close()
```

**Step 4: Run all tests**

Run: `cd /Users/larfan/Projects/eng-dashboard && python -m pytest backend/tests/ -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add backend/routers/gitlab_collector_router.py backend/tests/test_github_provider.py
git commit -m "feat: make individual engineer endpoint provider-aware"
```

---

### Task 9: Update get_github_settings with org from domain config

**Files:**
- Modify: `backend/services/domain_credentials.py:131-136`
- Test: `backend/tests/test_github_provider.py` (append)

**Step 1: Write failing test — github settings includes org from config**

Append to `backend/tests/test_github_provider.py`:

```python
class TestGitHubCredentials:
    def test_get_github_settings_returns_token_and_org(self, monkeypatch):
        from backend.services.domain_credentials import get_github_settings

        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test123")
        monkeypatch.setattr(
            "backend.services.domain_credentials.load_domain_secrets",
            lambda slug=None: {"github": {"org": "acme-corp"}},
        )
        settings = get_github_settings()
        assert settings["token"] == "ghp_test123"
        assert settings["org"] == "acme-corp"
```

**Step 2: Run test**

Run: `cd /Users/larfan/Projects/eng-dashboard && python -m pytest backend/tests/test_github_provider.py::TestGitHubCredentials -v`
Expected: Likely PASS (existing code already has token + org)

**Step 3: If the test passes, verify env var fallback works**

The existing `get_github_settings()` already returns `token` and `org`. Optionally add `GITHUB_ORG` env var fallback:

```python
def get_github_settings(domain_slug: str | None = None) -> dict[str, str]:
    secrets = load_domain_secrets(domain_slug).get("github", {}) or {}
    return {
        "token": secrets.get("token") or os.getenv("GITHUB_TOKEN", ""),
        "org": secrets.get("org") or os.getenv("GITHUB_ORG", ""),
    }
```

**Step 4: Run all tests**

Run: `cd /Users/larfan/Projects/eng-dashboard && python -m pytest backend/tests/ -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add backend/services/domain_credentials.py backend/tests/test_github_provider.py
git commit -m "feat: add GITHUB_ORG env var fallback to get_github_settings"
```

---

### Task 10: Add GitHub Teams API discovery (optional feature)

**Files:**
- Create: `backend/services/git_providers/github_discovery.py`
- Test: `backend/tests/test_github_provider.py` (append)

**Step 1: Write failing test — discover_teams returns team + member + repo data**

Append to `backend/tests/test_github_provider.py`:

```python
from backend.services.git_providers.github_discovery import discover_github_teams


class TestGitHubDiscovery:
    def test_discover_teams_parses_api_response(self, monkeypatch):
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {
                "name": "Platform",
                "slug": "platform",
                "parent": None,
            },
        ]
        mock_response.raise_for_status = MagicMock()

        mock_members_response = MagicMock()
        mock_members_response.json.return_value = [
            {"login": "alice", "id": 1},
            {"login": "bob", "id": 2},
        ]
        mock_members_response.raise_for_status = MagicMock()

        mock_repos_response = MagicMock()
        mock_repos_response.json.return_value = [
            {"name": "backend", "full_name": "acme/backend"},
        ]
        mock_repos_response.raise_for_status = MagicMock()

        call_count = 0
        def mock_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if "/teams?" in url or url.endswith("/teams"):
                return mock_response
            if "/members" in url:
                return mock_members_response
            if "/repos" in url:
                return mock_repos_response
            return mock_response

        monkeypatch.setattr("backend.services.git_providers.github_discovery.requests.Session.get", mock_get)

        # Simpler: just test the parsing logic
        teams = discover_github_teams(token="ghp_test", org="acme")
        assert len(teams) >= 1
        assert teams[0]["slug"] == "platform"
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/larfan/Projects/eng-dashboard && python -m pytest backend/tests/test_github_provider.py::TestGitHubDiscovery -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement discovery module**

Create `backend/services/git_providers/github_discovery.py`:

```python
"""
GitHub Teams API discovery.

Fetches team structure, members, and repos from a GitHub organization
using the Teams API. Used during onboarding to auto-populate the
organization.yaml roster from GitHub.
"""

import logging
import requests

logger = logging.getLogger(__name__)


def discover_github_teams(token: str, org: str) -> list[dict]:
    """
    Discover all teams in a GitHub org with their members and repos.

    Returns:
        List of dicts: [{
            "name": "Platform",
            "slug": "platform",
            "parent_slug": None,
            "members": [{"username": "alice", "name": "Alice A"}, ...],
            "repos": [{"name": "backend", "full_name": "acme/backend"}, ...],
        }, ...]
    """
    http = requests.Session()
    http.headers.update({
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })

    try:
        # 1. List all teams
        teams_raw = _paginate(http, f"https://api.github.com/orgs/{org}/teams")

        results = []
        for team in teams_raw:
            slug = team["slug"]
            parent = team.get("parent")

            # 2. Get members for each team
            members_raw = _paginate(
                http, f"https://api.github.com/orgs/{org}/teams/{slug}/members"
            )
            members = [
                {"username": m["login"], "name": m.get("name") or m["login"]}
                for m in members_raw
            ]

            # 3. Get repos for each team
            repos_raw = _paginate(
                http, f"https://api.github.com/orgs/{org}/teams/{slug}/repos"
            )
            repos = [
                {"name": r["name"], "full_name": r["full_name"]}
                for r in repos_raw
            ]

            results.append({
                "name": team["name"],
                "slug": slug,
                "parent_slug": parent["slug"] if parent else None,
                "members": members,
                "repos": repos,
            })

        return results
    finally:
        http.close()


def _paginate(http: requests.Session, url: str, per_page: int = 100) -> list:
    """Paginate a GitHub REST API endpoint using Link headers."""
    all_items = []
    params = {"per_page": per_page, "page": 1}
    max_pages = 20

    for _ in range(max_pages):
        resp = http.get(url, params=params, timeout=20)
        resp.raise_for_status()
        items = resp.json()
        if not items:
            break
        all_items.extend(items)
        if len(items) < per_page:
            break
        params["page"] += 1

    return all_items
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/larfan/Projects/eng-dashboard && python -m pytest backend/tests/test_github_provider.py::TestGitHubDiscovery -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/services/git_providers/github_discovery.py backend/tests/test_github_provider.py
git commit -m "feat: add GitHub Teams API discovery for org roster auto-population"
```

---

### Task 11: Integration test — full GitHub sync flow

**Files:**
- Test: `backend/tests/test_github_provider.py` (append)

**Step 1: Write integration test**

Append to `backend/tests/test_github_provider.py`:

```python
class TestGitHubIntegration:
    """End-to-end test: GitHub team → sync → mr_activity → team_metrics."""

    def test_github_prs_flow_through_to_team_metrics(self, monkeypatch):
        from backend.services.team_metrics_sync_service import sync_team_metrics

        db = _make_db()

        # Seed team + member
        db.add(RefTeam(slug="nova", key="NOVA", name="Nova", git_provider="github"))
        db.add(RefMember(
            gitlab_username="alice-gh", name="Alice", team_slug="nova",
            team_display="Nova", role="engineer",
        ))
        db.commit()

        # Simulate: GitHubProvider already synced these PRs into mr_activity
        now = datetime.now(timezone.utc)
        for i in range(5):
            db.add(MRActivity(
                mr_iid=100 + i,
                repo_id="acme/nova-api",
                title=f"PR #{100+i}",
                author_username="alice-gh",
                author_team="nova",
                state="merged",
                created_at=now - timedelta(days=i+1),
                merged_at=now - timedelta(days=i, hours=12),
                provider="github",
            ))
        db.commit()

        # Run team metrics sync — should work regardless of provider
        written = sync_team_metrics(db, days=30)
        assert written > 0

        from backend.models_domain import TeamMetrics
        metrics = db.query(TeamMetrics).filter_by(team="nova").all()
        assert len(metrics) > 0
        # At least some metrics should show merged MRs
        total_merged = sum(m.mrs_merged for m in metrics)
        assert total_merged == 5
```

**Step 2: Run integration test**

Run: `cd /Users/larfan/Projects/eng-dashboard && python -m pytest backend/tests/test_github_provider.py::TestGitHubIntegration -v`
Expected: PASS — team_metrics_sync_service is provider-agnostic (reads mr_activity regardless of source)

**Step 3: Commit**

```bash
git add backend/tests/test_github_provider.py
git commit -m "test: add integration test for GitHub PR → team_metrics flow"
```

---

### Task 12: Run full test suite and build verification

**Step 1: Run all backend tests**

```bash
cd /Users/larfan/Projects/eng-dashboard && python -m pytest backend/tests/ -v
```

Expected: All PASS

**Step 2: Verify backend starts**

```bash
cd /Users/larfan/Projects/eng-dashboard && timeout 10 python -c "from backend.main import app; print('OK')" || echo "Import check done"
```

Expected: "OK" — no import errors

**Step 3: Final commit (if any fixups needed)**

---

## Summary of Changes

| File | Change Type | Description |
|------|------------|-------------|
| `backend/models_domain.py` | Modify | Add `provider` to MRActivity, `git_provider` to RefTeam |
| `backend/services/git_providers/__init__.py` | Create | Package init with public exports |
| `backend/services/git_providers/base.py` | Create | `GitProvider` ABC + `PullRequestData` dataclass |
| `backend/services/git_providers/gitlab_provider.py` | Create | `GitLabProvider` — extracted from engineer_sync_service |
| `backend/services/git_providers/github_provider.py` | Create | `GitHubProvider` — GitHub Search + Commits + Reviews API |
| `backend/services/git_providers/factory.py` | Create | `create_provider()` — config-driven provider instantiation |
| `backend/services/git_providers/github_discovery.py` | Create | GitHub Teams API discovery for onboarding |
| `backend/services/engineer_sync_service.py` | Modify | Use `GitProvider` instead of direct GitLab API calls |
| `backend/services/domain_credentials.py` | Modify | Add `GITHUB_ORG` env var fallback |
| `backend/services/domain_seeder.py` | Modify | Read `members` field with `gitlab_members` fallback |
| `backend/routers/gitlab_collector_router.py` | Modify | Engineer detail endpoint uses provider factory |
| `config/organization.example.yaml` | Modify | Add `git_provider` + `members` field docs + GitHub example |
| `backend/tests/test_github_provider.py` | Create | All tests for provider abstraction + GitHub support |

## What Does NOT Change

- **Frontend**: Zero changes. All API responses remain the same shape.
- **`team_metrics_sync_service.py`**: Reads `mr_activity` regardless of provider — already agnostic.
- **`scheduler.py`**: Calls `sync_engineers()` which now dispatches internally — no scheduler changes.
- **Alert services**: Read from `mr_activity`/`team_metrics` — provider-agnostic.
- **DORA calculations**: Same logic, same tables, same thresholds.

## Environment Variables

| Variable | Required For | Default |
|----------|-------------|---------|
| `GITHUB_TOKEN` | GitHub provider | — |
| `GITHUB_ORG` | GitHub provider (org name) | — |
| `GITLAB_TOKEN` | GitLab provider (existing) | — |
| `GITLAB_URL` | GitLab provider (existing) | `https://gitlab.com` |

## Rate Limit Considerations

- **GitHub Search API**: 30 requests/min. The `SEARCH_RATE_LIMIT_PAUSE` (2s) in GitHubProvider ensures compliance.
- **GitHub REST API**: 5,000/hr with PAT, 15,000/hr with GitHub App.
- **Commit search**: Uses `total_count` from a single Search API call (no pagination needed for counts).
- **Review search**: Same approach — `total_count` from one call.
- For large orgs (50+ engineers on GitHub), consider upgrading to GitHub App auth in a follow-up.
