"""Abstract Operation interfaces (spec Section 3.1).

Each ABC defines one typed abstract method matching the spec's
input/output table for that operation. Parameter schemas live on the
operators themselves via ``get_param_schema(operation)`` and on the
:class:`~app.tools.scibit.core.stage.Stage` subclasses' default values —
the Operation ABCs no longer carry schema metadata.

Concrete operator classes (framework wrappers) inherit from one or more
of these ABCs via multiple inheritance and implement each ABC's named
method. Python's ABC machinery enforces this at instantiation time —
an operator missing one of the required methods raises ``TypeError``.
No framework imports appear in this module.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import numpy as np
from numpy.typing import NDArray

from app.tools.scibit.core.types import (
    BoundingBox,
    Contour,
    HomographyMatrix,
)

# ---------------------------------------------------------------------------
# Root Operation ABC
# ---------------------------------------------------------------------------


class Operation(ABC):
    """Marker base class for all operation interfaces.

    Operations are pipeline-agnostic and framework-agnostic.  They define
    the *what* (the type of CV/OCR task) independently of any specific
    implementation.  Operators implement one or more Operation ABCs via
    multiple inheritance; each concrete operation ABC declares the named
    abstract method an operator must provide.
    """


# ---------------------------------------------------------------------------
# ChipRegionDetection
# ---------------------------------------------------------------------------


class ChipRegionDetection(Operation, ABC):
    """Detect the chip boundary within the full (rotated) image.

    Returns either an axis-aligned bounding box or a contour, depending on
    what the operator produces (the pipeline treats both as valid).
    """

    @abstractmethod
    def detect_chip_region(
        self,
        image: NDArray[np.uint8],
        params: dict[str, Any],
    ) -> BoundingBox | Contour:
        """Detect chip boundary.

        Parameters
        ----------
        image : NDArray[np.uint8]
            Full input image, greyscale or BGR, uint8.
        params : dict[str, Any]
            Runtime parameter values for this stage.

        Returns
        -------
        BoundingBox | Contour
            Axis-aligned bounding box ``(x, y, w, h)`` **or** a contour
            array of shape ``(N, 1, 2)``.
        """


# ---------------------------------------------------------------------------
# FeatureBasedAlignment
# ---------------------------------------------------------------------------


class FeatureBasedAlignment(Operation, ABC):
    """Align an image to a template using keypoint matching.

    Computes a homography from descriptor matches and returns the warped
    image in canonical pose.  Used by Pipeline A (Feature-Based Alignment).
    """

    @abstractmethod
    def detect_and_compute(
        self,
        image: NDArray[np.uint8],
        params: dict[str, Any],
    ) -> tuple[list, NDArray]:
        """Extract keypoints and descriptors from *image*.

        Called during calibration to derive template features that are
        then stored on the session and passed back to :meth:`align_feature`
        for every batch image.  The returned types are opaque — only the
        same operator that produced them will consume them.

        Parameters
        ----------
        image : NDArray[np.uint8]
            Template chip crop captured during calibration.
        params : dict[str, Any]
            Runtime parameters (detector type, max features, …).

        Returns
        -------
        tuple[list, NDArray]
            ``(keypoints, descriptors)``.  ``descriptors`` may be ``None``
            and ``keypoints`` may be empty if no features were detected.
        """

    @abstractmethod
    def align_feature(
        self,
        image: NDArray[np.uint8],
        template_image: NDArray[np.uint8],
        template_keypoints: list,
        template_descriptors: NDArray,
        params: dict[str, Any],
    ) -> tuple[HomographyMatrix, NDArray[np.uint8]]:
        """Align *image* to the calibration template.

        Parameters
        ----------
        image : NDArray[np.uint8]
            Current chip image to align (greyscale or BGR, uint8).
        template_image : NDArray[np.uint8]
            Reference chip image captured during calibration.
        template_keypoints : list
            Template keypoints (list of ``cv2.KeyPoint``).
        template_descriptors : NDArray
            Template feature descriptors array matching *template_keypoints*.
        params : dict[str, Any]
            Runtime parameters.

        Returns
        -------
        tuple[HomographyMatrix, NDArray[np.uint8]]
            3×3 homography matrix and the warped image aligned to the
            template's coordinate system.
        """


# ---------------------------------------------------------------------------
# TextRegionDetection
# ---------------------------------------------------------------------------


class TextRegionDetection(Operation, ABC):
    """Detect all text regions within an image.

    Returns a list of axis-aligned bounding boxes, one per detected region,
    ordered by detection confidence descending.
    """

    @abstractmethod
    def detect_text_regions(
        self,
        image: NDArray[np.uint8],
        params: dict[str, Any],
    ) -> list[BoundingBox]:
        """Detect text regions.

        Parameters
        ----------
        image : NDArray[np.uint8]
            Image to search for text regions.
        params : dict[str, Any]
            Runtime parameters.

        Returns
        -------
        list[BoundingBox]
            Detected regions as ``(x, y, w, h)`` tuples, ordered by
            detection confidence descending.
        """


# ---------------------------------------------------------------------------
# ROIPreprocessing
# ---------------------------------------------------------------------------


class ROIPreprocessing(Operation, ABC):
    """Preprocess a cropped identifier ROI for OCR.

    Applies a strict-order chain of optional image-enhancement functions
    (CLAHE, adaptive thresholding, …) controlled by per-function enable
    flags and parameters in *params*.
    """

    @abstractmethod
    def preprocess_roi(
        self,
        image: NDArray[np.uint8],
        params: dict[str, Any],
    ) -> NDArray[np.uint8]:
        """Preprocess *image*.

        Parameters
        ----------
        image : NDArray[np.uint8]
            Raw identifier crop (greyscale).
        params : dict[str, Any]
            Runtime parameters; per-function enable flags and tuning values.

        Returns
        -------
        NDArray[np.uint8]
            Enhanced image ready for OCR.
        """


# ---------------------------------------------------------------------------
# TextRecognition
# ---------------------------------------------------------------------------


class TextRecognition(Operation, ABC):
    """Recognise text from a preprocessed identifier crop.

    Returns the recognised string and a confidence score in the range
    0.0–100.0.  An optional character set hint derived from the identifier
    regex may be passed to constrain recognition in supported frameworks.
    """

    @abstractmethod
    def recognise_text(
        self,
        image: NDArray[np.uint8],
        params: dict[str, Any],
        charset_hint: set[str] | None = None,
    ) -> tuple[str, float]:
        """Recognise text from *image*.

        Parameters
        ----------
        image : NDArray[np.uint8]
            Preprocessed identifier crop (greyscale).
        params : dict[str, Any]
            Runtime parameters.
        charset_hint : set[str] | None
            Optional set of allowed characters derived from the identifier
            regex pattern.  Operators that support constrained recognition
            (PaddleOCR, Tesseract) use this to bias predictions.  Pass
            ``None`` or an empty set to run unconstrained.

        Returns
        -------
        tuple[str, float]
            ``(recognised_text, confidence_0_to_100)``
        """
