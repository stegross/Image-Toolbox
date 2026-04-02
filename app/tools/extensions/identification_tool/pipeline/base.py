"""Shared data structures and abstract pipeline base class."""

from __future__ import annotations

import enum
from abc import abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QObject, QRectF, Signal

from app.tools.extensions.identification_tool.ocr.base import AbstractOcrEngine


# ---------------------------------------------------------------------------
# Shared data structures
# ---------------------------------------------------------------------------


@dataclass
class BoundingBox:
    """Axis-aligned bounding box.

    Coordinates may be either absolute pixels or normalised fractions
    depending on context — callers must track which unit they store.

    Parameters
    ----------
    x, y : float
        Top-left corner.
    width, height : float
        Dimensions.
    """

    x: float
    y: float
    width: float
    height: float

    def to_qrectf(self) -> QRectF:
        """Convert to a :class:`QRectF`."""
        return QRectF(self.x, self.y, self.width, self.height)

    @staticmethod
    def from_qrectf(rect: QRectF) -> "BoundingBox":
        """Create from a :class:`QRectF`."""
        return BoundingBox(rect.x(), rect.y(), rect.width(), rect.height())


@dataclass
class CalibrationData:
    """Reference data collected during the first-image calibration phase.

    Only the fields relevant to the chosen pipeline are populated; the
    rest remain ``None``.

    Parameters
    ----------
    chip_bbox : BoundingBox | None
        Absolute pixel bounding box of the chip in the reference image
        (Pipeline 1).
    identifier_bbox_norm : BoundingBox | None
        Identifier position and size expressed as proportions of
        ``chip_bbox`` (Pipeline 1).
    chip_aspect_ratio : float | None
        Width / height of the chip bounding box (Pipeline 1).
    roi_bbox : BoundingBox | None
        Absolute pixel bounding box of the ROI in the reference image
        (Pipeline 2).
    reference_resolution : tuple[int, int] | None
        ``(width, height)`` of the reference image (Pipeline 2).
    polarity : str
        ``"dark_on_light"`` or ``"light_on_dark"``.
    base_rotation : float
        Estimated in-plane rotation of the identifier in degrees.
    reference_identifier : str
        User-confirmed identifier text from the first image, used for
        batch pattern consistency checking.
    """

    chip_bbox: BoundingBox | None = None
    identifier_bbox_norm: BoundingBox | None = None
    chip_aspect_ratio: float | None = None
    roi_bbox: BoundingBox | None = None
    reference_resolution: tuple[int, int] | None = None
    polarity: str = "dark_on_light"
    base_rotation: float = 0.0
    reference_identifier: str = ""


class ResultStatus(enum.Enum):
    """Outcome classification for a single processed image."""

    ACCEPTED = "accepted"
    """OCR confidence met the threshold; file was renamed."""

    FAILED = "failed"
    """OCR confidence too low or no text found; needs manual review."""

    MANUAL = "manual"
    """User manually provided the identifier during the review phase."""


@dataclass
class PipelineResult:
    """Processing outcome for a single image.

    Parameters
    ----------
    original_path : Path
        The original image file path.
    recognized_text : str | None
        Best OCR guess, or ``None`` if detection failed entirely.
    confidence : float
        OCR confidence in ``[0.0, 1.0]``; ``-1.0`` if not available.
    status : ResultStatus
        Whether the result was accepted, failed, or manually corrected.
    new_path : Path | None
        Set to the renamed path after renaming; ``None`` until then.
    """

    original_path: Path
    recognized_text: str | None
    confidence: float
    status: ResultStatus
    new_path: Path | None = None


# ---------------------------------------------------------------------------
# Abstract pipeline
# ---------------------------------------------------------------------------


