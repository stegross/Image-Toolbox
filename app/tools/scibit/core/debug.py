"""Debug image export helpers.

Used by pipelines and controllers to persist intermediate images during
calibration and batch processing when debug export is enabled.
"""

from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np
from numpy.typing import NDArray

_log = logging.getLogger(__name__)


def write_debug_image(
    debug_image_dir: Path,
    filename: str,
    image: NDArray[np.uint8],
) -> None:
    """Write *image* to ``debug_image_dir / filename``, creating dirs as needed."""
    try:
        debug_image_dir.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(debug_image_dir / filename), image)
    except Exception:
        _log.warning(
            "Could not write debug image '%s/%s'.",
            debug_image_dir,
            filename,
            exc_info=True,
        )
