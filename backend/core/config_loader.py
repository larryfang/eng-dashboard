"""
Configuration Loader for Personal Assistant

Loads and validates organization.yaml configuration, providing typed access
to organization-specific settings throughout the application.

Usage:
    from backend.core import get_config, get_team

    # Get full configuration
    config = get_config()
    print(config.name)  # "Acme Engineering"

    # Get team by any identifier (key, name, scrum name, jira project)
    team = get_team("PLAT")  # or "Platform" or "Phoenix"
    print(team.name)  # "Platform"
    print(team.lead)  # "Jane Smith"

    # Get PROJECT_TO_TEAM mapping (compatibility)
    mapping = config.project_to_team_map
    print(mapping)  # {"PLAT": "Platform", "INT": "Integrations", ...}
"""

import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass, field

import yaml

logger = logging.getLogger(__name__)

# Default paths
_CONFIG_DIR = Path(__file__).parent.parent.parent / "config"
DEFAULT_CONFIG_PATH = _CONFIG_DIR / "organization.yaml"
SCHEMA_PATH = _CONFIG_DIR / "organization.schema.json"


def _resolve_config_path() -> Path:
    """Resolve config path: SETU_CONFIG env > organization.yaml > organization.example.yaml."""
    env_path = os.getenv("SETU_CONFIG")
    if env_path:
        return Path(env_path)
    user_config = _CONFIG_DIR / "organization.yaml"
    if user_config.exists():
        return user_config
    example_config = _CONFIG_DIR / "organization.example.yaml"
    if example_config.exists():
        return example_config
    return user_config  # Will raise FileNotFoundError downstream


@dataclass
class TeamMember:
    """Team member configuration for GitLab/GitHub metrics tracking."""
    username: str
    name: str
    role: str = "engineer"
    exclude_from_metrics: bool = False
    departed: bool = False
    jira_account_id: Optional[str] = None  # For matching Jira assignees
    email: Optional[str] = None            # Work email address


@dataclass
class Team:
    """Team configuration with all integration identifiers."""
    key: str
    name: str
    headcount: int
    slug: Optional[str] = None
    scrum_name: Optional[str] = None
    aliases: List[str] = field(default_factory=list)
    lead: Optional[str] = None
    lead_email: Optional[str] = None
    effective_engineers: Optional[int] = None
    products: List[str] = field(default_factory=list)

    # Issue tracking
    jira_project: Optional[str] = None
    github_repo: Optional[str] = None

    # Code platform
    gitlab_path: Optional[str] = None
    additional_gitlab_paths: List[str] = field(default_factory=list)
    github_repos: List[str] = field(default_factory=list)  # ["org/repo", ...]

    # Security
    snyk_org: Optional[str] = None

    # DORA metrics
    port_team_id: Optional[str] = None

    # Git provider: "gitlab" or "github"
    git_provider: str = "gitlab"

    # Team members
    gitlab_members: List[TeamMember] = field(default_factory=list)
    github_members: List[TeamMember] = field(default_factory=list)

    def __post_init__(self):
        """Set defaults after initialization."""
        if self.effective_engineers is None:
            self.effective_engineers = self.headcount
        if self.scrum_name is None:
            self.scrum_name = self.name
        if self.slug is None:
            self.slug = self.name.lower().replace(" ", "_")

    @property
    def jira_key(self) -> str:
        """Alias for jira_project for backward compatibility."""
        return self.jira_project or self.key

    @property
    def member_usernames(self) -> List[str]:
        """All member usernames (GitLab + GitHub)."""
        gitlab = [m.username for m in self.gitlab_members]
        github = [m.username for m in self.github_members]
        return list(set(gitlab + github))

    @property
    def active_members(self) -> List[TeamMember]:
        """Members included in metrics (not excluded)."""
        return [m for m in self.gitlab_members + self.github_members
                if not m.exclude_from_metrics]


