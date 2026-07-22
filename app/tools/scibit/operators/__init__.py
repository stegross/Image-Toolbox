"""SCIBIT concrete operator implementations.

Importing this package registers all operators with the
:class:`~app.tools.scibit.core.registry.OperatorRegistry` via the
``@register_operator`` decorator applied in each module.

Usage::

    import app.tools.scibit.operators  # registers all operators
"""

from app.tools.scibit.operators.easyocr_operator import EasyOCROperator
from app.tools.scibit.operators.opencv_operator import OpenCVOperator
from app.tools.scibit.operators.paddleocr_operator import PaddleOCROperator
from app.tools.scibit.operators.tesseract_operator import TesseractOperator

__all__ = [
    "OpenCVOperator",
    "PaddleOCROperator",
    "EasyOCROperator",
    "TesseractOperator",
]
