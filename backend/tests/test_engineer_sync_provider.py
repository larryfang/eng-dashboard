"""Tests for provider-aware engineer sync."""
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.models_domain import DomainBase, RefTeam, RefMember, MRActivity
from backend.services.git_providers.base import GitProvider, PullRequestData


def _make_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    DomainBase.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


class TestProviderAwareSync:
    def test_sync_creates_correct_provider_per_team(self, monkeypatch):
        """Engineers on GitHub teams use GitHubProvider, GitLab teams use GitLabProvider."""
        from backend.services.engineer_sync_service import sync_engineers

        db = _make_db()
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
            mock.close = MagicMock()
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

    def test_sync_writes_provider_to_mr_activity(self, monkeypatch):
        """MRs synced from GitHub should have provider='github' in mr_activity."""
        from backend.services.engineer_sync_service import sync_engineers

        db = _make_db()
        db.add(RefTeam(slug="beta", key="BETA", name="Beta", git_provider="github"))
        db.add(RefMember(
            gitlab_username="bob", name="Bob", team_slug="beta",
            team_display="Beta", role="engineer",
        ))
        db.commit()

        mock_provider = MagicMock(spec=GitProvider)
        mock_provider.fetch_pull_requests.return_value = [
            PullRequestData(
                pr_iid=101, repo_id="acme/repo", title="Fix bug",
                source_branch="fix/bug", author_username="bob",
                state="merged",
                created_at=datetime(2026, 1, 15, tzinfo=timezone.utc),
                merged_at=datetime(2026, 1, 16, tzinfo=timezone.utc),
                web_url="https://github.com/acme/repo/pull/101",
            ),
        ]
        mock_provider.close = MagicMock()

        monkeypatch.setattr(
            "backend.services.engineer_sync_service.create_provider",
            lambda name: mock_provider,
        )
        monkeypatch.setattr(
            "backend.services.engineer_sync_service.get_domain_config",
            lambda slug: MagicMock(jira_project_keys=[]),
        )
        monkeypatch.setattr(
            "backend.services.engineer_sync_service.get_active_slug",
            lambda: "test",
        )

        written = sync_engineers(db, days=30)
        assert written == 1

        row = db.query(MRActivity).first()
        assert row is not None
        assert row.provider == "github"
        assert row.author_username == "bob"
        assert row.author_team == "beta"

    def test_sync_skips_provider_without_credentials(self, monkeypatch):
        """If a provider has no credentials, skip those engineers gracefully."""
        from backend.services.engineer_sync_service import sync_engineers

        db = _make_db()
        db.add(RefTeam(slug="gamma", key="GAMMA", name="Gamma", git_provider="github"))
        db.add(RefMember(
            gitlab_username="charlie", name="Charlie", team_slug="gamma",
            team_display="Gamma", role="engineer",
        ))
        db.commit()

        def mock_create_provider(name):
            if name == "github":
                raise RuntimeError("GitHub credentials are not configured")
            mock = MagicMock(spec=GitProvider)
            mock.fetch_pull_requests.return_value = []
            mock.close = MagicMock()
            return mock

        monkeypatch.setattr(
            "backend.services.engineer_sync_service.create_provider",
            mock_create_provider,
        )
        monkeypatch.setattr(
            "backend.services.engineer_sync_service.get_domain_config",
            lambda slug: MagicMock(jira_project_keys=[]),
        )
        monkeypatch.setattr(
            "backend.services.engineer_sync_service.get_active_slug",
            lambda: "test",
        )

        # Should not raise — just skip the GitHub provider
        written = sync_engineers(db, days=30)
        assert written == 0

    def test_upsert_prs_creates_mr_activity_rows(self):
        """_upsert_prs should create MRActivity rows from PullRequestData objects."""
        import re
        from backend.services.engineer_sync_service import _upsert_prs

        db = _make_db()
        member = MagicMock()
        member.gitlab_username = "alice"
        member.team_slug = "alpha"

        prs = [
            PullRequestData(
                pr_iid=42, repo_id="123", title="PROJ-100 Add feature",
                source_branch="feature/PROJ-100-new-thing",
                author_username="alice", state="merged",
                created_at=datetime(2026, 1, 10, tzinfo=timezone.utc),
                merged_at=datetime(2026, 1, 11, tzinfo=timezone.utc),
                web_url="https://gitlab.com/mr/42",
                lines_added=50, lines_removed=10, files_changed=3,
                description="Some description",
            ),
        ]
        jira_pattern = re.compile(r'\b(PROJ)-(\d+)\b')

        count = _upsert_prs(db, member, prs, jira_pattern, provider="gitlab")
        assert count == 1

        row = db.query(MRActivity).first()
        assert row is not None
        assert row.mr_iid == 42
        assert row.repo_id == "123"
        assert row.provider == "gitlab"
        assert row.lines_added == 50
        assert row.jira_tickets is not None
        assert "PROJ-100" in row.jira_tickets

    def test_upsert_prs_updates_existing_row(self):
        """_upsert_prs should update existing rows instead of duplicating."""
        import re
        from backend.services.engineer_sync_service import _upsert_prs

        db = _make_db()
        member = MagicMock()
        member.gitlab_username = "alice"
        member.team_slug = "alpha"

        # Insert initial row
        db.add(MRActivity(
            mr_iid=42, repo_id="123", title="WIP",
            author_username="alice", author_team="old-team",
            state="opened",
            created_at=datetime(2026, 1, 10, tzinfo=timezone.utc),
            provider="gitlab",
        ))
        db.commit()

        # Now upsert with updated data
        prs = [
            PullRequestData(
                pr_iid=42, repo_id="123", title="Done feature",
                source_branch="main",
                author_username="alice", state="merged",
                created_at=datetime(2026, 1, 10, tzinfo=timezone.utc),
                merged_at=datetime(2026, 1, 12, tzinfo=timezone.utc),
                web_url="https://gitlab.com/mr/42",
            ),
        ]
        jira_pattern = re.compile(r'\b([A-Z]{2,8})-(\d+)\b')

        count = _upsert_prs(db, member, prs, jira_pattern, provider="gitlab")
        assert count == 1

        rows = db.query(MRActivity).all()
        assert len(rows) == 1
        assert rows[0].state == "merged"
        assert rows[0].author_team == "alpha"  # Updated from "old-team"
        assert rows[0].merged_at is not None