@dataclass
class Stakeholder:
    """Key stakeholder configuration."""
    name: str
    role: str
    relationship: Optional[str] = None
    email: Optional[str] = None
    title: Optional[str] = None
    importance: Optional[str] = None  # critical, high, medium, low


@dataclass
class IntegrationConfig:
    """Integration provider configuration."""
    provider: str
    config: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MetricsConfig:
    """Metrics configuration."""
    cache_ttl_hours: int = 24
    stale_epic_days: int = 14
    dora_targets: Dict[str, float] = field(default_factory=dict)


@dataclass
class OrganizationConfig:
    """
    Full organization configuration loaded from organization.yaml.

    Provides typed access to all configuration and convenience methods
    for looking up teams by various identifiers.
    """
    # Organization info
    name: str
    slug: str
    description: str = ""
    atlassian_cloud_id: Optional[str] = None
    atlassian_site_url: Optional[str] = None
    jira_roadmap_url: Optional[str] = None

    # User info
    user_name: str = ""
    user_email: str = ""
    user_role: str = ""
    user_timezone: str = "UTC"

    # Teams and stakeholders
    teams: List[Team] = field(default_factory=list)
    stakeholders: List[Stakeholder] = field(default_factory=list)

    # Integrations
    integrations: Dict[str, IntegrationConfig] = field(default_factory=dict)

    # DORA
    dora: Optional[IntegrationConfig] = None

    # Metrics
    metrics: MetricsConfig = field(default_factory=MetricsConfig)

    # Knowledge base: user-defined facts always available to the RAG system
    knowledge_base: List[str] = field(default_factory=list)

    # Lookup indexes (built in __post_init__)
    _team_by_key: Dict[str, Team] = field(default_factory=dict, repr=False)
    _team_by_name: Dict[str, Team] = field(default_factory=dict, repr=False)
    _team_by_slug: Dict[str, Team] = field(default_factory=dict, repr=False)
    _team_by_scrum: Dict[str, Team] = field(default_factory=dict, repr=False)
    _team_by_jira: Dict[str, Team] = field(default_factory=dict, repr=False)
    _team_by_snyk: Dict[str, Team] = field(default_factory=dict, repr=False)
    _team_by_port: Dict[str, Team] = field(default_factory=dict, repr=False)
    _team_by_alias: Dict[str, Team] = field(default_factory=dict, repr=False)

    def __post_init__(self):
        """Build lookup indexes for fast team access."""
        for team in self.teams:
            self._team_by_key[team.key] = team
            self._team_by_name[team.name] = team
            if team.slug:
                self._team_by_slug[team.slug] = team
            if team.scrum_name:
                self._team_by_scrum[team.scrum_name] = team
            if team.jira_project:
                self._team_by_jira[team.jira_project] = team
            if team.snyk_org:
                self._team_by_snyk[team.snyk_org] = team
            if team.port_team_id:
                self._team_by_port[team.port_team_id] = team
            for alias in team.aliases:
                self._team_by_alias[alias] = team

    def get_team(self, identifier: str) -> Optional[Team]:
        """
        Get team by any identifier (key, name, slug, scrum name, jira project, alias).

        Args:
            identifier: Team key, name, slug, scrum name, Jira project key, or alias

        Returns:
            Team if found, None otherwise
        """
        return (
            self._team_by_key.get(identifier) or
            self._team_by_slug.get(identifier) or
            self._team_by_name.get(identifier) or
            self._team_by_scrum.get(identifier) or
            self._team_by_jira.get(identifier) or
            self._team_by_alias.get(identifier)
        )

    def get_team_by_snyk_org(self, snyk_org: str) -> Optional[Team]:
        """Get team by Snyk organization name."""
        return self._team_by_snyk.get(snyk_org)

    def get_team_by_port_id(self, port_team_id: str) -> Optional[Team]:
        """Get team by Port.io team identifier."""
        return self._team_by_port.get(port_team_id)

    @property
    def jira_project_keys(self) -> List[str]:
        """All Jira project keys."""
        return [t.jira_project for t in self.teams if t.jira_project]

    @property
    def project_to_team_map(self) -> Dict[str, str]:
        """
        PROJECT_TO_TEAM compatibility map.

        Returns:
            Dict mapping Jira project key to team name
        """
        return {t.jira_project: t.name for t in self.teams if t.jira_project}

    @property
    def snyk_to_team_map(self) -> Dict[str, str]:
        """
        SNYK_TO_TEAM compatibility map.

        Returns:
            Dict mapping Snyk org name to team name
        """
        return {t.snyk_org: t.name for t in self.teams if t.snyk_org}

    @property
    def team_members_map(self) -> Dict[str, List[str]]:
        """
        TEAM_MEMBERS compatibility map.

        Returns:
            Dict mapping team name to list of GitLab usernames
        """
        return {t.name: [m.username for m in t.gitlab_members] for t in self.teams}

    @property
    def total_headcount(self) -> int:
        """Total headcount across all teams."""
        return sum(t.headcount for t in self.teams)

    @property
    def total_effective_engineers(self) -> int:
        """Total effective engineers (for metrics)."""
        return sum(t.effective_engineers or t.headcount for t in self.teams)

    def get_integration(self, integration_type: str) -> Optional[IntegrationConfig]:
        """Get integration configuration by type."""
        return self.integrations.get(integration_type)

    def get_enabled_integrations(self) -> List[str]:
        """
        Get list of configured integration types.

        Returns:
            List of integration type strings (e.g., ["issue_tracker", "code_platform", "security"])
        """
        enabled = list(self.integrations.keys())
        if self.dora:
            enabled.append("dora")
        return enabled

    def get_team_lead_emails(self) -> List[str]:
        """Get unique team lead emails sorted alphabetically."""
        emails = set()
        for team in self.teams:
            if team.lead_email:
                emails.add(team.lead_email)
        return sorted(emails)

    def get_stakeholder_emails(self) -> List[str]:
        """Get stakeholder emails."""
        return [s.email for s in self.stakeholders if s.email]

    def get_digest_recipients(self) -> List[str]:
        """Get all digest recipients (team leads + stakeholders)."""
        recipients = set()
        for team in self.teams:
            if team.lead_email:
                recipients.add(team.lead_email)
        for s in self.stakeholders:
            if s.email:
                recipients.add(s.email)
        return sorted(recipients)

    def get_em_team_map(self) -> Dict[str, List[str]]:
        """Build EM email → team keys mapping from config."""
        em_map: Dict[str, List[str]] = {}
        for team in self.teams:
            if team.lead_email:
                if team.lead_email not in em_map:
                    em_map[team.lead_email] = []
                em_map[team.lead_email].append(team.key)
        return em_map

    def get_excluded_authors(self) -> List[str]:
        """Get excluded authors for code metrics from code_platform config."""
        cp = self.integrations.get("code_platform")
        if cp:
            return cp.config.get("excluded_authors", [])
        return []

    def get_excluded_project_prefixes(self) -> List[str]:
        """Get excluded project path prefixes from code_platform config."""
        cp = self.integrations.get("code_platform")
        if cp:
            return cp.config.get("excluded_project_prefixes", [])
        return []

    def get_team_api_names(self) -> Dict[str, str]:
        """Build team key/alias → slug mapping for API name resolution."""
        result: Dict[str, str] = {}
        for team in self.teams:
            if team.slug:
                result[team.key] = team.slug
                if team.scrum_name:
                    result[team.scrum_name.lower().replace(" ", "-")] = team.slug
                for alias in team.aliases:
                    result[alias] = team.slug
        return result

    def get_team_by_slug(self, slug: str) -> Optional[Team]:
        """Get team by its slug identifier."""
        return self._team_by_slug.get(slug)

    def get_team_by_alias(self, alias: str) -> Optional[Team]:
        """Get team by an alias."""
        return self._team_by_alias.get(alias)

    @property
    def gitlab_team_paths(self) -> Dict[str, List[str]]:
        """
        Generate gitlab_teams.py-style TEAM_GITLAB_PATHS mapping.

        Returns:
            Dict mapping team slug to list of GitLab paths
        """
        result = {}
        for team in self.teams:
            if team.gitlab_path and team.slug:
                paths = [team.gitlab_path] + team.additional_gitlab_paths
                result[team.slug] = paths
        return result

    @property
    def gitlab_display_names(self) -> Dict[str, str]:
        """
        Generate gitlab_teams.py-style TEAM_DISPLAY_NAMES mapping.

        Returns:
            Dict mapping team slug to display name
        """
        result = {}
        for team in self.teams:
            if team.slug:
                if team.scrum_name and team.scrum_name != team.name:
                    result[team.slug] = f"{team.name} ({team.scrum_name})"
                else:
                    result[team.slug] = team.name
        return result

    @property
    def gitlab_jira_prefixes(self) -> Dict[str, str]:
        """
        Generate gitlab_teams.py-style TEAM_JIRA_PREFIXES mapping.

        Returns:
            Dict mapping team slug to Jira project key
        """
        return {
            t.slug: t.jira_project
            for t in self.teams
            if t.slug and t.jira_project
        }

    @property
    def gitlab_team_aliases(self) -> Dict[str, str]:
        """
        Generate gitlab_teams.py-style TEAM_ALIASES mapping.

        Returns:
            Dict mapping alias to team slug
        """
        result = {}
        for team in self.teams:
            if team.slug:
                for alias in team.aliases:
                    result[alias] = team.slug
        return result

    @property
    def github_team_repos(self) -> Dict[str, List[str]]:
        """
        Generate team-to-GitHub-repos mapping.

        Returns:
            Dict mapping team slug to list of GitHub repos (owner/repo format)
        """
        result = {}
        for team in self.teams:
            if team.github_repos and team.slug:
                result[team.slug] = team.github_repos
        return result


