"""Validation — final stage of every pipeline.

Built-in stage (no operator). The user reviews the OCR result produced
by the previous stage and clicks **Finish** to lock in calibration, or
**Previous** to go back and adjust.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import numpy as np
from numpy.typing import NDArray

from app.tools.scibit.core.stage import Stage, StageUIDescriptor

if TYPE_CHECKING:
    from app.tools.scibit.core.calibration import (
        CalibrationContext,
        CalibrationView,
    )
    from app.tools.scibit.core.session import CalibrationSession

_log = logging.getLogger(__name__)


class ValidationStage(Stage):
    """User-confirmation step at the end of calibration."""

    @property
    def name(self) -> str:
        """Return the stage's pipeline identifier."""
        return "validation"

    @property
    def display_name(self) -> str:
        """Return the human-readable stage name."""
        return "Validation"

    @property
    def required_operation(self) -> type | None:
        """Return ``None`` — this is a built-in stage with no operator."""
        return None

    def get_default_parameters(self) -> dict[str, Any]:
        """Return an empty parameter dict — this stage has no settings."""
        return {}

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
        """Return the descriptor that renders the final ``Finish`` confirmation."""
        return StageUIDescriptor(
            stage_name=self.name,
            display_name=self.display_name,
            confirm_label="Finish",
        )

    # ------------------------------------------------------------------
    # Calibration UI hooks
    # ------------------------------------------------------------------

    def present(self, view: CalibrationView, ctx: CalibrationContext) -> None:
        """No dynamic content — the user just confirms or goes back."""
        view.set_title(
            "Calibration complete — click Finish to start batch processing, or Previous to adjust."
        )
