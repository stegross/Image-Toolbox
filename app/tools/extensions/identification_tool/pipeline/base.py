"""Shared data structures, helpers, and abstract base classes."""

from __future__ import annotations

import enum
from abc import abstractmethod
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QRect, QRectF, QRunnable, Signal
from PySide6.QtGui import QImage

from app.tools.extensions.identification_tool.ocr.base import AbstractOcrEngine


# ---------------------------------------------------------------------------
# Shared data structures
# ---------------------------------------------------------------------------


@dataclass
class BoundingBox:
    """Axis-aligned bounding box in either pixel or normalised coordinates."""

    x: float
    y: float
    width: float
    height: float

    def to_qrectf(self) -> QRectF:
        return QRectF(self.x, self.y, self.width, self.height)

    @staticmethod
    def from_qrectf(rect: QRectF) -> "BoundingBox":
        return BoundingBox(rect.x(), rect.y(), rect.width(), rect.height())


@dataclass
class CalibrationData:
    """Base class for pipeline-specific calibration results.

    Each pipeline defines its own subclass containing only the fields it
    needs — no more optional union fields that only one pipeline uses.

    The single shared field is ``reference_identifier``: the user-confirmed
    OCR text from the first image, common to every pipeline.
    """

    reference_identifier: str = ""


class ResultStatus(enum.Enum):
    """Outcome classification for a single processed image."""

    ACCEPTED = "accepted"
    """OCR confidence met the threshold; file was auto-renamed."""

    PENDING = "pending"
    """OCR confidence met threshold but manual confirmation required."""

    FAILED = "failed"
    """OCR confidence too low or no text found; needs manual review."""

    MANUAL = "manual"
    """User manually confirmed and renamed the file during review."""


@dataclass
class PipelineResult:
    """Processing outcome for a single image."""

    original_path: Path
    recognized_text: str | None
    confidence: float
    status: ResultStatus
    new_path: Path | None = None


# ---------------------------------------------------------------------------
# Rename helper
# ---------------------------------------------------------------------------


def rename_to_identifier(path: Path, identifier: str) -> Path | None:
    """Rename *path* to ``{identifier}_{original_name}``.

    Appends a numeric suffix on conflict.  Returns the new path on success,
    ``None`` on failure.
    """
    import logging
    _log = logging.getLogger("vi_toolbox.tools.scibit.pipeline")
    new_name = f"{identifier}_{path.name}"
    candidate = path.parent / new_name
    counter = 1
    while candidate.exists() and candidate != path:
        candidate = path.parent / f"{identifier}_{counter}_{path.name}"
        counter += 1
    try:
        path.rename(candidate)
        _log.info("Renamed: %s -> %s", path.name, candidate.name)
        return candidate
    except OSError as exc:
        _log.error("Rename failed: %s -> %s: %s", path.name, candidate.name, exc)
        return None


# ---------------------------------------------------------------------------
# Shared background-worker signals and helpers
# (defined here so neither pipeline file imports from the other)
# ---------------------------------------------------------------------------


class WorkerSignals(QObject):
    """Qt signals used by background QRunnable workers.

    All signal names are generic.  Pipelines connect only the ones they use.
    ``chip_result`` / ``chip_failed`` are Pipeline-1-specific but live here
    so that :class:`Pipeline2` workers can reuse the same signal bus.
    """

    chip_result = Signal(list, float)    # (polygon, confidence)
    chip_failed = Signal(str)
    text_regions_result = Signal(list)   # list[QRectF]
    ocr_result = Signal(str, float)      # (text, confidence)
    batch_image_result = Signal(object)  # PipelineResult
    error = Signal(str)


def load_qimage(path: Path) -> QImage | None:
    """Load *path* as a greyscale QImage, or ``None`` on failure."""
    img = QImage(str(path))
    if img.isNull():
        return None
    return img.convertToFormat(QImage.Format.Format_Grayscale8)


def crop_qimage(img: QImage, bbox: BoundingBox) -> QImage:
    """Return a copy of *img* cropped to *bbox*, clamped to image bounds."""
    x = max(0, int(bbox.x))
    y = max(0, int(bbox.y))
    w = min(img.width() - x, max(1, int(bbox.width)))
    h = min(img.height() - y, max(1, int(bbox.height)))
    return img.copy(QRect(x, y, w, h))


