"""Cropping helpers shared by pipeline batch code and calibration stages.

The remaining helpers in this module are pure 2-D geometry utilities
(``crop_bbox``, ``crop_roi``) — operator and stage lookup happen via
:meth:`~app.tools.scibit.core.pipeline.Pipeline.get_stage` and
:class:`~app.tools.scibit.core.pool.OperatorPool` rather than free
functions.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from app.tools.scibit.core.types import BoundingBox


def crop_bbox(image: NDArray[np.uint8], bbox: BoundingBox) -> NDArray[np.uint8]:
    """Crop *image* to *bbox* (x, y, w, h), clamped to image bounds."""
    x, y, w, h = bbox
    ih, iw = image.shape[:2]
    x1, y1 = max(0, x), max(0, y)
    x2, y2 = min(iw, x + w), min(ih, y + h)
    return image[y1:y2, x1:x2]


def crop_roi(
    image: NDArray[np.uint8],
    roi: tuple[int, int, int, int],
    margin: int,
) -> NDArray[np.uint8]:
    """Return a sub-image of *image* at *roi*, expanded by *margin* pixels.

    The expanded rectangle is clamped to image bounds so no out-of-range
    indexing occurs.

    Parameters
    ----------
    image : NDArray[np.uint8]
        Source image.
    roi : tuple[int, int, int, int]
        ``(x, y, w, h)`` in pixel coordinates (calibrated coordinate system).
    margin : int
        Pixels to add on each side of the ROI.

    Returns
    -------
    NDArray[np.uint8]
        Cropped sub-image.
    """
    x, y, w, h = roi
    img_h, img_w = image.shape[:2]
    x1 = max(0, x - margin)
    y1 = max(0, y - margin)
    x2 = min(img_w, x + w + margin)
    y2 = min(img_h, y + h + margin)
    return image[y1:y2, x1:x2]
