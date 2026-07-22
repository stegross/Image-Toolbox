"""Chip Region Detection — Pipeline A stage 1.

Locates the chip's axis-aligned bounding box on the rotated image.
Default operator is :class:`OpenCVOperator` (adaptive threshold + largest
contour). Used by Pipeline A (Feature-Based Alignment).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import numpy as np
from numpy.typing import NDArray

from app.tools.scibit.core.debug import write_debug_image
from app.tools.scibit.core.helpers import crop_bbox
from app.tools.scibit.core.operations import ChipRegionDetection
from app.tools.scibit.core.stage import Stage

if TYPE_CHECKING:
    from app.tools.scibit.core.calibration import (
        CalibrationContext,
        CalibrationView,
    )
    from app.tools.scibit.core.session import CalibrationSession

_log = logging.getLogger(__name__)

_COLOR_CHIP = (0, 200, 0)


class ChipDetectionStage(Stage):
    """Detect chip region as an axis-aligned bounding box."""

    @property
    def name(self) -> str:
        """Return the stage's pipeline identifier."""
        return "chip_region_detection"

    @property
    def display_name(self) -> str:
        """Return the human-readable stage name."""
        return "Chip Region Detection"

    @property
    def required_operation(self) -> type | None:
        """Return :class:`ChipRegionDetection` — the operation this stage drives."""
        return ChipRegionDetection

    def get_default_operator_class(self) -> type | None:
        """Return :class:`OpenCVOperator` as the default chip-detection backend."""
        from app.tools.scibit.operators.opencv_operator import OpenCVOperator

        return OpenCVOperator

    def get_default_parameters(self) -> dict[str, Any]:
        """Return the default adaptive-threshold and morphology parameters."""
        return {
            "threshold_block_size": 11,
            "threshold_c": 2,
            "morph_kernel_size": 5,
        }

    def invoke(
        self,
        operator: ChipRegionDetection,
        image: NDArray[np.uint8],
        session: CalibrationSession,
        **kwargs: Any,
    ) -> Any:
        """Run *operator* with the stage's parameters to detect the chip region."""
        return operator.detect_chip_region(image, self._parameters)

    # ------------------------------------------------------------------
    # Calibration UI hooks
    # ------------------------------------------------------------------

    def present(self, view: CalibrationView, ctx: CalibrationContext) -> None:
        """Run chip detection live and overlay the resulting rectangle."""
        session = ctx.session
        if session is None:
            return
        view.set_preview_image(session.example_image)
        try:
            result = self.run(session.example_image, session)
        except Exception as exc:
            _log.exception("Chip detection raised during calibration.")
            view.show_error(f"Chip detection failed: {exc}")
            return
        if not result.ok:
            view.show_error(f"Chip detection error: {result.error}")
            return
        session.chip_region = result.data
        if ctx.debug_enabled:
            example_name = ctx.image_paths[ctx.image_idx].name
            write_debug_image(
                ctx.debug_dir / example_name,
                "1_chip_region_detection.png",
                session.example_image,
            )
        view.show_rect_overlay(session.chip_region, _COLOR_CHIP, 2)

    def confirm_calibration(self, view: CalibrationView, ctx: CalibrationContext) -> bool:
        """Crop the chip region from the example image into the session."""
        session = ctx.session
        if session is None or session.chip_region is None:
            view.show_error("No chip region available — adjust detection parameters and try again.")
            return False
        session.chip_crop = crop_bbox(session.example_image, session.chip_region)
        return True
