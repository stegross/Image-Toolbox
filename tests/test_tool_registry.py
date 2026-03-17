"""Tests for ToolRegistry."""

from __future__ import annotations

import pytest
from app.plugin.base import IBaseToolPlugin, IToolPlugin
from app.plugin.categories import ToolCategory
from app.plugin.registry import ToolRegistry

# ---------------------------------------------------------------------------
# Minimal concrete tool stubs (only used in tests)
# ---------------------------------------------------------------------------


class _FakeWidget:
    """Minimal stand-in for QWidget (no Qt required for registry tests)."""


class _ToolA(IToolPlugin):
    name = "Tool A"
    category = ToolCategory.IDENTIFICATION
    description = "Fake tool A"
    icon_path = ""
    version = "1.0.0"

    def create_widget(self, parent=None):  # noqa: ANN001, ANN201
        """Return a fake widget."""
        return _FakeWidget()


class _ToolB(IToolPlugin):
    name = "Tool B"
    category = ToolCategory.IDENTIFICATION
    description = "Fake tool B"
    icon_path = ""
    version = "1.0.0"

    def create_widget(self, parent=None):  # noqa: ANN001, ANN201
        """Return a fake widget."""
        return _FakeWidget()


class _BaseTool(IBaseToolPlugin):
    name = "Base Tool"
    description = "Fake base tool"
    icon_path = ""
    version = "1.0.0"

    def create_widget(self, parent=None):  # noqa: ANN001, ANN201
        """Return a fake widget."""
        return _FakeWidget()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestToolRegistryRegister:
    """Tests for ToolRegistry.register."""

    def test_register_adds_tool(self) -> None:
        """Registered tool is retrievable by name."""
        ToolRegistry.register(_ToolA)
        registry = ToolRegistry()
        assert registry.get_tool("Tool A") is _ToolA

    def test_register_duplicate_raises(self) -> None:
        """Re-registering a tool with the same name raises ValueError."""
        ToolRegistry.register(_ToolA)
        with pytest.raises(ValueError, match="already registered"):
            ToolRegistry.register(_ToolA)

    def test_register_multiple_tools(self) -> None:
        """Multiple tools can be registered independently."""
        ToolRegistry.register(_ToolA)
        ToolRegistry.register(_ToolB)
        registry = ToolRegistry()
        assert registry.get_tool("Tool A") is _ToolA
        assert registry.get_tool("Tool B") is _ToolB


class TestToolRegistryQuery:
    """Tests for ToolRegistry query methods."""

    def setup_method(self) -> None:
        """Register tools used across query tests."""
        ToolRegistry.register(_ToolA)
        ToolRegistry.register(_ToolB)
        ToolRegistry.register(_BaseTool)
        self.registry = ToolRegistry()

    def test_get_tool_unknown_raises(self) -> None:
        """Getting an unregistered tool raises KeyError."""
        with pytest.raises(KeyError, match="not registered"):
            self.registry.get_tool("Nonexistent")

    def test_get_tools_by_category(self) -> None:
        """Returns only tools in the given category."""
        identification = self.registry.get_tools_by_category(ToolCategory.IDENTIFICATION)
        assert set(identification) == {_ToolA, _ToolB}

    def test_get_tools_by_category_returns_only_matching(self) -> None:
        """Does not return tools from other categories."""
        application = self.registry.get_tools_by_category(ToolCategory.APPLICATION)
        assert _ToolA not in application
        assert _ToolB not in application

    def test_get_all_categories_sorted(self) -> None:
        """Returns categories sorted by display value."""
        categories = self.registry.get_all_categories()
        assert categories == sorted(categories, key=lambda c: c.value)
        assert ToolCategory.APPLICATION in categories
        assert ToolCategory.IDENTIFICATION in categories

    def test_get_base_tools(self) -> None:
        """Returns only IBaseToolPlugin subclasses."""
        base = self.registry.get_base_tools()
        assert base == [_BaseTool]


class TestToolRegistryInstances:
    """Tests for instance tracking in ToolRegistry."""

    def setup_method(self) -> None:
        """Register a tool and create a registry instance."""
        ToolRegistry.register(_ToolA)
        self.registry = ToolRegistry()
        self.widget = _FakeWidget()

    def test_is_instantiated_false_initially(self) -> None:
        """Tool is not instantiated before set_instance is called."""
        assert not self.registry.is_instantiated("Tool A")

    def test_set_instance_marks_as_instantiated(self) -> None:
        """set_instance causes is_instantiated to return True."""
        self.registry.set_instance("Tool A", self.widget)  # type: ignore[arg-type]
        assert self.registry.is_instantiated("Tool A")

    def test_remove_instance(self) -> None:
        """remove_instance clears the tracked instance."""
        self.registry.set_instance("Tool A", self.widget)  # type: ignore[arg-type]
        self.registry.remove_instance("Tool A")
        assert not self.registry.is_instantiated("Tool A")

    def test_remove_instance_noop_when_not_tracked(self) -> None:
        """remove_instance does not raise when tool is not tracked."""
        self.registry.remove_instance("Tool A")  # should not raise


class TestToolRegistryQueryEmpty:
    """Tests for get_tools_by_category when the category has no tools."""

    def test_get_tools_by_category_empty(self) -> None:
        """Returns empty list when no tools are registered in a category."""
        ToolRegistry.register(_BaseTool)  # APPLICATION only
        registry = ToolRegistry()
        assert registry.get_tools_by_category(ToolCategory.IDENTIFICATION) == []


class TestToolRegistryClear:
    """Tests for ToolRegistry._clear (test helper)."""

    def test_clear_removes_all_registrations(self) -> None:
        """After _clear the registry is empty."""
        ToolRegistry.register(_ToolA)
        ToolRegistry._clear()
        registry = ToolRegistry()
        assert registry.get_all_categories() == []

    def test_clear_removes_instances(self) -> None:
        """After _clear no instances are tracked."""
        ToolRegistry.register(_ToolA)
        registry = ToolRegistry()
        registry.set_instance("Tool A", _FakeWidget())  # type: ignore[arg-type]
        ToolRegistry._clear()
        registry2 = ToolRegistry()
        assert not registry2.is_instantiated("Tool A")
