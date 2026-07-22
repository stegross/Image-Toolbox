"""SCIBIT configuration types (spec Sections 3.7 and 5).

Two-level configuration approach:

1. **SessionConfig** — minimal UI state (last folder, last config name)
   persisted by the host shell's :class:`~app.core.config.ConfigManager`
   across application launches.  Provides :meth:`SessionConfig.load` and
   :meth:`SessionConfig.save` adapters for the ConfigManager API.

2. **PipelineOptions** — pipeline-level settings: preset, rotation,
   inversion, confidence threshold, debug export mode.

3. **StageConfig** — per-stage operator assignment and parameters.

4. **Configuration** — a full, JSON-serialisable pipeline configuration
   (one ``.json`` file per saved config).  The exact JSON schema follows
   spec Section 5.

5. **PipelineConfigStore** — manages a directory of saved pipeline
   configuration files and provides listing / load / save / delete.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from app.tools.scibit.core.types import DebugExportMode

if TYPE_CHECKING:
    from app.core.config import ConfigManager

_log = logging.getLogger(__name__)

#: Key used when storing session state inside the tool's ConfigManager dict.
_SESSION_KEY = "session"

#: Sub-directory (relative to ConfigManager's config_dir) that holds
#: individual pipeline configuration JSON files.
_PIPELINE_CONFIGS_SUBDIR = "scibit_configs"

#: Tool name used when calling ConfigManager for SCIBIT's session state.
SCIBIT_TOOL_NAME = "scibit"


# ---------------------------------------------------------------------------
# SessionConfig
# ---------------------------------------------------------------------------


@dataclass
class SessionConfig:
    """Minimal UI state persisted across application launches.

    Stored inside the host shell's :class:`~app.core.config.ConfigManager`
    under the key ``"session"`` within SCIBIT's tool config dict.

    Parameters
    ----------
    last_folder : Path | None
        The last folder the user opened, or ``None`` if never opened.
    last_pipeline_config_name : str | None
        Name of the last selected pipeline configuration (file stem), or
        ``None`` if none was selected.
    test_mode : bool
        When ``True``, batch completion compares each recognised identifier
        against the source filename's stem and logs an accuracy summary.
    """

    last_folder: Path | None = None
    last_pipeline_config_name: str | None = None
    test_mode: bool = False

    # ------------------------------------------------------------------
    # ConfigManager integration
    # ------------------------------------------------------------------

    @classmethod
    def load(
        cls,
        config_manager: ConfigManager,
        tool_name: str = SCIBIT_TOOL_NAME,
    ) -> SessionConfig:
        """Restore session state from *config_manager*.

        Reads the tool config dict for *tool_name* and extracts the
        ``"session"`` sub-dict.  Returns a default ``SessionConfig`` if no
        session data has been saved yet.

        Parameters
        ----------
        config_manager : ConfigManager
            Host shell configuration manager instance.
        tool_name : str
            Tool name key used with *config_manager* (defaults to
            ``SCIBIT_TOOL_NAME``).

        Returns
        -------
        SessionConfig
            Restored session state, or defaults if nothing is persisted.
        """
        tool_config = config_manager.get_tool_config(tool_name)
        raw = tool_config.get(_SESSION_KEY, {})
        return cls._from_raw(raw)

    def save(
        self,
        config_manager: ConfigManager,
        tool_name: str = SCIBIT_TOOL_NAME,
    ) -> None:
        """Persist the current session state via *config_manager*.

        Replaces the entire tool config dict with ``{"session": ...}``.

        Parameters
        ----------
        config_manager : ConfigManager
            Host shell configuration manager instance.
        tool_name : str
            Tool name key used with *config_manager*.
        """
        config_manager.set_tool_config(tool_name, {_SESSION_KEY: self._to_raw()})
        config_manager.save(tool_name)

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    def _to_raw(self) -> dict:
        """Serialise to a plain JSON-compatible dict."""
        return {
            "last_folder": str(self.last_folder) if self.last_folder else None,
            "last_pipeline_config_name": self.last_pipeline_config_name,
            "test_mode": self.test_mode,
        }

    @classmethod
    def _from_raw(cls, data: dict) -> SessionConfig:
        """Deserialise from a plain dict (as stored by ConfigManager)."""
        folder_raw = data.get("last_folder")
        return cls(
            last_folder=Path(folder_raw) if folder_raw else None,
            last_pipeline_config_name=data.get("last_pipeline_config_name"),
            test_mode=bool(data.get("test_mode", False)),
        )


# ---------------------------------------------------------------------------
# PipelineOptions
# ---------------------------------------------------------------------------


@dataclass
class PipelineOptions:
    """Pipeline-level configuration options (spec Section 3.7).

    These are the settings that apply to the whole pipeline rather than to
    individual stages.  They are stored in the top-level
    ``"pipeline_options"`` object of a pipeline configuration JSON file.

    Pre-rotation, colour inversion and downscale factor are *not* pipeline
    options — they are parameters of the built-in ``calibration_setup``
    stage and live in :class:`StageConfig` for that stage.

    Parameters
    ----------
    identifier_pattern_preset : str
        Name of the active
        :class:`~app.tools.scibit.config.preset.IdentifierPatternPreset`.
        Resolved to a regex at runtime via the registry.
    manual_confirmation_required : bool
        When ``True``, even ``PASSED`` results require user review before
        the output file is written.
    confidence_threshold_percent : float
        Minimum OCR confidence (``0.0``–``100.0``) for a result to
        be classified as ``PASSED`` (provided the regex also matches).
    debug_export_mode : DebugExportMode
        Controls whether interim processing images are written to disk
        (spec Section 8.7).
    """

    identifier_pattern_preset: str = "Default (accept any)"
    manual_confirmation_required: bool = True
    confidence_threshold_percent: float = 85.0
    debug_export_mode: DebugExportMode = DebugExportMode.DISABLED

    def to_dict(self) -> dict:
        """Serialise to a JSON-compatible dict (key names match Section 5)."""
        return {
            "identifier_pattern_preset": self.identifier_pattern_preset,
            "manual_confirmation_required": self.manual_confirmation_required,
            "confidence_threshold_percent": self.confidence_threshold_percent,
            "debug_export_mode": self.debug_export_mode.value,
        }

    @classmethod
    def from_dict(cls, data: dict) -> PipelineOptions:
        """Deserialise from a dict parsed out of a pipeline configuration JSON.

        Unknown keys are silently ignored; missing keys fall back to
        defaults.
        """
        return cls(
            identifier_pattern_preset=str(
                data.get("identifier_pattern_preset", "Default (accept any)")
            ),
            manual_confirmation_required=bool(data.get("manual_confirmation_required", True)),
            confidence_threshold_percent=float(data.get("confidence_threshold_percent", 85.0)),
            debug_export_mode=DebugExportMode(
                data.get("debug_export_mode", DebugExportMode.DISABLED.value)
            ),
        )


# ---------------------------------------------------------------------------
# StageConfig
# ---------------------------------------------------------------------------


@dataclass
class StageConfig:
    """Per-stage configuration stored inside a pipeline configuration file.

    Parameters
    ----------
    operator : str
        String identifier of the assigned operator class
        (e.g. ``"OpenCVOperator"``).  Empty string for built-in stages
        with no associated operator (e.g. ``calibration_setup``).
        Resolved to the actual class via
        :meth:`~app.tools.scibit.core.registry.OperatorRegistry.resolve_operator_class`
        at pipeline construction time.
    parameters : dict
        Parameter values for this stage. Keys are stage-specific and
        match those declared by the stage's
        :meth:`~app.tools.scibit.core.stage.Stage.get_default_parameters`
        (and the assigned operator's
        :meth:`get_param_schema`).
    """

    operator: str = ""
    parameters: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Serialise to a JSON-compatible dict."""
        return {"operator": self.operator, "parameters": dict(self.parameters)}

    @classmethod
    def from_dict(cls, data: dict) -> StageConfig:
        """Deserialise from a dict parsed out of a pipeline configuration JSON."""
        return cls(
            operator=str(data.get("operator", "")),
            parameters=dict(data.get("parameters", {})),
        )


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class Configuration:
    """Complete, serialisable pipeline configuration (spec Sections 3.7 and 5).

    One ``Configuration`` corresponds to one ``.json`` file on disk.  It
    stores everything needed to pre-fill calibration:

    - The pipeline variant identifier (``pipeline``).
    - Pipeline-level options (``pipeline_options``).
    - Per-stage operator assignments and parameter values (``stages``).

    It intentionally does **not** store calibration data (template images,
    keypoints, ROI coordinates), image data, or batch results.

    Parameters
    ----------
    pipeline : str
        Pipeline variant identifier, e.g. ``"feature_based_alignment"``.
        Must match the key used in the pipeline factory / registry.
    pipeline_options : PipelineOptions
        Pipeline-level settings.
    stages : dict[str, StageConfig]
        Mapping from stage name to its configuration.  Stage names must
        match those declared by the corresponding pipeline subclass.
    name : str
        Human-readable display name.  Derived from the file stem when
        loading from disk; defaults to ``"Untitled Configuration"``.
    """

    pipeline: str
    pipeline_options: PipelineOptions = field(default_factory=PipelineOptions)
    stages: dict[str, StageConfig] = field(default_factory=dict)
    name: str = "Untitled Configuration"

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Serialise to a JSON-compatible dict (schema per spec Section 5)."""
        return {
            "pipeline": self.pipeline,
            "pipeline_options": self.pipeline_options.to_dict(),
            "stages": {
                stage_name: stage_cfg.to_dict() for stage_name, stage_cfg in self.stages.items()
            },
        }

    def save(self, path: Path) -> None:
        """Write this configuration to *path* as a formatted JSON file.

        Parameters
        ----------
        path : Path
            Target file path.  The parent directory must already exist.

        Raises
        ------
        OSError
            If the file cannot be written.
        """
        with path.open("w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2, ensure_ascii=False)
        _log.debug("Configuration '%s' saved to %s.", self.name, path)

    # ------------------------------------------------------------------
    # Deserialisation
    # ------------------------------------------------------------------

    @classmethod
    def load(cls, path: Path) -> Configuration:
        """Load a configuration from the JSON file at *path*.

        Parameters
        ----------
        path : Path
            Path to a ``.json`` pipeline configuration file.

        Returns
        -------
        Configuration
            Populated configuration instance.  The ``name`` attribute is
            set to the file stem.

        Raises
        ------
        OSError
            If the file cannot be read.
        ValueError
            If the JSON is malformed or the ``"pipeline"`` key is absent.
        """
        with path.open(encoding="utf-8") as fh:
            try:
                data: dict = json.load(fh)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON in configuration file {path}: {exc}") from exc

        if "pipeline" not in data:
            raise ValueError(f"Configuration file {path} is missing the required 'pipeline' key.")

        stages: dict[str, StageConfig] = {}
        for stage_name, stage_data in data.get("stages", {}).items():
            try:
                stages[stage_name] = StageConfig.from_dict(stage_data)
            except (KeyError, TypeError) as exc:
                raise ValueError(f"Malformed stage config '{stage_name}' in {path}: {exc}") from exc

        return cls(
            pipeline=str(data["pipeline"]),
            pipeline_options=PipelineOptions.from_dict(data.get("pipeline_options", {})),
            stages=stages,
            name=path.stem,
        )


# ---------------------------------------------------------------------------
# PipelineConfigStore
# ---------------------------------------------------------------------------


class PipelineConfigStore:
    """Manages a directory of saved pipeline configuration files.

    Each file in *config_dir* whose name ends in ``.json`` is treated as a
    saved pipeline configuration.  The store provides listing, loading,
    saving, and deletion of named configurations.

    The store is typically pointed at a tool-specific subdirectory inside
    the host shell's config directory::

        store = PipelineConfigStore.from_config_manager(config_manager)

    Parameters
    ----------
    config_dir : Path
        Directory that contains (or will contain) pipeline configuration
        JSON files.  Created on first write if it does not yet exist.
    """

    def __init__(self, config_dir: Path) -> None:
        self._config_dir = config_dir

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_config_manager(
        cls,
        config_manager: ConfigManager,
    ) -> PipelineConfigStore:
        """Construct a store rooted at the ConfigManager's config directory.

        The store lives in a ``scibit_configs/`` sub-directory alongside the
        other tool config files.

        Parameters
        ----------
        config_manager : ConfigManager
            Host shell configuration manager instance.

        Returns
        -------
        PipelineConfigStore
            Store ready for use.
        """
        # ConfigManager stores the config_dir reference on ``_config_dir``.
        # We read it via the private attribute because ConfigManager has no
        # public accessor for the directory path.
        config_dir: Path = config_manager._config_dir / _PIPELINE_CONFIGS_SUBDIR  # type: ignore[attr-defined]
        return cls(config_dir)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def list_configs(self) -> list[str]:
        """Return the names of all saved configurations (file stems).

        Returns
        -------
        list[str]
            Configuration names sorted alphabetically.  Empty list if the
            directory does not exist or contains no ``.json`` files.
        """
        if not self._config_dir.exists():
            return []
        return sorted(p.stem for p in self._config_dir.glob("*.json") if p.is_file())

    def load_config(self, name: str) -> Configuration:
        """Load and return the named configuration.

        Parameters
        ----------
        name : str
            Configuration name (file stem, without ``.json`` extension).

        Returns
        -------
        Configuration
            The loaded configuration.

        Raises
        ------
        FileNotFoundError
            If no configuration with *name* exists.
        ValueError
            If the file is malformed.
        """
        path = self._path_for(name)
        if not path.exists():
            raise FileNotFoundError(
                f"No pipeline configuration named '{name}' found in {self._config_dir}."
            )
        return Configuration.load(path)

    def config_exists(self, name: str) -> bool:
        """Return ``True`` if a configuration with *name* exists on disk."""
        return self._path_for(name).exists()

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def save_config(self, config: Configuration) -> None:
        """Save *config* to disk, creating the directory if needed.

        The file is named ``<config.name>.json``.  Any characters in
        ``config.name`` that are illegal in file names are replaced with
        underscores before writing.

        Parameters
        ----------
        config : Configuration
            Configuration to persist.

        Raises
        ------
        OSError
            If the file cannot be written.
        """
        self._config_dir.mkdir(parents=True, exist_ok=True)
        safe_name = _sanitise_filename(config.name)
        path = self._config_dir / f"{safe_name}.json"
        config.save(path)
        _log.debug("Saved pipeline config '%s' to %s.", config.name, path)

    def delete_config(self, name: str) -> bool:
        """Delete the named configuration file.

        Parameters
        ----------
        name : str
            Configuration name (file stem).

        Returns
        -------
        bool
            ``True`` if the file existed and was deleted, ``False`` if it
            was not found (no error is raised in that case).
        """
        path = self._path_for(name)
        if not path.exists():
            return False
        path.unlink()
        _log.debug("Deleted pipeline config '%s' (%s).", name, path)
        return True

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _path_for(self, name: str) -> Path:
        return self._config_dir / f"{_sanitise_filename(name)}.json"


def _sanitise_filename(name: str) -> str:
    """Replace characters that are illegal in file names with underscores."""
    illegal = r'\/:*?"<>|'
    result = name
    for ch in illegal:
        result = result.replace(ch, "_")
    return result.strip() or "unnamed"
