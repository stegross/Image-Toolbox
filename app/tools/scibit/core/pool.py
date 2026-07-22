"""OperatorPool — pipeline-level instance cache for operator objects.

The pool ensures that when multiple stages are assigned to the same
operator class (e.g. ``PaddleOCROperator`` used for both text detection
and recognition), only one instance is created.  This avoids redundant
model initialisation, which is critical for large OCR frameworks that
consume significant memory and startup time.

Operator instances are stateless with respect to parameters — parameters
are passed per-call from the stage — so sharing a single instance between
two stages that use different parameter values is safe.

Design pattern: Object Pool / Flyweight (spec Section 3.6).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.tools.scibit.core.pipeline import Pipeline

_log = logging.getLogger(__name__)


class OperatorPool:
    """Manages operator instances for a single pipeline.

    Owned by the pipeline instance; destroyed when the pipeline is torn down
    (see :meth:`clear`).

    Parameters
    ----------
    pipeline : Pipeline
        The pipeline that owns this pool.  Used by :meth:`release_unused`
        to discover which operator classes are still referenced by active
        stages.
    """

    def __init__(self, pipeline: Pipeline) -> None:
        self._pipeline = pipeline
        self._instances: dict[type, object] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_operator(self, operator_class: type) -> object:
        """Return the shared operator instance for *operator_class*.

        Creates a new instance on first access; subsequent calls with the
        same class return the cached instance.

        Parameters
        ----------
        operator_class : type
            The operator class to instantiate or retrieve.

        Returns
        -------
        object
            The live operator instance.
        """
        if operator_class not in self._instances:
            _log.debug("OperatorPool: instantiating %s.", operator_class.__name__)
            self._instances[operator_class] = operator_class()
        return self._instances[operator_class]

    def release_unused(self) -> None:
        """Remove instances no longer referenced by any stage.

        Called after a stage's operator assignment changes during
        calibration.  If the old operator class is no longer referenced by
        any stage, its instance is dropped so GPU memory can be reclaimed
        (important for large OCR models).

        Operators that expose a ``release()`` method have it called before
        the instance is removed.
        """
        referenced: set[type] = {
            stage.assigned_operator_class
            for stage in self._pipeline.get_stages()
            if stage.assigned_operator_class is not None
        }
        unused = set(self._instances.keys()) - referenced
        for cls in unused:
            self._release_instance(cls)

    def clear(self) -> None:
        """Release **all** operator instances and empty the pool.

        Called when the pipeline is torn down.  Operators with a
        ``release()`` method have it called before removal.
        """
        for cls in list(self._instances.keys()):
            self._release_instance(cls)
        _log.debug("OperatorPool: cleared all instances.")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _release_instance(self, cls: type) -> None:
        """Remove and optionally release the instance for *cls*."""
        instance = self._instances.pop(cls, None)
        if instance is None:
            return
        if hasattr(instance, "release") and callable(instance.release):
            try:
                instance.release()
            except Exception:
                _log.exception("OperatorPool: error while releasing %s.", cls.__name__)
        _log.debug("OperatorPool: released %s.", cls.__name__)
