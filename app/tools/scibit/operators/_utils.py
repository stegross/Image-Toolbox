"""Shared image-conversion utilities for SCIBIT operators.

All operators receive greyscale ``NDArray[np.uint8]`` images from the
pipeline.  Some backends (PaddleOCR) require RGB input; these helpers
handle the conversion without duplicating code across operator modules.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray


def ensure_gray(image: NDArray[np.uint8]) -> NDArray[np.uint8]:
    """Return *image* as a single-channel greyscale array.

    If *image* is already 2-D (H × W) it is returned unchanged.
    If it is 3-D (H × W × 3) the standard luminance formula is applied.
    """
    if image.ndim == 2:
        return image
    import cv2

    return cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)


def ensure_rgb(image: NDArray[np.uint8]) -> NDArray[np.uint8]:
    """Return *image* as a 3-channel RGB array.

    If *image* is already 3-D (H × W × 3) it is returned unchanged.
    If it is 2-D (H × W greyscale) it is stacked into 3 identical channels.
    """
    if image.ndim == 3 and image.shape[2] == 3:
        return image
    import cv2

    return cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)
