"""Shared pytest fixtures for the VI-Toolbox test suite."""

from __future__ import annotations

import pytest
from app.plugin.registry import ToolRegistry


@pytest.fixture(autouse=True)
def clear_tool_registry() -> None:
    """Reset the ToolRegistry class-level state before every test.

    This prevents tool registrations in one test from leaking into
    another.
    """
    ToolRegistry._clear()