def _seed_one_team(db):
    db.add(RefTeam(slug="alpha", key="ALPHA", name="Alpha", git_provider="gitlab"))
    for name in ("alice", "bob"):
        db.add(RefMember(gitlab_username=name, name=name.title(), team_slug="alpha",
                         team_display="Alpha", role="engineer"))
    db.commit()


def _patch_config(monkeypatch, provider):
    monkeypatch.setattr("backend.services.engineer_sync_service.create_provider", lambda name: provider)
    monkeypatch.setattr("backend.services.engineer_sync_service.get_domain_config",
                        lambda slug: MagicMock(jira_project_keys=[]))
    monkeypatch.setattr("backend.services.engineer_sync_service.get_active_slug", lambda: "test")


class TestSyncFailureAndForceFull:
    def test_a_run_where_every_fetch_fails_is_an_error_not_a_success(self, monkeypatch):
        """Regression (2026-11-10): an expired token made every fetch fail; the run
        returned 0 and was recorded as `success records=0`."""
        from backend.services.engineer_sync_service import sync_engineers

        db = _make_db()
        _seed_one_team(db)
        provider = MagicMock(spec=GitProvider)
        provider.fetch_pull_requests.side_effect = RuntimeError("401 Unauthorized")
        _patch_config(monkeypatch, provider)

        with pytest.raises(RuntimeError, match="every engineer"):
            sync_engineers(db, days=30)

    def test_force_full_keeps_history_older_than_the_window(self, monkeypatch):
        """force_full deleted ALL rows of the members, then fetched only `days`:
        a full refresh with a 30-day window removed the 60/90/365-day history."""
        from datetime import timedelta

        from backend.services.engineer_sync_service import sync_engineers

        db = _make_db()
        _seed_one_team(db)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        db.add(MRActivity(repo_id="r", mr_iid=1, author_username="alice", title="old",
                          state="merged", created_at=now - timedelta(days=200)))
        db.add(MRActivity(repo_id="r", mr_iid=2, author_username="alice", title="recent",
                          state="merged", created_at=now - timedelta(days=3)))
        db.commit()
        provider = MagicMock(spec=GitProvider)
        provider.fetch_pull_requests.return_value = []
        _patch_config(monkeypatch, provider)

        sync_engineers(db, days=30, force_full=True)

        titles = {m.title for m in db.query(MRActivity).all()}
        assert titles == {"old"}  # in-window rows are rebuilt from the provider; older rows stay

    def test_force_full_with_a_failed_fetch_does_not_delete_that_engineers_rows(self, monkeypatch):
        """The delete ran before the fetch: a failed fetch left the window empty."""
        from datetime import timedelta

        from backend.services.engineer_sync_service import sync_engineers

        db = _make_db()
        _seed_one_team(db)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for iid, who in ((1, "alice"), (2, "bob")):
            db.add(MRActivity(repo_id="r", mr_iid=iid, author_username=who, title=f"{who} recent",
                              state="merged", created_at=now - timedelta(days=3)))
        db.commit()
        provider = MagicMock(spec=GitProvider)

        def fetch(username, since_iso):
            if username == "bob":
                raise RuntimeError("timeout")
            return []

        provider.fetch_pull_requests.side_effect = fetch
        _patch_config(monkeypatch, provider)

        sync_engineers(db, days=30, force_full=True)  # a partial failure does not raise

        assert {m.title for m in db.query(MRActivity).all()} == {"bob recent"}

    def test_force_full_when_every_fetch_fails_keeps_all_rows(self, monkeypatch):
        from datetime import timedelta

        from backend.services.engineer_sync_service import sync_engineers

        db = _make_db()
        _seed_one_team(db)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        db.add(MRActivity(repo_id="r", mr_iid=1, author_username="alice", title="recent",
                          state="merged", created_at=now - timedelta(days=3)))
        db.commit()
        provider = MagicMock(spec=GitProvider)
        provider.fetch_pull_requests.side_effect = RuntimeError("401 Unauthorized")
        _patch_config(monkeypatch, provider)

        with pytest.raises(RuntimeError, match="every engineer"):
            sync_engineers(db, days=30, force_full=True)
        assert db.query(MRActivity).count() == 1

    def test_a_provider_with_no_credentials_is_skipped_without_an_error(self, monkeypatch):
        from backend.services.engineer_sync_service import sync_engineers

        db = _make_db()
        _seed_one_team(db)

        def no_credentials(name):
            raise RuntimeError("GITLAB_TOKEN not configured")

        monkeypatch.setattr("backend.services.engineer_sync_service.create_provider", no_credentials)
        monkeypatch.setattr("backend.services.engineer_sync_service.get_domain_config",
                            lambda slug: MagicMock(jira_project_keys=[]))
        monkeypatch.setattr("backend.services.engineer_sync_service.get_active_slug", lambda: "test")
        assert sync_engineers(db, days=30) == 0
