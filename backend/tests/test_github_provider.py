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