class ConfigLoader:
    """
    Loads and validates organization configuration from YAML.

    The configuration is cached after first load for performance.
    """

    def __init__(self, config_path: Optional[Union[Path, str]] = None):
        """
        Initialize config loader.

        Args:
            config_path: Path to organization.yaml (resolved via SETU_CONFIG env,
                         organization.yaml, or organization.example.yaml if not provided)
        """
        if config_path is None:
            self.config_path = _resolve_config_path()
        elif isinstance(config_path, str):
            self.config_path = Path(config_path)
        else:
            self.config_path = config_path
        self._config: Optional[OrganizationConfig] = None

    def load(self, validate: bool = True) -> OrganizationConfig:
        """
        Load configuration from YAML file.

        Args:
            validate: Whether to validate against JSON schema

        Returns:
            OrganizationConfig object

        Raises:
            FileNotFoundError: If config file doesn't exist
            yaml.YAMLError: If YAML is invalid
            jsonschema.ValidationError: If validation fails
        """
        if self._config is not None:
            return self._config

        if not self.config_path.exists():
            raise FileNotFoundError(
                f"Configuration file not found: {self.config_path}\n"
                f"Create one from config/examples/ or run setup wizard."
            )

        with open(self.config_path) as f:
            raw = yaml.safe_load(f)

        if validate:
            self._validate(raw)

        self._config = self._parse(raw)
        logger.info(f"Loaded configuration for: {self._config.name}")
        return self._config

    def reload(self) -> OrganizationConfig:
        """Force reload configuration from disk."""
        self._config = None
        return self.load()

    def _validate(self, raw: dict) -> None:
        """Validate configuration against JSON schema."""
        if not SCHEMA_PATH.exists():
            logger.warning(f"Schema not found, skipping validation: {SCHEMA_PATH}")
            return

        try:
            import jsonschema
            with open(SCHEMA_PATH) as f:
                schema = json.load(f)
            jsonschema.validate(raw, schema)
        except ImportError:
            logger.warning("jsonschema not installed, skipping validation")
        except Exception as e:
            logger.error(f"Configuration validation failed: {e}")
            raise

    def _parse(self, raw: dict) -> OrganizationConfig:
        """Parse raw YAML into typed OrganizationConfig."""
        org = raw.get("organization", {})
        user = raw.get("user", {})

        # Parse teams
        teams = []
        for t in raw.get("teams", []):
            # Parse team members
            # "members" is the preferred field; fall back to "gitlab_members"
            # for backward compatibility with existing configs.
            raw_members = t.get("members") or t.get("gitlab_members") or []
            gitlab_members = [
                TeamMember(
                    username=m["username"],
                    name=m["name"],
                    role=m.get("role", "engineer"),
                    exclude_from_metrics=m.get("exclude_from_metrics", False),
                    departed=m.get("departed", False),
                    jira_account_id=m.get("jira_account_id"),
                    email=m.get("email"),
                )
                for m in raw_members
            ]
            github_members = [
                TeamMember(
                    username=m["username"],
                    name=m["name"],
                    role=m.get("role", "engineer"),
                    exclude_from_metrics=m.get("exclude_from_metrics", False),
                    departed=m.get("departed", False),
                    jira_account_id=m.get("jira_account_id"),
                    email=m.get("email"),
                )
                for m in t.get("github_members", [])
            ]

            github_repos_raw = t.get("github_repos", [])
            if isinstance(github_repos_raw, list):
                github_repos = [repo for repo in github_repos_raw if isinstance(repo, str) and repo]
            elif isinstance(github_repos_raw, str) and github_repos_raw:
                github_repos = [github_repos_raw]
            else:
                github_repos = []

            if (not github_repos) and t.get("github_repo"):
                github_repos = [t["github_repo"]]

            teams.append(Team(
                key=t["key"],
                name=t["name"],
                slug=t.get("slug"),
                scrum_name=t.get("scrum_name"),
                aliases=t.get("aliases", []),
                lead=t.get("lead"),
                lead_email=t.get("lead_email"),
                headcount=t.get("headcount", 0),
                effective_engineers=t.get("effective_engineers"),
                products=t.get("products", []),
                jira_project=t.get("jira_project"),
                github_repo=t.get("github_repo"),
                github_repos=github_repos,
                gitlab_path=t.get("gitlab_path"),
                additional_gitlab_paths=t.get("additional_gitlab_paths", []),
                snyk_org=t.get("snyk_org"),
                port_team_id=t.get("port_team_id"),
                git_provider=t.get("git_provider", "gitlab"),
                gitlab_members=gitlab_members,
                github_members=github_members,
            ))

        # Parse stakeholders
        stakeholders = [
            Stakeholder(
                name=s["name"],
                role=s["role"],
                relationship=s.get("relationship"),
                email=s.get("email"),
                title=s.get("title"),
                importance=s.get("importance"),
            )
            for s in raw.get("stakeholders", [])
        ]

        # Parse integrations
        integrations = {
            k: IntegrationConfig(
                provider=v["provider"],
                config=v.get("config", {})
            )
            for k, v in raw.get("integrations", {}).items()
        }

        # Parse DORA
        dora_raw = raw.get("dora")
        dora = IntegrationConfig(
            provider=dora_raw["provider"],
            config=dora_raw.get("config", {})
        ) if dora_raw else None

        # Parse metrics
        metrics_raw = raw.get("metrics", {})
        metrics = MetricsConfig(
            cache_ttl_hours=metrics_raw.get("cache_ttl_hours", 24),
            stale_epic_days=metrics_raw.get("stale_epic_days", 14),
            dora_targets=metrics_raw.get("dora_targets", {})
        )

        # Parse knowledge base
        knowledge_base = raw.get("knowledge_base", [])
        if not isinstance(knowledge_base, list):
            knowledge_base = []

        return OrganizationConfig(
            name=org.get("name", ""),
            slug=org.get("slug", ""),
            description=org.get("description", ""),
            atlassian_cloud_id=org.get("atlassian_cloud_id"),
            atlassian_site_url=org.get("atlassian_site_url"),
            jira_roadmap_url=org.get("jira_roadmap_url"),
            user_name=user.get("name", ""),
            user_email=user.get("email", ""),
            user_role=user.get("role", ""),
            user_timezone=user.get("timezone", "UTC"),
            teams=teams,
            stakeholders=stakeholders,
            integrations=integrations,
            dora=dora,
            metrics=metrics,
            knowledge_base=knowledge_base,
        )


