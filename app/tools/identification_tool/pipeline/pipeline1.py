"""Pipeline 1: Normalized Coordinates via Chip Shape Recognition."""

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

_logger = logging.getLogger("vi_toolbox.tools.scibit.pipeline1")


# ---------------------------------------------------------------------------
# Pipeline 1 calibration data
# ---------------------------------------------------------------------------


@dataclass
class Pipeline1CalibrationData(CalibrationData):
    """Calibration data for Pipeline 1.

    Parameters
    ----------
    chip_bbox
        Absolute pixel bounding box of the chip in the reference image.
    identifier_bbox_norm
        Identifier position/size as proportions of ``chip_bbox``.
    chip_aspect_ratio
        ``chip_bbox.width / chip_bbox.height``.
    """

    chip_bbox: BoundingBox | None = None
    identifier_bbox_norm: BoundingBox | None = None
    chip_aspect_ratio: float | None = None


# ---------------------------------------------------------------------------
# Background workers
# ---------------------------------------------------------------------------


class _ChipDetectionWorker(QRunnable):
    def __init__(self, image_path: Path, signals: WorkerSignals) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._path = image_path
        self._signals = signals

    def run(self) -> None:  # noqa: N802
        try:
            import cv2  # type: ignore[import]
            img = cv2.imread(str(self._path), cv2.IMREAD_GRAYSCALE)
            if img is None:
                self._signals.chip_failed.emit(f"Could not read image: {self._path.name}")
                return
            _, thresh = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            h, w = img.shape
            valid = [c for c in contours if not _touches_border(c, w, h, margin=5)]
            if not valid:
                self._signals.chip_failed.emit("No chip contour found after border filtering.")
                return
            largest = max(valid, key=cv2.contourArea)
            x, y, cw, ch = cv2.boundingRect(largest)
            polygon = [
                (float(x), float(y)), (float(x + cw), float(y)),
                (float(x + cw), float(y + ch)), (float(x), float(y + ch)),
            ]
            self._signals.chip_result.emit(polygon, 0.9)
        except ImportError:
            self._signals.chip_failed.emit(
                "OpenCV (cv2) is required for chip detection but is not installed."
            )
        except Exception as exc:  # noqa: BLE001
            self._signals.chip_failed.emit(str(exc))


def _touches_border(contour, w: int, h: int, margin: int) -> bool:
    for pt in contour:
        x, y = pt[0]
        if x < margin or y < margin or x > w - margin or y > h - margin:
            return True
    return False


class _TextDetectionWorker(QRunnable):
    def __init__(
        self,
        image_path: Path,
        chip_bbox: BoundingBox,
        detection_engine: AbstractOcrEngine,
        signals: WorkerSignals,
    ) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._path = image_path
        self._chip_bbox = chip_bbox
        self._detection_engine = detection_engine
        self._signals = signals

    def run(self) -> None:  # noqa: N802
        try:
            img = load_qimage(self._path)
            if img is None:
                self._signals.error.emit(f"Cannot read image: {self._path.name}")
                return
            bb = self._chip_bbox
            chip_crop = crop_qimage(img, bb)
            regions = self._detection_engine.detect_text_regions(chip_crop)
            rects = [QRectF(r.x + bb.x, r.y + bb.y, r.width, r.height) for r in regions]
            self._signals.text_regions_result.emit(rects)
        except Exception as exc:  # noqa: BLE001
            self._signals.error.emit(str(exc))


