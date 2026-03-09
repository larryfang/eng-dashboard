"""Integration test: GitHub PRs → mr_activity → team_metrics."""
import pytest
from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.models_domain import DomainBase, RefTeam, RefMember, MRActivity, TeamMetrics
from backend.services.team_metrics_sync_service import sync_team_metrics


def _make_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    DomainBase.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


class TestGitHubIntegration:
    """End-to-end: GitHub team → mr_activity → team_metrics → DORA."""

    def test_github_prs_flow_through_to_team_metrics(self):
        db = _make_db()

        # Seed team + member
        db.add(RefTeam(slug="nova", key="NOVA", name="Nova", git_provider="github"))
        db.add(RefMember(
            gitlab_username="alice-gh", name="Alice", team_slug="nova",
            team_display="Nova", role="engineer",
        ))
        db.commit()

        # Simulate GitHubProvider having synced 5 merged PRs
        now = datetime.now(timezone.utc)
        for i in range(5):
            db.add(MRActivity(
                mr_iid=100 + i,
                repo_id="acme/nova-api",
                title=f"PR #{100 + i}",
                author_username="alice-gh",
                author_team="nova",
                state="merged",
                created_at=now - timedelta(days=i + 1),
                merged_at=now - timedelta(days=i, hours=12),
                provider="github",
            ))
        db.commit()

        # Run team metrics sync — should work regardless of provider
        written = sync_team_metrics(db, days=30)
        assert written > 0

        metrics = db.query(TeamMetrics).filter_by(team="nova").all()
        assert len(metrics) > 0

        # Total merged across all days should be 5
        total_merged = sum(m.mrs_merged for m in metrics)
        assert total_merged == 5

    def test_mixed_provider_teams_both_contribute_metrics(self):
        """Teams on different providers both produce team_metrics."""
        db = _make_db()

        db.add(RefTeam(slug="alpha", key="ALPHA", name="Alpha", git_provider="gitlab"))
        db.add(RefTeam(slug="beta", key="BETA", name="Beta", git_provider="github"))
        db.commit()

        now = datetime.now(timezone.utc)
        # GitLab team: 3 MRs
        for i in range(3):
            db.add(MRActivity(
                mr_iid=200 + i,
                repo_id="group/alpha-repo",
                title=f"MR #{200 + i}",
                author_username="alice",
                author_team="alpha",
                state="merged",
                created_at=now - timedelta(days=i + 1),
                merged_at=now - timedelta(days=i, hours=6),
                provider="gitlab",
            ))
        # GitHub team: 4 PRs
        for i in range(4):
            db.add(MRActivity(
                mr_iid=300 + i,
                repo_id="acme/beta-api",
                title=f"PR #{300 + i}",
                author_username="bob-gh",
                author_team="beta",
                state="merged",
                created_at=now - timedelta(days=i + 1),
                merged_at=now - timedelta(days=i, hours=8),
                provider="github",
            ))
        db.commit()

        written = sync_team_metrics(db, days=30)
        assert written > 0

        alpha_metrics = db.query(TeamMetrics).filter_by(team="alpha").all()
        beta_metrics = db.query(TeamMetrics).filter_by(team="beta").all()

        alpha_total = sum(m.mrs_merged for m in alpha_metrics)
        beta_total = sum(m.mrs_merged for m in beta_metrics)

        assert alpha_total == 3
        assert beta_total == 4

    def test_dora_level_computed_for_github_team(self):
        """DORA level is computed correctly for GitHub-sourced MRs."""
        db = _make_db()

        db.add(RefTeam(slug="gamma", key="GAMMA", name="Gamma", git_provider="github"))
        db.commit()

        # Create 10 merged PRs in the last 7 days (should be "Elite" level)
        now = datetime.now(timezone.utc)
        for i in range(10):
            created = now - timedelta(days=i % 7, hours=2)
            merged = created + timedelta(hours=4)  # 4h cycle time (< 24h)
            db.add(MRActivity(
                mr_iid=400 + i,
                repo_id="acme/gamma-service",
                title=f"PR #{400 + i}",
                author_username="charlie-gh",
                author_team="gamma",
                state="merged",
                created_at=created,
                merged_at=merged,
                provider="github",
            ))
        db.commit()

        written = sync_team_metrics(db, days=30)
        assert written > 0

        # At least one metric row should have Elite or High DORA level
        metrics = db.query(TeamMetrics).filter_by(team="gamma").all()
        dora_levels = [m.dora_level for m in metrics if m.dora_level]
        assert any(level in ("Elite", "High") for level in dora_levels), \
            f"Expected Elite or High DORA level, got: {dora_levels}"

    def test_provider_column_preserved_in_mr_activity(self):
        """The provider column value persists through the pipeline."""
        db = _make_db()

        now = datetime.now(timezone.utc)
        db.add(MRActivity(
            mr_iid=500,
            repo_id="acme/test",
            title="Test PR",
            author_username="dev",
            author_team="test",
            state="merged",
            created_at=now - timedelta(days=1),
            merged_at=now,
            provider="github",
        ))
        db.commit()

        row = db.query(MRActivity).filter_by(mr_iid=500).first()
        assert row.provider == "github"
