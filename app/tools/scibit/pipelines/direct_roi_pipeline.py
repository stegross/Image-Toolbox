"""Pipeline C — Direct ROI (spec Section 4.3).

The simplest pipeline variant.  Assumes images are already roughly
aligned (fixed-camera setup) so no feature or contour alignment is
needed.  The user draws the identifier ROI once during calibration; all
batch images are cropped at that position (±tolerance margin), passed
through the optional ROI preprocessing chain, and fed to the assigned
:class:`~app.tools.scibit.core.operations.TextRecognition` operator.

Stage sequence (5 stages total):

+---+-----------------------------+--------------------+
| # | Name                        | Required operation |
+===+=============================+====================+
| 0 | calibration_setup           | *(built-in)*       |
+---+-----------------------------+--------------------+
| 1 | identifier_region_selection | *(built-in)*       |
+---+-----------------------------+--------------------+
| 2 | roi_preprocess              | ROIPreprocessing   |
+---+-----------------------------+--------------------+
| 3 | text_recognition            | TextRecognition    |
+---+-----------------------------+--------------------+
| 4 | validation                  | *(built-in)*       |
+---+-----------------------------+--------------------+

JSON pipeline identifier: ``"direct_roi"``
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Final

from app.tools.scibit.core.debug import write_debug_image
from app.tools.scibit.core.helpers import crop_roi
from app.tools.scibit.core.pipeline import (
    BatchContext,
    Pipeline,
    _classify_outcome,
    _preprocess_image,
)
from app.tools.scibit.core.stage import Stage
from app.tools.scibit.core.types import BatchResult, DebugExportMode, ProcessingOutcome

if TYPE_CHECKING:
    from PySide6.QtCore import QObject

    from app.tools.scibit.config.config import PipelineOptions
    from app.tools.scibit.config.preset import IdentifierPatternPresetRegistry
    from app.tools.scibit.core.session import CalibrationSession

_log = logging.getLogger(__name__)


class DirectROIPipeline(Pipeline):
    """Concrete pipeline for fixed-camera / pre-aligned images (spec Section 4.3).

    Skips chip detection and alignment entirely.  The user manually marks
    the identifier ROI once during calibration; batch processing crops
    that region (expanded by ``roi_tolerance_margin`` pixels) from every
    image and recognises it with the assigned :class:`TextRecognition`
    operator.

    Parameters
    ----------
    options : PipelineOptions
        Pipeline-level configuration (preset, rotation, threshold, etc.).
    preset_registry : IdentifierPatternPresetRegistry
        Registry used to resolve the active identifier pattern preset.
    parent : QObject | None
        Optional Qt parent.
    """

    PIPELINE_ID: Final = "direct_roi"

    def __init__(
        self,
        options: PipelineOptions,
        preset_registry: IdentifierPatternPresetRegistry,
        parent: QObject | None = None,
    ) -> None:
        # Must be set before super().__init__() because the base class
        # calls get_stages() during __init__ via _init_stages().
        self._direct_roi_stages: list[Stage] | None = None
        super().__init__(options, preset_registry, parent)

    # ------------------------------------------------------------------
    # Abstract interface implementation
    # ------------------------------------------------------------------

    def get_stages(self) -> list[Stage]:
        """Return the five-stage sequence for Pipeline C.

        The list is created once and cached; every call returns the same
        objects so the pool's ``set_pool()`` injections remain valid.

        Returns
        -------
        list[Stage]
            Ordered stages: Calibration Setup, Identifier Region Selection,
            ROI Preprocess, Text Recognition, Validation.
        """
        if self._direct_roi_stages is None:
            from app.tools.scibit.stages import (
                CalibrationSetupStage,
                IdentifierRegionSelectionStage,
                RoiPreprocessStage,
                TextRecognitionStage,
                ValidationStage,
            )

            self._direct_roi_stages = [
                CalibrationSetupStage(),
                IdentifierRegionSelectionStage(),
                RoiPreprocessStage(),
                TextRecognitionStage(),
                ValidationStage(),
            ]
        return self._direct_roi_stages

    # ------------------------------------------------------------------
    # Batch processing override
    # ------------------------------------------------------------------

    def _process_single_image(
        self,
        image_path: Path,
        session: CalibrationSession,
        ctx: BatchContext,
    ) -> BatchResult:
        """Load, crop to calibrated ROI, run OCR, and return a BatchResult.

        Inserts the ROI crop step between global preprocessing and the
        TextRecognition stage; handles debug image export for the crop.
        """
        filename = image_path.name

        try:
            if session.identifier_roi is None:
                raise RuntimeError(
                    "No identifier ROI set in session — calibration must "
                    "complete before batch processing starts."
                )

            # 1. Load and apply global preprocessing (diagonal canvas, matching calibration).
            image = _preprocess_image(
                image_path,
                session.rotation_degrees,
                session.invert_colors,
                session.downscale_factor,
            )

            # 2. Crop to calibrated ROI, expanded by tolerance margin.
            crop = crop_roi(image, session.identifier_roi, session.roi_tolerance_margin)

            debug = (
                self._options.debug_export_mode == DebugExportMode.ALL and ctx.debug_dir is not None
            )
            if debug:
                write_debug_image(
                    ctx.debug_dir / filename,
                    "1_identifier_crop.png",
                    crop,
                )

            # 3. ROI preprocessing chain (CLAHE, adaptive threshold, …).
            preprocess_stage = self.get_stage("roi_preprocess")
            if preprocess_stage is not None:
                preprocess_result = preprocess_stage.run(crop, session)
                if not preprocess_result.ok:
                    raise RuntimeError(f"ROI preprocessing failed: {preprocess_result.error}")
                if preprocess_result.data is not None:
                    crop = preprocess_result.data
                if debug:
                    write_debug_image(
                        ctx.debug_dir / filename,
                        "2_roi_preprocessed.png",
                        crop,
                    )

            # 4. Run the TextRecognition stage on the (preprocessed) crop.
            ocr_stage = self.get_stage("text_recognition")
            if ocr_stage is None:
                raise RuntimeError("text_recognition stage not found.")
            ocr_result = ocr_stage.run(crop, session, charset_hint=ctx.charset_hint)
            if not ocr_result.ok:
                raise RuntimeError(f"OCR failed: {ocr_result.error}")
            if isinstance(ocr_result.data, tuple) and len(ocr_result.data) == 2:
                text, confidence = ocr_result.data
            else:
                text, confidence = "", 0.0

            # 5. Classify outcome and build BatchResult.
            outcome = _classify_outcome(
                text,
                confidence,
                self._options.confidence_threshold_percent,
                ctx.regex,
            )
            return BatchResult(
                filename=filename,
                identifier_text=text,
                confidence=confidence,
                outcome=outcome,
            )

        except Exception as exc:
            _log.exception("Error processing image '%s'.", filename)
            return BatchResult(
                filename=filename,
                identifier_text="",
                confidence=0.0,
                outcome=ProcessingOutcome.PROCESSING_ERROR,
                error_detail=str(exc),
            )
