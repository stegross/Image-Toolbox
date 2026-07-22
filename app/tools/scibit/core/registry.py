"""OperatorRegistry — singleton plugin registry for operator discovery.

Operators register themselves at import time using the
:func:`register_operator` decorator.  The registry maps each operation
type to the list of operator classes that implement it.

The decorator additionally verifies that the operator class inherits
from every Operation ABC it claims to implement, so a mismatched
declaration fails at import time rather than at first use.

Usage (in an operator module)::

    from app.tools.scibit.core.registry import register_operator
    from app.tools.scibit.core.operations import TextRecognition, TextRegionDetection

    @register_operator([TextRegionDetection, TextRecognition])
    class PaddleOCROperator(TextRegionDetection, TextRecognition):
        ...

Querying the registry::

    registry = OperatorRegistry()
    candidates = registry.get_operators_for(TextRecognition)
    # → [PaddleOCROperator, EasyOCROperator, TesseractOperator]
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from app.tools.scibit.core.operations import Operation

if TYPE_CHECKING:
    from app.tools.scibit.core.pipeline import Pipeline

_log = logging.getLogger(__name__)


class OperatorRegistry:
    """Singleton registry that maps operations to their implementing operators.

    The registry is populated at import time when operator modules are
    imported.  It is queried at runtime by the UI to populate operator
    selection dropdowns and to validate pipeline configurations before
    a batch run.

    Design pattern: Registry / Plugin (spec Section 3.3).
    """

    _instance: OperatorRegistry | None = None

    def __new__(cls) -> OperatorRegistry:
        """Return the singleton instance, creating it on first call."""
        if cls._instance is None:
            inst = super().__new__(cls)
            inst._registry: dict[type[Operation], list[type]] = {}
            cls._instance = inst
        return cls._instance

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self,
        operator_class: type,
        operations: list[type[Operation]],
    ) -> None:
        """Register *operator_class* as implementing each type in *operations*.

        Called at import time by the :func:`register_operator` decorator or
        by explicit call.  Duplicate registrations are silently ignored.

        Parameters
        ----------
        operator_class : type
            The concrete operator class to register.
        operations : list[type[Operation]]
            Operation ABCs that *operator_class* implements.

        Raises
        ------
        ValueError
            If *operations* is empty.
        TypeError
            If *operator_class* does not inherit from every type in
            *operations*.  ABC inheritance is what makes
            :func:`isinstance` / :func:`issubclass` checks against
            operations work and what triggers Python's abstract-method
            enforcement at first instantiation.
        """
        if not operations:
            raise ValueError(
                f"Operator '{operator_class.__name__}' must declare at least "
                "one operation during registration."
            )
        for op in operations:
            if not issubclass(operator_class, op):
                raise TypeError(
                    f"Operator '{operator_class.__name__}' is registered for "
                    f"operation '{op.__name__}' but does not inherit from it. "
                    f"Add '{op.__name__}' to the class's base list."
                )
            bucket = self._registry.setdefault(op, [])
            if operator_class not in bucket:
                bucket.append(operator_class)
                _log.debug(
                    "OperatorRegistry: registered %s for %s.",
                    operator_class.__name__,
                    op.__name__,
                )

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_operators_for(self, operation: type[Operation]) -> list[type]:
        """Return all operator classes that implement *operation*.

        Parameters
        ----------
        operation : type[Operation]
            An :class:`~app.tools.scibit.core.operations.Operation`
            subclass (the ABC itself, not an instance).

        Returns
        -------
        list[type]
            Operator classes in registration order.  Empty list if no
            operator is registered for *operation*.
        """
        return list(self._registry.get(operation, []))

    def validate_assignment(self, pipeline: Pipeline) -> bool:
        """Verify that every stage in *pipeline* has a valid operator.

        A stage assignment is valid when:

        - The stage has no ``required_operation`` (built-in stage), **or**
        - The ``assigned_operator_class`` is a subclass of the stage's
          ``required_operation`` (Operation ABC).

        Parameters
        ----------
        pipeline : Pipeline
            The pipeline whose stage assignments are checked.

        Returns
        -------
        bool
            ``True`` if every stage is correctly assigned.
        """
        valid = True
        for stage in pipeline.get_stages():
            if stage.required_operation is None:
                continue  # built-in stage — no operator needed

            if stage.assigned_operator_class is None:
                _log.warning(
                    "Stage '%s' has required_operation '%s' but no assigned operator_class.",
                    stage.name,
                    stage.required_operation.__name__,
                )
                valid = False
                continue

            if not issubclass(stage.assigned_operator_class, stage.required_operation):
                _log.warning(
                    "Stage '%s': assigned operator '%s' does not inherit from operation '%s'.",
                    stage.name,
                    stage.assigned_operator_class.__name__,
                    stage.required_operation.__name__,
                )
                valid = False

        return valid

    def resolve_operator_class(self, identifier: str) -> type | None:
        """Look up an operator class by its string identifier.

        Searches all registered operator classes for one whose
        ``__name__`` matches *identifier*.

        Parameters
        ----------
        identifier : str
            The operator class name (e.g. ``"PaddleOCROperator"``).

        Returns
        -------
        type | None
            The matching operator class, or ``None`` if not found.
        """
        seen: set[type] = set()
        for classes in self._registry.values():
            for cls in classes:
                if cls not in seen:
                    seen.add(cls)
                    if cls.__name__ == identifier:
                        return cls
        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @classmethod
    def _reset(cls) -> None:
        """Reset the singleton — intended for use in tests only."""
        cls._instance = None


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------


def register_operator(operations: list[type]) -> Callable[[type], type]:
    """Class decorator that registers the decorated class in :class:`OperatorRegistry`.

    Parameters
    ----------
    operations : list[type]
        Operation ABCs that the decorated class implements.

    Returns
    -------
    Callable[[type], type]
        The decorator, which returns the class unchanged after registering it.

    Examples
    --------
    ::

        @register_operator([TextRegionDetection, TextRecognition])
        class PaddleOCROperator(TextRegionDetection, TextRecognition):
            ...
    """

    def decorator(cls: type) -> type:
        OperatorRegistry().register(cls, operations)
        return cls

    return decorator
