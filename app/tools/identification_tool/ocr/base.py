"""Abstract OCR engine wrapper."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from PySide6.QtGui import QImage


@dataclass
class OcrResult:
    """Result of a text recognition call.

    Attributes
    ----------
    text : str
        Recognised character sequence (may be empty).
    confidence : float
        Overall confidence in ``[0.0, 1.0]``.  ``-1.0`` if the engine
        does not report confidence.
    """

    text: str
    confidence: float


@dataclass
class DetectedRegion:
    """A single text region returned by a text detection call.

    All coordinates are in pixel space of the image passed to
    :meth:`AbstractOcrEngine.detect_text_regions`.

    Attributes
    ----------
    x, y : float
        Top-left corner.
    width, height : float
        Region dimensions.
    confidence : float
        Detection confidence in ``[0.0, 1.0]``.
    """

    x: float
    y: float
    width: float
    height: float
    confidence: float = 1.0


class AbstractOcrEngine(ABC):
    """Shared interface for text detection and recognition backends.

    A concrete engine wraps one external library (PaddleOCR, EasyOCR, …)
    and normalises its output into :class:`DetectedRegion` /
    :class:`OcrResult` objects.

    Images are passed as :class:`PySide6.QtGui.QImage`.  Concrete
    implementations that require numpy arrays should convert internally
    (e.g. ``np.frombuffer(image.bits(), dtype=np.uint8)``).
    """

    @abstractmethod
    def detect_text_regions(self, image: QImage) -> list[DetectedRegion]:
        """Locate all text regions in *image*.

        Parameters
        ----------
        image : QImage
            Greyscale or RGB image.

        Returns
        -------
        list[DetectedRegion]
            Detected regions, possibly empty.
        """

    @abstractmethod
    def recognize_text(self, image: QImage) -> OcrResult:
        """Decode the text contained in *image*.

        Parameters
        ----------
        image : QImage
            Tightly cropped image of a single text region, already
            preprocessed (deskewed, normalised).

        Returns
        -------
        OcrResult
            Recognised text and confidence.
        """
