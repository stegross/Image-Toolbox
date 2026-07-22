"""Tests for :class:`~app.tools.scibit.core.registry.OperatorRegistry`.

Two concerns are checked:

1. **End-to-end registration of the four shipped operators.** Importing
   :mod:`app.tools.scibit.operators` triggers the
   :func:`~app.tools.scibit.core.registry.register_operator` decorators
   in every operator module, which must populate the registry with the
   correct Operation → Operator mappings. This is the SCIBIT counterpart
   to the host shell's plugin discovery and underpins the *Open/Closed*
   extensibility argument (Spec §3.3 / FF1).

2. **Decorator-level invariants** that protect against misregistration:
   the operations list must be non-empty, and the operator class must
   actually inherit from every Operation ABC it claims to implement
   (otherwise abstract methods would silently go unimplemented).
"""

from __future__ import annotations

# Importing the operators package registers all four shipped operators
# via @register_operator decorators applied at module import time.
import app.tools.scibit.operators as _operators  # noqa: F401, E402
import pytest
from app.tools.scibit.core.operations import (
    ChipRegionDetection,
    FeatureBasedAlignment,
    ROIPreprocessing,
    TextRecognition,
    TextRegionDetection,
)
from app.tools.scibit.core.registry import OperatorRegistry, register_operator
from app.tools.scibit.operators.easyocr_operator import EasyOCROperator
from app.tools.scibit.operators.opencv_operator import OpenCVOperator
from app.tools.scibit.operators.paddleocr_operator import PaddleOCROperator
from app.tools.scibit.operators.tesseract_operator import TesseractOperator


@pytest.fixture()
def registry() -> OperatorRegistry:
    """Return the singleton registry (already populated at import time)."""
    return OperatorRegistry()


class TestShippedOperatorRegistration:
    """The four shipped operators register themselves with correct capabilities."""

    def test_opencv_operator_covers_cv_operations(self, registry: OperatorRegistry) -> None:
        """OpenCVOperator is the sole provider of all three CV operations."""
        assert OpenCVOperator in registry.get_operators_for(ChipRegionDetection)
        assert OpenCVOperator in registry.get_operators_for(FeatureBasedAlignment)
        assert OpenCVOperator in registry.get_operators_for(ROIPreprocessing)

    def test_three_ocr_operators_cover_text_recognition(self, registry: OperatorRegistry) -> None:
        """Tesseract, EasyOCR, and PaddleOCR all implement TextRecognition."""
        text_recognisers = set(registry.get_operators_for(TextRecognition))
        assert {TesseractOperator, EasyOCROperator, PaddleOCROperator} <= text_recognisers

    def test_two_operators_cover_text_region_detection(self, registry: OperatorRegistry) -> None:
        """Only EasyOCR and PaddleOCR detect text regions; Tesseract does not."""
        detectors = set(registry.get_operators_for(TextRegionDetection))
        assert {EasyOCROperator, PaddleOCROperator} <= detectors
        assert TesseractOperator not in detectors
        assert OpenCVOperator not in detectors

    def test_opencv_operator_is_not_an_ocr_engine(self, registry: OperatorRegistry) -> None:
        """OpenCVOperator must not appear as a TextRecognition provider."""
        assert OpenCVOperator not in registry.get_operators_for(TextRecognition)


class TestResolveOperatorClass:
    """``resolve_operator_class`` maps the string identifier from a config back to the class."""

    def test_resolves_known_operator(self, registry: OperatorRegistry) -> None:
        """A registered operator is found by its ``__name__``."""
        assert registry.resolve_operator_class("PaddleOCROperator") is PaddleOCROperator
        assert registry.resolve_operator_class("OpenCVOperator") is OpenCVOperator

    def test_returns_none_for_unknown(self, registry: OperatorRegistry) -> None:
        """An unregistered identifier resolves to ``None``, not an exception."""
        assert registry.resolve_operator_class("NoSuchOperator") is None


class TestRegisterDecoratorInvariants:
    """Negative tests for the ``@register_operator`` decorator's checks."""

    def test_empty_operations_list_rejected(self) -> None:
        """Registering with an empty operations list raises ValueError."""
        with pytest.raises(ValueError, match="at least one operation"):

            @register_operator([])
            class _Bad(TextRecognition):  # pragma: no cover — fails at decoration
                pass

    def test_non_subclass_rejected(self) -> None:
        """Claiming to implement an Operation without inheriting raises TypeError."""

        class _NotARealRecogniser:
            """Does NOT inherit from TextRecognition — registration must fail."""

        with pytest.raises(TypeError, match="does not inherit"):
            OperatorRegistry().register(_NotARealRecogniser, [TextRecognition])
