"""SCIBIT concrete pipeline implementations.

Importing this package side-effect-imports every concrete pipeline
module, which is what makes them visible to
:meth:`~app.tools.scibit.core.pipeline.Pipeline.for_id` and to direct
``Pipeline.__subclasses__()`` walks — only imported classes appear.

Available pipelines and their JSON identifiers:

- :class:`~app.tools.scibit.pipelines.direct_roi_pipeline.DirectROIPipeline`
  — ``"direct_roi"``
- :class:`~app.tools.scibit.pipelines.feature_alignment_pipeline.FeatureBasedAlignmentPipeline`
  — ``"feature_based_alignment"``
"""

from app.tools.scibit.pipelines.direct_roi_pipeline import DirectROIPipeline
from app.tools.scibit.pipelines.feature_alignment_pipeline import (
    FeatureBasedAlignmentPipeline,
)

__all__ = [
    "DirectROIPipeline",
    "FeatureBasedAlignmentPipeline",
]
