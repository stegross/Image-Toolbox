"""PaddleOCR v3.x concrete operator (spec Section 6.3).

Implements :class:`~app.tools.scibit.core.operations.TextRegionDetection`
and :class:`~app.tools.scibit.core.operations.TextRecognition` using
PaddleOCR's unified ``predict()`` API (v3.x).

Two independent model caches are held — one for detection calls, one
for recognition calls — so the two stages can pick different model
backbones without thrashing each other's PaddleOCR instance.  Each
cache is keyed on (resolved model name, gpu) and a model is only
rebuilt when *its own* parameters change.

The PaddleOCR model is created lazily on first use so startup cost is
deferred until the operator is actually invoked.  The ``PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK``
environment variable must be set **before** the paddleocr package is
imported; this module sets it at import time.

Language resolution: PaddleOCR ignores the ``lang`` argument as soon as
an explicit ``text_recognition_model_name`` is passed (it emits a
warning and falls back to the model's built-in character dict, which is
Chinese-default for the unprefixed ``PP-OCRv5_*_rec`` models).  The
recognition dropdown therefore stores a size token (``mobile`` /
``server``) and the operator maps ``(lang, size)`` to the correct
language-prefixed model name before calling PaddleOCR.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import numpy as np
from numpy.typing import NDArray

# Must be set before importing paddleocr.
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

from app.tools.scibit.core.operations import TextRecognition, TextRegionDetection
from app.tools.scibit.core.registry import register_operator
from app.tools.scibit.core.types import BoundingBox
from app.tools.scibit.operators._utils import ensure_rgb

_log = logging.getLogger(__name__)


@register_operator([TextRegionDetection, TextRecognition])
class PaddleOCROperator(TextRegionDetection, TextRecognition):
    """PaddleOCR-backed OCR operator for text region detection and recognition.

    A single PaddleOCR model handles both detection and recognition via
    ``predict()``.  The model is initialised lazily on the first call.
    """

    def __init__(self) -> None:
        # Separate cache slots for the two operations so the detection
        # and recognition stages don't invalidate each other's model.
        self._det_inst: Any = None
        self._det_key: str = ""
        self._rec_inst: Any = None
        self._rec_key: str = ""

    # Resolution table for PP-OCRv5 recognition models.  Mirrors PaddleOCR's
    # own ``_get_ocr_model_names`` logic (see paddleocr/_pipelines/ocr.py):
    # only the *mobile* recognizer ships language-specific variants
    # (``en_*``, ``latin_*``).  The *server* recognizer exists solely as the
    # generic multilingual ``PP-OCRv5_server_rec``, so every language maps to
    # it regardless of selection.
    _REC_MODEL_BY_LANG_SIZE: dict[tuple[str, str], str] = {
        ("en", "mobile"): "en_PP-OCRv5_mobile_rec",
        ("en", "server"): "PP-OCRv5_server_rec",
        ("german", "mobile"): "latin_PP-OCRv5_mobile_rec",
        ("german", "server"): "PP-OCRv5_server_rec",
    }

    @staticmethod
    def _resolve_rec_model_name(lang: str, size: str) -> str:
        """Map a ``(lang, size)`` UI selection to the actual PaddleOCR model name.

        *size* is normalised to a ``mobile`` / ``server`` token first.
        Configs saved by an older build stored the *full* PaddleOCR model
        name (e.g. ``PP-OCRv5_server_rec``) under ``rec_model``, so any
        string containing ``server`` is treated as the server size and
        everything else as mobile.
        """
        size = "server" if "server" in size.lower() else "mobile"
        try:
            return PaddleOCROperator._REC_MODEL_BY_LANG_SIZE[(lang, size)]
        except KeyError:
            _log.warning(
                "No PP-OCRv5 rec model mapping for (lang=%s, size=%s); "
                "falling back to en_PP-OCRv5_mobile_rec.",
                lang,
                size,
            )
            return "en_PP-OCRv5_mobile_rec"

    @classmethod
    def get_param_schema(cls, operation: type | None) -> list:
        """Return the dynamic UI parameter schema for *operation*.

        The schema branches per operation: the detection stage exposes
        only detection-backbone choices and the recognition stage only
        recognition-backbone choices.  Sharing a single schema between
        them was the bug that caused model-cache thrashes — both stages
        would write to the same ``det_model`` key, and any divergence
        forced a full PaddleOCR rebuild on every cross-stage call.
        """
        from app.tools.scibit.core.stage import ParamSpec

        if operation not in (TextRegionDetection, TextRecognition):
            return []

        lang_spec = ParamSpec(
            key="paddle_lang",
            label="Language",
            type="choice",
            options=[("English", "en"), ("German", "german")],
            default="en",
        )
        gpu_spec = ParamSpec(
            key="gpu",
            label="GPU",
            type="choice",
            options=[("Disabled", False), ("Enabled", True)],
            default=False,
        )

        if operation is TextRegionDetection:
            return [
                lang_spec,
                ParamSpec(
                    key="det_model",
                    label="Det. Model",
                    type="choice",
                    options=[
                        ("Mobile v5 (fast)", "PP-OCRv5_mobile_det"),
                        ("Server v5 (accurate)", "PP-OCRv5_server_det"),
                    ],
                    default="PP-OCRv5_mobile_det",
                    tooltip="PaddleOCR text-detection backbone.",
                ),
                gpu_spec,
            ]

        # TextRecognition
        return [
            lang_spec,
            ParamSpec(
                key="rec_model",
                label="Rec. Model",
                type="choice",
                options=[
                    ("Mobile v5 (fast)", "mobile"),
                    ("Server v5 (accurate)", "server"),
                ],
                default="mobile",
                tooltip=(
                    "PaddleOCR text-recognition size. The actual model is "
                    "resolved from (language, size); only the mobile "
                    "recognizer is language-specific, while server always "
                    "uses the generic multilingual PP-OCRv5_server_rec."
                ),
            ),
            gpu_spec,
        ]

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
            List of ``(x, y, width, height)`` bounding boxes, one per
            detected text region.
        """
        model = self._get_det_model(params)
        rgb = ensure_rgb(image)
        results = model.predict(rgb)

        boxes: list[BoundingBox] = []
        if not results:
            return boxes

        for item in results:
            polys = item.get("dt_polys", [])
            for poly in polys:
                pts = np.array(poly, dtype=np.float32)
                x, y, w, h = cv2_bounding_rect(pts)
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

        *charset_hint* is accepted for API compatibility but PaddleOCR does
        not support character whitelisting directly; it is ignored here.

        Returns
        -------
        tuple[str, float]
            Concatenated recognised text and mean confidence (0–100).
        """
        model = self._get_rec_model(params)
        rgb = ensure_rgb(image)
        results = model.predict(rgb)

        if not results:
            return "", 0.0

        texts: list[str] = []
        scores: list[float] = []

        for item in results:
            for text, score in zip(
                item.get("rec_texts", []),
                item.get("rec_scores", []),
            ):
                if text:
                    texts.append(str(text))
                    scores.append(float(score))

        if not texts:
            return "", 0.0

        combined = " ".join(texts)
        confidence = (sum(scores) / len(scores)) * 100.0
        return combined, confidence

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_det_model(self, params: dict) -> Any:
        """Return the PaddleOCR instance for the detection stage's params."""
        det_model = str(params.get("det_model", "PP-OCRv5_mobile_det"))
        gpu = bool(params.get("gpu", False))
        key = f"det={det_model},gpu={gpu}"

        if self._det_inst is None or self._det_key != key:
            self._det_inst = self._build_model(gpu=gpu, text_detection_model_name=det_model)
            self._det_key = key
        return self._det_inst

    def _get_rec_model(self, params: dict) -> Any:
        """Return the PaddleOCR instance for the recognition stage's params."""
        lang = str(params.get("paddle_lang", "en"))
        size = str(params.get("rec_model", "mobile"))
        gpu = bool(params.get("gpu", False))
        rec_model = self._resolve_rec_model_name(lang, size)
        key = f"rec={rec_model},gpu={gpu}"

        if self._rec_inst is None or self._rec_key != key:
            self._rec_inst = self._build_model(gpu=gpu, text_recognition_model_name=rec_model)
            self._rec_key = key
        return self._rec_inst

    def _build_model(self, *, gpu: bool, **model_overrides: Any) -> Any:
        """Instantiate a PaddleOCR pipeline with the common defaults applied.

        ``lang`` is intentionally not forwarded: PaddleOCR ignores it
        whenever an explicit model name is given (it warns and falls
        back to the model's built-in dict), so language is encoded by
        resolving to the correct ``text_recognition_model_name``
        upstream in :meth:`_get_rec_model`.
        """
        try:
            from paddleocr import PaddleOCR  # type: ignore[import]
        except ImportError as exc:
            raise RuntimeError(
                "PaddleOCR is not installed. Install it with: pip install paddleocr"
            ) from exc

        device = "gpu" if gpu else "cpu"
        _log.debug(
            "Initialising PaddleOCR (device=%s, overrides=%s).",
            device,
            model_overrides,
        )
        return PaddleOCR(
            device=device,
            enable_mkldnn=False,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            **model_overrides,
        )

    # ------------------------------------------------------------------
    # Pool lifecycle
    # ------------------------------------------------------------------

    def release(self) -> None:
        """Release both cached PaddleOCR instances."""
        self._det_inst = None
        self._det_key = ""
        self._rec_inst = None
        self._rec_key = ""


def cv2_bounding_rect(pts: np.ndarray) -> BoundingBox:
    """Convert a polygon point array to an axis-aligned bounding box."""
    import cv2

    pts_int = pts.reshape(-1, 1, 2).astype(np.int32)
    x, y, w, h = cv2.boundingRect(pts_int)
    return (x, y, w, h)
