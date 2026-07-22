"""Image conversion utilities for the SCIBIT UI layer.

Converts OpenCV-style NumPy arrays (greyscale or RGB uint8) to
:class:`PySide6.QtGui.QPixmap` objects for display in Qt widgets.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from PySide6.QtGui import QImage, QPixmap


def ndarray_to_pixmap(image: NDArray[np.uint8]) -> QPixmap:
    """Convert a uint8 NumPy image to a :class:`QPixmap`.

    Parameters
    ----------
    image : NDArray[np.uint8]
        2-D greyscale ``(H, W)`` or 3-D RGB ``(H, W, 3)`` array.

    Returns
    -------
    QPixmap
        Pixel-perfect rendering of *image*.

    Raises
    ------
    ValueError
        If *image* has an unsupported shape.
    """
    img = np.ascontiguousarray(image, dtype=np.uint8)

    if img.ndim == 2:
        h, w = img.shape
        qimg = QImage(
            img.tobytes(),
            w,
            h,
            w,
            QImage.Format.Format_Grayscale8,
        )
    elif img.ndim == 3 and img.shape[2] == 3:
        h, w, _ = img.shape
        qimg = QImage(
            img.tobytes(),
            w,
            h,
            w * 3,
            QImage.Format.Format_RGB888,
        )
    else:
        raise ValueError(
            f"ndarray_to_pixmap: unsupported image shape {img.shape}. Expected (H, W) or (H, W, 3)."
        )

    return QPixmap.fromImage(qimg)
