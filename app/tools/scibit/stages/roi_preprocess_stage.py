"""ROI Preprocessing — runs between identifier crop and text recognition.

Applies a strict-order chain of optional image enhancement functions
(CLAHE, adaptive thresholding, …) to the cropped identifier ROI. The
parameter schema is supplied by the assigned operator so adding a new
preprocessing function is an operator-side change only.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import numpy as np
from numpy.typing import NDArray

from app.tools.scibit.core.debug import write_debug_image
from app.tools.scibit.core.operations import ROIPreprocessing
from app.tools.scibit.core.stage import Stage

if TYPE_CHECKING:
    from app.tools.scibit.core.calibration import (
        CalibrationContext,
        CalibrationView,
    )
    from app.tools.scibit.core.session import CalibrationSession

_log = logging.getLogger(__name__)


class RoiPreprocessStage(Stage):
    """Apply enabled preprocessing functions to the identifier ROI crop."""

    @property
    def name(self) -> str:
        """Return the stage's pipeline identifier."""
        return "roi_preprocess"

    @property
    def display_name(self) -> str:
        """Return the human-readable stage name."""
        return "ROI Preprocessing"

    @property
    def required_operation(self) -> type | None:
        """Return :class:`ROIPreprocessing` — the operation this stage drives."""
        return ROIPreprocessing

    def get_default_operator_class(self) -> type | None:
        """Return :class:`OpenCVOperator` as the default preprocessing backend."""
        from app.tools.scibit.operators.opencv_operator import OpenCVOperator

        return OpenCVOperator

    def get_default_parameters(self) -> dict[str, Any]:
        """Return the default CLAHE and adaptive-threshold parameters (all disabled)."""
        return {
            "clahe_enabled": False,
            "clahe_clip_limit": 2.0,
            "clahe_tile_grid_size": 8,
            "adaptive_threshold_enabled": False,
            "adaptive_threshold_method": "GAUSSIAN",
            "adaptive_threshold_block_size": 11,
            "adaptive_threshold_c": 2,
            "adaptive_threshold_invert": False,
        }

    def invoke(
        self,
        operator: ROIPreprocessing,
        image: NDArray[np.uint8],
        session: CalibrationSession,
        **kwargs: Any,
    ) -> Any:
        """Run the preprocessing chain on *image* via *operator*."""
        return operator.preprocess_roi(image, self._parameters)

    # ------------------------------------------------------------------
    # Calibration UI hooks
    # ------------------------------------------------------------------

    def present(self, view: CalibrationView, ctx: CalibrationContext) -> None:
        """Run the preprocessing chain on the current crop and display the result."""
        session = ctx.session
        if session is None or session.current_crop is None:
            return
        try:
            result = self.run(session.current_crop, session)
        except Exception as exc:
            _log.exception("ROI preprocessing raised during calibration.")
            view.show_error(f"ROI preprocessing failed: {exc}")
            return
        if not result.ok:
            view.show_error(f"ROI preprocessing error: {result.error}")
            return
        session.preprocessed_crop = result.data if result.data is not None else session.current_crop
        if ctx.debug_enabled:
            example_name = ctx.image_paths[ctx.image_idx].name
            write_debug_image(
                ctx.debug_dir / example_name,
                "5_roi_preprocessed.png",
                session.preprocessed_crop,
            )
        view.set_preview_image(session.preprocessed_crop)
