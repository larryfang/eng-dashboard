"""
Core module for Personal Assistant.

Contains portable, organization-agnostic functionality:
- Configuration loading and validation
- Base data models
- Core services (entries, todos, search, etc.)
"""

from .config_loader import (
    ConfigLoader,
    OrganizationConfig,
    Team,
    TeamMember,
    Stakeholder,
    IntegrationConfig,
    get_config,
    get_team,
)

__all__ = [
    "ConfigLoader",
    "OrganizationConfig",
    "Team",
    "TeamMember",
    "Stakeholder",
    "IntegrationConfig",
    "get_config",
    "get_team",
]
