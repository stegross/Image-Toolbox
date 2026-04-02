"""PaddleOCR engine wrapper (requires ``paddleocr``)."""

from __future__ import annotations

import logging

from PySide6.QtGui import QImage

from app.tools.extensions.identification_tool.ocr._convert import qimage_to_numpy_gray
from app.tools.extensions.identification_tool.ocr.base import (
    AbstractOcrEngine,
    DetectedRegion,
    OcrResult,
)

_logger = logging.getLogger("vi_toolbox.tools.scibit.ocr.paddleocr")


class PaddleOcrEngine(AbstractOcrEngine):
    """OCR engine backed by `PaddleOCR <https://github.com/PaddlePaddle/PaddleOCR>`_.

    Requires:
    - ``pip install paddleocr``

    The engine is initialised in English-only mode with angle classification
    enabled (handles ±90° rotations) and logging suppressed.

    Raises
    ------
    ImportError
        If ``paddleocr`` is not installed.
    """

    def __init__(self) -> None:
        try:
            from paddleocr import PaddleOCR  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "paddleocr is not installed. Run: pip install paddleocr"
            ) from exc
        self._ocr = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
        _logger.info("PaddleOcrEngine initialised.")

    def detect_text_regions(self, image: QImage) -> list[DetectedRegion]:
        arr = qimage_to_numpy_gray(image)
        result = self._ocr.ocr(arr, cls=True)
        if not result or not result[0]:
            return []
        regions: list[DetectedRegion] = []
        for line in result[0]:
            bbox, (_text, conf) = line
            xs = [p[0] for p in bbox]
            ys = [p[1] for p in bbox]
            x, y = min(xs), min(ys)
            regions.append(
                DetectedRegion(
                    x=x,
                    y=y,
                    width=max(xs) - x,
                    height=max(ys) - y,
                    confidence=float(conf),
                )
            )
        return regions

    def recognize_text(self, image: QImage) -> OcrResult:
        arr = qimage_to_numpy_gray(image)
        result = self._ocr.ocr(arr, cls=True)
        if not result or not result[0]:
            return OcrResult(text="", confidence=0.0)
        texts: list[str] = []
        confs: list[float] = []
        for line in result[0]:
            _bbox, (text, conf) = line
            if str(text).strip():
                texts.append(str(text).strip())
                confs.append(float(conf))
        combined = " ".join(texts)
        avg_conf = sum(confs) / len(confs) if confs else 0.0
        return OcrResult(text=combined, confidence=avg_conf)
