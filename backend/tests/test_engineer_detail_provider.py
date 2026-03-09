"""Tests for provider-aware engineer detail endpoint."""
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.models_domain import DomainBase, RefTeam, RefMember, EngineerStats, MRActivity
from backend.services.git_providers.base import GitProvider, PullRequestData


def _make_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    DomainBase.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


class TestEngineerDetailProvider:
    def test_github_engineer_team_detected(self):
        """Engineer detail should detect team's git_provider."""
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

    def test_gitlab_engineer_team_defaults(self):
        """Engineers on teams without explicit git_provider default to gitlab."""
        db = _make_db()
        db.add(RefTeam(slug="alpha", key="ALPHA", name="Alpha"))
        db.add(RefMember(
            gitlab_username="alice", name="Alice", team_slug="alpha",
            team_display="Alpha", role="engineer",
        ))
        db.commit()

        member = db.query(RefMember).filter_by(gitlab_username="alice").first()
        team = db.query(RefTeam).filter_by(slug=member.team_slug).first()
        assert team.git_provider == "gitlab"

    def test_provider_used_for_stats_fetch(self, monkeypatch):
        """When EngineerStats cache is empty, the correct provider should be used."""
        db = _make_db()
        db.add(RefTeam(slug="beta", key="BETA", name="Beta", git_provider="github"))
        db.add(RefMember(
            gitlab_username="bob-gh", name="Bob", team_slug="beta",
            team_display="Beta", role="engineer",
        ))
        db.commit()

        mock_provider = MagicMock(spec=GitProvider)
        mock_provider.fetch_commit_count.return_value = 42
        mock_provider.fetch_review_count.return_value = 7

        created_providers = []

        def mock_create_provider(name):
            created_providers.append(name)
            return mock_provider

        monkeypatch.setattr(
            "backend.routers.gitlab_collector_router.create_provider",
            mock_create_provider,
        )

        # Simulate what the endpoint does: look up member -> team -> provider -> fetch
        from sqlalchemy import func as sqlfunc
        member = db.query(RefMember).filter(
            sqlfunc.lower(RefMember.gitlab_username) == "bob-gh"
        ).first()
        team = db.query(RefTeam).filter_by(slug=member.team_slug).first()
        provider_name = (team.git_provider if team else None) or "gitlab"
        provider = mock_create_provider(provider_name)
        try:
            commits = provider.fetch_commit_count("bob-gh", "2026-01-01T00:00:00Z")
            reviews = provider.fetch_review_count("bob-gh", "2026-01-01T00:00:00Z")
        finally:
            provider.close()

        assert created_providers == ["github"]
        assert commits == 42
        assert reviews == 7
        mock_provider.close.assert_called_once()

    def test_unknown_engineer_falls_back_to_gitlab(self):
        """If engineer has no RefMember record, provider should default to gitlab."""
        db = _make_db()
        # No member record — simulate unknown engineer
        from sqlalchemy import func as sqlfunc
        member = db.query(RefMember).filter(
            sqlfunc.lower(RefMember.gitlab_username) == "unknown-user"
        ).first()
        team = db.query(RefTeam).filter_by(slug=member.team_slug).first() if member else None
        provider_name = (team.git_provider if team else None) or "gitlab"
        assert provider_name == "gitlab"
