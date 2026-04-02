"""Stub OCR engine for development and testing.

Returns predictable fake results so the UI and pipeline logic can be
exercised without any actual OCR library installed.
"""

from __future__ import annotations

from app.tools.extensions.identification_tool.ocr.base import (
    AbstractOcrEngine,
    DetectedRegion,
    OcrResult,
)


class StubOcrEngine(AbstractOcrEngine):
    """Fake OCR engine that returns hard-coded results.

    Useful during development and for unit tests.  Detects a single
    region at a fixed position and recognises it as ``"C001-01"`` with
    confidence 0.95.
    """

    def detect_text_regions(self, image: "np.ndarray") -> list[DetectedRegion]:  # type: ignore[name-defined]
        h, w = image.shape[:2]
        rw, rh = w * 0.20, h * 0.10
        rx, ry = (w - rw) / 2, (h - rh) / 2
        return [DetectedRegion(x=rx, y=ry, width=rw, height=rh, confidence=0.95)]

    def recognize_text(self, image: "np.ndarray") -> OcrResult:  # type: ignore[name-defined]
        return OcrResult(text="C001-01", confidence=0.95)
