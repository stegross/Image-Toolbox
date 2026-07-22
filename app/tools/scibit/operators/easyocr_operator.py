"""EasyOCR concrete operator (spec Section 6.3).

Implements :class:`~app.tools.scibit.core.operations.TextRegionDetection`
and :class:`~app.tools.scibit.core.operations.TextRecognition` using the
EasyOCR library.

The ``easyocr.Reader`` is initialised lazily on first use.  EasyOCR
accepts greyscale arrays directly via ``readtext()``.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
from numpy.typing import NDArray

from app.tools.scibit.core.operations import TextRecognition, TextRegionDetection
from app.tools.scibit.core.registry import register_operator
from app.tools.scibit.core.types import BoundingBox
from app.tools.scibit.operators._utils import ensure_gray

_log = logging.getLogger(__name__)


@register_operator([TextRegionDetection, TextRecognition])
class EasyOCROperator(TextRegionDetection, TextRecognition):
    """EasyOCR-backed operator for text detection and recognition.

    A single ``easyocr.Reader`` instance is shared across calls and
    initialised on first use (lazy loading).
    """

    def __init__(self) -> None:
        self._reader: Any = None
        self._lang_key: str = ""

    @classmethod
    def get_param_schema(cls, operation: type | None) -> list:
        """Return the dynamic UI parameter schema for *operation*."""
        from app.tools.scibit.core.stage import ParamSpec

        languages_spec = ParamSpec(
            key="languages",
            label="Language",
            type="choice",
            options=[("English", ["en"]), ("German", ["de"])],
            default=["en"],
        )
        gpu_spec = ParamSpec(
            key="gpu",
            label="GPU",
            type="choice",
            options=[("Disabled", False), ("Enabled", True)],
            default=False,
        )

        if operation is TextRegionDetection:
            return [languages_spec, gpu_spec]
        if operation is TextRecognition:
            return [
                languages_spec,
                ParamSpec(
                    key="decoder",
                    label="Decoder",
                    type="choice",
                    options=[
                        ("Greedy", "greedy"),
                        ("Beam Search", "beamsearch"),
                        ("Word Beam Search", "wordbeamsearch"),
                    ],
                    default="greedy",
                    tooltip="EasyOCR decoding algorithm",
                ),
                gpu_spec,
            ]
        return []

    # ------------------------------------------------------------------
    # TextRegionDetection
    # ------------------------------------------------------------------

    def detect_text_regions(
        self,
        image: NDArray[np.uint8],
        params: dict,
    ) -> list[BoundingBox]:
        """Detect text bounding boxes in *image*.

        Returns
        -------
        list[BoundingBox]
            List of ``(x, y, width, height)`` bounding boxes.
        """
        reader = self._get_reader(params)
        gray = ensure_gray(image)
        raw = reader.readtext(gray, detail=1)

        boxes: list[BoundingBox] = []
        for bbox_pts, _text, _conf in raw:
            pts = np.array(bbox_pts, dtype=np.float32)
            xs = pts[:, 0]
            ys = pts[:, 1]
            x = int(xs.min())
            y = int(ys.min())
            w = int(xs.max() - xs.min())
            h = int(ys.max() - ys.min())
            boxes.append((x, y, w, h))

        return boxes

    # ------------------------------------------------------------------
    # TextRecognition
    # ------------------------------------------------------------------

    def recognise_text(
        self,
        image: NDArray[np.uint8],
        params: dict,
        charset_hint: set[str] | None = None,
    ) -> tuple[str, float]:
        """Recognise text in *image* and return ``(text, confidence)``.

        Returns
        -------
        tuple[str, float]
            Concatenated text and mean confidence (0–100).
        """
        reader = self._get_reader(params)
        gray = ensure_gray(image)

        allowlist: str | None = None
        if charset_hint:
            allowlist = "".join(sorted(charset_hint))

        decoder = str(params.get("decoder", "greedy"))
        raw = reader.readtext(gray, detail=1, allowlist=allowlist, decoder=decoder)

        if not raw:
            return "", 0.0

        texts = [str(text) for _, text, _ in raw if text]
        scores = [float(conf) for _, _, conf in raw]

        if not texts:
            return "", 0.0

        combined = " ".join(texts)
        confidence = (sum(scores) / len(scores)) * 100.0
        return combined, confidence

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_reader(self, params: dict) -> Any:
        languages = params.get("languages", ["en"])
        gpu = bool(params.get("gpu", False))
        lang_key = ",".join(sorted(languages)) + f":gpu={gpu}"

        if self._reader is None or self._lang_key != lang_key:
            try:
                import easyocr  # type: ignore[import]
            except ImportError as exc:
                raise RuntimeError(
                    "EasyOCR is not installed. Install it with: pip install easyocr"
                ) from exc

            _log.debug("Initialising EasyOCR reader (languages=%s, gpu=%s).", languages, gpu)
            self._reader = easyocr.Reader(languages, gpu=gpu, verbose=False)
            self._lang_key = lang_key

        return self._reader

    # ------------------------------------------------------------------
    # Pool lifecycle
    # ------------------------------------------------------------------

    def release(self) -> None:
        """Release the EasyOCR reader."""
        self._reader = None
        self._lang_key = ""
