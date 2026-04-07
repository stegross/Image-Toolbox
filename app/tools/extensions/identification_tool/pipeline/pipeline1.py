"""Pipeline 1: Normalized Coordinates via Chip Shape Recognition."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QRect, QRectF, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QImage, QImageReader

from app.tools.extensions.identification_tool.ocr.base import AbstractOcrEngine, DetectedRegion
from app.tools.extensions.identification_tool.pipeline.base import (
    AbstractPipeline,
    BoundingBox,
    CalibrationData,
    PipelineResult,
    ResultStatus,
    rename_to_identifier,
)

_logger = logging.getLogger("vi_toolbox.tools.scibit.pipeline1")


# ---------------------------------------------------------------------------
# Background worker signals
# ---------------------------------------------------------------------------


class _WorkerSignals(QObject):
    chip_result = Signal(list, float)   # (polygon, confidence)
    chip_failed = Signal(str)
    text_regions_result = Signal(list)  # list[QRectF]
    ocr_result = Signal(str, float)     # (text, confidence)
    batch_image_result = Signal(object) # PipelineResult
    error = Signal(str)


# ---------------------------------------------------------------------------
# Background workers (QRunnable)
# ---------------------------------------------------------------------------


class _ChipDetectionWorker(QRunnable):
    def __init__(self, image_path: Path, signals: _WorkerSignals) -> None:
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
            valid = [
                c for c in contours
                if not _touches_border(c, w, h, margin=5)
            ]
            if not valid:
                self._signals.chip_failed.emit("No chip contour found after border filtering.")
                return
            largest = max(valid, key=cv2.contourArea)
            rect = cv2.boundingRect(largest)
            x, y, cw, ch = rect
            polygon = [(float(x), float(y)), (float(x + cw), float(y)),
                       (float(x + cw), float(y + ch)), (float(x), float(y + ch))]
            self._signals.chip_result.emit(polygon, 0.9)
        except ImportError:
            # cv2 not available — fall back to a centred stub result
            _logger.warning("OpenCV not available; using stub chip detection.")
            import cv2  # noqa: F811 — intentionally re-raising; but we catch ImportError
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
        signals: _WorkerSignals,
    ) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._path = image_path
        self._chip_bbox = chip_bbox
        self._detection_engine = detection_engine
        self._signals = signals

    def run(self) -> None:  # noqa: N802
        try:
            img = _load_qimage(self._path)
            if img is None:
                self._signals.error.emit(f"Cannot read image: {self._path.name}")
                return
            bb = self._chip_bbox
            chip_crop = _crop_qimage(img, bb)
            regions = self._detection_engine.detect_text_regions(chip_crop)
            # Offset detected regions back to full-image coordinates
            rects = [
                QRectF(r.x + bb.x, r.y + bb.y, r.width, r.height)
                for r in regions
            ]
            self._signals.text_regions_result.emit(rects)
        except Exception as exc:  # noqa: BLE001
            self._signals.error.emit(str(exc))


class _OcrWorker(QRunnable):
    def __init__(
        self,
        image_path: Path,
        identifier_bbox: BoundingBox,
        recognition_engine: AbstractOcrEngine,
        signals: _WorkerSignals,
    ) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._path = image_path
        self._bbox = identifier_bbox
        self._recognition_engine = recognition_engine
        self._signals = signals

    def run(self) -> None:  # noqa: N802
        try:
            img = _load_qimage(self._path)
            if img is None:
                self._signals.error.emit(f"Cannot read image: {self._path.name}")
                return
            crop = _crop_qimage(img, self._bbox)
            result = self._recognition_engine.recognize_text(crop)
            self._signals.ocr_result.emit(result.text, result.confidence)
        except Exception as exc:  # noqa: BLE001
            self._signals.error.emit(str(exc))


class _BatchImageWorker(QRunnable):
    def __init__(
        self,
        image_path: Path,
        calib: CalibrationData,
        min_confidence: float,
        recognition_engine: AbstractOcrEngine,
        signals: _WorkerSignals,
        rename_preview: bool = False,
    ) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._path = image_path
        self._calib = calib
        self._min_confidence = min_confidence
        self._recognition_engine = recognition_engine
        self._signals = signals
        self._rename_preview = rename_preview

    def run(self) -> None:  # noqa: N802
        try:
            img = _load_qimage(self._path)
            chip_bbox = self._calib.chip_bbox
            id_norm = self._calib.identifier_bbox_norm

            if img is None or chip_bbox is None or id_norm is None:
                self._signals.batch_image_result.emit(PipelineResult(
                    original_path=self._path,
                    recognized_text=None,
                    confidence=0.0,
                    status=ResultStatus.FAILED,
                ))
                return

            # Direct crop using normalised coordinates applied to detected chip bbox.
            id_bbox = BoundingBox(
                x=chip_bbox.x + id_norm.x * chip_bbox.width,
                y=chip_bbox.y + id_norm.y * chip_bbox.height,
                width=id_norm.width * chip_bbox.width,
                height=id_norm.height * chip_bbox.height,
            )
            crop = _crop_qimage(img, id_bbox)
            ocr_result = self._recognition_engine.recognize_text(crop)
            accepted = (
                ocr_result.confidence >= self._min_confidence
                and bool(ocr_result.text.strip())
            )
            new_path: Path | None = None
            if accepted and self._rename_preview:
                status = ResultStatus.PENDING
            elif accepted:
                new_path = rename_to_identifier(self._path, ocr_result.text.strip())
                status = ResultStatus.ACCEPTED if new_path else ResultStatus.FAILED
            else:
                status = ResultStatus.FAILED

            self._signals.batch_image_result.emit(PipelineResult(
                original_path=self._path,
                recognized_text=ocr_result.text,
                confidence=ocr_result.confidence,
                status=status,
                new_path=new_path,
            ))
        except Exception as exc:  # noqa: BLE001
            _logger.warning("Batch processing error for %s: %s", self._path.name, exc)
            self._signals.batch_image_result.emit(PipelineResult(
                original_path=self._path,
                recognized_text=None,
                confidence=0.0,
                status=ResultStatus.FAILED,
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
        self._pending_batch_results: list[PipelineResult] = []
        self._batch_total: int = 0
        self._batch_done: int = 0
        self._min_confidence: float = 0.75
        self._calib_data: CalibrationData | None = None

        self._signals = _WorkerSignals()
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
        try:
            import cv2  # noqa: F401
            worker: QRunnable = _ChipDetectionWorker(image, self._signals)
        except ImportError:
            worker = _ChipDetectionStubWorker(image, self._signals)
        QThreadPool.globalInstance().start(worker)

    def _on_chip_detected(self, polygon: list[tuple[float, float]], confidence: float) -> None:
        if self._stopped:
            return
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
        if accepted and manual_polygon is None:
            # Use the last detected polygon — retrieve from stored state
            # (chip_bbox was not yet set; we set it here on confirmation)
            pass

        if not accepted and manual_polygon is not None:
            # User drew manually
            xs = [p[0] for p in manual_polygon]
            ys = [p[1] for p in manual_polygon]
            self._chip_bbox = BoundingBox(
                x=min(xs), y=min(ys),
                width=max(xs) - min(xs),
                height=max(ys) - min(ys),
            )
        elif not accepted:
            # Retry
            if self._ref_image:
                self._run_chip_detection(self._ref_image)
            return

        if self._chip_bbox is None:
            return

        # Run text detection inside chip
        worker = _TextDetectionWorker(
            self._ref_image, self._chip_bbox, self._detection_engine, self._signals
        )
        QThreadPool.globalInstance().start(worker)

    def _on_text_regions_detected(self, rects: list[QRectF]) -> None:
        if self._stopped:
            return
        self.text_regions_detected.emit(rects)

    def select_identifier_region(
        self,
        region_index: int | None = None,
        manual_rect: QRectF | None = None,
    ) -> None:
        if self._stopped:
            return
        if region_index is not None:
            # Will be set from the list delivered by text_regions_detected
            # The CalibrationWidget passes the QRectF directly
            return
        if manual_rect is not None:
            self._identifier_bbox = BoundingBox.from_qrectf(manual_rect)
            self._run_calibration_ocr()

    def set_identifier_bbox(self, rect: QRectF) -> None:
        """Called by the calibration widget with the selected identifier region."""
        if self._chip_bbox is None:
            return
        self._identifier_bbox = BoundingBox.from_qrectf(rect)
        self._run_calibration_ocr()

    def _run_calibration_ocr(self) -> None:
        if self._ref_image is None or self._identifier_bbox is None:
            return
        worker = _OcrWorker(
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
        # Compute normalised identifier position
        id_norm = BoundingBox(
            x=(self._identifier_bbox.x - self._chip_bbox.x) / self._chip_bbox.width,
            y=(self._identifier_bbox.y - self._chip_bbox.y) / self._chip_bbox.height,
            width=self._identifier_bbox.width / self._chip_bbox.width,
            height=self._identifier_bbox.height / self._chip_bbox.height,
        )
        calib = CalibrationData(
            chip_bbox=self._chip_bbox,
            identifier_bbox_norm=id_norm,
            chip_aspect_ratio=self._chip_bbox.width / max(self._chip_bbox.height, 1),
            reference_identifier=text,
        )
        self._calib_data = calib
        self.calibration_complete.emit(calib)

    # Store chip bbox when detected (before user confirmation)
    def _store_chip_bbox(self, polygon: list[tuple[float, float]]) -> None:
        xs = [p[0] for p in polygon]
        ys = [p[1] for p in polygon]
        self._chip_bbox = BoundingBox(
            x=min(xs), y=min(ys),
            width=max(xs) - min(xs),
            height=max(ys) - min(ys),
        )

    # ------------------------------------------------------------------
    # Batch processing
    # ------------------------------------------------------------------

    def start_batch(
        self, images: list[Path], calib: CalibrationData, min_confidence: float,
        rename_preview: bool = False,
    ) -> None:
        self._stopped = False
        self._min_confidence = min_confidence
        self._calib_data = calib
        self._batch_total = len(images)
        self._batch_done = 0
        self._pending_batch_results.clear()

        if not images:
            self.batch_complete.emit()
            return

        for path in images:
            worker = _BatchImageWorker(
                path, calib, min_confidence, self._recognition_engine, self._signals,
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
# QImage helpers
# ---------------------------------------------------------------------------


def _load_qimage(path: Path) -> QImage | None:
    """Load *path* as a greyscale :class:`QImage`, or ``None`` on failure."""
    img = QImage(str(path))
    if img.isNull():
        return None
    return img.convertToFormat(QImage.Format.Format_Grayscale8)


def _crop_qimage(img: QImage, bbox: BoundingBox) -> QImage:
    """Return a copy of *img* cropped to *bbox*, clamped to image bounds."""
    x = max(0, int(bbox.x))
    y = max(0, int(bbox.y))
    w = min(img.width() - x, max(1, int(bbox.width)))
    h = min(img.height() - y, max(1, int(bbox.height)))
    return img.copy(QRect(x, y, w, h))
