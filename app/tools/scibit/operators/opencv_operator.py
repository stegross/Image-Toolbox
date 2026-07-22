"""OpenCV-based concrete operator (spec Section 6.3).

Implements three operations using only OpenCV:

- :class:`~app.tools.scibit.core.operations.ChipRegionDetection`
- :class:`~app.tools.scibit.core.operations.FeatureBasedAlignment`
- :class:`~app.tools.scibit.core.operations.ROIPreprocessing`

Feature detectors (ORB, SIFT, AKAZE) are created lazily on first use.
The instance is obtained from the pipeline's OperatorPool so the
detector is only initialised once per pipeline run.
"""

from __future__ import annotations

import logging

import cv2
import numpy as np
from numpy.typing import NDArray

from app.tools.scibit.core.operations import (
    ChipRegionDetection,
    FeatureBasedAlignment,
    ROIPreprocessing,
)
from app.tools.scibit.core.registry import register_operator
from app.tools.scibit.core.types import BoundingBox, HomographyMatrix

_log = logging.getLogger(__name__)


@register_operator(
    [
        ChipRegionDetection,
        FeatureBasedAlignment,
        ROIPreprocessing,
    ]
)
class OpenCVOperator(ChipRegionDetection, FeatureBasedAlignment, ROIPreprocessing):
    """OpenCV-only operator covering chip detection, alignment, and ROI preprocessing.

    Parameters are sourced from the stage's ``parameters`` dict on every
    call so a single pooled instance can serve multiple stages with
    different settings (spec Section 3.6).
    """

    def __init__(self) -> None:
        self._detector: cv2.Feature2D | None = None
        self._detector_type: str = ""

    @classmethod
    def get_param_schema(cls, operation: type | None) -> list:
        """Return the dynamic UI parameter schema for *operation*."""
        from app.tools.scibit.core.stage import ParamSpec

        if operation is ChipRegionDetection:
            return [
                ParamSpec(
                    key="threshold_block_size",
                    label="Block Size",
                    type="int",
                    default=11,
                    min=3,
                    max=51,
                    step=2,
                    tooltip="Adaptive threshold neighbourhood size (must be odd).",
                ),
                ParamSpec(
                    key="threshold_c",
                    label="Threshold C",
                    type="int",
                    default=2,
                    min=-10,
                    max=30,
                    step=1,
                    tooltip="Constant subtracted from the adaptive threshold mean.",
                ),
                ParamSpec(
                    key="morph_kernel_size",
                    label="Morph Kernel",
                    type="int",
                    default=5,
                    min=1,
                    max=21,
                    step=2,
                    tooltip="Morphological kernel size for chip region cleaning.",
                ),
            ]
        if operation is FeatureBasedAlignment:
            return [
                ParamSpec(
                    key="detector",
                    label="Detector",
                    type="choice",
                    options=[("ORB", "ORB"), ("SIFT", "SIFT"), ("AKAZE", "AKAZE")],
                    default="ORB",
                ),
                ParamSpec(
                    key="max_features",
                    label="Max Features",
                    type="int",
                    default=500,
                    min=50,
                    max=10000,
                    step=100,
                ),
                ParamSpec(
                    key="match_ratio",
                    label="Match Ratio",
                    type="float",
                    default=0.75,
                    min=0.10,
                    max=1.00,
                    step=0.05,
                    tooltip="Lowe's ratio-test threshold for feature matching.",
                ),
                ParamSpec(
                    key="min_matches",
                    label="Min Matches",
                    type="int",
                    default=10,
                    min=4,
                    max=500,
                    step=1,
                ),
            ]
        if operation is ROIPreprocessing:
            return [
                ParamSpec(
                    key="clahe",
                    label="CLAHE",
                    type="group",
                    enable_key="clahe_enabled",
                    children=(
                        ParamSpec(
                            key="clahe_clip_limit",
                            label="Clip Limit",
                            type="float",
                            default=2.0,
                            min=0.1,
                            max=40.0,
                            step=0.1,
                            tooltip="Threshold for contrast limiting.",
                        ),
                        ParamSpec(
                            key="clahe_tile_grid_size",
                            label="Tile Grid",
                            type="int",
                            default=8,
                            min=1,
                            max=64,
                            step=1,
                            tooltip="Number of tiles per row/column for CLAHE.",
                        ),
                    ),
                ),
                ParamSpec(
                    key="adaptive_threshold",
                    label="Adaptive Threshold",
                    type="group",
                    enable_key="adaptive_threshold_enabled",
                    children=(
                        ParamSpec(
                            key="adaptive_threshold_method",
                            label="Method",
                            type="choice",
                            options=[("Gaussian", "GAUSSIAN"), ("Mean", "MEAN")],
                            default="GAUSSIAN",
                        ),
                        ParamSpec(
                            key="adaptive_threshold_block_size",
                            label="Block Size",
                            type="int",
                            default=11,
                            min=3,
                            max=99,
                            step=2,
                            tooltip="Neighbourhood size (must be odd).",
                        ),
                        ParamSpec(
                            key="adaptive_threshold_c",
                            label="C",
                            type="int",
                            default=2,
                            min=-30,
                            max=30,
                            step=1,
                            tooltip="Constant subtracted from the local mean.",
                        ),
                        ParamSpec(
                            key="adaptive_threshold_invert",
                            label="Invert",
                            type="bool",
                            default=False,
                            tooltip="Use THRESH_BINARY_INV instead of THRESH_BINARY.",
                        ),
                    ),
                ),
            ]
        return []

    # ------------------------------------------------------------------
    # ChipRegionDetection
    # ------------------------------------------------------------------

    def detect_chip_region(
        self,
        image: NDArray[np.uint8],
        params: dict,
    ) -> BoundingBox:
        """Find the axis-aligned bounding box of the chip region.

        Uses adaptive thresholding + morphological closing followed by the
        largest external contour.

        Returns
        -------
        BoundingBox
            ``(x, y, width, height)`` in pixel coordinates.
        """
        block = int(params.get("threshold_block_size", 11))
        c_val = int(params.get("threshold_c", 2))
        k_size = int(params.get("morph_kernel_size", 5))

        h, w = image.shape[:2]
        binary = cv2.adaptiveThreshold(
            image,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV,
            block,
            c_val,
        )
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (k_size, k_size))
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return (0, 0, w, h)

        largest = max(contours, key=cv2.contourArea)
        x, y, bw, bh = cv2.boundingRect(largest)
        return (x, y, bw, bh)

    # ------------------------------------------------------------------
    # FeatureBasedAlignment
    # ------------------------------------------------------------------

    def detect_and_compute(
        self,
        image: NDArray[np.uint8],
        params: dict,
    ) -> tuple[list, NDArray]:
        """Detect keypoints and compute descriptors on *image*.

        Returns
        -------
        tuple[list, NDArray]
            ``(keypoints, descriptors)`` produced by the configured
            detector.  ``descriptors`` is ``None`` when no features were
            detected.
        """
        detector_type = str(params.get("detector", "ORB"))
        max_features = int(params.get("max_features", 500))
        detector = self._get_detector(detector_type, max_features)
        return detector.detectAndCompute(image, None)

    def align_feature(
        self,
        image: NDArray[np.uint8],
        template_image: NDArray[np.uint8],
        template_keypoints: list,
        template_descriptors: NDArray,
        params: dict,
    ) -> tuple[HomographyMatrix, NDArray[np.uint8]]:
        """Compute homography between *image* and the calibration template.

        Returns
        -------
        tuple[HomographyMatrix, NDArray[np.uint8]]
            ``(homography_matrix, warped_image)``.

        Raises
        ------
        RuntimeError
            If fewer than ``min_matches`` good feature pairs are found.
        """
        detector_type = str(params.get("detector", "ORB"))
        ratio = float(params.get("match_ratio", 0.75))
        min_matches = int(params.get("min_matches", 10))

        kp, desc = self.detect_and_compute(image, params)

        if desc is None or len(kp) < 2:
            raise RuntimeError("Not enough keypoints in the query image.")

        if detector_type == "SIFT":
            matcher = cv2.BFMatcher(cv2.NORM_L2)
        else:
            matcher = cv2.BFMatcher(cv2.NORM_HAMMING)

        raw_matches = matcher.knnMatch(template_descriptors, desc, k=2)
        good = [m for m, n in raw_matches if m.distance < ratio * n.distance]

        if len(good) < min_matches:
            raise RuntimeError(f"Only {len(good)} good matches found (need {min_matches}).")

        src_pts = np.float32([template_keypoints[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
        dst_pts = np.float32([kp[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)

        H, mask = cv2.findHomography(dst_pts, src_pts, cv2.RANSAC, 5.0)  # noqa: N806 — H is the conventional symbol for a homography matrix
        if H is None:
            raise RuntimeError("Homography computation failed (RANSAC returned None).")

        h, w = template_image.shape[:2]
        warped = cv2.warpPerspective(image, H, (w, h))
        return H.astype(np.float64), warped

    def _get_detector(self, detector_type: str, max_features: int) -> cv2.Feature2D:
        """Return a cached (or newly created) feature detector."""
        key = f"{detector_type}:{max_features}"
        if self._detector is None or self._detector_type != key:
            if detector_type == "SIFT":
                self._detector = cv2.SIFT_create(nfeatures=max_features)
            elif detector_type == "AKAZE":
                self._detector = cv2.AKAZE_create()
            else:
                self._detector = cv2.ORB_create(nfeatures=max_features)
            self._detector_type = key
        return self._detector

    # ------------------------------------------------------------------
    # ROIPreprocessing
    # ------------------------------------------------------------------

    def preprocess_roi(
        self,
        image: NDArray[np.uint8],
        params: dict,
    ) -> NDArray[np.uint8]:
        """Apply enabled enhancement functions to *image* in strict order.

        Order: CLAHE → Adaptive Threshold. Each step is skipped when its
        enable flag in *params* is falsy.
        """
        result = image
        if result.ndim == 3:
            result = cv2.cvtColor(result, cv2.COLOR_BGR2GRAY)

        if bool(params.get("clahe_enabled", False)):
            clip = float(params.get("clahe_clip_limit", 2.0))
            grid = max(1, int(params.get("clahe_tile_grid_size", 8)))
            clahe = cv2.createCLAHE(clipLimit=clip, tileGridSize=(grid, grid))
            result = clahe.apply(result)

        if bool(params.get("adaptive_threshold_enabled", False)):
            method_name = str(params.get("adaptive_threshold_method", "GAUSSIAN"))
            method = (
                cv2.ADAPTIVE_THRESH_MEAN_C
                if method_name == "MEAN"
                else cv2.ADAPTIVE_THRESH_GAUSSIAN_C
            )
            block = int(params.get("adaptive_threshold_block_size", 11))
            if block < 3:
                block = 3
            if block % 2 == 0:
                block += 1
            c_val = int(params.get("adaptive_threshold_c", 2))
            thresh_type = (
                cv2.THRESH_BINARY_INV
                if bool(params.get("adaptive_threshold_invert", False))
                else cv2.THRESH_BINARY
            )
            result = cv2.adaptiveThreshold(
                result,
                255,
                method,
                thresh_type,
                block,
                c_val,
            )

        return result

    # ------------------------------------------------------------------
    # Pool lifecycle
    # ------------------------------------------------------------------

    def release(self) -> None:
        """Release cached detector resources."""
        self._detector = None
        self._detector_type = ""