# --- Multi-domain support ---
_CONFIG_DOMAINS_DIR = _CONFIG_DIR / "domains"

_loaders: dict[str, "ConfigLoader"] = {}


def get_domain_config(domain_slug: str) -> "OrganizationConfig":
    """Load config for a specific domain slug from config/domains/{slug}.yaml."""
    global _loaders
    if domain_slug not in _loaders:
        path = _CONFIG_DOMAINS_DIR / f"{domain_slug}.yaml"
        _loaders[domain_slug] = ConfigLoader(path)
    return _loaders[domain_slug].load()


def reload_domain_config(domain_slug: str) -> "OrganizationConfig":
    """Force reload a domain's config from disk."""
    global _loaders
    if domain_slug in _loaders:
        return _loaders[domain_slug].reload()
    return get_domain_config(domain_slug)


def list_domain_slugs() -> list:
    """Return slugs of all configured domains (config/domains/*.yaml files)."""
    if not _CONFIG_DOMAINS_DIR.exists():
        return []
    return [f.stem for f in sorted(_CONFIG_DOMAINS_DIR.glob("*.yaml"))]


# Singleton loader for application-wide access
_config_loader: Optional[ConfigLoader] = None


def get_config(config_path: Optional[Path] = None) -> OrganizationConfig:
    """
    Get the loaded organization configuration.

    Args:
        config_path: Optional explicit path to a config file.

    Returns:
        OrganizationConfig object
    """
    if config_path is None:
        try:
            from backend.services.domain_registry import get_active_slug
            active_slug = get_active_slug()
            active_path = _CONFIG_DOMAINS_DIR / f"{active_slug}.yaml"
            if active_path.exists():
                return get_domain_config(active_slug)
        except Exception:
            pass

    global _config_loader
    if _config_loader is None:
        _config_loader = ConfigLoader(config_path)
    return _config_loader.load()


def get_team(identifier: str) -> Optional[Team]:
    """
    Convenience function to get team by any identifier.

    Args:
        identifier: Team key, name, scrum name, or Jira project key

    Returns:
        Team if found, None otherwise
    """
    return get_config().get_team(identifier)


def reload_config() -> OrganizationConfig:
    """Force reload the active configuration from disk."""
    try:
        from backend.services.domain_registry import get_active_slug
        active_slug = get_active_slug()
        active_path = _CONFIG_DOMAINS_DIR / f"{active_slug}.yaml"
        if active_path.exists():
            return reload_domain_config(active_slug)
    except Exception:
        pass

    global _config_loader
    if _config_loader is not None:
        return _config_loader.reload()
    return get_config()


# Export compatibility functions for gradual migration
def get_project_to_team_map() -> Dict[str, str]:
    """Get PROJECT_TO_TEAM mapping (backward compatibility)."""
    return get_config().project_to_team_map


def get_snyk_to_team_map() -> Dict[str, str]:
    """Get SNYK_TO_TEAM mapping (backward compatibility)."""
    return get_config().snyk_to_team_map


def get_team_members_map() -> Dict[str, List[str]]:
    """Get TEAM_MEMBERS mapping (backward compatibility)."""
    return get_config().team_members_map
