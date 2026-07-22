"""Tesseract concrete operator (spec Section 6.3).

Implements :class:`~app.tools.scibit.core.operations.TextRecognition`
using pytesseract (Tesseract 4+ OCR engine).

Configuration:
- ``--psm 7`` — single text line mode, suitable for identifier strings.
- ``charset_hint`` is mapped to Tesseract's ``tessedit_char_whitelist``
  configuration variable so OCR is constrained to the expected character set.

The Tesseract binary is verified at operator construction time via
``pytesseract.get_tesseract_version()``.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
from numpy.typing import NDArray

from app.tools.scibit.core.operations import TextRecognition
from app.tools.scibit.core.registry import register_operator
from app.tools.scibit.operators._utils import ensure_gray

_log = logging.getLogger(__name__)


@register_operator([TextRecognition])
class TesseractOperator(TextRecognition):
    """Tesseract-backed OCR operator for single-line identifier recognition.

    Uses ``--psm 7`` (single line) and applies ``tessedit_char_whitelist``
    when a ``charset_hint`` is provided.  Confidence is averaged across
    all word boxes returned by ``image_to_data``.
    """

    def __init__(self) -> None:
        self._verified = False

    @classmethod
    def get_param_schema(cls, operation: type | None) -> list:
        """Return the dynamic UI parameter schema for *operation*."""
        from app.tools.scibit.core.stage import ParamSpec

        if operation is TextRecognition:
            return [
                ParamSpec(
                    key="lang",
                    label="Language",
                    type="choice",
                    options=[("English", "eng"), ("German", "deu")],
                    default="eng",
                ),
                ParamSpec(
                    key="psm",
                    label="PSM",
                    type="choice",
                    options=[
                        ("6 — Uniform text block", 6),
                        ("7 — Single text line", 7),
                        ("8 — Single word", 8),
                        ("11 — Sparse text", 11),
                        ("13 — Raw line", 13),
                    ],
                    default=7,
                    tooltip="Tesseract page segmentation mode",
                ),
                ParamSpec(
                    key="oem",
                    label="OEM",
                    type="choice",
                    options=[
                        ("3 — Default", 3),
                        ("1 — LSTM only", 1),
                        ("0 — Legacy only", 0),
                        ("2 — Legacy + LSTM", 2),
                    ],
                    default=3,
                    tooltip="Tesseract OCR engine mode",
                ),
            ]
        return []

    # ------------------------------------------------------------------
    # TextRecognition
    # ------------------------------------------------------------------

    def recognise_text(
        self,
        image: NDArray[np.uint8],
        params: dict,
        charset_hint: set[str] | None = None,
    ) -> tuple[str, float]:
        """Recognise a single identifier line in *image*.

        Returns
        -------
        tuple[str, float]
            Concatenated recognised text and mean word confidence (0–100).
        """
        try:
            import pytesseract  # type: ignore[import]
            from pytesseract import Output
        except ImportError as exc:
            raise RuntimeError(
                "pytesseract is not installed. Install it with: pip install pytesseract"
            ) from exc

        self._ensure_binary_available(pytesseract)

        psm = int(params.get("psm", 7))
        oem = int(params.get("oem", 3))
        lang = str(params.get("lang", "eng"))

        config_parts = [f"--psm {psm}", f"--oem {oem}"]
        if charset_hint:
            whitelist = "".join(sorted(charset_hint))
            config_parts.append(f"-c tessedit_char_whitelist={whitelist}")

        config_str = " ".join(config_parts)
        gray = ensure_gray(image)

        data = pytesseract.image_to_data(
            gray,
            lang=lang,
            config=config_str,
            output_type=Output.DICT,
        )

        words: list[str] = []
        confs: list[float] = []
        for text, conf in zip(data["text"], data["conf"]):
            text = str(text).strip()
            conf_val = float(conf)
            if text and conf_val >= 0:
                words.append(text)
                confs.append(conf_val)

        if not words:
            return "", 0.0

        combined = "".join(words)
        confidence = sum(confs) / len(confs)
        return combined, confidence

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_binary_available(self, pytesseract: Any) -> None:
        if not self._verified:
            try:
                pytesseract.get_tesseract_version()
                self._verified = True
            except Exception as exc:
                raise RuntimeError(
                    "Tesseract binary not found or not accessible. "
                    "Install Tesseract OCR and ensure it is on PATH."
                ) from exc

    # ------------------------------------------------------------------
    # Pool lifecycle
    # ------------------------------------------------------------------

    def release(self) -> None:
        """Reset verification state (no heavy resources held)."""
        self._verified = False
