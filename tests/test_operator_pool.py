"""Tests for :class:`~app.tools.scibit.core.pool.OperatorPool`.

The pool's job is to make multi-stage pipelines memory-efficient: when
two stages use the same operator class, only one instance is created;
when a stage's assigned operator changes during calibration, the freshly
unreferenced instance is released so heavy OCR models do not stay in
memory.

Fake operator classes are used so the test stays a pure component test
(no OCR backend involved). One fake exposes a ``release()`` method to
exercise the optional cleanup hook.
"""

from __future__ import annotations

import pytest
from app.tools.scibit.core.pool import OperatorPool


class _FakeOperatorA:
    """Operator-stand-in without a ``release()`` hook."""


class _FakeOperatorB:
    """Operator-stand-in without a ``release()`` hook."""


class _ReleasableOperator:
    """Operator-stand-in with a ``release()`` hook counted per call."""

    def __init__(self) -> None:
        self.released = 0

    def release(self) -> None:
        """Record that the pool called us during cleanup."""
        self.released += 1


class _FakeStage:
    """Minimal stage stand-in: only the attribute the pool reads."""

    def __init__(self, operator_class: type | None) -> None:
        self.assigned_operator_class: type | None = operator_class


class _FakePipeline:
    """Pipeline stand-in: only ``get_stages()`` is touched by the pool."""

    def __init__(self, stages: list[_FakeStage]) -> None:
        self._stages = stages

    def get_stages(self) -> list[_FakeStage]:
        """Return the stage list as the real pipeline would."""
        return self._stages

    def set_assignment(self, stage_index: int, operator_class: type | None) -> None:
        """Test helper — simulate a calibration-time operator change."""
        self._stages[stage_index].assigned_operator_class = operator_class


@pytest.fixture()
def two_stage_pipeline() -> _FakePipeline:
    """Return a pipeline with two stages, both initially using FakeOperatorA."""
    return _FakePipeline([_FakeStage(_FakeOperatorA), _FakeStage(_FakeOperatorA)])


class TestGetOperatorSharesInstances:
    """``get_operator`` is the central deduplication: same class → same instance."""

    def test_returns_same_instance_on_repeated_get(self, two_stage_pipeline: _FakePipeline) -> None:
        """A second ``get_operator`` call returns the cached instance."""
        pool = OperatorPool(two_stage_pipeline)
        first = pool.get_operator(_FakeOperatorA)
        second = pool.get_operator(_FakeOperatorA)
        assert first is second

    def test_returns_distinct_instances_for_different_classes(
        self, two_stage_pipeline: _FakePipeline
    ) -> None:
        """Two different operator classes get two independent instances."""
        pool = OperatorPool(two_stage_pipeline)
        a = pool.get_operator(_FakeOperatorA)
        b = pool.get_operator(_FakeOperatorB)
        assert a is not b
        assert isinstance(a, _FakeOperatorA)
        assert isinstance(b, _FakeOperatorB)


class TestReleaseUnused:
    """``release_unused`` drops only operators no longer referenced by any stage."""

    def test_drops_instance_when_no_stage_references_it(
        self, two_stage_pipeline: _FakePipeline
    ) -> None:
        """Switching every stage off an operator triggers its release."""
        pool = OperatorPool(two_stage_pipeline)
        pool.get_operator(_FakeOperatorA)
        # Calibration switches both stages to a different operator.
        two_stage_pipeline.set_assignment(0, _FakeOperatorB)
        two_stage_pipeline.set_assignment(1, _FakeOperatorB)
        pool.release_unused()
        # FakeOperatorA has no remaining stage referrer — must be gone.
        assert _FakeOperatorA not in pool._instances
        # Re-getting builds a fresh instance.
        assert isinstance(pool.get_operator(_FakeOperatorA), _FakeOperatorA)

    def test_keeps_instance_when_one_stage_still_references_it(
        self, two_stage_pipeline: _FakePipeline
    ) -> None:
        """Switching only one of two stages keeps the shared instance alive."""
        pool = OperatorPool(two_stage_pipeline)
        original = pool.get_operator(_FakeOperatorA)
        two_stage_pipeline.set_assignment(0, _FakeOperatorB)
        # Stage 1 still references FakeOperatorA.
        pool.release_unused()
        assert pool.get_operator(_FakeOperatorA) is original

    def test_calls_release_on_operators_that_define_it(self) -> None:
        """Operators with a ``release()`` method are notified before removal."""
        stages = [_FakeStage(_ReleasableOperator)]
        pipeline = _FakePipeline(stages)
        pool = OperatorPool(pipeline)
        instance = pool.get_operator(_ReleasableOperator)
        # All stages now reference None → instance becomes unused.
        stages[0].assigned_operator_class = None
        pool.release_unused()
        assert instance.released == 1


class TestClear:
    """``clear`` empties the pool unconditionally."""

    def test_clear_removes_all_instances(self, two_stage_pipeline: _FakePipeline) -> None:
        """After clear the pool has no live instances of any class."""
        pool = OperatorPool(two_stage_pipeline)
        pool.get_operator(_FakeOperatorA)
        pool.get_operator(_FakeOperatorB)
        pool.clear()
        assert pool._instances == {}

    def test_clear_calls_release_on_each_releasable_instance(self) -> None:
        """Each releasable operator is notified exactly once during clear."""
        stages = [_FakeStage(_ReleasableOperator)]
        pipeline = _FakePipeline(stages)
        pool = OperatorPool(pipeline)
        instance = pool.get_operator(_ReleasableOperator)
        pool.clear()
        assert instance.released == 1
