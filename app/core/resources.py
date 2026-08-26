"""Loader for bundled SCIBIT configs (embedded in EXE or read from dev folder).

In a frozen (PyInstaller) build, the configs are compiled into the PYZ
archive as the module :mod:`app.tools.scibit._bundled_configs`, so they
live **inside** the EXE binary and cannot be modified by end users.

When running from source (development), the JSON files under
``app/tools/scibit/packaged_configs/`` are read directly so developers
can iterate without regenerating the embedded module.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

#: Developer-facing config directory (only used in non-frozen / dev mode).
_PACKAGED_CONFIGS_DIR = Path(__file__).parent.parent / "tools" / "scibit" / "packaged_configs"

#: Sub-directory holding individual pipeline configuration JSON files.
_PIPELINE_CONFIGS_SUBDIR = _PACKAGED_CONFIGS_DIR / "pipeline_configs"

#: The regex presets JSON file (dev mode only).
_PRESETS_FILE = _PACKAGED_CONFIGS_DIR / "scibit_regex_presets.json"


def load_bundled_pipeline_configs() -> dict[str, dict]:
    """Load all bundled pipeline configs as a name -> parsed-dict mapping.

    Returns
    -------
    dict[str, dict]
        Mapping from config name (file stem) to parsed JSON dict.
    """
    if getattr(sys, "frozen", False):
        from app.tools.scibit._bundled_configs import PIPELINE_CONFIGS

        return dict(PIPELINE_CONFIGS)

    configs: dict[str, dict] = {}
    for path in sorted(_PIPELINE_CONFIGS_SUBDIR.glob("*.json")):
        with path.open(encoding="utf-8") as fh:
            configs[path.stem] = json.load(fh)
    return configs


def load_bundled_presets_data() -> list[dict]:
    """Load bundled regex presets as a list of parsed dicts.

    Returns
    -------
    list[dict]
        List of preset entries (name, regex, description).
    """
    if getattr(sys, "frozen", False):
        from app.tools.scibit._bundled_configs import REGEX_PRESETS

        return list(REGEX_PRESETS)

    with _PRESETS_FILE.open(encoding="utf-8") as fh:
        return json.load(fh)
