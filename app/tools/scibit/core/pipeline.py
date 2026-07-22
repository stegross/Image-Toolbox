"""Pipeline abstract base class (spec Section 3.5).

The Pipeline base class implements the **Template Method** pattern:

- ``get_stages()`` and ``_process_single_image()`` are abstract — each
  concrete pipeline subclass defines its own stage sequence and image
  processing.
- ``run_batch()`` implements the surrounding batch loop (per-batch context
  setup, per-image dispatch, signal emission).

PySide6 signals decouple batch progress from the UI (Observer pattern).

No UI code, no concrete operators, no concrete pipelines in this module.
"""

from __future__ import annotations

import logging
import math
import re
from abc import abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

import cv2
import numpy as np
from numpy.typing import NDArray
from PySide6.QtCore import QObject, Signal

from app.tools.scibit.core.pool import OperatorPool
from app.tools.scibit.core.types import (
    BatchResult,
    DebugExportMode,
    ProcessingOutcome,
)

if TYPE_CHECKING:
    from app.tools.scibit.config.config import Configuration, PipelineOptions
    from app.tools.scibit.config.preset import IdentifierPatternPresetRegistry
    from app.tools.scibit.core.session import CalibrationSession
    from app.tools.scibit.core.stage import Stage

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class BatchContext:
    """Per-batch runtime context — built once in :meth:`Pipeline.run_batch`.

    Encapsulates the ephemeral state of a single batch run (regex, charset
    hint, debug directory) so it does not have to live on the
    :class:`~app.tools.scibit.core.session.CalibrationSession`, which is
    conceptually the immutable output of calibration.
    """

    regex: str
    charset_hint: set[str] | None
    debug_dir: Path | None


