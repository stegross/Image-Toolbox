"""Factory for creating OCR engine instances by framework name."""

from __future__ import annotations

import importlib

from app.tools.extensions.identification_tool.ocr.base import AbstractOcrEngine

# Maps the display name (as shown in the UI) to (module, class).
_ENGINE_MAP: dict[str, tuple[str, str]] = {
    "Tesseract": (
        "app.tools.extensions.identification_tool.ocr.tesseract",
        "TesseractEngine",
    ),
    "PaddleOCR": (
        "app.tools.extensions.identification_tool.ocr.paddleocr_engine",
        "PaddleOcrEngine",
    ),
    "EasyOCR": (
        "app.tools.extensions.identification_tool.ocr.easyocr_engine",
        "EasyOcrEngine",
    ),
}


def available_frameworks() -> list[str]:
    """Return the ordered list of supported framework display names."""
    return list(_ENGINE_MAP)


def create_engine(name: str) -> AbstractOcrEngine:
    """Instantiate and return the engine for *name*.

    Parameters
    ----------
    name : str
        Display name of the framework (e.g. ``"Tesseract"``).

    Returns
    -------
    AbstractOcrEngine
        Ready-to-use engine instance.

    Raises
    ------
    ValueError
        If *name* is not a known framework.
    ImportError
        If the required library is not installed.
    RuntimeError
        If the engine fails to initialise (e.g. missing binary).
    """
    if name not in _ENGINE_MAP:
        raise ValueError(
            f"Unknown OCR framework {name!r}. "
            f"Available: {list(_ENGINE_MAP)}"
        )
    module_path, class_name = _ENGINE_MAP[name]
    module = importlib.import_module(module_path)
    engine_cls = getattr(module, class_name)
    return engine_cls()