class OcrWorker(QRunnable):
    """Background worker: runs OCR on a single cropped region."""

    def __init__(
        self,
        image_path: Path,
        identifier_bbox: BoundingBox,
        recognition_engine: AbstractOcrEngine,
        signals: WorkerSignals,
    ) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._path = image_path
        self._bbox = identifier_bbox
        self._recognition_engine = recognition_engine
        self._signals = signals

    def run(self) -> None:  # noqa: N802
        try:
            img = load_qimage(self._path)
            if img is None:
                self._signals.error.emit(f"Cannot read image: {self._path.name}")
                return
            crop = crop_qimage(img, self._bbox)
            result = self._recognition_engine.recognize_text(crop)
            self._signals.ocr_result.emit(result.text, result.confidence)
        except Exception as exc:  # noqa: BLE001
            self._signals.error.emit(str(exc))


# ---------------------------------------------------------------------------
# Abstract calibration controller
# ---------------------------------------------------------------------------


class AbstractCalibrationController(QObject):
    """Drives the calibration UI for one specific pipeline.

    Each pipeline ships a concrete subclass (as ``Pipeline.CalibrationController``)
    that owns its calibration state machine.  :class:`CalibrationWidget` is a
    dumb surface; the controller calls its API to update the UI.

    Signals
    -------
    calibration_complete(CalibrationData)
    calibration_cancelled
    """

    calibration_complete = Signal(object)   # CalibrationData
    calibration_cancelled = Signal()

    @abstractmethod
    def start(self, widget: object, image_paths: list[Path]) -> None:
        """Attach to *widget* and begin the calibration flow."""


# ---------------------------------------------------------------------------
# Abstract pipeline
# ---------------------------------------------------------------------------


class AbstractPipeline(QObject):
    """Abstract base class for identification pipelines.

    Signals common to every pipeline
    ---------------------------------
    ocr_result_ready(text, confidence)
        OCR result for the reference image; user must confirm.
    calibration_complete(CalibrationData)
        All calibration steps passed.
    calibration_error(message)
        Unrecoverable calibration error.
    image_processed(PipelineResult)
        One batch image finished.
    progress_updated(current, total)
        Batch progress tick.
    batch_complete
        All batch images processed.
    batch_error(message)
        Unrecoverable batch error.

    Pipeline-specific calibration signals (e.g. chip_detected, roi_confirmed)
    are defined on the concrete subclass — not here.  Controllers hold a
    typed reference to the concrete pipeline and access them directly.
    """

    # --- Universal calibration signals ---
    ocr_result_ready = Signal(str, float)
    calibration_complete = Signal(object)   # CalibrationData
    calibration_error = Signal(str)

    # --- Batch signals ---
    image_processed = Signal(object)        # PipelineResult
    progress_updated = Signal(int, int)
    batch_complete = Signal()
    batch_error = Signal(str)

    def __init__(
        self,
        detection_engine: AbstractOcrEngine,
        recognition_engine: AbstractOcrEngine,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._detection_engine = detection_engine
        self._recognition_engine = recognition_engine
        self._stopped = False

    # ------------------------------------------------------------------
    # Calibration interface
    # ------------------------------------------------------------------

    @abstractmethod
    def start_calibration(self, image: Path) -> None:
        """Begin calibration on the reference *image*."""

    @abstractmethod
    def confirm_ocr_result(self, text: str) -> None:
        """User confirmed (and possibly corrected) the OCR result.

        Builds the pipeline-specific CalibrationData and emits
        ``calibration_complete``.
        """

    def create_calibration_controller(self) -> AbstractCalibrationController:
        """Return a new controller that drives the calibration UI.

        The default implementation instantiates ``self.CalibrationController(self)``.
        Every concrete pipeline **must** define a nested class::

            class MyPipeline(AbstractPipeline):
                class CalibrationController(AbstractCalibrationController):
                    ...
        """
        return self.CalibrationController(self)  # type: ignore[attr-defined]

    def reset(self) -> None:
        """Clear the stopped flag so the pipeline can be restarted."""
        self._stopped = False

    def stop(self) -> None:
        """Request a graceful abort of any ongoing processing."""
        self._stopped = True

    # ------------------------------------------------------------------
    # Batch processing interface
    # ------------------------------------------------------------------

    @abstractmethod
    def start_batch(
        self,
        images: list[Path],
        calib: CalibrationData,
        min_confidence: float,
        rename_preview: bool = False,
    ) -> None:
        """Process *images* using calibration reference *calib*.

        Emits ``image_processed`` per image and ``batch_complete`` when done.
        """
