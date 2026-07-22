"""Calibration Setup — first stage of every pipeline.

Built-in stage (no operator). Hosts the live Qt-level preview transforms
applied to the example image: rotation, colour inversion, and an
optional downscale factor.  On confirm, builds the pipeline-specific
:class:`CalibrationSession` from the preprocessed example image and
sets up the calibration debug directory.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

import numpy as np
from numpy.typing import NDArray

from app.tools.scibit.core.pipeline import _preprocess_image
from app.tools.scibit.core.session import CalibrationSession
from app.tools.scibit.core.stage import ParamSpec, Stage, StageUIDescriptor

if TYPE_CHECKING:
    from app.tools.scibit.core.calibration import (
        CalibrationContext,
        CalibrationView,
    )

_log = logging.getLogger(__name__)


class CalibrationSetupStage(Stage):
    """Pre-processing transforms applied before any operator runs.

    ``downscale_factor`` is stored internally as a percent (10–100) so
    the UI form and the in-memory value agree.  Conversion to the 0.0–1.0
    fraction expected by the session and batch preprocessing happens in
    :meth:`confirm_calibration` at the boundary where a fraction is
    needed.
    """

    @property
    def name(self) -> str:
        """Return the stage's pipeline identifier."""
        return "calibration_setup"

    @property
    def display_name(self) -> str:
        """Return the human-readable stage name."""
        return "Calibration Setup"

    @property
    def required_operation(self) -> type | None:
        """Return ``None`` — this is a built-in stage with no operator."""
        return None

    def get_default_parameters(self) -> dict[str, Any]:
        """Return the default rotation, invert, and downscale values."""
        return {
            "rotation_degrees": 0.0,
            "invert_colors": False,
            "downscale_factor": 100,
        }

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
        """Return the descriptor that renders the rotation/invert/downscale form."""
        return StageUIDescriptor(
            stage_name=self.name,
            display_name=self.display_name,
            has_previous=False,
            extra_buttons=[{"label": "Skip Image", "action": "skip"}],
            parameters=[
                ParamSpec(
                    key="rotation_degrees",
                    label="Rotation",
                    type="float",
                    default=0.0,
                    min=-180.0,
                    max=180.0,
                    step=1.0,
                    suffix="°",
                ),
                ParamSpec(
                    key="invert_colors",
                    label="Invert Colors",
                    type="bool",
                    default=False,
                ),
                ParamSpec(
                    key="downscale_factor",
                    label="Downscale",
                    type="int",
                    default=100,
                    min=10,
                    max=100,
                    step=5,
                    suffix="%",
                    tooltip="Downscale percentage applied before processing.",
                ),
            ],
            parameter_values=dict(self._parameters),
        )

    # ------------------------------------------------------------------
    # Calibration UI hooks
    # ------------------------------------------------------------------

    def present(self, view: CalibrationView, ctx: CalibrationContext) -> None:
        """Display the example image for the current candidate index.

        The widget's preview transforms (rotation, invert, downscale) are
        driven by the descriptor's parameter values, so no per-call work
        is needed here beyond loading the file.
        """
        if ctx.image_idx >= len(ctx.image_paths):
            view.show_error("No suitable images remain.\nCannot proceed with calibration.")
            return
        view.load_image(ctx.image_paths[ctx.image_idx])

    def confirm_calibration(self, view: CalibrationView, ctx: CalibrationContext) -> bool:
        """Build the :class:`CalibrationSession` from the example image.

        Loads + preprocesses the image, instantiates the session, and sets
        up the calibration debug directory when debug export is enabled.
        """
        path = ctx.image_paths[ctx.image_idx]
        rotation = float(self._parameters.get("rotation_degrees", 0.0))
        invert = bool(self._parameters.get("invert_colors", False))
        downscale_pct = int(self._parameters.get("downscale_factor", 100))
        downscale_factor = max(10, min(100, downscale_pct)) / 100.0
        try:
            image = _preprocess_image(path, rotation, invert, downscale_factor)
        except OSError as exc:
            view.show_error(f"Could not load image: {exc}")
            return False
        ctx.session = CalibrationSession(
            example_image=image,
            rotation_degrees=rotation,
            invert_colors=invert,
            downscale_factor=downscale_factor,
        )
        if ctx.options.debug_export_mode.value in ("calibration", "all"):
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            ctx.debug_dir = path.parent / f"_debug_{timestamp}"
        return True

    def on_action(self, view: CalibrationView, ctx: CalibrationContext, action: str) -> None:
        """``"skip"`` advances to the next candidate image and re-presents."""
        if action != "skip":
            return
        ctx.image_idx += 1
        self.present(view, ctx)
