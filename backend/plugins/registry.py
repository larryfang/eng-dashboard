"""
Plugin registry with decorator-based registration.

Enables adding providers without modifying core code:
  @register("git_provider", "bitbucket")
  class BitbucketProvider(GitProvider):
      ...

External plugins can be discovered via setuptools entry_points
(group: "eng_dashboard.plugins").
"""

_registry: dict[str, dict[str, type]] = {}


def register(plugin_type: str, name: str):
    """Decorator: @register("git_provider", "bitbucket")"""

    def decorator(cls):
        _registry.setdefault(plugin_type, {})[name] = cls
        return cls

    return decorator


def get_plugin_class(plugin_type: str, name: str) -> type:
    """Get a registered plugin class. Raises KeyError if not found."""
    try:
        return _registry[plugin_type][name]
    except KeyError:
        available = list(_registry.get(plugin_type, {}).keys())
        raise KeyError(
            f"No '{name}' plugin registered for '{plugin_type}'. "
            f"Available: {available}"
        )


def list_plugins(plugin_type: str) -> list[str]:
    """List registered plugin names for a type."""
    return list(_registry.get(plugin_type, {}).keys())


def list_plugin_types() -> list[str]:
    """List all registered plugin types."""
    return list(_registry.keys())


def discover_entrypoints():
    """Load external plugins via setuptools entry_points."""
    from importlib.metadata import entry_points

    for ep in entry_points(group="eng_dashboard.plugins"):
        ep.load()  # triggers @register decorators
