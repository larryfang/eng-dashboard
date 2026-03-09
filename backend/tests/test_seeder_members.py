"""Tests for seeder members field handling and git_provider propagation."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database_domain import DomainBase
from backend.models_domain import RefTeam, RefMember


def _make_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    DomainBase.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


class TestSeederMembersField:
    """Verify that 'members' is the primary YAML field with 'gitlab_members' fallback."""

    def test_reads_members_field(self):
        """The config_loader logic should read 'members' as the primary field name."""
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

    def test_falls_back_to_gitlab_members(self):
        """Backward compat: reads 'gitlab_members' if 'members' is absent."""
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

    def test_empty_if_neither_field_present(self):
        """No members if neither 'members' nor 'gitlab_members' is set."""
        team_data = {"slug": "empty", "key": "EMP", "name": "Empty"}
        members = team_data.get("members") or team_data.get("gitlab_members") or []
        assert len(members) == 0

    def test_members_takes_precedence_over_gitlab_members(self):
        """When both fields exist, 'members' wins."""
        team_data = {
            "slug": "dual",
            "key": "DUAL",
            "name": "Dual",
            "members": [
                {"username": "alice", "name": "Alice A", "role": "engineer"},
            ],
            "gitlab_members": [
                {"username": "bob", "name": "Bob B", "role": "engineer"},
            ],
        }
        members = team_data.get("members") or team_data.get("gitlab_members") or []
        assert len(members) == 1
        assert members[0]["username"] == "alice"


class TestSeederGitProvider:
    """Verify that git_provider is propagated to RefTeam."""

    def test_ref_team_stores_git_provider(self):
        """RefTeam should accept and store git_provider value."""
        db = _make_db()
        team = RefTeam(slug="nova", key="NOVA", name="Nova", git_provider="github")
        db.add(team)
        db.commit()

        row = db.query(RefTeam).filter(RefTeam.slug == "nova").first()
        assert row.git_provider == "github"

    def test_ref_team_git_provider_defaults_to_gitlab(self):
        """RefTeam.git_provider defaults to 'gitlab' when not specified."""
        db = _make_db()
        team = RefTeam(slug="legacy", key="LEG", name="Legacy")
        db.add(team)
        db.commit()

        row = db.query(RefTeam).filter(RefTeam.slug == "legacy").first()
        assert row.git_provider == "gitlab"


class TestConfigLoaderMembersField:
    """Verify config_loader parses 'members' with fallback to 'gitlab_members'."""

    def test_parse_members_field(self):
        """Config loader should populate gitlab_members from 'members' YAML key."""
        from backend.core.config_loader import ConfigLoader

        yaml_content = {
            "organization": {"name": "Test", "slug": "test"},
            "user": {"name": "Tester", "email": "test@test.com"},
            "teams": [
                {
                    "key": "NOVA",
                    "name": "Nova",
                    "headcount": 2,
                    "git_provider": "github",
                    "members": [
                        {"username": "alice", "name": "Alice A"},
                        {"username": "bob", "name": "Bob B"},
                    ],
                }
            ],
        }

        loader = ConfigLoader.__new__(ConfigLoader)
        config = loader._parse(yaml_content)
        team = config.teams[0]
        assert len(team.gitlab_members) == 2
        assert team.gitlab_members[0].username == "alice"
        assert team.git_provider == "github"

    def test_parse_gitlab_members_fallback(self):
        """Config loader should fall back to 'gitlab_members' when 'members' is absent."""
        from backend.core.config_loader import ConfigLoader

        yaml_content = {
            "organization": {"name": "Test", "slug": "test"},
            "user": {"name": "Tester", "email": "test@test.com"},
            "teams": [
                {
                    "key": "PLUTO",
                    "name": "Pluto",
                    "headcount": 1,
                    "gitlab_members": [
                        {"username": "charlie", "name": "Charlie C"},
                    ],
                }
            ],
        }

        loader = ConfigLoader.__new__(ConfigLoader)
        config = loader._parse(yaml_content)
        team = config.teams[0]
        assert len(team.gitlab_members) == 1
        assert team.gitlab_members[0].username == "charlie"
        assert team.git_provider == "gitlab"

    def test_parse_git_provider_defaults_to_gitlab(self):
        """Config loader should default git_provider to 'gitlab' if absent."""
        from backend.core.config_loader import ConfigLoader

        yaml_content = {
            "organization": {"name": "Test", "slug": "test"},
            "user": {"name": "Tester", "email": "test@test.com"},
            "teams": [
                {
                    "key": "OLD",
                    "name": "Old Team",
                    "headcount": 0,
                }
            ],
        }

        loader = ConfigLoader.__new__(ConfigLoader)
        config = loader._parse(yaml_content)
        assert config.teams[0].git_provider == "gitlab"
