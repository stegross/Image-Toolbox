"""Tesseract OCR engine wrapper (requires ``pytesseract`` + Tesseract binary)."""

from __future__ import annotations

import logging

from PySide6.QtGui import QImage

from app.tools.extensions.identification_tool.ocr._convert import qimage_to_numpy_gray
from app.tools.extensions.identification_tool.ocr.base import (
    AbstractOcrEngine,
    DetectedRegion,
    OcrResult,
)

_logger = logging.getLogger("vi_toolbox.tools.scibit.ocr.tesseract")


class TesseractEngine(AbstractOcrEngine):
    """OCR engine backed by `pytesseract <https://github.com/madmaze/pytesseract>`_.

    Requires:
    - ``pip install pytesseract``
    - Tesseract binary installed and on PATH (or ``pytesseract.pytesseract.tesseract_cmd`` set).

    Raises
    ------
    ImportError
        If ``pytesseract`` is not installed.
    RuntimeError
        If the Tesseract binary cannot be found.
    """

    def __init__(self) -> None:
        try:
            import pytesseract  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "pytesseract is not installed. Run: pip install pytesseract"
            ) from exc
        # Verify the binary is reachable — raises on failure.
        try:
            pytesseract.get_tesseract_version()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"Tesseract binary not found or not accessible: {exc}"
            ) from exc
        self._tess = pytesseract
        _logger.info("TesseractEngine initialised (version %s).", pytesseract.get_tesseract_version())

    def detect_text_regions(self, image: QImage) -> list[DetectedRegion]:
        arr = qimage_to_numpy_gray(image)
        data = self._tess.image_to_data(arr, output_type=self._tess.Output.DICT)
        regions: list[DetectedRegion] = []
        for i, text in enumerate(data["text"]):
            conf = int(data["conf"][i])
            if conf < 0 or not str(text).strip():
                continue
            regions.append(
                DetectedRegion(
                    x=float(data["left"][i]),
                    y=float(data["top"][i]),
                    width=float(data["width"][i]),
                    height=float(data["height"][i]),
                    confidence=conf / 100.0,
                )
            )
        return regions

    def recognize_text(self, image: QImage) -> OcrResult:
        arr = qimage_to_numpy_gray(image)
        # --psm 7 = single text line, best for a tightly cropped identifier.
        data = self._tess.image_to_data(
            arr,
            config="--psm 7",
            output_type=self._tess.Output.DICT,
        )
        texts: list[str] = []
        confs: list[float] = []
        for i, text in enumerate(data["text"]):
            conf = int(data["conf"][i])
            if conf < 0 or not str(text).strip():
                continue
            texts.append(str(text).strip())
            confs.append(conf / 100.0)
        combined = " ".join(texts)
        avg_conf = sum(confs) / len(confs) if confs else 0.0
        return OcrResult(text=combined, confidence=avg_conf)
