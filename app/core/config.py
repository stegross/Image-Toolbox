"""Per-tool configuration management (REQ-HS-006)."""

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
        # Keyed tool_name → {str(instance_id): config_dict}
        self._instance_configs: dict[str, dict[str, dict]] = {}

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
    # Instance config (multi-instance tools only)
    # ------------------------------------------------------------------

    def get_instance_config(self, tool_name: str, instance_id: int) -> dict:
        """Return the in-memory instance config for *tool_name* / *instance_id*.

        Loads the instance config file on first access for this tool and
        caches all instance entries together.

        Parameters
        ----------
        tool_name : str
            The tool's :attr:`~app.plugin.base.IToolPlugin.name`.
        instance_id : int
            Positive integer instance identifier.

        Returns
        -------
        dict
            Configuration dictionary for this instance (empty if none saved).
        """
        if tool_name not in self._instance_configs:
            self._instance_configs[tool_name] = self._load_instances(tool_name)
        return self._instance_configs[tool_name].get(str(instance_id), {})

    def set_instance_config(self, tool_name: str, instance_id: int, config: dict) -> None:
        """Store *config* for *tool_name* / *instance_id* in memory.

        Parameters
        ----------
        tool_name : str
            The tool's :attr:`~app.plugin.base.IToolPlugin.name`.
        instance_id : int
            Positive integer instance identifier.
        config : dict
            Configuration dictionary to store.
        """
        if tool_name not in self._instance_configs:
            self._instance_configs[tool_name] = self._load_instances(tool_name)
        self._instance_configs[tool_name][str(instance_id)] = config

    def remove_instance_config(self, tool_name: str, instance_id: int) -> None:
        """Remove the config entry for *tool_name* / *instance_id*.

        Called when an instance closes mid-session so it is not written at
        shutdown.  No-op if the entry does not exist.

        Parameters
        ----------
        tool_name : str
            The tool's :attr:`~app.plugin.base.IToolPlugin.name`.
        instance_id : int
            Positive integer instance identifier.
        """
        if tool_name in self._instance_configs:
            self._instance_configs[tool_name].pop(str(instance_id), None)

    def save_instance_configs(self, tool_name: str) -> None:
        """Persist all in-memory instance configs for *tool_name* to disk.

        Parameters
        ----------
        tool_name : str
            The tool's :attr:`~app.plugin.base.IToolPlugin.name`.
        """
        data = self._instance_configs.get(tool_name, {})
        path = self._instances_path(tool_name)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
            _logger.debug("Instance configs saved: %s -> %s", tool_name, path)
        except OSError as exc:
            _logger.error("Failed to save instance configs for '%s': %s", tool_name, exc)

    def save_all_instances(self) -> None:
        """Persist every cached instance config to disk."""
        for tool_name in list(self._instance_configs):
            self.save_instance_configs(tool_name)

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

    def _instances_path(self, tool_name: str) -> Path:
        """Return the instance config JSON file path for *tool_name*.

        Parameters
        ----------
        tool_name : str
            The tool's :attr:`~app.plugin.base.IToolPlugin.name`.

        Returns
        -------
        Path
            Path to the ``<tool_name>_instances.json`` file.
        """
        filename = tool_name.lower().replace(" ", "_") + "_instances.json"
        return self._config_dir / filename

    def _load_instances(self, tool_name: str) -> dict[str, dict]:
        """Load the instance config file for *tool_name* from disk.

        Parameters
        ----------
        tool_name : str
            The tool's :attr:`~app.plugin.base.IToolPlugin.name`.

        Returns
        -------
        dict[str, dict]
            Mapping of ``str(instance_id)`` to config dict.  Empty dict if
            the file does not exist or cannot be parsed.
        """
        path = self._instances_path(tool_name)
        if not path.exists():
            return {}
        try:
            with path.open(encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, OSError) as exc:
            _logger.warning("Failed to load instance configs for '%s': %s", tool_name, exc)
        return {}
