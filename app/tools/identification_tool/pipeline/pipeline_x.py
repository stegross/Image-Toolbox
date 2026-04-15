"""Pipeline X: <Short description of what makes this pipeline unique>.

Replace all occurrences of "X" / "PipelineX" with your pipeline number/name.

Checklist for adding a new pipeline
-------------------------------------
1. Implement this file (CalibrationData subclass, batch worker, pipeline class,
   calibration controller class).
2. Add a human-readable entry to the pipeline_combo in tool.ui.
3. Add an ``elif pipeline_index == N`` branch in tool.py (_start method).
That is all — CalibrationWidget needs no changes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QRectF, QRunnable, QThreadPool

from app.tools.identification_tool.ocr.base import AbstractOcrEngine
from app.tools.identification_tool.pipeline.base import (  # noqa: F401
    AbstractCalibrationController,
    AbstractPipeline,
    BoundingBox,
    CalibrationData,
    OcrWorker,
    PipelineResult,
    ResultStatus,
    WorkerSignals,
    crop_qimage,
    load_qimage,
    rename_to_identifier,
)

_logger = logging.getLogger("vi_toolbox.tools.scibit.pipelinex")


# ---------------------------------------------------------------------------
# 1. Calibration data — only the fields YOUR pipeline needs
# ---------------------------------------------------------------------------


@dataclass
class PipelineXCalibrationData(CalibrationData):
    """Calibration result for Pipeline X.

    Add only the fields your batch worker needs.  The base class already
    provides ``reference_identifier``.
    """

    # TODO: add your fields, e.g.:
    # roi_bbox: BoundingBox | None = None


# ---------------------------------------------------------------------------
# 2. Batch worker — sequential, one thread, engine called once at a time
# ---------------------------------------------------------------------------


class _SequentialBatchWorkerX(QRunnable):
    """Processes all images sequentially on a single background thread.

    Keep OCR calls sequential — engines are not thread-safe.
    """

    def __init__(
        self,
        images: list[Path],
        calib: PipelineXCalibrationData,
        min_confidence: float,
        detection_engine: AbstractOcrEngine,
        recognition_engine: AbstractOcrEngine,
        signals: WorkerSignals,
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
                    original_path=path, recognized_text=None,
                    confidence=0.0, status=ResultStatus.FAILED,
                )
            self._signals.batch_image_result.emit(result)

    def _process_one(self, path: Path) -> PipelineResult:  # noqa: ARG002
        """Return a PipelineResult for a single image.

        TODO: implement your per-image logic here.
        Typical steps:
          1. img = load_qimage(path)
          2. Locate identifier region using self._calib data.
          3. crop = crop_qimage(img, bbox)
          4. ocr_result = self._recognition_engine.recognize_text(crop)
          5. Decide ACCEPTED / PENDING / FAILED based on confidence.
          6. Optionally rename with rename_to_identifier(path, text).
        """
        raise NotImplementedError("_process_one not implemented for PipelineX")


# ---------------------------------------------------------------------------
# 3. Pipeline class
# ---------------------------------------------------------------------------


class PipelineX(AbstractPipeline):
    """Pipeline X: <description>.

    Calibration flow
    ----------------
    Describe the steps the user goes through during calibration.

    Batch flow
    ----------
    Describe how calibration data is applied to each subsequent image.
    """

    # Add pipeline-specific calibration signals here, e.g.:
    # some_step_done = Signal(QRectF)

    # Assigned at module level below after the controller class is defined.
    CalibrationController: type

    def __init__(
        self,
        detection_engine: AbstractOcrEngine,
        recognition_engine: AbstractOcrEngine,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(detection_engine, recognition_engine, parent)
        self._ref_image: Path | None = None
        self._batch_total: int = 0
        self._batch_done: int = 0

        self._signals = WorkerSignals()
        # Connect whichever WorkerSignals slots your pipeline uses:
        self._signals.batch_image_result.connect(self._on_batch_image_result)
        self._signals.error.connect(self.calibration_error)
        # self._signals.ocr_result.connect(self._on_ocr_result)
        # self._signals.text_regions_result.connect(...)

    # ------------------------------------------------------------------
    # Calibration
    # ------------------------------------------------------------------

    def start_calibration(self, image: Path) -> None:
        """Store the reference image and kick off the first calibration step.

        For automatic step 1 (e.g. chip detection): start a background worker.
        For user-driven step 1 (e.g. draw ROI): just store and return — the
        controller calls the appropriate method when the user acts.
        """
        self._ref_image = image
        self._stopped = False
        # TODO: start first step, or just store and wait.

    def confirm_ocr_result(self, text: str) -> None:
        """Build PipelineXCalibrationData and emit calibration_complete."""
        if self._stopped or self._ref_image is None:
            return
        calib = PipelineXCalibrationData(
            reference_identifier=text,
            # TODO: populate your fields
        )
        self.calibration_complete.emit(calib)

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
        assert isinstance(calib, PipelineXCalibrationData)
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


# ---------------------------------------------------------------------------
# 4. Calibration controller
# ---------------------------------------------------------------------------


class _PipelineXCalibrationController(AbstractCalibrationController):
    """Drives calibration for Pipeline X.

    Widget API
    ----------
    self._widget.load_image(path)
    self._widget.set_step(current, total, description)
    self._widget.set_buttons([(name, label), ...])
    self._widget.button(name) -> QPushButton | None
    self._widget.start_roi_selection(mode)
    self._widget.stop_roi_selection()
    self._widget.show_rect_overlay(rect, color, width) -> item
    self._widget.show_rects_overlay(rects, color, width) -> [items]
    self._widget.clear_overlays()
    self._widget.show_ocr_panel(text)
    self._widget.hide_ocr_panel()
    self._widget.show_error(message)
    self._widget.selected_scene_items()

    Widget signals
    --------------
    self._widget.roi_drawn       -> Signal(mode: str, rect: QRectF)
    self._widget.ocr_confirmed   -> Signal(text: str)
    self._widget.scene_selection_changed -> Signal()
    """

    def __init__(self, pipeline: PipelineX) -> None:
        super().__init__()
        self._pipeline = pipeline
        self._widget = None
        self._image_paths: list[Path] = []
        self._image_index: int = 0

    def start(self, widget, image_paths: list[Path]) -> None:
        self._widget = widget
        self._image_paths = image_paths
        self._image_index = 0

        # 1. Connect pipeline signals:
        self._pipeline.ocr_result_ready.connect(self._on_ocr_result_ready)
        self._pipeline.calibration_complete.connect(self._on_calibration_complete)
        self._pipeline.calibration_error.connect(self._on_calibration_error)
        # Add: self._pipeline.some_step_done.connect(...)

        # 2. Connect widget signals:
        self._widget.ocr_confirmed.connect(self._on_ocr_confirmed)
        # self._widget.roi_drawn.connect(self._on_roi_drawn)
        # self._widget.scene_selection_changed.connect(...)

        self._step1()

    # ------------------------------------------------------------------
    # Steps
    # ------------------------------------------------------------------

    def _step1(self) -> None:
        """TODO: describe step 1."""
        self._widget.load_image(self._image_path())
        self._widget.set_step(1, 2, "TODO: step description")
        self._widget.set_buttons(self._skip_spec() + [("cancel", "Cancel")])
        self._connect_cancel()
        self._connect_skip()
        self._pipeline.start_calibration(self._image_path())

    # def _step2(self) -> None: ...

    # ------------------------------------------------------------------
    # Signal handlers
    # ------------------------------------------------------------------

    def _on_ocr_result_ready(self, text: str, confidence: float) -> None:
        self._widget.set_step(2, 2, f"Confirm OCR result (confidence: {confidence:.0%})")
        self._widget.show_ocr_panel(text)
        self._widget.set_buttons([])

    def _on_ocr_confirmed(self, text: str) -> None:
        self._widget.hide_ocr_panel()
        self._pipeline.confirm_ocr_result(text)

    def _on_calibration_complete(self, data: CalibrationData) -> None:
        self.calibration_complete.emit(data)

    def _on_calibration_error(self, message: str) -> None:
        self._widget.show_error(message)
        self.calibration_cancelled.emit()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _image_path(self) -> Path:
        return self._image_paths[self._image_index]

    def _skip_spec(self) -> list[tuple[str, str]]:
        return [("skip_calib", "Skip Image")] if self._image_index < len(self._image_paths) - 1 else []

    def _connect_cancel(self) -> None:
        btn = self._widget.button("cancel")
        if btn:
            btn.clicked.connect(self.calibration_cancelled)

    def _connect_skip(self) -> None:
        btn = self._widget.button("skip_calib")
        if btn:
            btn.clicked.connect(self._on_skip)

    def _on_skip(self) -> None:
        if self._image_index >= len(self._image_paths) - 1:
            return
        self._image_index += 1
        self._widget.clear_overlays()
        self._pipeline.reset()
        self._step1()


# Wire the controller to the pipeline class
PipelineX.CalibrationController = _PipelineXCalibrationController
