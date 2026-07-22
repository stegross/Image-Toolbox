"""Identifier Region Selection — Pipeline C stage 1.

Built-in stage (no operator). The user draws the identifier ROI on the
preprocessed example image during calibration; batch processing crops
the same rectangle (expanded by ``roi_tolerance_margin``) from each
image. Used by Pipeline C (Direct ROI).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import numpy as np
from numpy.typing import NDArray

from app.tools.scibit.core.helpers import crop_roi
from app.tools.scibit.core.stage import ParamSpec, Stage, StageUIDescriptor
from app.tools.scibit.core.types import BoundingBox

if TYPE_CHECKING:
    from app.tools.scibit.core.calibration import (
        CalibrationContext,
        CalibrationView,
    )
    from app.tools.scibit.core.session import CalibrationSession

_log = logging.getLogger(__name__)

_COLOR_ROI = (0, 200, 0)  # green  — calibrated ROI
_COLOR_MARGIN = (200, 130, 0)  # orange — tolerance-expanded area


class IdentifierRegionSelectionStage(Stage):
    """Manual identifier ROI placement with a tolerance margin parameter."""

    @property
    def name(self) -> str:
        """Return the stage's pipeline identifier."""
        return "identifier_region_selection"

    @property
    def display_name(self) -> str:
        """Return the human-readable stage name."""
        return "Identifier Region Selection"

    @property
    def required_operation(self) -> type | None:
        """Return ``None`` — this is a built-in stage with no operator."""
        return None

    def get_default_parameters(self) -> dict[str, Any]:
        """Return the default tolerance margin used when cropping the ROI."""
        return {"roi_tolerance_margin": 10}

    def invoke(
        self,
        operator: object,
        image: NDArray[np.uint8],
        session: CalibrationSession,
        **kwargs: Any,
    ) -> Any:
        """Built-in stage — never invoked through an operator."""
        return None

    def get_ui_descriptor(self) -> StageUIDescriptor:
        """Return the descriptor that enables ROI drawing for this stage."""
        return StageUIDescriptor(
            stage_name=self.name,
            display_name=self.display_name,
            enable_roi_drawing=True,
            roi_mode="identifier",
            extra_buttons=[
                {"label": "Draw Manually", "action": "draw"},
            ],
            parameters=[
                ParamSpec(
                    key="roi_tolerance_margin",
                    label="Tolerance Margin",
                    type="int",
                    default=10,
                    min=0,
                    max=200,
                    step=1,
                    suffix=" px",
                    tooltip="Pixels added on each side of the ROI during batch.",
                ),
            ],
            parameter_values=dict(self._parameters),
        )

    # ------------------------------------------------------------------
    # Calibration UI hooks
    # ------------------------------------------------------------------

    def present(self, view: CalibrationView, ctx: CalibrationContext) -> None:
        """Show the example image and start ROI drawing or redraw the existing ROI."""
        session = ctx.session
        if session is None:
            return
        view.set_preview_image(session.example_image)
        if session.identifier_roi is None:
            view.start_roi_selection("identifier")
        else:
            view.stop_roi_selection()
            self._draw_roi_with_margin(view, ctx)

    def confirm_calibration(self, view: CalibrationView, ctx: CalibrationContext) -> bool:
        """Persist the ROI and crop the identifier region for downstream stages."""
        session = ctx.session
        if session is None or session.identifier_roi is None:
            view.show_error("Please draw the identifier region first.")
            return False
        margin = int(self._parameters.get("roi_tolerance_margin", 10))
        session.roi_tolerance_margin = margin
        session.current_crop = crop_roi(
            session.example_image,
            session.identifier_roi,
            margin,
        )
        return True

    def on_action(self, view: CalibrationView, ctx: CalibrationContext, action: str) -> None:
        """Handle the *Draw Manually* button by clearing the ROI and restarting drawing."""
        if action != "draw":
            return
        session = ctx.session
        if session is None:
            return
        session.identifier_roi = None
        view.clear_overlays()
        view.start_roi_selection("identifier")

    def on_roi_drawn(
        self,
        view: CalibrationView,
        ctx: CalibrationContext,
        mode: str,
        rect: BoundingBox,
    ) -> None:
        """Store the drawn rectangle as the identifier ROI and redraw overlays."""
        if mode != "identifier":
            return
        session = ctx.session
        if session is None:
            return
        session.identifier_roi = rect
        view.stop_roi_selection()
        self._draw_roi_with_margin(view, ctx)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _draw_roi_with_margin(self, view: CalibrationView, ctx: CalibrationContext) -> None:
        """Draw the staged ROI (green) plus its tolerance-expanded area (orange)."""
        session = ctx.session
        if session is None or session.identifier_roi is None:
            return
        margin = int(self._parameters.get("roi_tolerance_margin", 10))
        x, y, w, h = session.identifier_roi
        img_h, img_w = session.example_image.shape[:2]
        x1 = max(0, x - margin)
        y1 = max(0, y - margin)
        x2 = min(img_w, x + w + margin)
        y2 = min(img_h, y + h + margin)
        expanded = (x1, y1, x2 - x1, y2 - y1)
        view.clear_overlays()
        view.show_rect_overlay(session.identifier_roi, _COLOR_ROI, 2)
        view.show_rect_overlay(expanded, _COLOR_MARGIN, 2)
