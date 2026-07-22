"""Identifier Region Detection — Pipeline A stage 3.

Runs an OCR text-region detector on the aligned chip crop. Default
operator is :class:`EasyOCROperator`. Candidates are offered as
clickable overlays; the user can also draw the region manually with
the "Draw Manually" button.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import numpy as np
from numpy.typing import NDArray

from app.tools.scibit.core.debug import write_debug_image
from app.tools.scibit.core.helpers import crop_bbox
from app.tools.scibit.core.operations import TextRegionDetection
from app.tools.scibit.core.stage import Stage, StageUIDescriptor
from app.tools.scibit.core.types import BoundingBox

if TYPE_CHECKING:
    from app.tools.scibit.core.calibration import (
        CalibrationContext,
        CalibrationView,
    )
    from app.tools.scibit.core.session import CalibrationSession

_log = logging.getLogger(__name__)

_COLOR_ID_REG = (200, 0, 200)
_COLOR_SELECTED = (0, 120, 255)


class IdentifierRegionDetectionStage(Stage):
    """Detect candidate text regions on the aligned chip crop."""

    @property
    def name(self) -> str:
        """Return the stage's pipeline identifier."""
        return "identifier_region_detection"

    @property
    def display_name(self) -> str:
        """Return the human-readable stage name."""
        return "Identifier Region Detection"

    @property
    def required_operation(self) -> type | None:
        """Return :class:`TextRegionDetection` — the operation this stage drives."""
        return TextRegionDetection

    def get_default_operator_class(self) -> type | None:
        """Return :class:`EasyOCROperator` as the default text-region detector."""
        from app.tools.scibit.operators.easyocr_operator import EasyOCROperator

        return EasyOCROperator

    def get_default_parameters(self) -> dict[str, Any]:
        """Return an empty parameter dict — operator defaults apply."""
        return {}

    def invoke(
        self,
        operator: TextRegionDetection,
        image: NDArray[np.uint8],
        session: CalibrationSession,
        **kwargs: Any,
    ) -> Any:
        """Run *operator* to detect candidate text regions on *image*."""
        return operator.detect_text_regions(image, self._parameters)

    def get_ui_descriptor(self) -> StageUIDescriptor:
        """Return the descriptor with manual-draw and selectable-overlay support."""
        descriptor = super().get_ui_descriptor()
        descriptor.enable_roi_drawing = False
        descriptor.roi_mode = "identifier"
        descriptor.selectable_overlays = True
        descriptor.extra_buttons = [
            {"label": "Draw Manually", "action": "draw"},
        ]
        return descriptor

    # ------------------------------------------------------------------
    # Calibration UI hooks
    # ------------------------------------------------------------------

    def present(self, view: CalibrationView, ctx: CalibrationContext) -> None:
        """Run text-region detection and offer candidates as clickable overlays."""
        session = ctx.session
        if session is None or session.chip_crop is None:
            return
        view.set_preview_image(session.chip_crop)

        # Preserve a manually drawn ROI across re-runs (e.g. param edits).
        # An auto-picked ROI is dropped so fresh parameters produce fresh
        # candidate regions for the user to choose from.
        if session.identifier_roi is not None and session.identifier_bbox_is_manual:
            view.show_rect_overlay(session.identifier_roi, _COLOR_SELECTED, 2)
            return
        session.identifier_roi = None

        try:
            result = self.run(session.chip_crop, session)
        except Exception as exc:
            _log.exception("Text region detection raised during calibration.")
            view.show_error(f"Text region detection failed: {exc}")
            return
        if not result.ok or not isinstance(result.data, list):
            view.set_title("No text regions detected. Draw the region manually.")
            return

        session.detected_regions = result.data
        if ctx.debug_enabled:
            example_name = ctx.image_paths[ctx.image_idx].name
            write_debug_image(
                ctx.debug_dir / example_name,
                "3_text_regions.png",
                session.chip_crop,
            )
        if not session.detected_regions:
            return
        view.show_rects_overlay(session.detected_regions, _COLOR_ID_REG, selectable=True)

    def confirm_calibration(self, view: CalibrationView, ctx: CalibrationContext) -> bool:
        """Require that an identifier region has been selected or drawn."""
        session = ctx.session
        if session is None or session.identifier_roi is None:
            view.show_error("No region selected. Click a region or draw manually.")
            return False
        if session.chip_crop is not None:
            session.current_crop = crop_bbox(session.chip_crop, session.identifier_roi)
        return True

    def on_action(self, view: CalibrationView, ctx: CalibrationContext, action: str) -> None:
        """Handle the *Draw Manually* button by entering ROI-draw mode."""
        if action != "draw":
            return
        session = ctx.session
        if session is None:
            return
        session.identifier_roi = None
        session.identifier_bbox_is_manual = False
        view.clear_overlays()
        view.start_roi_selection("identifier")

    def on_roi_drawn(
        self,
        view: CalibrationView,
        ctx: CalibrationContext,
        mode: str,
        rect: BoundingBox,
    ) -> None:
        """Store the manually drawn rectangle as the identifier ROI."""
        if mode != "identifier":
            return
        session = ctx.session
        if session is None:
            return
        session.identifier_roi = rect
        session.identifier_bbox_is_manual = True
        view.stop_roi_selection()
        view.clear_overlays()
        view.show_rect_overlay(rect, _COLOR_SELECTED, 2)

    def on_scene_selection(
        self,
        view: CalibrationView,
        ctx: CalibrationContext,
        rect: BoundingBox,
    ) -> None:
        """Handle a click on one of the candidate overlay rectangles."""
        session = ctx.session
        if session is None:
            return
        session.identifier_roi = rect
        session.identifier_bbox_is_manual = False
        view.clear_overlays()
        view.show_rects_overlay(session.detected_regions, _COLOR_ID_REG, selectable=True)
        view.show_rect_overlay(rect, _COLOR_SELECTED, 2)
