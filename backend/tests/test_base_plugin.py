"""Tests for base plugin classes."""
import pytest
from backend.base import BasePlugin, PluginConfig


class TestPluginConfig:
    def test_default_settings(self):
        config = PluginConfig()
        assert config.settings == {}

    def test_custom_settings(self):
        config = PluginConfig(settings={"org": "acme", "url": "https://example.com"})
        assert config.settings["org"] == "acme"
        assert config.settings.get("missing", "default") == "default"


class TestBasePlugin:
    def test_cannot_instantiate_directly(self):
        """BasePlugin is abstract -- cannot be instantiated."""
        with pytest.raises(TypeError):
            BasePlugin(config=PluginConfig())

    def test_concrete_subclass(self):
        class ConcretePlugin(BasePlugin):
            @property
            def name(self) -> str:
                return "test"

            @property
            def provider(self) -> str:
                return "test-provider"

        plugin = ConcretePlugin(config=PluginConfig(settings={"key": "val"}))
        assert plugin.name == "test"
        assert plugin.provider == "test-provider"
        assert plugin.config.settings["key"] == "val"

    def test_initialize_and_health_check(self):
        class ConcretePlugin(BasePlugin):
            @property
            def name(self) -> str:
                return "test"

            @property
            def provider(self) -> str:
                return "test"

        plugin = ConcretePlugin(config=PluginConfig())
        plugin.initialize()  # Should not raise
        assert plugin.health_check() is True  # Default returns True