class AbstractPipeline(QObject):
    """Abstract base class for identification pipelines.

    Each pipeline is a QObject so it can emit Qt signals across threads.
    Heavy computation steps are run on a background thread via QRunnable;
    results are delivered back to the main thread via queued signals.
    User-confirmation steps pause execution and wait for calls to the
    corresponding ``confirm_*`` / ``select_*`` methods.

    Signals
    -------
    Calibration signals (emitted when user input is needed):

    chip_detected
        ``(polygon_points: list[tuple[float, float]], confidence: float)``
        — Pipeline 1: chip boundary found; user must confirm/reject.
    chip_detection_failed
        ``(reason: str)`` — automatic chip detection yielded no result.
    text_regions_detected
        ``(regions: list[QRectF])`` — text regions found inside the chip
        area; user must select the identifier region.
    roi_confirmed
        ``(snapped: QRectF)`` — Pipeline 2: text detection snapped the
        ROI; user must confirm the snapped region.
    ocr_result_ready
        ``(text: str, confidence: float)`` — OCR result for the first
        image; user must confirm or correct.
    calibration_complete
        ``(data: CalibrationData)`` — all calibration steps passed.
    calibration_error
        ``(message: str)`` — unrecoverable calibration error.

    Batch signals:

    image_processed
        ``(result: PipelineResult)`` — one image finished processing.
    progress_updated
        ``(current: int, total: int)`` — batch progress tick.
    batch_complete
        Emitted when all images in the batch have been processed.
    batch_error
        ``(message: str)`` — unrecoverable batch error.
    """

    # --- Calibration signals ---
    chip_detected = Signal(list, float)
    chip_detection_failed = Signal(str)
    text_regions_detected = Signal(list)
    roi_confirmed = Signal(QRectF)
    ocr_result_ready = Signal(str, float)
    calibration_complete = Signal(object)  # CalibrationData
    calibration_error = Signal(str)

    # --- Batch signals ---
    image_processed = Signal(object)  # PipelineResult
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
        """Begin calibration on the reference *image*.

        Triggers the first automatic step immediately (chip detection for
        Pipeline 1, or waits for user ROI for Pipeline 2).

        Parameters
        ----------
        image : Path
            Path to the first image in the batch.
        """

    def confirm_chip(self, accepted: bool, manual_polygon: list[tuple[float, float]] | None = None) -> None:
        """Respond to a :attr:`chip_detected` or :attr:`chip_detection_failed` signal.

        Parameters
        ----------
        accepted : bool
            ``True`` to accept the detected polygon; ``False`` to retry or
            use *manual_polygon*.
        manual_polygon : list[tuple[float, float]] | None
            User-drawn polygon corners in image pixel space.  Used when
            ``accepted`` is ``False`` and the user chose to draw manually.
        """

    def set_roi(self, rect: QRectF) -> None:
        """Supply the user-drawn ROI rectangle (Pipeline 2 calibration start).

        Parameters
        ----------
        rect : QRectF
            Rectangle in image pixel coordinates.
        """

    def confirm_roi(self, accepted: bool, manual_rect: QRectF | None = None) -> None:
        """Respond to a :attr:`roi_confirmed` signal.

        Parameters
        ----------
        accepted : bool
            ``True`` to accept the snapped region.
        manual_rect : QRectF | None
            Used when ``accepted`` is ``False`` and the user chose to draw
            the region manually.
        """

    def select_identifier_region(
        self,
        region_index: int | None = None,
        manual_rect: QRectF | None = None,
    ) -> None:
        """Respond to a :attr:`text_regions_detected` signal.

        Parameters
        ----------
        region_index : int | None
            Index into the list supplied by the signal, or ``None`` for
            manual drawing.
        manual_rect : QRectF | None
            User-drawn rectangle; used when ``region_index`` is ``None``.
        """

    def confirm_ocr_result(self, text: str) -> None:
        """Respond to a :attr:`ocr_result_ready` signal.

        Parameters
        ----------
        text : str
            Confirmed (possibly user-corrected) identifier text.
        """

    # ------------------------------------------------------------------
    # Batch processing interface
    # ------------------------------------------------------------------

    @abstractmethod
    def start_batch(self, images: list[Path], calib: CalibrationData, min_confidence: float) -> None:
        """Process *images* using the calibration reference *calib*.

        Emits :attr:`image_processed` for each image and
        :attr:`batch_complete` when done.

        Parameters
        ----------
        images : list[Path]
            Images to process (the reference image must be excluded).
        calib : CalibrationData
            Reference data from the calibration phase.
        min_confidence : float
            Results with confidence below this value are classified as
            :attr:`ResultStatus.FAILED`.
        """

    def stop(self) -> None:
        """Request a graceful abort of any ongoing processing."""
        self._stopped = True
