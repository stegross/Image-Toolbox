"""Pipeline 2: ROI Selection with Tolerance Correction."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QRect, QRectF, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QImage

from app.tools.extensions.identification_tool.ocr.base import AbstractOcrEngine
from app.tools.extensions.identification_tool.pipeline.base import (
    AbstractPipeline,
    BoundingBox,
    CalibrationData,
    PipelineResult,
    ResultStatus,
    rename_to_identifier,
)
from app.tools.extensions.identification_tool.pipeline.pipeline1 import (
    _OcrWorker,
    _WorkerSignals,
    _crop_qimage,
    _load_qimage,
)

_logger = logging.getLogger("vi_toolbox.tools.scibit.pipeline2")

# Tolerance margin for the search region (fraction of ROI size added on each side).
_TOLERANCE = 0.40


# ---------------------------------------------------------------------------
# Background workers
# ---------------------------------------------------------------------------


class _RoiTextDetectionWorker(QRunnable):
    """Detect text inside the user-selected ROI to snap to precise boundaries."""

    def __init__(
        self,
        image_path: Path,
        roi_bbox: BoundingBox,
        detection_engine: AbstractOcrEngine,
        signals: _WorkerSignals,
    ) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._path = image_path
        self._roi = roi_bbox
        self._detection_engine = detection_engine
        self._signals = signals

    def run(self) -> None:  # noqa: N802
        try:
            img = _load_qimage(self._path)
            if img is None:
                self._signals.error.emit(f"Cannot read image: {self._path.name}")
                return
            crop = _crop_qimage(img, self._roi)
            regions = self._detection_engine.detect_text_regions(crop)
            if regions:
                # Use the region closest to the ROI centre
                roi_cx, roi_cy = self._roi.width / 2, self._roi.height / 2
                best = min(
                    regions,
                    key=lambda r: (r.x + r.width / 2 - roi_cx) ** 2
                    + (r.y + r.height / 2 - roi_cy) ** 2,
                )
                snapped = QRectF(
                    self._roi.x + best.x,
                    self._roi.y + best.y,
                    best.width,
                    best.height,
                )
            else:
                snapped = self._roi.to_qrectf()
            self._signals.text_regions_result.emit([snapped])
        except Exception as exc:  # noqa: BLE001
            self._signals.error.emit(str(exc))


class _SequentialBatchWorker2(QRunnable):
    """Processes all batch images sequentially on a single background thread."""

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
        roi = self._calib.roi_bbox
        ref_res = self._calib.reference_resolution
        for path in self._images:
            try:
                img = _load_qimage(path)
                if img is None or roi is None or ref_res is None:
                    self._signals.batch_image_result.emit(
                        PipelineResult(
                            original_path=path,
                            recognized_text=None,
                            confidence=0.0,
                            status=ResultStatus.FAILED,
                        )
                    )
                    continue

                w, h = img.width(), img.height()
                ref_w, ref_h = ref_res
                sx = w / ref_w
                sy = h / ref_h

                tw = roi.width * sx * _TOLERANCE
                th = roi.height * sy * _TOLERANCE
                search = BoundingBox(
                    x=max(0, roi.x * sx - tw),
                    y=max(0, roi.y * sy - th),
                    width=min(w, roi.width * sx + 2 * tw),
                    height=min(h, roi.height * sy + 2 * th),
                )

                crop = _crop_qimage(img, search)
                regions = self._detection_engine.detect_text_regions(crop)

                if not regions:
                    self._signals.batch_image_result.emit(
                        PipelineResult(
                            original_path=path,
                            recognized_text=None,
                            confidence=0.0,
                            status=ResultStatus.FAILED,
                        )
                    )
                    continue

                exp_cx = (roi.x * sx) - search.x + (roi.width * sx) / 2
                exp_cy = (roi.y * sy) - search.y + (roi.height * sy) / 2
                best = min(
                    regions,
                    key=lambda r: (r.x + r.width / 2 - exp_cx) ** 2
                    + (r.y + r.height / 2 - exp_cy) ** 2,
                )
                id_bbox = BoundingBox(
                    x=search.x + best.x,
                    y=search.y + best.y,
                    width=best.width,
                    height=best.height,
                )
                id_crop = _crop_qimage(img, id_bbox)
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

                self._signals.batch_image_result.emit(
                    PipelineResult(
                        original_path=path,
                        recognized_text=ocr_result.text,
                        confidence=ocr_result.confidence,
                        status=status,
                        new_path=new_path,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                _logger.warning("Batch error for %s: %s", path.name, exc)
                self._signals.batch_image_result.emit(
                    PipelineResult(
                        original_path=path,
                        recognized_text=None,
                        confidence=0.0,
                        status=ResultStatus.FAILED,
                    )
                )


# ---------------------------------------------------------------------------
# Pipeline 2
# ---------------------------------------------------------------------------


class Pipeline2(AbstractPipeline):
    """Pipeline 2: ROI Selection with Tolerance Correction.

    The user draws a rectangle on the first image; subsequent images are
    processed by searching for text within a tolerance-expanded version
    of that rectangle after rescaling to the reference resolution.
    """

    def __init__(
        self,
        detection_engine: AbstractOcrEngine,
        recognition_engine: AbstractOcrEngine,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(detection_engine, recognition_engine, parent)
        self._ref_image: Path | None = None
        self._roi_bbox: BoundingBox | None = None
        self._snapped_bbox: BoundingBox | None = None
        self._batch_total: int = 0
        self._batch_done: int = 0

        self._signals = _WorkerSignals()
        self._signals.text_regions_result.connect(self._on_roi_snapped)
        self._signals.ocr_result.connect(self._on_ocr_result)
        self._signals.batch_image_result.connect(self._on_batch_image_result)
        self._signals.error.connect(self.calibration_error)

    # ------------------------------------------------------------------
    # Calibration
    # ------------------------------------------------------------------

    def start_calibration(self, image: Path) -> None:
        self._ref_image = image
        self._stopped = False
        # Pipeline 2 starts by waiting for the user to draw an ROI.
        # The CalibrationWidget will call set_roi() once the user draws.

    def set_roi(self, rect: QRectF) -> None:
        if self._stopped:
            return
        self._roi_bbox = BoundingBox.from_qrectf(rect)
        # Run text detection to snap to precise text boundary
        worker = _RoiTextDetectionWorker(
            self._ref_image, self._roi_bbox, self._detection_engine, self._signals
        )
        QThreadPool.globalInstance().start(worker)

    def _on_roi_snapped(self, rects: list[QRectF]) -> None:
        if self._stopped or not rects:
            return
        self._snapped_bbox = BoundingBox.from_qrectf(rects[0])
        self.roi_confirmed.emit(rects[0])

    def confirm_roi(self, accepted: bool, manual_rect: QRectF | None = None) -> None:
        if self._stopped:
            return
        if not accepted and manual_rect is not None:
            self._snapped_bbox = BoundingBox.from_qrectf(manual_rect)
        elif not accepted:
            # User wants to redraw — reset; CalibrationWidget will call set_roi() again
            self._snapped_bbox = None
            return

        if self._snapped_bbox is None:
            return
        worker = _OcrWorker(
            self._ref_image, self._snapped_bbox, self._recognition_engine, self._signals
        )
        QThreadPool.globalInstance().start(worker)

    def _on_ocr_result(self, text: str, confidence: float) -> None:
        if self._stopped:
            return
        self.ocr_result_ready.emit(text, confidence)

    def confirm_ocr_result(self, text: str) -> None:
        if self._stopped or self._ref_image is None or self._snapped_bbox is None:
            return
        from PySide6.QtGui import QImageReader
        reader = QImageReader(str(self._ref_image))
        size = reader.size()
        ref_res = (size.width(), size.height()) if size.isValid() else (1000, 1000)
        calib = CalibrationData(
            roi_bbox=self._snapped_bbox,
            reference_resolution=ref_res,
            reference_identifier=text,
        )
        self.calibration_complete.emit(calib)

    # ------------------------------------------------------------------
    # Batch processing
    # ------------------------------------------------------------------

    def start_batch(
        self, images: list[Path], calib: CalibrationData, min_confidence: float,
        rename_preview: bool = False,
    ) -> None:
        self._stopped = False
        self._batch_total = len(images)
        self._batch_done = 0

        if not images:
            self.batch_complete.emit()
            return

        worker = _SequentialBatchWorker2(
            images, calib, min_confidence, self._detection_engine, self._recognition_engine,
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
