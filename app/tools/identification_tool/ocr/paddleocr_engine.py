"""PaddleOCR engine wrapper (requires ``paddleocr``)."""

from __future__ import annotations

import logging

from PySide6.QtGui import QImage

from app.tools.identification_tool.ocr._convert import qimage_to_numpy_rgb
from app.tools.identification_tool.ocr.base import (
    AbstractOcrEngine,
    DetectedRegion,
    OcrResult,
)

_logger = logging.getLogger("vi_toolbox.tools.scibit.ocr.paddleocr")


class PaddleOcrEngine(AbstractOcrEngine):
    """OCR engine backed by `PaddleOCR <https://github.com/PaddlePaddle/PaddleOCR>`_.

    Requires:
    - ``pip install paddleocr paddlepaddle``

    Raises
    ------
    ImportError
        If ``paddleocr`` is not installed.
    """

    def __init__(self) -> None:
        import os
        # Must be set before importing paddleocr — the connectivity check runs at import time
        os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
        try:
            from paddleocr import PaddleOCR  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "paddleocr is not installed. Run: pip install paddleocr paddlepaddle"
            ) from exc
        # Lightweight config for chip crops:
        # - Mobile detection model instead of server (much smaller, faster)
        # - Document orientation + unwarping disabled (not needed for chip images)
        # - Angle classification disabled (chips are upright)
        # - oneDNN disabled (unimplemented ops on Windows with PP-OCRv5)
        self._ocr = PaddleOCR(
            lang="en",
            enable_mkldnn=False,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            text_detection_model_name="PP-OCRv5_mobile_det",
            text_det_limit_side_len=1920,
            text_det_limit_type="max",
        )
        _logger.info("PaddleOcrEngine initialised.")

    @staticmethod
    def _unpack(result: list) -> tuple[list, list, list]:
        """Extract parallel lists of polygons, texts and scores from a v3.x result dict."""
        d = result[0] if result else {}
        if not isinstance(d, dict):
            return [], [], []
        return (
            d.get("dt_polys") or [],
            d.get("rec_texts") or [],
            d.get("rec_scores") or [],
        )

    def detect_text_regions(self, image: QImage) -> list[DetectedRegion]:
        arr = qimage_to_numpy_rgb(image)
        result = self._ocr.predict(arr)
        polys, _, scores = self._unpack(result)
        regions: list[DetectedRegion] = []
        for bbox, conf in zip(polys, scores):
            xs = [p[0] for p in bbox]
            ys = [p[1] for p in bbox]
            x, y = min(xs), min(ys)
            regions.append(DetectedRegion(x=x, y=y, width=max(xs) - x, height=max(ys) - y, confidence=float(conf)))
        return regions

    def recognize_text(self, image: QImage) -> OcrResult:
        arr = qimage_to_numpy_rgb(image)
        result = self._ocr.predict(arr)
        _, texts, scores = self._unpack(result)
        texts_out: list[str] = []
        confs_out: list[float] = []
        for text, conf in zip(texts, scores):
            if str(text).strip():
                texts_out.append(str(text).strip())
                confs_out.append(float(conf))
        combined = " ".join(texts_out)
        avg_conf = sum(confs_out) / len(confs_out) if confs_out else 0.0
        return OcrResult(text=combined, confidence=avg_conf)
