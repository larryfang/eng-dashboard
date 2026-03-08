"""
GitLab team path mappings for DevOps metrics.

Maps team identifiers to GitLab group paths for API queries.
All data is loaded lazily from organization.yaml via config_loader.

Public API (backward compatible):
    TEAM_GITLAB_PATHS   - Dict[str, List[str]]: team slug -> gitlab paths
    TEAM_DISPLAY_NAMES  - Dict[str, str]: team slug -> display name
    TEAM_JIRA_PREFIXES  - Dict[str, str]: team slug -> Jira project key
    JIRA_PREFIX_TO_TEAM - Dict[str, str]: Jira project key -> team slug
    TEAM_ALIASES        - Dict[str, str]: alias -> team slug
    ALL_TEAMS           - List[str]: all team slugs
    GITLAB_BASE         - str: common base path (if extractable)
"""

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Internal state
_loaded = False
_team_gitlab_paths: Dict[str, List[str]] = {}
_team_display_names: Dict[str, str] = {}
_team_jira_prefixes: Dict[str, str] = {}
_jira_prefix_to_team: Dict[str, str] = {}
_team_aliases: Dict[str, str] = {}
_all_teams: List[str] = []
_gitlab_base: str = ""


def _ensure_loaded() -> None:
    """Load team data from config on first access."""
    global _loaded, _team_gitlab_paths, _team_display_names
    global _team_jira_prefixes, _jira_prefix_to_team
    global _team_aliases, _all_teams, _gitlab_base

    if _loaded:
        return

    try:
        from backend.core.config_loader import get_config
        config = get_config()

        _team_gitlab_paths = config.gitlab_team_paths
        _team_display_names = config.gitlab_display_names
        _team_jira_prefixes = config.gitlab_jira_prefixes
        _jira_prefix_to_team = {v: k for k, v in _team_jira_prefixes.items()}
        _team_aliases = config.gitlab_team_aliases
        _all_teams = list(_team_gitlab_paths.keys())

        # Extract common base path from gitlab paths
        all_paths = []
        for paths in _team_gitlab_paths.values():
            all_paths.extend(paths)
        if all_paths:
            # Find common prefix by splitting on /
            parts_list = [p.split("/") for p in all_paths]
            common = []
            for segments in zip(*parts_list):
                if len(set(segments)) == 1:
                    common.append(segments[0])
                else:
                    break
            _gitlab_base = "/".join(common)

        _loaded = True
        logger.debug(f"Loaded {len(_all_teams)} teams from config")

    except Exception as e:
        logger.warning(f"Failed to load team config, module will have empty data: {e}")
        _loaded = True  # Don't retry on every access


class _LazyDict(dict):
    """Dict that triggers config loading on first access."""

    def __init__(self, getter):
        super().__init__()
        self._getter = getter
        self._populated = False

    def _load(self):
        if self._populated:
            return
        _ensure_loaded()
        self.update(self._getter())
        self._populated = True

    def __getitem__(self, key):
        if not self._populated:
            self._load()
        return super().__getitem__(key)

    def __contains__(self, key):
        if not self._populated:
            self._load()
        return super().__contains__(key)

    def __iter__(self):
        if not self._populated:
            self._load()
        return super().__iter__()

    def __len__(self):
        if not self._populated:
            self._load()
        return super().__len__()

    def keys(self):
        if not self._populated:
            self._load()
        return super().keys()

    def values(self):
        if not self._populated:
            self._load()
        return super().values()

    def items(self):
        if not self._populated:
            self._load()
        return super().items()

    def get(self, key, default=None):
        if not self._populated:
            self._load()
        return super().get(key, default)

    def __repr__(self):
        if not self._populated:
            self._load()
        return super().__repr__()

    def clear(self):
        super().clear()
        self._populated = False


class _LazyList(list):
    """List that triggers config loading on first access."""

    def __init__(self, getter):
        super().__init__()
        self._getter = getter
        self._populated = False

    def _load(self):
        if self._populated:
            return
        _ensure_loaded()
        self.extend(self._getter())
        self._populated = True

    def __iter__(self):
        if not self._populated:
            self._load()
        return super().__iter__()

    def __len__(self):
        if not self._populated:
            self._load()
        return super().__len__()

    def __contains__(self, item):
        if not self._populated:
            self._load()
        return super().__contains__(item)

    def __getitem__(self, index):
        if not self._populated:
            self._load()
        return super().__getitem__(index)

    def __repr__(self):
        if not self._populated:
            self._load()
        return super().__repr__()

    def clear(self):
        super().clear()
        self._populated = False


