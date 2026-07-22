"""Text Recognition — final OCR stage of every pipeline.

Runs an OCR engine on the identifier crop and returns
``(recognised_text, confidence_0_to_100)``. The optional ``charset_hint``
constrains predictions in supported frameworks (Tesseract, PaddleOCR).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import numpy as np
from numpy.typing import NDArray

from app.tools.scibit.core.debug import write_debug_image
from app.tools.scibit.core.operations import TextRecognition
from app.tools.scibit.core.stage import Stage, StageUIDescriptor

if TYPE_CHECKING:
    from app.tools.scibit.core.calibration import (
        CalibrationContext,
        CalibrationView,
    )
    from app.tools.scibit.core.session import CalibrationSession

_log = logging.getLogger(__name__)


class TextRecognitionStage(Stage):
    """Recognise text from the identifier crop."""

    @property
    def name(self) -> str:
        """Return the stage's pipeline identifier."""
        return "text_recognition"

    @property
    def display_name(self) -> str:
        """Return the human-readable stage name."""
        return "Text Recognition"

    @property
    def required_operation(self) -> type | None:
        """Return :class:`TextRecognition` — the operation this stage drives."""
        return TextRecognition

    def get_default_operator_class(self) -> type | None:
        """Return :class:`TesseractOperator` as the default OCR backend."""
        from app.tools.scibit.operators.tesseract_operator import TesseractOperator

        return TesseractOperator

    def get_default_parameters(self) -> dict[str, Any]:
        """Return an empty parameter dict — operator defaults apply."""
        return {}

    def invoke(
        self,
        operator: TextRecognition,
        image: NDArray[np.uint8],
        session: CalibrationSession,
        *,
        charset_hint: set[str] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Run OCR on *image* via *operator*, optionally constrained by *charset_hint*."""
        return operator.recognise_text(image, self._parameters, charset_hint)

    def get_ui_descriptor(self) -> StageUIDescriptor:
        """Return the descriptor that enables the text-result display."""
        descriptor = super().get_ui_descriptor()
        descriptor.shows_text_result = True
        return descriptor

    # ------------------------------------------------------------------
    # Calibration UI hooks
    # ------------------------------------------------------------------

    def present(self, view: CalibrationView, ctx: CalibrationContext) -> None:
        """Run OCR on the (preprocessed) crop and display the recognised text."""
        session = ctx.session
        if session is None or session.current_crop is None:
            return
        crop_for_ocr = (
            session.preprocessed_crop
            if session.preprocessed_crop is not None
            else session.current_crop
        )
        if ctx.debug_enabled:
            example_name = ctx.image_paths[ctx.image_idx].name
            write_debug_image(
                ctx.debug_dir / example_name,
                "6_text_recognition_crop.png",
                crop_for_ocr,
            )
        view.set_preview_image(crop_for_ocr)

        charset_hint = self._derive_charset_hint(ctx)
        try:
            result = self.run(crop_for_ocr, session, charset_hint=charset_hint)
        except Exception as exc:
            _log.exception("OCR stage raised during calibration.")
            view.show_error(f"OCR failed: {exc}")
            return
        text, confidence = "", 0.0
        if result.ok and isinstance(result.data, tuple) and len(result.data) == 2:
            text, confidence = result.data
        view.show_text_result(text, confidence)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _derive_charset_hint(self, ctx: CalibrationContext) -> set[str] | None:
        """Compute the OCR charset hint from the active identifier preset."""
        from app.tools.scibit.core.pipeline import _derive_charset_hint

        preset = ctx.preset_registry.get_preset(
            ctx.options.identifier_pattern_preset,
        )
        return _derive_charset_hint(preset.regex)