class Pipeline(QObject):
    """Abstract pipeline base class.

    Subclasses must implement :meth:`get_stages` and
    :meth:`_process_single_image`.

    Parameters
    ----------
    options : PipelineOptions
        Pipeline-level configuration (preset, rotation, threshold, etc.).
    preset_registry : IdentifierPatternPresetRegistry
        Registry used to resolve the active identifier pattern preset.

    Signals
    -------
    progress_updated(current: int, total: int)
        Emitted after each image is processed.  ``current`` is 1-based.
    image_completed(filename: str, result: BatchResult)
        Emitted once per processed image.
    batch_completed(results: list[BatchResult])
        Emitted once when the full batch finishes.
    """

    #: JSON-stable slug used both as the visible label in the pipeline
    #: combo and as the ``"pipeline"`` key in saved configuration files.
    #: Concrete subclasses MUST set this (declare with ``Final`` so the
    #: type checker flags accidental reassignment in deeper subclasses).
    #: The value must never change once shipped, or saved configs will
    #: fail to map back to a class.
    PIPELINE_ID: ClassVar[str] = ""

    progress_updated = Signal(int, int)
    image_completed = Signal(str, object)  # (filename, BatchResult)
    batch_completed = Signal(list)  # list[BatchResult]

    # ------------------------------------------------------------------
    # Subclass discovery
    # ------------------------------------------------------------------

    @classmethod
    def for_id(cls, pipeline_id: str) -> type[Pipeline] | None:
        """Return the registered subclass whose ``PIPELINE_ID`` matches.

        Walks :meth:`type.__subclasses__` so newly-added pipeline modules
        are discovered automatically once their module has been imported
        (see :mod:`app.tools.scibit.pipelines`). Returns ``None`` when
        no match is found — callers handle missing pipelines explicitly
        rather than silently substituting a default.
        """
        for sub in cls.__subclasses__():
            if sub.PIPELINE_ID == pipeline_id:
                return sub
        return None

    def __init__(
        self,
        options: PipelineOptions,
        preset_registry: IdentifierPatternPresetRegistry,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._options = options
        self._preset_registry = preset_registry
        # Cooperative cancellation flag — set from any thread via cancel(),
        # checked by run_batch between images. Bool writes are GIL-atomic
        # in CPython so no lock is needed.
        self._cancelled = False

        # Pool is created first; stages are initialised next and receive the
        # pool reference.  Both are set up here so the pipeline is fully
        # functional after __init__ completes.
        self._pool = OperatorPool(self)
        self._stages: list[Stage] = self._init_stages()

    # ------------------------------------------------------------------
    # Abstract interface — subclasses must implement
    # ------------------------------------------------------------------

    @abstractmethod
    def get_stages(self) -> list[Stage]:
        """Return the ordered list of stages for this pipeline.

        Each call must return the **same** list that was created during
        ``__init__`` (after :meth:`_init_stages` has run).  Subclasses
        should cache the stage list rather than rebuilding it on each call.
        """

    @abstractmethod
    def _process_single_image(
        self,
        image_path: Path,
        session: CalibrationSession,
        ctx: BatchContext,
    ) -> BatchResult:
        """Process one image and return its :class:`BatchResult`.

        Implementations are responsible for the full pipeline: loading,
        preprocessing, threading the image through stages, classifying the
        outcome, and (optionally) writing debug images to ``ctx.debug_dir``.
        """

    # ------------------------------------------------------------------
    # Factory classmethod
    # ------------------------------------------------------------------

    @classmethod
    def from_config(
        cls,
        config: Configuration,
        preset_registry: IdentifierPatternPresetRegistry,
        parent: QObject | None = None,
    ) -> Pipeline:
        """Construct a fully configured pipeline from a saved *config*.

        Creates the pipeline instance, then delegates per-stage state
        restoration to :meth:`Stage.apply_config`. Stages whose names are
        absent from *config* keep the defaults set by their constructor.
        """
        pipeline = cls(config.pipeline_options, preset_registry, parent)
        for stage in pipeline.get_stages():
            stage_cfg = config.stages.get(stage.name)
            if stage_cfg is not None:
                stage.apply_config(stage_cfg)
        return pipeline

    # ------------------------------------------------------------------
    # Batch processing (Template Method)
    # ------------------------------------------------------------------

    def run_batch(
        self,
        images: list[Path],
        session: CalibrationSession,
    ) -> list[BatchResult]:
        """Process all images in the batch.

        Builds a :class:`BatchContext` (regex, charset hint, debug dir) once
        per run, dispatches each image to :meth:`_process_single_image`, and
        emits progress / completion signals.  The session is treated as
        read-only calibration output — it is never mutated here.

        Returns
        -------
        list[BatchResult]
            One result per image, in the same order as *images*.  May be
            shorter than *images* if :meth:`cancel` was called mid-batch.
        """
        self._cancelled = False
        preset = self._preset_registry.get_preset(self._options.identifier_pattern_preset)

        debug_dir: Path | None = None
        if self._options.debug_export_mode != DebugExportMode.DISABLED and images:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            debug_dir = images[0].parent / f"_debug_{timestamp}"

        ctx = BatchContext(
            regex=preset.regex,
            charset_hint=_derive_charset_hint(preset.regex),
            debug_dir=debug_dir,
        )

        results: list[BatchResult] = []
        total = len(images)

        for i, image_path in enumerate(images):
            if self._cancelled:
                _log.info("Batch cancelled after %d/%d images.", i, total)
                break
            result = self._process_single_image(image_path, session, ctx)
            results.append(result)
            self.image_completed.emit(image_path.name, result)
            self.progress_updated.emit(i + 1, total)

        self.batch_completed.emit(results)
        _log.debug("Batch finished: %d/%d image(s) processed.", len(results), total)
        return results

    def cancel(self) -> None:
        """Request cancellation of an in-progress batch.

        Thread-safe — sets a flag checked between images in
        :meth:`run_batch`.  The currently-processing image runs to
        completion (OCR engines are opaque and can't be preempted);
        nothing else starts.  ``batch_completed`` is still emitted, with
        the partial result list, so downstream cleanup paths fire.
        """
        self._cancelled = True

    # ------------------------------------------------------------------
    # Stage lookup
    # ------------------------------------------------------------------

    def get_stage(self, name: str) -> Stage | None:
        """Return the first stage with the given *name*, or ``None``.

        Convenience for batch code that picks specific stages by name
        (e.g. cropping between alignment and OCR).
        """
        for stage in self._stages:
            if stage.name == name:
                return stage
        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def cleanup(self) -> None:
        """Release all operator resources held by this pipeline.

        Calls :meth:`~app.tools.scibit.core.pool.OperatorPool.clear` so that
        large models (e.g. OCR engines loaded onto the GPU) are freed
        immediately rather than waiting for Python's garbage collector.
        """
        self._pool.clear()

    def _init_stages(self) -> list[Stage]:
        """Create stages, inject the pool, and return the list."""
        stages = self.get_stages()
        for stage in stages:
            stage.set_pool(self._pool)
        return stages


# ---------------------------------------------------------------------------
# Module-level helper functions
# ---------------------------------------------------------------------------


def _load_image(path: Path) -> NDArray[np.uint8]:
    """Load *path* as a greyscale uint8 image.

    Raises
    ------
    OSError
        If OpenCV cannot decode the file.
    """
    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise OSError(f"OpenCV could not load image: {path}")
    return image


def _preprocess_image(
    path: Path,
    rotation_degrees: float,
    invert: bool,
    downscale_factor: float = 1.0,
) -> NDArray[np.uint8]:
    """Load and preprocess an image using the same approach as calibration.

    Rotates onto an exact-size canvas (minimum bounding box for the rotated
    image) so no uniform padding is introduced and coordinate spaces match
    the calibration session data exactly (ROI positions, keypoints, contours).
    Downscaling matches the ``downscale_factor`` set during calibration.

    Raises
    ------
    OSError
        If OpenCV cannot decode the file.
    """
    image = _load_image(path)
    h, w = image.shape[:2]
    if rotation_degrees != 0.0:
        cos_a = abs(math.cos(math.radians(rotation_degrees)))
        sin_a = abs(math.sin(math.radians(rotation_degrees)))
        new_w = math.ceil(w * cos_a + h * sin_a)
        new_h = math.ceil(h * cos_a + w * sin_a)
        matrix = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), -rotation_degrees, 1.0)
        matrix[0, 2] += (new_w - w) / 2.0
        matrix[1, 2] += (new_h - h) / 2.0
        canvas = cv2.warpAffine(image, matrix, (new_w, new_h), borderValue=255)
    else:
        canvas = image
    if invert:
        canvas = cv2.bitwise_not(canvas)
    if downscale_factor < 1.0:
        new_w = max(1, round(canvas.shape[1] * downscale_factor))
        new_h = max(1, round(canvas.shape[0] * downscale_factor))
        canvas = cv2.resize(canvas, (new_w, new_h), interpolation=cv2.INTER_AREA)
    return canvas


