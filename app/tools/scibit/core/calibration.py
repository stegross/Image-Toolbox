"""Calibration view abstraction and shared context (spec Section 3.10).

This module defines the contract between calibration-driving stages and
the :class:`~app.tools.scibit.ui.calibration_widget.CalibrationWidget`,
without either side importing the other:

* :class:`CalibrationView` — the structural Protocol of UI primitives a
  stage may invoke during its calibration flow.  Stages depend on this
  abstraction; the concrete widget satisfies it through duck typing so
  no inheritance or registration is required.
* :class:`CalibrationContext` — the mutable per-run state passed into
  every stage hook.  Parallels :class:`~app.tools.scibit.core.pipeline.BatchContext`
  for batch mode.

Stages access these via the calibration hooks they choose to implement
(see ``app/tools/scibit/stages/*``).  There is no abstract base class
for "calibratable stage"; stages opt in by simply defining the methods.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import numpy as np
from numpy.typing import NDArray

from app.tools.scibit.core.types import BoundingBox, DebugExportMode

if TYPE_CHECKING:
    from app.tools.scibit.config.config import PipelineOptions
    from app.tools.scibit.config.preset import IdentifierPatternPresetRegistry
    from app.tools.scibit.core.pipeline import Pipeline
    from app.tools.scibit.core.session import CalibrationSession


# ---------------------------------------------------------------------------
# View Protocol — UI primitives a stage may call
# ---------------------------------------------------------------------------


class CalibrationView(Protocol):
    """Structural Protocol of UI operations available to calibration stages.

    The concrete :class:`~app.tools.scibit.ui.calibration_widget.CalibrationWidget`
    satisfies this Protocol through duck typing — no explicit inheritance
    is required.  Stages depend on this abstraction so they can be unit
    tested with a lightweight fake view.

    The widget owns the fixed layout (title bar, image panel, parameter
    panel, button bar).  These methods let a stage populate the dynamic
    parts of that layout: title text, image content with overlays, ROI
    drawing mode, the optional text-result panel, and error messages.
    The parameter panel and button bar are rebuilt by the widget from
    each stage's :class:`~app.tools.scibit.core.stage.StageUIDescriptor`
    and are not driven through this Protocol.
    """

    # ------------------------------------------------------------------
    # Title bar
    # ------------------------------------------------------------------

    def set_title(self, text: str) -> None:
        """Replace the title bar text."""

    # ------------------------------------------------------------------
    # Image panel
    # ------------------------------------------------------------------

    def load_image(self, path: Path) -> None:
        """Load an image from disk into the image panel."""

    def set_preview_image(self, image: NDArray[np.uint8]) -> None:
        """Display *image* (already in memory) in the image panel."""

    # ------------------------------------------------------------------
    # Overlays drawn on top of the image
    # ------------------------------------------------------------------

    def show_rect_overlay(
        self,
        rect: BoundingBox,
        color: tuple[int, int, int],
        width: int,
    ) -> None:
        """Draw a single rectangular overlay on the image panel."""

    def show_rects_overlay(
        self,
        rects: list[BoundingBox],
        color: tuple[int, int, int],
        *,
        selectable: bool,
    ) -> None:
        """Draw multiple rectangular overlays on the image panel.

        When *selectable* is ``True`` the user can click one and the widget
        emits its bounding box to the active stage's :meth:`on_scene_selection`.
        """

    def clear_overlays(self) -> None:
        """Remove all overlays from the image panel."""

    # ------------------------------------------------------------------
    # ROI drawing mode (rubber-band selection on the image panel)
    # ------------------------------------------------------------------

    def start_roi_selection(self, mode: str) -> None:
        """Enter rubber-band drawing mode tagged with *mode*.

        When the user finishes drawing, the widget routes the resulting
        rectangle to the active stage's :meth:`on_roi_drawn` along with
        the same *mode* string so the stage can distinguish among multiple
        ROI uses within a single stage.
        """

    def stop_roi_selection(self) -> None:
        """Leave rubber-band drawing mode."""

    # ------------------------------------------------------------------
    # Result panel (generic text + confidence display)
    # ------------------------------------------------------------------

    def show_text_result(self, text: str, confidence: float) -> None:
        """Show the result panel with *text* and a confidence value.

        The confidence is expected in the range ``0.0``–``100.0`` and is
        rendered as a bar or numeric badge alongside the text.
        """

    def hide_text_result(self) -> None:
        """Hide the result panel."""

    # ------------------------------------------------------------------
    # Error display
    # ------------------------------------------------------------------

    def show_error(self, message: str) -> None:
        """Display an error message to the user."""


# ---------------------------------------------------------------------------
# Calibration run context — mutable state shared across stage hooks
# ---------------------------------------------------------------------------


@dataclass
class CalibrationContext:
    """Per-run state passed into every calibration hook.

    Parallels :class:`~app.tools.scibit.core.pipeline.BatchContext` for
    batch mode.  The context is mutated across stages: the
    ``CalibrationSetupStage`` populates :attr:`session`, downstream
    stages read and write through it.

    Parameters
    ----------
    pipeline : Pipeline
        The pipeline whose stages are being driven.  Used by stages
        that need pipeline-level services (e.g. ``Pipeline.get_stage``).
    options : PipelineOptions
        Pipeline-level configuration shared with batch mode.
    preset_registry : IdentifierPatternPresetRegistry
        Registry used to resolve the active identifier-pattern preset
        (used by ``TextRecognitionStage`` to derive a charset hint).
    image_paths : list[Path]
        Candidate calibration images.  ``image_paths[image_idx]`` is the
        currently selected example image.
    image_idx : int
        Index of the example image being used for calibration.  Advances
        when the user requests skip-to-next-image.
    debug_dir : Path | None
        Directory into which calibration-phase debug images are written,
        or ``None`` when debug export is disabled for calibration.
        Populated by ``CalibrationSetupStage.confirm_calibration``.
    session : CalibrationSession | None
        The pipeline-specific calibration session being built.  ``None``
        until ``CalibrationSetupStage.confirm_calibration`` constructs it.
    """

    pipeline: Pipeline
    options: PipelineOptions
    preset_registry: IdentifierPatternPresetRegistry
    image_paths: list[Path]
    image_idx: int = 0
    debug_dir: Path | None = None
    session: CalibrationSession | None = None

    @property
    def debug_enabled(self) -> bool:
        """``True`` when calibration-phase debug export should be written.

        Convenience for stages that conditionally call
        :func:`~app.tools.scibit.core.debug.write_debug_image`.
        """
        return self.debug_dir is not None and self.options.debug_export_mode in (
            DebugExportMode.CALIBRATION,
            DebugExportMode.ALL,
        )
