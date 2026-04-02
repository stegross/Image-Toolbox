"""EasyOCR engine wrapper (requires ``easyocr``)."""

from __future__ import annotations

import logging

from PySide6.QtGui import QImage

from app.tools.extensions.identification_tool.ocr._convert import qimage_to_numpy_gray
from app.tools.extensions.identification_tool.ocr.base import (
    AbstractOcrEngine,
    DetectedRegion,
    OcrResult,
)

_logger = logging.getLogger("vi_toolbox.tools.scibit.ocr.easyocr")


class EasyOcrEngine(AbstractOcrEngine):
    """OCR engine backed by `EasyOCR <https://github.com/JaidedAI/EasyOCR>`_.

    Requires:
    - ``pip install easyocr``

    The reader is initialised for English only without GPU.  Model weights
    are downloaded on first use.

    Raises
    ------
    ImportError
        If ``easyocr`` is not installed.
    """

    def __init__(self) -> None:
        try:
            import easyocr  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "easyocr is not installed. Run: pip install easyocr"
            ) from exc
        self._reader = easyocr.Reader(["en"], gpu=False, verbose=False)
        _logger.info("EasyOcrEngine initialised.")

    def detect_text_regions(self, image: QImage) -> list[DetectedRegion]:
        arr = qimage_to_numpy_gray(image)
        results = self._reader.readtext(arr, detail=1)
        regions: list[DetectedRegion] = []
        for bbox, _text, conf in results:
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
        # paragraph=False keeps individual word results with per-word confidence.
        results = self._reader.readtext(arr, detail=1, paragraph=False)
        if not results:
            return OcrResult(text="", confidence=0.0)
        texts: list[str] = []
        confs: list[float] = []
        for _bbox, text, conf in results:
            if str(text).strip():
                texts.append(str(text).strip())
                confs.append(float(conf))
        combined = " ".join(texts)
        avg_conf = sum(confs) / len(confs) if confs else 0.0
        return OcrResult(text=combined, confidence=avg_conf)
