"""Feature-Based Alignment — Pipeline A stage 2.

Matches the chip image to the calibration template via keypoints,
computes a homography, and warps the chip to canonical pose.

During **calibration**, this stage doesn't run alignment itself (there
is no target image to align against yet) — instead it extracts the
template keypoints and descriptors from the confirmed chip crop and
stores them on the session for batch alignment to use.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import cv2
import numpy as np
from numpy.typing import NDArray

from app.tools.scibit.core.debug import write_debug_image
from app.tools.scibit.core.operations import FeatureBasedAlignment
from app.tools.scibit.core.stage import Stage

if TYPE_CHECKING:
    from app.tools.scibit.core.calibration import (
        CalibrationContext,
        CalibrationView,
    )
    from app.tools.scibit.core.session import CalibrationSession

_log = logging.getLogger(__name__)


class FeatureAlignmentStage(Stage):
    """Compute homography to template and warp the chip."""

    @property
    def name(self) -> str:
        """Return the stage's pipeline identifier."""
        return "feature_based_alignment"

    @property
    def display_name(self) -> str:
        """Return the human-readable stage name."""
        return "Feature-Based Alignment"

    @property
    def required_operation(self) -> type | None:
        """Return :class:`FeatureBasedAlignment` — the operation this stage drives."""
        return FeatureBasedAlignment

    def get_default_operator_class(self) -> type | None:
        """Return :class:`OpenCVOperator` as the default alignment backend."""
        from app.tools.scibit.operators.opencv_operator import OpenCVOperator

        return OpenCVOperator

    def get_default_parameters(self) -> dict[str, Any]:
        """Return the default detector, feature-count, and matching parameters."""
        return {
            "detector": "ORB",
            "max_features": 500,
            "match_ratio": 0.75,
            "min_matches": 10,
        }

    def invoke(
        self,
        operator: FeatureBasedAlignment,
        image: NDArray[np.uint8],
        session: CalibrationSession,
        **kwargs: Any,
    ) -> Any:
        """Align *image* against the session's template via *operator*."""
        return operator.align_feature(
            image,
            session.template_image,
            session.template_keypoints,
            session.template_descriptors,
            self._parameters,
        )

    # ------------------------------------------------------------------
    # Calibration UI hooks
    # ------------------------------------------------------------------

    def present(self, view: CalibrationView, ctx: CalibrationContext) -> None:
        """Extract template keypoints from the chip crop and overlay them."""
        session = ctx.session
        if session is None or session.chip_crop is None:
            return
        view.set_preview_image(session.chip_crop)

        if self._pool is None or self._assigned_operator_class is None:
            view.show_error("Feature alignment operator not configured.")
            return

        operator = self._pool.get_operator(self._assigned_operator_class)
        try:
            kp, desc = operator.detect_and_compute(session.chip_crop, self._parameters)
        except Exception as exc:
            _log.exception("Feature extraction raised during calibration.")
            view.show_error(f"Feature extraction failed: {exc}")
            return

        if desc is None or len(kp) < 4:
            view.show_error(
                f"Insufficient keypoints detected ({len(kp)} found, need ≥ 4).\n"
                "Try a different image or adjust alignment parameters."
            )
            return

        session.template_image = session.chip_crop
        session.template_keypoints = kp
        session.template_descriptors = desc

        kp_img = cv2.drawKeypoints(
            session.chip_crop,
            kp,
            None,
            color=(0, 200, 0),
            flags=cv2.DRAW_MATCHES_FLAGS_DRAW_RICH_KEYPOINTS,
        )
        if kp_img is not None:
            view.set_preview_image(cv2.cvtColor(kp_img, cv2.COLOR_BGR2RGB))

        if ctx.debug_enabled:
            example_name = ctx.image_paths[ctx.image_idx].name
            write_debug_image(
                ctx.debug_dir / example_name,
                "2_template_keypoints.png",
                kp_img if kp_img is not None else session.chip_crop,
            )

        view.set_title(f"Template ready: {len(kp)} keypoints extracted.")

    def confirm_calibration(self, view: CalibrationView, ctx: CalibrationContext) -> bool:
        """Require that template keypoints have been extracted before proceeding."""
        session = ctx.session
        if session is None or session.template_keypoints is None or not session.template_keypoints:
            view.show_error("Feature extraction has not completed yet.")
            return False
        return True
