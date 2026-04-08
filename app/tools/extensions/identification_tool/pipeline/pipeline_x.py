"""Pipeline X: <Short description of what makes this pipeline unique>.

Replace all occurrences of "X" / "PipelineX" with your pipeline number/name.

Checklist for adding a new pipeline
-------------------------------------
1. Implement this file (pipeline and batch worker).
2. Add a PipelineXCalibrationController to ui/calibration_controller.py.
3. Register the pipeline in tool.py (_start method, pipeline_index branch).
4. Add a human-readable entry to the pipeline_combo in tool.ui.
That is all — CalibrationWidget needs no changes.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QRectF, QRunnable, QThreadPool

from app.tools.extensions.identification_tool.ocr.base import AbstractOcrEngine
from app.tools.extensions.identification_tool.pipeline.base import (
    AbstractCalibrationController,
    AbstractPipeline,
    CalibrationData,
    PipelineResult,
    ResultStatus,
    rename_to_identifier,
)
from app.tools.extensions.identification_tool.pipeline.pipeline1 import (
    _WorkerSignals,
    _crop_qimage,
    _load_qimage,
)

_logger = logging.getLogger("vi_toolbox.tools.scibit.pipelinex")


# ---------------------------------------------------------------------------
# Batch worker — sequential, one thread, engine called once at a time
# ---------------------------------------------------------------------------


class _SequentialBatchWorkerX(QRunnable):
    """Processes all batch images sequentially on a single background thread.

    Keep OCR engine calls sequential — engines are not thread-safe.
    """

    def __init__(
        self,
        images: list[Path],
        calib: CalibrationData,
        min_confidence: float,
        detection_engine: AbstractOcrEngine,
        recognition_engine: AbstractOcrEngine,
        signals: _WorkerSignals,
        rename_preview: bool = False,
    ) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._images = images
        self._calib = calib
        self._min_confidence = min_confidence
        self._detection_engine = detection_engine
        self._recognition_engine = recognition_engine
        self._signals = signals
        self._rename_preview = rename_preview

    def run(self) -> None:  # noqa: N802
        for path in self._images:
            try:
                result = self._process_one(path)
            except Exception as exc:  # noqa: BLE001
                _logger.warning("Batch error for %s: %s", path.name, exc)
                result = PipelineResult(
                    original_path=path,
                    recognized_text=None,
                    confidence=0.0,
                    status=ResultStatus.FAILED,
                )
            self._signals.batch_image_result.emit(result)

    def _process_one(self, path: Path) -> PipelineResult:
        """Return a PipelineResult for a single image.

        TODO: implement your per-image logic here.
        Typical steps:
          1. Load the image with _load_qimage(path).
          2. Use calib data to locate the identifier region.
          3. Crop with _crop_qimage(img, bbox).
          4. Call self._recognition_engine.recognize_text(crop).
          5. Decide ACCEPTED / PENDING / FAILED based on confidence.
          6. Optionally rename with rename_to_identifier(path, text).
        """
        img = _load_qimage(path)
        if img is None:
            return PipelineResult(
                original_path=path,
                recognized_text=None,
                confidence=0.0,
                status=ResultStatus.FAILED,
            )

        # --- TODO: derive identifier crop from calib ---
        # crop = _crop_qimage(img, some_bbox)
        # ocr_result = self._recognition_engine.recognize_text(crop)

        raise NotImplementedError("_process_one not implemented for PipelineX")


# ---------------------------------------------------------------------------
# Pipeline X
# ---------------------------------------------------------------------------


class PipelineX(AbstractPipeline):
    """Pipeline X: <description>.

    Calibration flow
    ----------------
    Describe the steps the user goes through during calibration, e.g.:
      1. …
      2. …

    Batch flow
    ----------
    Describe how calibration data is applied to each subsequent image.
    """

    def __init__(
        self,
        detection_engine: AbstractOcrEngine,
        recognition_engine: AbstractOcrEngine,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(detection_engine, recognition_engine, parent)
        self._ref_image: Path | None = None

        self._signals = _WorkerSignals()
        # Connect whichever _WorkerSignals you use to the pipeline's public signals.
        # Calibration signals (choose what applies):
        #   self._signals.chip_result        → self.chip_detected
        #   self._signals.chip_failed        → self.chip_detection_failed
        #   self._signals.text_regions_result→ self.text_regions_detected
        #   self._signals.ocr_result         → self.ocr_result_ready
        # Always connect these two:
        self._signals.batch_image_result.connect(self._on_batch_image_result)
        self._signals.error.connect(self.calibration_error)

        # --- TODO: add your own state fields ---
        self._batch_total: int = 0
        self._batch_done: int = 0

    # ------------------------------------------------------------------
    # Calibration
    # ------------------------------------------------------------------

    def start_calibration(self, image: Path) -> None:
        """Store the reference image and kick off the first calibration step.

        For pipelines where step 1 is fully automatic (e.g. chip detection),
        start a background worker here.  For pipelines where step 1 waits for
        user input (e.g. draw ROI), just store the image and return — the
        controller will call the appropriate method when the user acts.
        """
        self._ref_image = image
        self._stopped = False
        # TODO: start first automatic step, or just store and wait.

    # Add confirm_*/set_*/select_* methods as needed by your calibration flow.
    # See pipeline1.py (confirm_chip, set_identifier_bbox) and
    # pipeline2.py (set_roi, confirm_roi) for examples.

    def confirm_ocr_result(self, text: str) -> None:
        """User confirmed the OCR result. Build CalibrationData and emit calibration_complete."""
        if self._stopped or self._ref_image is None:
            return
        # TODO: populate CalibrationData with the fields your batch worker needs.
        calib = CalibrationData(
            reference_identifier=text,
            # chip_bbox=...,
            # roi_bbox=...,
            # reference_resolution=...,
        )
        self.calibration_complete.emit(calib)

    # ------------------------------------------------------------------
    # Calibration controller factory — required by AbstractPipeline
    # ------------------------------------------------------------------

    def create_calibration_controller(self) -> AbstractCalibrationController:
        from app.tools.extensions.identification_tool.ui.calibration_controller import (
            PipelineXCalibrationController,  # TODO: implement this class
        )
        return PipelineXCalibrationController(self)

    # ------------------------------------------------------------------
    # Batch processing
    # ------------------------------------------------------------------

    def start_batch(
        self,
        images: list[Path],
        calib: CalibrationData,
        min_confidence: float,
        rename_preview: bool = False,
    ) -> None:
        self._stopped = False
        self._batch_total = len(images)
        self._batch_done = 0

        if not images:
            self.batch_complete.emit()
            return

        worker = _SequentialBatchWorkerX(
            images, calib, min_confidence,
            self._detection_engine, self._recognition_engine,
            self._signals, rename_preview=rename_preview,
        )
        QThreadPool.globalInstance().start(worker)

    def _on_batch_image_result(self, result: PipelineResult) -> None:
        if self._stopped:
            return
        self._batch_done += 1
        self.image_processed.emit(result)
        self.progress_updated.emit(self._batch_done, self._batch_total)
        if self._batch_done >= self._batch_total:
            self.batch_complete.emit()
