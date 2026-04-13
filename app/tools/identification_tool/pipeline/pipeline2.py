"""Pipeline 2: ROI Selection."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QRectF, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QColor

from app.tools.identification_tool.ocr.base import AbstractOcrEngine
from app.tools.identification_tool.pipeline.base import (
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

_logger = logging.getLogger("vi_toolbox.tools.scibit.pipeline2")

# Fraction of ROI width/height added on each side during batch processing.
# 0.25 → total region is 1.5× the user-drawn ROI in each dimension.
_TOLERANCE = 0.25


# ---------------------------------------------------------------------------
# Pipeline 2 calibration data
# ---------------------------------------------------------------------------


@dataclass
class Pipeline2CalibrationData(CalibrationData):
    """Calibration data for Pipeline 2.

    Parameters
    ----------
    roi_bbox
        Absolute pixel bounding box of the user-selected identifier region in
        the reference image.
    reference_resolution
        ``(width, height)`` of the reference image, used to scale the ROI
        to images of different sizes.
    """

    roi_bbox: BoundingBox | None = None
    reference_resolution: tuple[int, int] | None = None


# ---------------------------------------------------------------------------
# Background workers
# ---------------------------------------------------------------------------


class _SequentialBatchWorker2(QRunnable):
    """Processes all batch images sequentially on a single background thread."""

    def __init__(
        self,
        images: list[Path],
        calib: Pipeline2CalibrationData,
        min_confidence: float,
        recognition_engine: AbstractOcrEngine,
        signals: WorkerSignals,
        rename_preview: bool = False,
    ) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._images = images
        self._calib = calib
        self._min_confidence = min_confidence
        self._recognition_engine = recognition_engine
        self._signals = signals
        self._rename_preview = rename_preview

    def run(self) -> None:  # noqa: N802
        roi = self._calib.roi_bbox
        ref_res = self._calib.reference_resolution
        for path in self._images:
            try:
                img = load_qimage(path)
                if img is None or roi is None or ref_res is None:
                    self._signals.batch_image_result.emit(PipelineResult(
                        original_path=path, recognized_text=None,
                        confidence=0.0, status=ResultStatus.FAILED,
                    ))
                    continue

                w, h = img.width(), img.height()
                ref_w, ref_h = ref_res
                sx, sy = w / ref_w, h / ref_h

                # Scale the user-selected ROI and expand by tolerance on each side.
                tw = roi.width * sx * _TOLERANCE
                th = roi.height * sy * _TOLERANCE
                id_bbox = BoundingBox(
                    x=max(0, roi.x * sx - tw),
                    y=max(0, roi.y * sy - th),
                    width=min(w, roi.width * sx + 2 * tw),
                    height=min(h, roi.height * sy + 2 * th),
                )

                id_crop = crop_qimage(img, id_bbox)
                ocr_result = self._recognition_engine.recognize_text(id_crop)
                accepted = (
                    ocr_result.confidence >= self._min_confidence
                    and bool(ocr_result.text.strip())
                )
                new_path: Path | None = None
                if accepted and self._rename_preview:
                    status = ResultStatus.PENDING
                elif accepted:
                    new_path = rename_to_identifier(path, ocr_result.text.strip())
                    status = ResultStatus.ACCEPTED if new_path else ResultStatus.FAILED
                else:
                    status = ResultStatus.FAILED

                self._signals.batch_image_result.emit(PipelineResult(
                    original_path=path,
                    recognized_text=ocr_result.text,
                    confidence=ocr_result.confidence,
                    status=status,
                    new_path=new_path,
                ))
            except Exception as exc:  # noqa: BLE001
                _logger.warning("Batch error for %s: %s", path.name, exc)
                self._signals.batch_image_result.emit(PipelineResult(
                    original_path=path, recognized_text=None,
                    confidence=0.0, status=ResultStatus.FAILED,
                ))


# ---------------------------------------------------------------------------
# Pipeline 2
# ---------------------------------------------------------------------------


class Pipeline2(AbstractPipeline):
    """Pipeline 2: ROI Selection.

    The user draws a rectangle on the first image to mark the identifier
    region. Subsequent images are processed by scaling that rectangle to each
    image's resolution (plus a small tolerance margin) and running OCR
    directly on the crop.
    """

    # Pipeline-2-specific calibration signal
    roi_confirmed = Signal(QRectF)

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
        self._roi_bbox: BoundingBox | None = None
        self._batch_total: int = 0
        self._batch_done: int = 0

        self._signals = WorkerSignals()
        self._signals.ocr_result.connect(self._on_ocr_result)
        self._signals.batch_image_result.connect(self._on_batch_image_result)
        self._signals.error.connect(self.calibration_error)

    # ------------------------------------------------------------------
    # Calibration
    # ------------------------------------------------------------------

    def start_calibration(self, image: Path) -> None:
        self._ref_image = image
        self._stopped = False

    def set_roi(self, rect: QRectF) -> None:
        if self._stopped:
            return
        self._roi_bbox = BoundingBox.from_qrectf(rect)
        self.roi_confirmed.emit(rect)

    def confirm_roi(self, accepted: bool, manual_rect: QRectF | None = None) -> None:
        if self._stopped:
            return
        if not accepted and manual_rect is not None:
            self._roi_bbox = BoundingBox.from_qrectf(manual_rect)
        elif not accepted:
            self._roi_bbox = None
            return
        if self._roi_bbox is None:
            return
        worker = OcrWorker(
            self._ref_image, self._roi_bbox, self._recognition_engine, self._signals
        )
        QThreadPool.globalInstance().start(worker)

    def _on_ocr_result(self, text: str, confidence: float) -> None:
        if self._stopped:
            return
        self.ocr_result_ready.emit(text, confidence)

    def confirm_ocr_result(self, text: str) -> None:
        if self._stopped or self._ref_image is None or self._roi_bbox is None:
            return
        from PySide6.QtGui import QImageReader
        reader = QImageReader(str(self._ref_image))
        size = reader.size()
        ref_res = (size.width(), size.height()) if size.isValid() else (1000, 1000)
        calib = Pipeline2CalibrationData(
            roi_bbox=self._roi_bbox,
            reference_resolution=ref_res,
            reference_identifier=text,
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
        assert isinstance(calib, Pipeline2CalibrationData)
        self._stopped = False
        self._batch_total = len(images)
        self._batch_done = 0

        if not images:
            self.batch_complete.emit()
            return

        worker = _SequentialBatchWorker2(
            images, calib, min_confidence,
            self._recognition_engine,
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
# Calibration controller for Pipeline 2
# ---------------------------------------------------------------------------


def _tolerance_rect(roi: QRectF) -> QRectF:
    """Return the tolerance-expanded version of *roi* (1.5× in each dimension)."""
    tw = roi.width() * _TOLERANCE
    th = roi.height() * _TOLERANCE
    return QRectF(roi.x() - tw, roi.y() - th, roi.width() + 2 * tw, roi.height() + 2 * th)


class _Pipeline2CalibrationController(AbstractCalibrationController):
    """3-step ROI-selection calibration controller.

    Steps
    -----
    1. User draws ROI around identifier
    2. User confirms / redraws the region (both the exact ROI and the
       tolerance-expanded search area are shown)
    3. OCR on confirmed region → user confirms text
    """

    def __init__(self, pipeline: Pipeline2) -> None:
        super().__init__()
        self._pipeline = pipeline
        self._widget = None
        self._image_paths: list[Path] = []
        self._image_index: int = 0

    def start(self, widget, image_paths: list[Path]) -> None:
        self._widget = widget
        self._image_paths = image_paths
        self._image_index = 0

        self._pipeline.roi_confirmed.connect(self._on_roi_confirmed)
        self._pipeline.ocr_result_ready.connect(self._on_ocr_result_ready)
        self._pipeline.calibration_complete.connect(self._on_calibration_complete)
        self._pipeline.calibration_error.connect(self._on_calibration_error)

        widget.roi_drawn.connect(self._on_roi_drawn)
        widget.ocr_confirmed.connect(self._on_ocr_confirmed)

        self._step1()

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

    def _step1(self) -> None:
        self._widget.load_image(self._image_path())
        self._widget.set_step(1, 3, "Draw ROI around the identifier")
        self._widget.start_roi_selection("roi")
        self._widget.set_buttons(self._skip_spec() + [("cancel", "Cancel")])
        self._connect_cancel()
        self._connect_skip()
        self._pipeline.start_calibration(self._image_path())

    def _on_skip(self) -> None:
        if self._image_index >= len(self._image_paths) - 1:
            return
        self._image_index += 1
        self._widget.clear_overlays()
        self._pipeline.reset()
        self._step1()

    def _on_roi_drawn(self, mode: str, rect: QRectF) -> None:  # noqa: ARG002
        self._widget.stop_roi_selection()
        self._pipeline.set_roi(rect)

    def _on_roi_confirmed(self, roi: QRectF) -> None:
        self._widget.set_step(2, 3, "Confirm identifier region (orange = tolerance area)")
        self._widget.clear_overlays()
        self._widget.show_rect_overlay(_tolerance_rect(roi), QColor(255, 165, 0), width=4)
        self._widget.show_rect_overlay(roi, QColor(0, 200, 0), width=8)
        self._widget.set_buttons([
            ("confirm", "Confirm"), ("redraw", "Redraw"), ("cancel", "Cancel"),
        ])
        self._widget.button("confirm").clicked.connect(lambda: self._pipeline.confirm_roi(True))
        self._widget.button("redraw").clicked.connect(self._on_redraw)
        self._connect_cancel()

    def _on_redraw(self) -> None:
        self._widget.clear_overlays()
        self._widget.start_roi_selection("roi")
        self._widget.set_step(1, 3, "Draw ROI around the identifier")
        self._widget.set_buttons(self._skip_spec() + [("cancel", "Cancel")])
        self._connect_cancel()
        self._connect_skip()

    def _on_ocr_result_ready(self, text: str, confidence: float) -> None:
        self._widget.set_step(3, 3, f"Confirm OCR result (confidence: {confidence:.0%})")
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


# Wire the controller to the pipeline class
Pipeline2.CalibrationController = _Pipeline2CalibrationController