class _SequentialBatchWorker(QRunnable):
    """Processes all batch images sequentially on a single background thread."""

    def __init__(
        self,
        images: list[Path],
        calib: Pipeline1CalibrationData,
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
        chip_bbox = self._calib.chip_bbox
        id_norm = self._calib.identifier_bbox_norm
        for path in self._images:
            try:
                img = load_qimage(path)
                if img is None or chip_bbox is None or id_norm is None:
                    self._signals.batch_image_result.emit(PipelineResult(
                        original_path=path, recognized_text=None,
                        confidence=0.0, status=ResultStatus.FAILED,
                    ))
                    continue

                id_bbox = BoundingBox(
                    x=chip_bbox.x + id_norm.x * chip_bbox.width,
                    y=chip_bbox.y + id_norm.y * chip_bbox.height,
                    width=id_norm.width * chip_bbox.width,
                    height=id_norm.height * chip_bbox.height,
                )
                crop = crop_qimage(img, id_bbox)
                ocr_result = self._recognition_engine.recognize_text(crop)
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
                _logger.warning("Batch processing error for %s: %s", path.name, exc)
                self._signals.batch_image_result.emit(PipelineResult(
                    original_path=path, recognized_text=None,
                    confidence=0.0, status=ResultStatus.FAILED,
                ))


# ---------------------------------------------------------------------------
# Pipeline 1
# ---------------------------------------------------------------------------


class Pipeline1(AbstractPipeline):
    """Pipeline 1: Chip Shape Recognition.

    Detects the chip boundary by thresholding, expresses the identifier
    region as normalised coordinates within the chip bounding box, and
    applies these coordinates to each subsequent image.
    """

    # Pipeline-1-specific calibration signals
    chip_detected = Signal(list, float)   # (polygon, confidence)
    chip_detection_failed = Signal(str)
    text_regions_detected = Signal(list)  # list[QRectF]

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
        self._chip_bbox: BoundingBox | None = None
        self._identifier_bbox: BoundingBox | None = None
        self._batch_total: int = 0
        self._batch_done: int = 0

        self._signals = WorkerSignals()
        self._signals.chip_result.connect(self._on_chip_detected)
        self._signals.chip_failed.connect(self._on_chip_failed)
        self._signals.text_regions_result.connect(self._on_text_regions_detected)
        self._signals.ocr_result.connect(self._on_ocr_result)
        self._signals.batch_image_result.connect(self._on_batch_image_result)
        self._signals.error.connect(self.calibration_error)

    # ------------------------------------------------------------------
    # Calibration
    # ------------------------------------------------------------------

    def start_calibration(self, image: Path) -> None:
        self._ref_image = image
        self._stopped = False
        self._run_chip_detection(image)

    def _run_chip_detection(self, image: Path) -> None:
        worker = _ChipDetectionWorker(image, self._signals)
        QThreadPool.globalInstance().start(worker)

    def _on_chip_detected(self, polygon: list[tuple[float, float]], confidence: float) -> None:
        if self._stopped:
            return
        self._store_chip_bbox(polygon)
        self.chip_detected.emit(polygon, confidence)

    def _on_chip_failed(self, reason: str) -> None:
        if self._stopped:
            return
        self.chip_detection_failed.emit(reason)

    def confirm_chip(
        self,
        accepted: bool,
        manual_polygon: list[tuple[float, float]] | None = None,
    ) -> None:
        if self._stopped:
            return
        if not accepted and manual_polygon is not None:
            xs = [p[0] for p in manual_polygon]
            ys = [p[1] for p in manual_polygon]
            self._chip_bbox = BoundingBox(
                x=min(xs), y=min(ys),
                width=max(xs) - min(xs), height=max(ys) - min(ys),
            )
        elif not accepted:
            if self._ref_image:
                self._run_chip_detection(self._ref_image)
            return
        # accepted=True: _chip_bbox already stored in _on_chip_detected

        if self._chip_bbox is None:
            return
        worker = _TextDetectionWorker(
            self._ref_image, self._chip_bbox, self._detection_engine, self._signals
        )
        QThreadPool.globalInstance().start(worker)

    def _on_text_regions_detected(self, rects: list[QRectF]) -> None:
        if self._stopped:
            return
        self.text_regions_detected.emit(rects)

    def set_identifier_bbox(self, rect: QRectF) -> None:
        if self._chip_bbox is None:
            return
        self._identifier_bbox = BoundingBox.from_qrectf(rect)
        self._run_calibration_ocr()

    def _run_calibration_ocr(self) -> None:
        if self._ref_image is None or self._identifier_bbox is None:
            return
        worker = OcrWorker(
            self._ref_image, self._identifier_bbox, self._recognition_engine, self._signals
        )
        QThreadPool.globalInstance().start(worker)

    def _on_ocr_result(self, text: str, confidence: float) -> None:
        if self._stopped:
            return
        self.ocr_result_ready.emit(text, confidence)

    def confirm_ocr_result(self, text: str) -> None:
        if self._stopped or self._chip_bbox is None or self._identifier_bbox is None:
            return
        id_norm = BoundingBox(
            x=(self._identifier_bbox.x - self._chip_bbox.x) / self._chip_bbox.width,
            y=(self._identifier_bbox.y - self._chip_bbox.y) / self._chip_bbox.height,
            width=self._identifier_bbox.width / self._chip_bbox.width,
            height=self._identifier_bbox.height / self._chip_bbox.height,
        )
        calib = Pipeline1CalibrationData(
            chip_bbox=self._chip_bbox,
            identifier_bbox_norm=id_norm,
            chip_aspect_ratio=self._chip_bbox.width / max(self._chip_bbox.height, 1),
            reference_identifier=text,
        )
        self.calibration_complete.emit(calib)

    def _store_chip_bbox(self, polygon: list[tuple[float, float]]) -> None:
        xs = [p[0] for p in polygon]
        ys = [p[1] for p in polygon]
        self._chip_bbox = BoundingBox(
            x=min(xs), y=min(ys),
            width=max(xs) - min(xs), height=max(ys) - min(ys),
        )

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
        assert isinstance(calib, Pipeline1CalibrationData)
        self._stopped = False
        self._batch_total = len(images)
        self._batch_done = 0

        if not images:
            self.batch_complete.emit()
            return

        worker = _SequentialBatchWorker(
            images, calib, min_confidence, self._recognition_engine, self._signals,
            rename_preview=rename_preview,
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
# Calibration controller for Pipeline 1
# ---------------------------------------------------------------------------


class _Pipeline1CalibrationController(AbstractCalibrationController):
    """5-step chip-shape calibration controller.

    Steps
    -----
    1. Chip boundary detection (automatic)
    2. User confirms / retries / draws chip boundary manually
    3. Text-region detection inside chip (automatic)
    4. User selects identifier region (click or draw)
    5. OCR on selected region → user confirms text
    """

    def __init__(self, pipeline: Pipeline1) -> None:
        super().__init__()
        self._pipeline = pipeline
        self._widget = None
        self._image_paths: list[Path] = []
        self._image_index: int = 0

    def start(self, widget, image_paths: list[Path]) -> None:
        self._widget = widget
        self._image_paths = image_paths
        self._image_index = 0

        self._pipeline.chip_detected.connect(self._on_chip_detected)
        self._pipeline.chip_detection_failed.connect(self._on_chip_detection_failed)
        self._pipeline.text_regions_detected.connect(self._on_text_regions_detected)
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
        self._widget.set_step(1, 5, "Detecting chip boundary…")
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

    def _on_chip_detected(self, polygon: list[tuple[float, float]], _confidence: float) -> None:
        self._widget.set_step(2, 5, "Confirm chip boundary")
        self._widget.clear_overlays()
        self._widget.show_rect_overlay(_polygon_to_qrectf(polygon), QColor(0, 200, 0), width=8)
        self._widget.set_buttons([
            ("confirm", "Confirm"), ("reject_retry", "Retry"),
            ("reject_manual", "Draw Manually"), ("cancel", "Cancel"),
        ])
        self._widget.button("confirm").clicked.connect(self._on_confirm_chip)
        self._widget.button("reject_retry").clicked.connect(self._on_retry_chip)
        self._widget.button("reject_manual").clicked.connect(self._on_manual_chip)
        self._connect_cancel()

    def _on_chip_detection_failed(self, reason: str) -> None:
        self._widget.set_step(1, 5, f"Detection failed: {reason}")
        self._widget.set_buttons(self._skip_spec() + [
            ("retry", "Retry"), ("manual", "Draw Manually"), ("cancel", "Cancel"),
        ])
        self._widget.button("retry").clicked.connect(lambda: self._pipeline.confirm_chip(False))
        self._widget.button("manual").clicked.connect(self._on_manual_chip)
        self._connect_cancel()
        self._connect_skip()

    def _on_confirm_chip(self) -> None:
        self._widget.set_step(3, 5, "Detecting text regions…")
        self._widget.set_buttons([("cancel", "Cancel")])
        self._connect_cancel()
        self._pipeline.confirm_chip(True)

    def _on_retry_chip(self) -> None:
        self._widget.set_step(1, 5, "Detecting chip boundary…")
        self._widget.clear_overlays()
        self._widget.set_buttons(self._skip_spec() + [("cancel", "Cancel")])
        self._connect_cancel()
        self._connect_skip()
        self._pipeline.confirm_chip(False)

    def _on_manual_chip(self) -> None:
        self._widget.set_step(2, 5, "Draw chip boundary manually")
        self._widget.clear_overlays()
        self._widget.start_roi_selection("chip")
        self._widget.set_buttons([("cancel", "Cancel")])
        self._connect_cancel()

    def _on_text_regions_detected(self, rects: list[QRectF]) -> None:
        self._widget.set_step(4, 5, "Select the identifier region")
        self._widget.clear_overlays()
        items = self._widget.show_rects_overlay(rects, QColor(255, 0, 255), width=8)
        self._widget.set_buttons([("manual_id", "Draw Manually"), ("cancel", "Cancel")])
        self._widget.button("manual_id").clicked.connect(self._on_manual_identifier)
        self._connect_cancel()
        for item in items:
            item.setFlag(item.GraphicsItemFlag.ItemIsSelectable, True)
        self._widget.scene_selection_changed.connect(self._on_scene_selection_changed)

    def _on_scene_selection_changed(self) -> None:
        selected = self._widget.selected_scene_items()
        if not selected:
            return
        item = selected[0]
        rect = item.rect() if hasattr(item, "rect") else item.boundingRect()
        self._widget.scene_selection_changed.disconnect(self._on_scene_selection_changed)
        self._widget.set_step(5, 5, "Running OCR…")
        self._widget.set_buttons([("cancel", "Cancel")])
        self._connect_cancel()
        self._pipeline.set_identifier_bbox(rect)

    def _on_manual_identifier(self) -> None:
        self._widget.set_step(4, 5, "Draw the identifier region")
        self._widget.start_roi_selection("identifier")
        self._widget.set_buttons([("cancel", "Cancel")])
        self._connect_cancel()

    def _on_roi_drawn(self, mode: str, rect: QRectF) -> None:
        self._widget.clear_overlays()
        if mode == "chip":
            polygon = [
                (rect.x(), rect.y()), (rect.right(), rect.y()),
                (rect.right(), rect.bottom()), (rect.x(), rect.bottom()),
            ]
            self._widget.show_rect_overlay(rect, QColor(0, 120, 255), width=8)
            self._pipeline.confirm_chip(False, polygon)
        elif mode == "identifier":
            self._widget.show_rect_overlay(rect, QColor(0, 120, 255), width=8)
            self._widget.set_step(5, 5, "Running OCR…")
            self._widget.set_buttons([("cancel", "Cancel")])
            self._connect_cancel()
            self._pipeline.set_identifier_bbox(rect)

    def _on_ocr_result_ready(self, text: str, confidence: float) -> None:
        self._widget.set_step(5, 5, f"Confirm OCR result (confidence: {confidence:.0%})")
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


def _polygon_to_qrectf(polygon: list[tuple[float, float]]) -> QRectF:
    xs = [p[0] for p in polygon]
    ys = [p[1] for p in polygon]
    x, y = min(xs), min(ys)
    return QRectF(x, y, max(xs) - x, max(ys) - y)


# Wire the controller to the pipeline class
Pipeline1.CalibrationController = _Pipeline1CalibrationController
