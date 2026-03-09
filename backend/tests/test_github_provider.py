"""Tests for GitHub provider support."""
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.models_domain import DomainBase, MRActivity, RefTeam, RefMember
from backend.services.git_providers.base import GitProvider
from backend.services.git_providers.gitlab_provider import GitLabProvider


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


class TestGitProviderInterface:
    def test_pull_request_data_is_a_dataclass(self):
        from backend.services.git_providers.base import GitProvider, PullRequestData

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
        from backend.services.git_providers.base import GitProvider

        with pytest.raises(TypeError):
            GitProvider()  # Cannot instantiate abstract class


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
