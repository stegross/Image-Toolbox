"""Stage ABC — the structural unit of a pipeline.

A Stage is a named slot in a pipeline's sequence. Each concrete subclass
declares its own name, required operation, default parameters, and how
to invoke its operator. The pipeline holds a list of Stage instances and
threads images through them; the calibration controller drives the same
stages interactively.

Design (spec Section 6.5): the Stage contains **no UI logic**. The
UI is rebuilt from a :class:`StageUIDescriptor` returned by the stage
itself, so adding a new stage requires no widget changes.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np
from numpy.typing import NDArray

from app.tools.scibit.core.types import StageResult

if TYPE_CHECKING:
    from app.tools.scibit.config.config import StageConfig
    from app.tools.scibit.core.operations import Operation
    from app.tools.scibit.core.pool import OperatorPool
    from app.tools.scibit.core.session import CalibrationSession

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# UI metadata types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ParamSpec:
    """Declarative parameter descriptor for dynamic UI generation.

    The CalibrationWidget consumes a list of ``ParamSpec`` instances and
    builds the right-side parameter form widget-by-widget.

    The ``"group"`` type renders a checkable QGroupBox whose toggle state
    is stored under :attr:`enable_key`. Nested parameters live in
    :attr:`children` and are disabled while the group is unchecked. They
    are flat in the parameter dict — pick unique keys (e.g. prefix with
    the group name) so they do not collide with siblings.
    """

    key: str
    label: str
    type: str  # "choice", "int", "float", "bool", "group"
    default: Any = None
    options: list[tuple[str, Any]] | None = None  # for "choice": [(display, value), ...]
    min: float | None = None
    max: float | None = None
    step: float | None = None
    suffix: str = ""
    tooltip: str = ""

    # Group-only fields. ``enable_key`` is the bool parameter that backs
    # the group's check state; ``children`` are the nested parameters.
    enable_key: str = ""
    children: tuple[ParamSpec, ...] = ()


@dataclass
class StageUIDescriptor:
    """Everything the CalibrationWidget needs to render one stage."""

    stage_name: str
    display_name: str

    # Navigation
    has_previous: bool = True
    has_confirm: bool = True
    confirm_label: str = "Confirm"
    previous_label: str = "← Previous"

    # Operator selection (always present, even with 1 option)
    available_operators: list[tuple[str, str]] = field(default_factory=list)
    # [(display_name, operator_key), ...]
    selected_operator: str = ""

    # Parameters for the currently selected operator (dynamic form)
    parameters: list[ParamSpec] = field(default_factory=list)
    parameter_values: dict[str, Any] = field(default_factory=dict)

    # Output display hints
    shows_image: bool = True
    shows_text_result: bool = False

    # Custom actions beyond confirm/previous (e.g. "Draw Manually", "Flip 180°")
    extra_buttons: list[dict[str, Any]] = field(default_factory=list)
    # [{"label": "Draw Manually", "action": "draw"}, ...]

    # Stage-specific UI mode hints
    enable_roi_drawing: bool = False
    roi_mode: str = ""  # e.g. "chip", "identifier"
    selectable_overlays: bool = False


# ---------------------------------------------------------------------------
# Stage ABC
# ---------------------------------------------------------------------------


class Stage(ABC):
    """Abstract base for all pipeline stages.

    Concrete subclasses declare:

    - :attr:`name` — string identifier used in config files.
    - :attr:`display_name` — human-readable label.
    - :attr:`required_operation` — Operation ABC, or ``None`` for built-ins.
    - :meth:`get_default_parameters` — initial parameter values.
    - :meth:`invoke` — operator dispatch with stage-specific argument mapping.
    - (optional) :meth:`get_default_operator_class` — initial operator.
    - (optional) :meth:`get_ui_descriptor` — custom calibration UI.
    """

    def __init__(self) -> None:
        self._pool: OperatorPool | None = None
        self._parameters: dict[str, Any] = {}
        self._assigned_operator_class: type | None = None
        self._init_defaults()

    # ------------------------------------------------------------------
    # Identity (subclasses must declare)
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique stage identifier within a pipeline."""

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable name shown in the UI."""

    @property
    @abstractmethod
    def required_operation(self) -> type[Operation] | None:
        """The Operation ABC this stage requires, or None for built-in stages."""

    # ------------------------------------------------------------------
    # Mutable state
    # ------------------------------------------------------------------

    @property
    def assigned_operator_class(self) -> type | None:
        """Operator class currently assigned to this stage, or ``None``."""
        return self._assigned_operator_class

    @assigned_operator_class.setter
    def assigned_operator_class(self, value: type | None) -> None:
        self._assigned_operator_class = value

    @property
    def parameters(self) -> dict[str, Any]:
        """Live parameter dict consumed by :meth:`invoke` and the UI form."""
        return self._parameters

    @parameters.setter
    def parameters(self, value: dict[str, Any]) -> None:
        self._parameters = value

    # ------------------------------------------------------------------
    # Pool injection
    # ------------------------------------------------------------------

    def set_pool(self, pool: OperatorPool) -> None:
        """Inject the owning pipeline's :class:`OperatorPool`."""
        self._pool = pool

    # ------------------------------------------------------------------
    # Defaults (subclasses override)
    # ------------------------------------------------------------------

    @abstractmethod
    def get_default_parameters(self) -> dict[str, Any]:
        """Return this stage's default parameter values."""

    def get_default_operator_class(self) -> type | None:
        """Return the default operator class for this stage, or None."""
        return None

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    @abstractmethod
    def invoke(
        self,
        operator: Operation,
        image: NDArray[np.uint8],
        session: CalibrationSession,
        **kwargs: Any,
    ) -> Any:
        """Execute *operator* with stage-specific argument mapping.

        Subclasses narrow *operator* to the concrete :class:`Operation`
        subclass declared by :attr:`required_operation`, then call the
        operation's named method (e.g. ``operator.detect_chip_region``).

        Built-in stages (``required_operation`` is ``None``) should return
        ``None``; their :meth:`run` short-circuits before reaching here.
        """

    def run(
        self,
        image: NDArray[np.uint8],
        session: CalibrationSession,
        *,
        charset_hint: set[str] | None = None,
    ) -> StageResult:
        """Execute this stage. Used by both calibration and batch."""
        if self.required_operation is None:
            return StageResult(data=None)

        if self._pool is None:
            raise RuntimeError(
                f"Stage '{self.name}': OperatorPool has not been set. "
                "Call set_pool() before running the stage."
            )
        if self._assigned_operator_class is None:
            raise RuntimeError(
                f"Stage '{self.name}' requires operation "
                f"'{self.required_operation.__name__}' but has no assigned "
                "operator class."
            )

        operator = self._pool.get_operator(self._assigned_operator_class)
        try:
            result_data = self.invoke(operator, image, session, charset_hint=charset_hint)
            return StageResult(data=result_data)
        except Exception as exc:
            _log.exception("Stage '%s' raised an exception.", self.name)
            return StageResult(data=None, error=str(exc))

    # ------------------------------------------------------------------
    # UI descriptor (overridable)
    # ------------------------------------------------------------------

    def get_ui_descriptor(self) -> StageUIDescriptor:
        """Return the UI descriptor for this stage's current state.

        Default implementation builds from the operator registry plus the
        operator's ``get_param_schema``. Stages with custom calibration
        behaviour override this.
        """
        from app.tools.scibit.core.registry import OperatorRegistry

        available_operators: list[tuple[str, str]] = []
        selected = ""
        params: list[ParamSpec] = []

        if self.required_operation is not None:
            operators = OperatorRegistry().get_operators_for(self.required_operation)
            available_operators = [(cls.__name__, cls.__name__) for cls in operators]
            if self._assigned_operator_class is not None:
                selected = self._assigned_operator_class.__name__
            elif available_operators:
                selected = available_operators[0][1]
            params = self._get_operator_param_schema()

        return StageUIDescriptor(
            stage_name=self.name,
            display_name=self.display_name,
            available_operators=available_operators,
            selected_operator=selected,
            parameters=params,
            parameter_values=dict(self._parameters),
        )

    def _get_operator_param_schema(self) -> list[ParamSpec]:
        """Ask the assigned operator for its parameter schema.

        Operators are expected to expose ``get_param_schema(operation)``
        once Phase 2 is complete. Falls back to an empty list otherwise.
        """
        if self._pool is None or self._assigned_operator_class is None:
            return []
        try:
            op = self._pool.get_operator(self._assigned_operator_class)
            if hasattr(op, "get_param_schema"):
                return op.get_param_schema(self.required_operation)
        except Exception:
            _log.exception(
                "Stage '%s': error fetching param schema from %s.",
                self.name,
                getattr(self._assigned_operator_class, "__name__", "?"),
            )
        return []

    # ------------------------------------------------------------------
    # Config serialisation
    # ------------------------------------------------------------------

    def to_config(self) -> StageConfig:
        """Serialise this stage's state to a :class:`StageConfig`."""
        from app.tools.scibit.config.config import StageConfig

        op_name = (
            self._assigned_operator_class.__name__
            if self._assigned_operator_class is not None
            else ""
        )
        return StageConfig(operator=op_name, parameters=dict(self._parameters))

    def apply_config(self, stage_config: StageConfig) -> None:
        """Apply a saved :class:`StageConfig` to this stage."""
        from app.tools.scibit.core.registry import OperatorRegistry

        if stage_config.operator:
            op_cls = OperatorRegistry().resolve_operator_class(stage_config.operator)
            if op_cls is not None:
                self._assigned_operator_class = op_cls
        merged = dict(self._parameters)
        merged.update(stage_config.parameters)
        self._parameters = merged

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _init_defaults(self) -> None:
        self._parameters = self.get_default_parameters()
        self._assigned_operator_class = self.get_default_operator_class()
