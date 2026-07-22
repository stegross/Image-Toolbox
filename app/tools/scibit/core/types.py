"""Shared geometric types, result containers, and enumerations for SCIBIT.

This module is a pure-data leaf with no intra-package imports, so it is
safe to import from anywhere in the ``scibit`` package without creating
circular dependencies.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from numpy.typing import NDArray

# ---------------------------------------------------------------------------
# Geometric primitive type aliases (follow OpenCV conventions)
# ---------------------------------------------------------------------------

# Axis-aligned bounding box: (x, y, width, height)
BoundingBox = tuple[int, int, int, int]

# Contour as returned by cv2.findContours — shape (N, 1, 2), dtype int32
Contour = NDArray[np.int32]

# 3×3 homography matrix as returned by cv2.findHomography — dtype float64
HomographyMatrix = NDArray[np.float64]


# ---------------------------------------------------------------------------
# Stage result
# ---------------------------------------------------------------------------


@dataclass
class StageResult:
    """Output of a single stage execution (calibration or batch mode).

    Parameters
    ----------
    data : Any
        The primary result produced by the operator.  The concrete type
        depends on the operation:

        - ``BoundingBox | Contour`` — chip region detection
        - ``(HomographyMatrix, ndarray)`` — feature-based alignment
        - ``ndarray`` — crop preprocessing
        - ``list[BoundingBox]`` — text region detection
        - ``(str, float)`` — text recognition ``(text, confidence_0_100)``

        ``None`` for built-in stages (Calibration Setup, Validation) and
        when *error* is set.
    debug_images : list[tuple[str, NDArray]]
        Optional ``(label, image)`` pairs captured by the stage when debug
        export is enabled.  The label is a short, filesystem-safe name
        (e.g. ``"thresholded"``, ``"contours"``).
    error : str | None
        If the stage raised an exception, the error message is stored here
        and *data* is ``None``.
    """

    data: Any
    debug_images: list[tuple[str, NDArray]] = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        """``True`` when the stage completed without error."""
        return self.error is None


# ---------------------------------------------------------------------------
# Batch result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BatchResult:
    """Processing result for a single image in a batch.

    Produced by the pipeline after all stages have run.  The pipeline only
    assigns ``ProcessingOutcome`` — the UI layer maps this to
    ``ReviewState`` using :class:`ReviewStateMapping`.

    Parameters
    ----------
    filename : str
        Original filename (stem + suffix, no directory component).
    identifier_text : str
        OCR-recognised identifier string.  Empty string when recognition
        failed or was not reached.
    confidence : float
        OCR confidence in the range ``0.0``–``100.0``.
    outcome : ProcessingOutcome
        Classification of the result.
    error_detail : str | None
        Human-readable error description when *outcome* is
        ``PROCESSING_ERROR``, otherwise ``None``.
    """

    filename: str
    identifier_text: str
    confidence: float
    outcome: ProcessingOutcome
    error_detail: str | None = None


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ProcessingOutcome(enum.Enum):
    """Result classification produced by the pipeline (spec Section 8.2).

    The pipeline assigns this based on the OCR confidence threshold and
    regex validation.  No UI concern is encoded here.
    """

    PASSED = "passed"
    LOW_CONFIDENCE = "low_confidence"
    VALIDATION_FAILED = "validation_failed"
    FAILED = "failed"
    PROCESSING_ERROR = "processing_error"


class ReviewState(enum.Enum):
    """UI-level review state mapped from :class:`ProcessingOutcome`.

    Each member carries an RGB colour tuple used by the results list widget
    (spec Section 8.3).
    """

    AUTO_ACCEPTED = "auto_accepted"
    PENDING_REVIEW = "pending_review"
    NEEDS_ATTENTION = "needs_attention"
    CRITICAL = "critical"
    MANUALLY_CONFIRMED = "manually_confirmed"

    @property
    def color(self) -> tuple[int, int, int]:
        """RGB colour ``(r, g, b)`` for this review state."""
        return _REVIEW_STATE_COLORS[self]


_REVIEW_STATE_COLORS: dict[ReviewState, tuple[int, int, int]] = {
    ReviewState.AUTO_ACCEPTED: (180, 230, 180),
    ReviewState.PENDING_REVIEW: (255, 235, 150),
    ReviewState.NEEDS_ATTENTION: (255, 200, 130),
    ReviewState.CRITICAL: (240, 180, 180),
    ReviewState.MANUALLY_CONFIRMED: (160, 200, 240),
}


class DebugExportMode(enum.Enum):
    """Controls when interim processing images are written to disk.

    See spec Section 8.7 for the output directory structure.
    """

    DISABLED = "disabled"
    CALIBRATION = "calibration"
    ALL = "all"


# ---------------------------------------------------------------------------
# Review state mapping (spec Section 8.3)
# ---------------------------------------------------------------------------


class ReviewStateMapping:
    """Map :class:`ProcessingOutcome` to :class:`ReviewState`.

    Two static lookup tables are provided, one for each manual-confirmation
    setting.  The pipeline produces only :class:`ProcessingOutcome` values;
    ``ResultsWidget`` applies one of these mappings to decide how each
    result is displayed and whether it requires user action.
    """

    #: Mapping used when ``manual_confirmation_required = false``.
    #: Passing results are auto-accepted (renamed immediately, no review).
    AUTO_MODE: dict[ProcessingOutcome, ReviewState] = {
        ProcessingOutcome.PASSED: ReviewState.AUTO_ACCEPTED,
        ProcessingOutcome.LOW_CONFIDENCE: ReviewState.PENDING_REVIEW,
        ProcessingOutcome.VALIDATION_FAILED: ReviewState.PENDING_REVIEW,
        ProcessingOutcome.FAILED: ReviewState.CRITICAL,
        ProcessingOutcome.PROCESSING_ERROR: ReviewState.CRITICAL,
    }

    #: Mapping used when ``manual_confirmation_required = true``.
    #: All results require user review before file operations are performed.
    MANUAL_MODE: dict[ProcessingOutcome, ReviewState] = {
        ProcessingOutcome.PASSED: ReviewState.PENDING_REVIEW,
        ProcessingOutcome.LOW_CONFIDENCE: ReviewState.NEEDS_ATTENTION,
        ProcessingOutcome.VALIDATION_FAILED: ReviewState.NEEDS_ATTENTION,
        ProcessingOutcome.FAILED: ReviewState.CRITICAL,
        ProcessingOutcome.PROCESSING_ERROR: ReviewState.CRITICAL,
    }

    @classmethod
    def select(cls, manual_confirmation_required: bool) -> dict[ProcessingOutcome, ReviewState]:
        """Return the mapping dict for *manual_confirmation_required*.

        Parameters
        ----------
        manual_confirmation_required : bool
            When ``True`` returns :attr:`MANUAL_MODE`, otherwise
            :attr:`AUTO_MODE`.

        Returns
        -------
        dict[ProcessingOutcome, ReviewState]
            The active mapping.
        """
        return cls.MANUAL_MODE if manual_confirmation_required else cls.AUTO_MODE
