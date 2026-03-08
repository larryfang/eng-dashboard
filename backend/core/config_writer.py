"""
Shared configuration writer for organization.yaml and .env files.

Used by CLI commands, TUI, and Settings API to persist configuration changes.
Single write path prevents drift between different surfaces.
"""

import logging
from pathlib import Path
from typing import Any

import yaml

from .config_loader import DEFAULT_CONFIG_PATH

logger = logging.getLogger(__name__)


class ConfigWriter:
    """Read-modify-write helper for organization.yaml and .env files."""

    def __init__(
        self,
        cfg_path: Path | None = None,
        env_path: Path | None = None,
    ):
        self.cfg_path = cfg_path or DEFAULT_CONFIG_PATH
        self.env_path = env_path or (self.cfg_path.parent.parent / ".env")

    # ------------------------------------------------------------------
    # YAML helpers
    # ------------------------------------------------------------------

    def read_raw(self) -> dict:
        """Load the raw YAML dict from organization.yaml."""
        if not self.cfg_path.exists():
            raise FileNotFoundError(
                f"Config file not found: {self.cfg_path}\nRun 'setu setup' to create it first."
            )
        return yaml.safe_load(self.cfg_path.read_text()) or {}

    def _write_raw(self, data: dict) -> None:
        """Write dict back to organization.yaml (preserves key order)."""
        with open(self.cfg_path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_integration(
        self,
        category: str,
        provider: str,
        config: dict[str, Any] | None = None,
    ) -> None:
        """
        Write or update an integration entry in organization.yaml.

        Deep-merges ``config`` into the existing ``config`` block so that
        keys not present in the new dict are preserved.
        """
        data = self.read_raw()
        if "integrations" not in data:
            data["integrations"] = {}

        existing = data["integrations"].get(category, {})
        existing["provider"] = provider

        if config:
            existing_config = existing.get("config", {}) or {}
            existing_config.update(config)
            existing["config"] = existing_config

        data["integrations"][category] = existing
        self._write_raw(data)
        logger.info("Updated integration %s -> %s in %s", category, provider, self.cfg_path)

    def update_llm_model(self, model: str) -> None:
        """Convenience shortcut to change just the LLM model."""
        data = self.read_raw()
        integrations = data.get("integrations", {})
        llm = integrations.get("llm", {})
        llm_config = llm.get("config", {}) or {}
        llm_config["model"] = model
        llm["config"] = llm_config
        integrations["llm"] = llm
        data["integrations"] = integrations
        self._write_raw(data)
        logger.info("Updated LLM model to %s", model)

    def update_env_vars(self, env_vars: dict[str, str]) -> None:
        """
        Comment-preserving .env merge.

        1. Read existing lines, preserve comments and blanks.
        2. Replace matching keys inline.
        3. Append new keys at bottom.
        """
        if not env_vars:
            return

        lines: list[str] = []
        seen_keys: set[str] = set()

        if self.env_path.exists():
            for line in self.env_path.read_text().splitlines():
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and "=" in stripped:
                    key = stripped.split("=", 1)[0].strip()
                    if key in env_vars:
                        lines.append(f"{key}={env_vars[key]}")
                        seen_keys.add(key)
                        continue
                lines.append(line)

        new_keys = {k: v for k, v in env_vars.items() if k not in seen_keys}
        if new_keys:
            lines.append("")
            lines.append("# Added by setu settings")
            for k, v in new_keys.items():
                lines.append(f"{k}={v}")

        self.env_path.write_text("\n".join(lines) + "\n")
        logger.info("Updated %d env vars in %s", len(env_vars), self.env_path)

    def get_current_integration(self, category: str) -> dict[str, Any] | None:
        """Return the raw integration dict for a category, or None."""
        data = self.read_raw()
        return data.get("integrations", {}).get(category)

    def get_all_integrations(self) -> dict[str, Any]:
        """Return the full integrations dict."""
        data = self.read_raw()
        return data.get("integrations", {})

    def reload_config(self) -> None:
        """Force the global config singleton to reload from disk."""
        import backend.core.config_loader as cl

        cl._config_loader = None  # clear cached singleton
        logger.info("Config cache cleared — next get_config() will reload from disk")
