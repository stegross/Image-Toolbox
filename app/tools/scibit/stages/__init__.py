"""Concrete pipeline stage subclasses.

Each module in this package defines exactly one Stage subclass. Pipelines
compose their stage list from these classes; controllers and the
calibration widget interact with them only through the abstract Stage
interface (:mod:`app.tools.scibit.core.stage`).
"""

from app.tools.scibit.stages.calibration_setup_stage import CalibrationSetupStage
from app.tools.scibit.stages.chip_detection_stage import ChipDetectionStage
from app.tools.scibit.stages.feature_alignment_stage import FeatureAlignmentStage
from app.tools.scibit.stages.identifier_region_detection_stage import (
    IdentifierRegionDetectionStage,
)
from app.tools.scibit.stages.identifier_region_selection_stage import (
    IdentifierRegionSelectionStage,
)
from app.tools.scibit.stages.roi_preprocess_stage import RoiPreprocessStage
from app.tools.scibit.stages.text_recognition_stage import TextRecognitionStage
from app.tools.scibit.stages.validation_stage import ValidationStage

__all__ = [
    "CalibrationSetupStage",
    "ChipDetectionStage",
    "FeatureAlignmentStage",
    "IdentifierRegionDetectionStage",
    "IdentifierRegionSelectionStage",
    "RoiPreprocessStage",
    "TextRecognitionStage",
    "ValidationStage",
]
