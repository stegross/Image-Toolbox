"""Pipeline A — Feature-Based Alignment (spec Section 4.1).

Seven stages:

+---+-----------------------------+-----------------------+
| # | Name                        | Required operation    |
+===+=============================+=======================+
| 0 | calibration_setup           | *(built-in)*          |
+---+-----------------------------+-----------------------+
| 1 | chip_region_detection       | ChipRegionDetection   |
+---+-----------------------------+-----------------------+
| 2 | feature_based_alignment     | FeatureBasedAlignment |
+---+-----------------------------+-----------------------+
| 3 | identifier_region_detection | TextRegionDetection   |
+---+-----------------------------+-----------------------+
| 4 | roi_preprocess              | ROIPreprocessing      |
+---+-----------------------------+-----------------------+
| 5 | text_recognition            | TextRecognition       |
+---+-----------------------------+-----------------------+
| 6 | validation                  | *(built-in)*          |
+---+-----------------------------+-----------------------+

JSON pipeline identifier: ``"feature_based_alignment"``
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Final

from app.tools.scibit.core.debug import write_debug_image
from app.tools.scibit.core.helpers import crop_bbox
from app.tools.scibit.core.pipeline import (
    BatchContext,
    Pipeline,
    _classify_outcome,
    _preprocess_image,
)
from app.tools.scibit.core.stage import Stage
from app.tools.scibit.core.types import (
    BatchResult,
    BoundingBox,
    DebugExportMode,
    ProcessingOutcome,
)

if TYPE_CHECKING:
    from PySide6.QtCore import QObject

    from app.tools.scibit.config.config import PipelineOptions
    from app.tools.scibit.config.preset import IdentifierPatternPresetRegistry
    from app.tools.scibit.core.session import CalibrationSession

_log = logging.getLogger(__name__)


class FeatureBasedAlignmentPipeline(Pipeline):
    """Pipeline A: Feature-Based Alignment (spec Section 4.1).

    Template keypoints extracted during calibration are matched against each
    batch image to compute a homography and warp the chip to a canonical pose.
    The identifier crop is then extracted from the warped image.

    Parameters
    ----------
    options : PipelineOptions
        Pipeline-level configuration.
    preset_registry : IdentifierPatternPresetRegistry
        Registry used to resolve the active identifier pattern preset.
    parent : QObject | None
        Optional Qt parent.
    """

    PIPELINE_ID: Final = "feature_based_alignment"

    def __init__(
        self,
        options: PipelineOptions,
        preset_registry: IdentifierPatternPresetRegistry,
        parent: QObject | None = None,
    ) -> None:
        self._fa_stages: list[Stage] | None = None
        super().__init__(options, preset_registry, parent)

    # ------------------------------------------------------------------
    # Abstract interface implementation
    # ------------------------------------------------------------------

    def get_stages(self) -> list[Stage]:
        """Return the seven stages of Pipeline A in execution order."""
        if self._fa_stages is None:
            from app.tools.scibit.stages import (
                CalibrationSetupStage,
                ChipDetectionStage,
                FeatureAlignmentStage,
                IdentifierRegionDetectionStage,
                RoiPreprocessStage,
                TextRecognitionStage,
                ValidationStage,
            )

            self._fa_stages = [
                CalibrationSetupStage(),
                ChipDetectionStage(),
                FeatureAlignmentStage(),
                IdentifierRegionDetectionStage(),
                RoiPreprocessStage(),
                TextRecognitionStage(),
                ValidationStage(),
            ]
        return self._fa_stages

    # ------------------------------------------------------------------
    # Batch processing
    # ------------------------------------------------------------------

    def _process_single_image(
        self,
        image_path: Path,
        session: CalibrationSession,
        ctx: BatchContext,
    ) -> BatchResult:
        filename = image_path.name
        debug = self._options.debug_export_mode == DebugExportMode.ALL and ctx.debug_dir is not None

        try:
            if not session.template_keypoints or session.template_descriptors is None:
                raise RuntimeError("Template features not set — calibration incomplete.")
            if session.identifier_roi is None:
                raise RuntimeError("Identifier ROI not set — calibration incomplete.")

            # 1. Load + global preprocessing (diagonal canvas, matching calibration).
            image = _preprocess_image(
                image_path,
                session.rotation_degrees,
                session.invert_colors,
                session.downscale_factor,
            )

            # 2. Chip region detection.
            chip_stage = self.get_stage("chip_region_detection")
            if chip_stage is None:
                raise RuntimeError("chip_region_detection stage not found.")
            chip_result = chip_stage.run(image, session)
            if not chip_result.ok:
                raise RuntimeError(f"Chip detection failed: {chip_result.error}")
            chip_bbox: BoundingBox = chip_result.data
            chip_crop = crop_bbox(image, chip_bbox)

            if debug and ctx.debug_dir:
                write_debug_image(ctx.debug_dir / filename, "1_chip_region.png", chip_crop)

            # 3. Feature-based alignment — warp chip to template pose.
            align_stage = self.get_stage("feature_based_alignment")
            if align_stage is None:
                raise RuntimeError("feature_based_alignment stage not found.")
            align_result = align_stage.run(chip_crop, session)
            if not align_result.ok:
                raise RuntimeError(f"Alignment failed: {align_result.error}")
            _, warped = align_result.data

            if debug and ctx.debug_dir:
                write_debug_image(ctx.debug_dir / filename, "2_aligned.png", warped)

            # 4. Crop identifier ROI from warped image.
            id_crop = crop_bbox(warped, session.identifier_roi)

            if debug and ctx.debug_dir:
                write_debug_image(ctx.debug_dir / filename, "3_identifier_crop.png", id_crop)

            # 5. ROI preprocessing chain (CLAHE, adaptive threshold, …).
            preprocess_stage = self.get_stage("roi_preprocess")
            if preprocess_stage is not None:
                preprocess_result = preprocess_stage.run(id_crop, session)
                if not preprocess_result.ok:
                    raise RuntimeError(f"ROI preprocessing failed: {preprocess_result.error}")
                if preprocess_result.data is not None:
                    id_crop = preprocess_result.data
                if debug and ctx.debug_dir:
                    write_debug_image(
                        ctx.debug_dir / filename,
                        "4_roi_preprocessed.png",
                        id_crop,
                    )

            # 6. Text recognition.
            ocr_stage = self.get_stage("text_recognition")
            if ocr_stage is None:
                raise RuntimeError("text_recognition stage not found.")
            ocr_result = ocr_stage.run(id_crop, session, charset_hint=ctx.charset_hint)
            if not ocr_result.ok:
                raise RuntimeError(f"OCR failed: {ocr_result.error}")
            if isinstance(ocr_result.data, tuple) and len(ocr_result.data) == 2:
                text, confidence = ocr_result.data
            else:
                text, confidence = "", 0.0

            # 7. Classify.
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
            _log.exception("Error processing '%s'.", filename)
            return BatchResult(
                filename=filename,
                identifier_text="",
                confidence=0.0,
                outcome=ProcessingOutcome.PROCESSING_ERROR,
                error_detail=str(exc),
            )
