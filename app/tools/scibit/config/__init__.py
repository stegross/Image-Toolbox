"""SCIBIT configuration sub-package.

This package is the authoritative home for all SCIBIT configuration types.
The ``core/`` package re-exports these for backwards compatibility.

Typical imports::

    from app.tools.scibit.config import (
        Configuration,
        PipelineOptions,
        PipelineConfigStore,
        SessionConfig,
        StageConfig,
        IdentifierPatternPreset,
        IdentifierPatternPresetRegistry,
        DebugExportMode,          # convenience re-export from core.types
    )
"""

from app.tools.scibit.config.config import (
    SCIBIT_TOOL_NAME,
    Configuration,
    PipelineConfigStore,
    PipelineOptions,
    SessionConfig,
    StageConfig,
)
from app.tools.scibit.config.preset import (
    IdentifierPatternPreset,
    IdentifierPatternPresetRegistry,
)

# DebugExportMode lives in core.types (it is a processing type, not purely a
# config type), but is re-exported here for convenience so callers can import
# everything configuration-related from one place.
from app.tools.scibit.core.types import DebugExportMode

__all__ = [
    "Configuration",
    "DebugExportMode",
    "IdentifierPatternPreset",
    "IdentifierPatternPresetRegistry",
    "PipelineConfigStore",
    "PipelineOptions",
    "SCIBIT_TOOL_NAME",
    "SessionConfig",
    "StageConfig",
]