def _classify_outcome(
    text: str,
    confidence: float,
    threshold: float,
    regex: str,
) -> ProcessingOutcome:
    """Return the :class:`ProcessingOutcome` for *text* and *confidence*.

    Follows the decision table in spec Section 8.2.
    """
    regex_matches = bool(re.fullmatch(regex, text)) if text else False
    above_threshold = confidence >= threshold

    if above_threshold and regex_matches:
        return ProcessingOutcome.PASSED
    if not above_threshold and regex_matches:
        return ProcessingOutcome.LOW_CONFIDENCE
    if above_threshold and not regex_matches:
        return ProcessingOutcome.VALIDATION_FAILED
    return ProcessingOutcome.FAILED


def _derive_charset_hint(pattern: str) -> set[str] | None:
    """Derive an allowed character set from a regex *pattern*.

    Used to constrain OCR recognition in frameworks that support it
    (spec Section 3.9 / 6.2).  Returns ``None`` for unconstrained patterns.
    """
    if not pattern or pattern in {".*", ".+", ".*?", ".+?", "(.*)"}:
        return None

    chars: set[str] = set()

    if r"\d" in pattern:
        chars.update("0123456789")
    if r"\w" in pattern:
        chars.update("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")
    if r"\u" in pattern:
        chars.update("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    if r"\l" in pattern:
        chars.update("abcdefghijklmnopqrstuvwxyz")

    for match in re.finditer(r"\[(\^?)([^\]]+)\]", pattern):
        negated, content = match.group(1), match.group(2)
        if negated:
            continue
        idx = 0
        while idx < len(content):
            if content[idx] == "\\" and idx + 1 < len(content):
                escape = content[idx + 1]
                if escape == "d":
                    chars.update("0123456789")
                elif escape == "w":
                    chars.update("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")
                else:
                    chars.add(escape)
                idx += 2
            elif idx + 2 < len(content) and content[idx + 1] == "-":
                start, end = ord(content[idx]), ord(content[idx + 2])
                chars.update(chr(c) for c in range(start, end + 1))
                idx += 3
            else:
                chars.add(content[idx])
                idx += 1

    stripped = re.sub(r"\[[^\]]*\]", "", pattern)
    stripped = re.sub(r"[\\^$.|?*+(){}]", " ", stripped)
    for ch in stripped:
        if ch.isalnum():
            chars.add(ch)

    return chars if chars else None
