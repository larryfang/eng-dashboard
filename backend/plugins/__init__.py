"""Plugin system for eng-dashboard providers."""

from backend.plugins.registry import (
    discover_entrypoints,
    get_plugin_class,
    list_plugin_types,
    list_plugins,
    register,
)

__all__ = [
    "register",
    "get_plugin_class",
    "list_plugins",
    "list_plugin_types",
    "discover_entrypoints",
]
