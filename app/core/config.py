"""Per-tool configuration management (REQ-HS-009)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

_logger = logging.getLogger("vi_toolbox.core.config")


class ConfigManager:
    """Manages per-tool JSON configuration files.

    Each tool's config is stored as ``<config_dir>/<tool_name>.json``
    (spaces in tool names are replaced with underscores, all lower-case).
    Configs are lazily loaded and cached in memory.

    Parameters
    ----------
    config_dir : Path
        Directory where tool configuration files are stored.
        Created automatically if it does not exist.
    """

    def __init__(self, config_dir: Path) -> None:
        self._config_dir = config_dir
        self._config_dir.mkdir(parents=True, exist_ok=True)
        self._tool_configs: dict[str, dict] = {}

    def get_tool_config(self, tool_name: str) -> dict:
        """Return the in-memory config dict for *tool_name*.

        Loads from disk on first access and caches the result.

        Parameters
        ----------
        tool_name : str
            The tool's :attr:`~app.plugin.base.IToolPlugin.name`.

        Returns
        -------
        dict
            Configuration dictionary (empty dict if none exists).
        """
        if tool_name not in self._tool_configs:
            self._tool_configs[tool_name] = self.load(tool_name)
        return self._tool_configs[tool_name]

    def set_tool_config(self, tool_name: str, config: dict) -> None:
        """Replace the in-memory config for *tool_name*.

        Parameters
        ----------
        tool_name : str
            The tool's :attr:`~app.plugin.base.IToolPlugin.name`.
        config : dict
            New configuration dictionary.
        """
        self._tool_configs[tool_name] = config

    def save(self, tool_name: str) -> None:
        """Persist the in-memory config for *tool_name* to disk.

        Parameters
        ----------
        tool_name : str
            The tool's :attr:`~app.plugin.base.IToolPlugin.name`.
        """
        config = self._tool_configs.get(tool_name, {})
        path = self._config_path(tool_name)
        try:
            with path.open("w", encoding="utf-8") as fh:
                json.dump(config, fh, indent=2)
            _logger.debug("Config saved: %s -> %s", tool_name, path)
        except OSError as exc:
            _logger.error("Failed to save config for '%s': %s", tool_name, exc)

    def load(self, tool_name: str) -> dict:
        """Load *tool_name*'s config from disk.

        Parameters
        ----------
        tool_name : str
            The tool's :attr:`~app.plugin.base.IToolPlugin.name`.

        Returns
        -------
        dict
            Loaded configuration, or an empty dict if the file does not
            exist or cannot be parsed.
        """
        path = self._config_path(tool_name)
        if not path.exists():
            return {}
        try:
            with path.open(encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            _logger.warning("Failed to load config for '%s': %s", tool_name, exc)
            return {}

    def save_all(self) -> None:
        """Persist every cached tool config to disk."""
        for tool_name in list(self._tool_configs):
            self.save(tool_name)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _config_path(self, tool_name: str) -> Path:
        """Return the JSON file path for *tool_name*.

        Parameters
        ----------
        tool_name : str
            The tool's :attr:`~app.plugin.base.IToolPlugin.name`.

        Returns
        -------
        Path
            Path to the ``<tool_name>.json`` file.
        """
        filename = tool_name.lower().replace(" ", "_") + ".json"
        return self._config_dir / filename
