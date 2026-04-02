"""Shared QImage → numpy conversion utilities for OCR engines."""

from __future__ import annotations

import numpy as np
from PySide6.QtGui import QImage


def qimage_to_numpy_gray(image: QImage) -> np.ndarray:
    """Return *image* as a greyscale ``uint8`` numpy array with shape ``(H, W)``.

    Parameters
    ----------
    image : QImage
        Source image.  Converted to ``Format_Grayscale8`` if necessary.

    Returns
    -------
    np.ndarray
        Contiguous ``uint8`` array of shape ``(height, width)``.
    """
    if image.format() != QImage.Format.Format_Grayscale8:
        image = image.convertToFormat(QImage.Format.Format_Grayscale8)
    ptr = image.bits()
    arr = np.frombuffer(ptr, dtype=np.uint8).reshape((image.height(), image.bytesPerLine()))
    return arr[:, : image.width()].copy()