class _LazyStr:
    """String-like object that triggers config loading on first access."""

    def __init__(self, getter):
        self._getter = getter
        self._value: str = ""

    def _load(self):
        _ensure_loaded()
        self._value = self._getter() or ""

    def __str__(self) -> str:
        if not self._value:
            self._load()
        return self._value

    def __repr__(self):
        return repr(str(self))

    def __eq__(self, other):
        return str(self) == other

    def __hash__(self):
        return hash(str(self))

    def __add__(self, other):
        return str(self) + other

    def __radd__(self, other):
        return other + str(self)

    def __format__(self, format_spec):
        return format(str(self), format_spec)


# Module-level names (backward compatible API)
# These are lazy proxies that load from config on first access.
TEAM_GITLAB_PATHS = _LazyDict(lambda: _team_gitlab_paths)
TEAM_DISPLAY_NAMES = _LazyDict(lambda: _team_display_names)
TEAM_JIRA_PREFIXES = _LazyDict(lambda: _team_jira_prefixes)
JIRA_PREFIX_TO_TEAM = _LazyDict(lambda: _jira_prefix_to_team)
TEAM_ALIASES = _LazyDict(lambda: _team_aliases)
ALL_TEAMS = _LazyList(lambda: _all_teams)
GITLAB_BASE = _LazyStr(lambda: _gitlab_base)


def get_all_gitlab_paths() -> list[str]:
    """Get all unique GitLab paths across all teams."""
    _ensure_loaded()
    paths = []
    for team_paths in _team_gitlab_paths.values():
        paths.extend(team_paths)
    return list(set(paths))


def get_team_for_path(gitlab_path: str) -> str | None:
    """Given a GitLab path, return the team it belongs to."""
    _ensure_loaded()
    for team, paths in _team_gitlab_paths.items():
        if gitlab_path in paths:
            return team
    return None


def normalize_team_name(name: str) -> str | None:
    """
    Normalize a team name to its canonical slug.

    Args:
        name: Team name in any form (slug, display name, alias)

    Returns:
        Canonical team slug or None if not recognized
    """
    _ensure_loaded()
    name_lower = name.lower().strip().replace(" ", "_").replace("-", "_")

    # Direct match
    if name_lower in _all_teams:
        return name_lower

    # Check aliases
    if name_lower in _team_aliases:
        return _team_aliases[name_lower]

    # Check display names
    for team, display in _team_display_names.items():
        if name_lower in display.lower():
            return team

    return None


def get_team_display_name(team: str) -> str:
    """Get the display name for a team slug."""
    _ensure_loaded()
    normalized = normalize_team_name(team) or team
    return _team_display_names.get(normalized, team.title())


def get_team_jira_prefix(team: str) -> str | None:
    """Get the Jira project prefix for a team."""
    _ensure_loaded()
    normalized = normalize_team_name(team)
    if normalized:
        return _team_jira_prefixes.get(normalized)
    return None


def get_team_from_jira_key(jira_key: str) -> str | None:
    """
    Extract team from a Jira issue key.

    Args:
        jira_key: Jira issue key like "EEH-123"

    Returns:
        Team slug or None
    """
    _ensure_loaded()
    if not jira_key or "-" not in jira_key:
        return None
    prefix = jira_key.split("-")[0].upper()
    return _jira_prefix_to_team.get(prefix)


def _reset_for_testing() -> None:
    """Reset loaded state (for tests only)."""
    global _loaded
    _loaded = False
    _team_gitlab_paths.clear()
    _team_display_names.clear()
    _team_jira_prefixes.clear()
    _jira_prefix_to_team.clear()
    _team_aliases.clear()
    _all_teams.clear()
    # Clear lazy proxy caches
    TEAM_GITLAB_PATHS.clear()
    TEAM_DISPLAY_NAMES.clear()
    TEAM_JIRA_PREFIXES.clear()
    JIRA_PREFIX_TO_TEAM.clear()
    TEAM_ALIASES.clear()
    ALL_TEAMS.clear()
