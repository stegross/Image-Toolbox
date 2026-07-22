"""CalibrationSession — the bag of state built up during calibration.

A single, pipeline-agnostic dataclass.  Each pipeline fills the slots it
cares about; downstream stages read whatever slots they need.  Slots
that a given pipeline never populates stay at their default (``None``
or empty collection) and are simply ignored.

Two field groups, documented but not enforced by type:

* **Persistent** — read by batch processing to reproduce calibration's
  coordinate space.  This is the actual output of calibration.
* **Calibration-only** — populated by stages during a calibration run so
  downstream stages can reuse derived crops without recomputing them.
  Cleared via :meth:`clear_calibration_scratch` before the session is
  emitted as the calibration result.

Per-batch ephemeral state (regex, charset hint, debug directory) lives
in :class:`~app.tools.scibit.core.pipeline.BatchContext`, **not** here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray

from app.tools.scibit.core.types import BoundingBox, Contour


@dataclass
class CalibrationSession:
    """Single, pipeline-agnostic calibration session.

    Stages depend on this concrete type and read/write the slots they
    need.  A pipeline that doesn't use a given slot just leaves it at
    its default; the stage that produces or consumes that slot won't run
    in that pipeline anyway.

    Parameters
    ----------
    example_image : NDArray[np.uint8]
        The example image selected during Stage 0 (Calibration Setup),
        with rotation and colour inversion already applied.
    rotation_degrees : float
        Rotation angle (degrees, CCW positive) applied to every batch image
        before pipeline stages run.
    invert_colors : bool
        When ``True``, ``cv2.bitwise_not`` is applied to every batch image
        after rotation.
    downscale_factor : float
        Downscaling factor applied to every batch image after rotation /
        inversion.  ``1.0`` disables downscaling.

    chip_region : BoundingBox | Contour | None
        Chip boundary detected during chip-region detection.  Set by
        pipelines that include a chip-detection stage; ``None`` otherwise.
    identifier_roi : BoundingBox | None
        Bounding box of the identifier region in the coordinate system
        used by the OCR stage (chip-cropped for feature-alignment
        pipelines, full image for direct-ROI pipelines).
    roi_tolerance_margin : int
        Pixel margin added around *identifier_roi* during batch
        processing.  Only consulted by pipelines that crop the ROI
        directly from the full image.
    template_image : NDArray[np.uint8] | None
        Aligned chip image used as the alignment reference template.
        Set by feature-alignment pipelines, ``None`` otherwise.
    template_keypoints : list
        ``cv2.KeyPoint`` objects extracted from *template_image*.
    template_descriptors : NDArray | None
        Feature descriptor array matching *template_keypoints*.

    current_crop : NDArray[np.uint8] | None
        Calibration-only cache: the identifier crop most recently
        produced for the example image.
    preprocessed_crop : NDArray[np.uint8] | None
        Calibration-only cache: the output of the ROI-preprocessing
        stage applied to *current_crop*.
    chip_crop : NDArray[np.uint8] | None
        Calibration-only cache: ``example_image`` cropped to
        ``chip_region``.  Input to feature extraction and identifier
        region detection.
    detected_regions : list[BoundingBox]
        Calibration-only cache: auto-detected text-region candidates
        produced by the identifier-region-detection stage; offered to
        the user as clickable overlays.
    identifier_bbox_is_manual : bool
        Calibration-only flag: ``True`` when the user drew the
        identifier ROI by hand (so a parameter re-run preserves it),
        ``False`` when it was picked from ``detected_regions``.
    """

    # ------------------------------------------------------------------
    # Persistent — read by batch
    # ------------------------------------------------------------------

    example_image: NDArray[np.uint8]
    rotation_degrees: float = 0.0
    invert_colors: bool = False
    downscale_factor: float = 1.0

    chip_region: BoundingBox | Contour | None = None
    identifier_roi: BoundingBox | None = None
    roi_tolerance_margin: int = 10

    template_image: NDArray[np.uint8] | None = None
    template_keypoints: list = field(default_factory=list)
    template_descriptors: NDArray | None = None

    # ------------------------------------------------------------------
    # Calibration-only — cleared before batch
    # ------------------------------------------------------------------

    current_crop: NDArray[np.uint8] | None = None
    preprocessed_crop: NDArray[np.uint8] | None = None
    chip_crop: NDArray[np.uint8] | None = None
    detected_regions: list[BoundingBox] = field(default_factory=list)
    identifier_bbox_is_manual: bool = False

    def clear_calibration_scratch(self) -> None:
        """Reset all calibration-only fields to their unpopulated state.

        Called by the calibration shell after the final stage is confirmed
        so the session handed to batch contains only persistent fields.
        """
        self.current_crop = None
        self.preprocessed_crop = None
        self.chip_crop = None
        self.detected_regions = []
        self.identifier_bbox_is_manual = False
