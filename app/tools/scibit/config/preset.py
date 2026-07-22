r"""IdentifierPatternPreset and IdentifierPatternPresetRegistry (spec Section 3.9).

Presets bundle a human-readable name, a regex pattern, and an optional
description, making regex-based validation accessible to non-technical
users without requiring them to write regular expressions.

Presets are loaded from a JSON file at startup; no GUI editing is provided
in this version (spec Section 3.9: "read-only — no editing via GUI").

The hardcoded **default preset** ("Default (accept any)", regex ``.*``) is
always present even when the JSON file is missing or empty, ensuring the
pipeline never runs without a valid preset.

JSON preset file format::

    [
        {
            "name": "Standard Cxxx-yy",
            "regex": "^C\\d{3}-\\d{2}$",
            "description": "Matches identifiers like C042-17."
        },
        ...
    ]
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

_log = logging.getLogger(__name__)

_DEFAULT_PRESET_NAME = "Default (accept any)"
_DEFAULT_PRESET_REGEX = ".*"
_DEFAULT_PRESET_DESCRIPTION = (
    "Accept any OCR output without pattern filtering. "
    "Validation always passes and no character set hint is derived."
)


# ---------------------------------------------------------------------------
# Preset dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IdentifierPatternPreset:
    """A named, reusable identifier pattern definition.

    Parameters
    ----------
    name : str
        Human-readable label shown in the UI combo box
        (e.g. ``"Standard Cxxx-yy"``).
    regex : str
        Regular expression the recognised text must **fully** match
        (applied via ``re.fullmatch``).
    description : str
        Optional tooltip / help text explaining what the pattern matches.
        Shown in the UI as a tooltip on the combo box item.
    """

    name: str
    regex: str
    description: str = ""


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class IdentifierPatternPresetRegistry:
    """Registry of named identifier pattern presets.

    Create an empty registry (containing only the default) with the
    constructor, or load from a JSON file via :meth:`load`.

    The registry is **ordered** — the default preset is always first,
    followed by presets from the file in their original order.

    Parameters
    ----------
    presets : list[IdentifierPatternPreset] | None
        Additional presets to register beyond the default.  Entries whose
        name matches the default preset name are silently ignored.
    """

    _DEFAULT: IdentifierPatternPreset = IdentifierPatternPreset(
        name=_DEFAULT_PRESET_NAME,
        regex=_DEFAULT_PRESET_REGEX,
        description=_DEFAULT_PRESET_DESCRIPTION,
    )

    def __init__(self, presets: list[IdentifierPatternPreset] | None = None) -> None:
        # Use insertion-ordered dict; default is always at index 0.
        self._presets: dict[str, IdentifierPatternPreset] = {_DEFAULT_PRESET_NAME: self._DEFAULT}
        for preset in presets or []:
            if preset.name == _DEFAULT_PRESET_NAME:
                continue  # cannot override the hardcoded default
            self._presets[preset.name] = preset

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def load(cls, path: Path) -> IdentifierPatternPresetRegistry:
        """Load presets from a JSON file at *path*.

        On any error (missing file, parse failure, invalid entry) the
        registry falls back to containing only the default preset and logs
        a warning.

        Parameters
        ----------
        path : Path
            Path to the JSON preset configuration file.

        Returns
        -------
        IdentifierPatternPresetRegistry
            Registry populated with the file's presets (plus the default).
        """
        if not path.exists():
            _log.warning("Preset file not found: %s — using default preset only.", path)
            return cls()

        try:
            with path.open(encoding="utf-8") as fh:
                raw: list = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            _log.error("Failed to load preset file %s: %s", path, exc)
            return cls()

        if not isinstance(raw, list):
            _log.error(
                "Preset file %s must contain a JSON array, got %s.",
                path,
                type(raw).__name__,
            )
            return cls()

        presets: list[IdentifierPatternPreset] = []
        for idx, entry in enumerate(raw):
            try:
                presets.append(
                    IdentifierPatternPreset(
                        name=str(entry["name"]),
                        regex=str(entry["regex"]),
                        description=str(entry.get("description", "")),
                    )
                )
            except (KeyError, TypeError) as exc:
                _log.warning(
                    "Skipping malformed preset entry at index %d in %s: %s",
                    idx,
                    path,
                    exc,
                )

        _log.debug("Loaded %d preset(s) from %s (+ default).", len(presets), path)
        return cls(presets)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_preset_names(self) -> list[str]:
        """Return all preset names in insertion order (default first).

        Returns
        -------
        list[str]
            Preset names suitable for populating a UI combo box.
        """
        return list(self._presets.keys())

    def get_preset(self, name: str) -> IdentifierPatternPreset:
        """Return the preset with *name*.

        Falls back to the default preset and logs a warning when *name* is
        not found, preventing a missing preset from crashing a batch run.

        Parameters
        ----------
        name : str
            Preset name as returned by :meth:`get_preset_names`.

        Returns
        -------
        IdentifierPatternPreset
            The requested preset, or the default if *name* is unknown.
        """
        if name not in self._presets:
            _log.warning("Preset '%s' not found — falling back to default preset.", name)
            return self._DEFAULT
        return self._presets[name]

    @property
    def default_preset(self) -> IdentifierPatternPreset:
        """The hardcoded default "accept any" preset."""
        return self._DEFAULT

    def __len__(self) -> int:
        """Return the number of registered presets (including the default)."""
        return len(self._presets)

    def __contains__(self, name: object) -> bool:
        """Return whether a preset with the given *name* is registered."""
        return name in self._presets
