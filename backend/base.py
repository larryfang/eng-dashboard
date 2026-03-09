"""
Base plugin interface for all eng-dashboard plugins.

Provides PluginConfig (settings container) and BasePlugin (ABC that all
plugin categories — issue trackers, code platforms, etc. — inherit from).
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class PluginConfig:
    """Configuration passed to plugin constructors.

    Attributes:
        settings: Provider-specific key-value settings sourced from
                  organization.yaml or environment variables.
    """
    settings: dict = field(default_factory=dict)


class BasePlugin(ABC):
    """Abstract base for every plugin in the system.

    Subclasses must implement the ``name`` and ``provider`` properties.
    They may override ``initialize`` and ``health_check`` as needed.
    """

    def __init__(self, config: PluginConfig) -> None:
        self.config = config

    # -- identity ----------------------------------------------------------

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable plugin name (e.g. 'jira', 'github-issues')."""
        ...

    @property
    @abstractmethod
    def provider(self) -> str:
        """Provider identifier used for routing (e.g. 'jira', 'github', 'gitlab')."""
        ...

    # -- lifecycle ---------------------------------------------------------

    def initialize(self) -> None:
        """Called once after construction to set up connections / caches.

        Subclasses should call ``super().initialize()`` first, then perform
        their own setup (e.g. verifying credentials).
        """
        logger.info("Initializing plugin: %s (provider=%s)", self.name, self.provider)

    def health_check(self) -> bool:
        """Return True if the plugin can reach its backing service.

        The default implementation always returns True.  Plugins should
        override this to perform a real connectivity test.
        """
        return True
