"""Integration test for the VI-Toolbox host shell.

Verifies that the four shell subsystems wire up correctly as a system:

* :class:`~app.plugin.registry.ToolRegistry` — plugin registration,
* :class:`~app.shell.main_window.MainWindow` — top-level shell,
* :class:`~app.shell.docking_manager.DockingManager` — dock area,
* the dynamically built category menu bar (navigation).

Fake tools are registered for the duration of each test so the
integration is exercised without dragging in heavy real tools (which
each require Qt UI files, OCR libraries, etc.). The autouse fixture
:func:`tests.conftest.clear_tool_registry` resets the registry between
tests so registrations cannot leak.

Covers REQ-HS-001 (docking-based window management), REQ-HS-004
(top-level category navigation), and REQ-HS-011 (new tools without
modifying the core).
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import pytest
from app.core.config import ConfigManager
from app.core.roles import RoleManager
from app.plugin.base import IToolPlugin
from app.plugin.categories import ToolCategory
from app.plugin.registry import ToolRegistry
from app.shell.layout import LayoutPersistence
from app.shell.main_window import MainWindow
from PySide6.QtWidgets import QLabel, QMenu, QWidget
from pytestqt.qtbot import QtBot

# ---------------------------------------------------------------------------
# Fake tools
# ---------------------------------------------------------------------------


class _FakeBaseTool(IToolPlugin):
    """Minimal IToolPlugin used as an auto-opening base tool in tests."""

    name: ClassVar[str] = "Fake Base Tool"
    category: ClassVar[ToolCategory] = ToolCategory.BASE
    description: ClassVar[str] = "Fake base tool for integration tests."
    icon_path: ClassVar[str] = ""
    version: ClassVar[str] = "1.0.0"
    allow_multiple_instances: ClassVar[bool] = False
    closable: ClassVar[bool] = True

    def __init__(self, config_manager: ConfigManager) -> None:
        self._config_manager = config_manager

    def create_widget(self, parent: QWidget | None = None) -> QWidget:
        """Return a trivial QLabel as the tool's content widget."""
        return QLabel(self.name, parent)


class _FakeIdentificationTool(IToolPlugin):
    """Minimal IToolPlugin used as a non-auto-opening extension tool in tests."""

    name: ClassVar[str] = "Fake ID Tool"
    category: ClassVar[ToolCategory] = ToolCategory.IDENTIFICATION
    description: ClassVar[str] = "Fake identification tool for integration tests."
    icon_path: ClassVar[str] = ""
    version: ClassVar[str] = "1.0.0"
    allow_multiple_instances: ClassVar[bool] = False
    closable: ClassVar[bool] = True

    def __init__(self, config_manager: ConfigManager) -> None:
        self._config_manager = config_manager

    def create_widget(self, parent: QWidget | None = None) -> QWidget:
        """Return a trivial QLabel as the tool's content widget."""
        return QLabel(self.name, parent)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def fake_tools_registered() -> None:
    """Register two fake tools (one auto-open base, one extension)."""
    ToolRegistry.register(_FakeBaseTool, auto_open=True)
    ToolRegistry.register(_FakeIdentificationTool)


@pytest.fixture()
def main_window(
    qtbot: QtBot,
    tmp_path: Path,
    fake_tools_registered: None,  # noqa: ARG001 — fixture only needed for side effect
) -> MainWindow:
    """Build a real MainWindow wired to disposable tmp_path-based services."""
    config_manager = ConfigManager(tmp_path / "config")
    role_manager = RoleManager(tmp_path / "config")
    layout_persistence = LayoutPersistence(tmp_path / "layout.state")
    window = MainWindow(
        tool_registry=ToolRegistry(),
        role_manager=role_manager,
        config_manager=config_manager,
        layout_persistence=layout_persistence,
    )
    qtbot.addWidget(window)
    return window


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _menu_titles(window: MainWindow) -> list[str]:
    """Return the title of every top-level menu in the menu bar."""
    return [a.text() for a in window.menuBar().actions()]


def _menu_by_title(window: MainWindow, title: str) -> QMenu | None:
    """Return the QMenu attached to the menu bar entry titled *title*.

    Uses ``findChildren(QMenu)`` rather than ``action.menu()`` because the
    latter returns a transient PySide6 wrapper that the GC may drop before
    the test can call ``.actions()`` on it.
    """
    for menu in window.menuBar().findChildren(QMenu):
        if menu.title() == title:
            return menu
    return None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRegistryToMenuBar:
    """Registered tools must appear in the dynamically built category menus."""

    def test_one_menu_per_category(self, main_window: MainWindow) -> None:
        """Each registered tool category gets its own menu bar entry."""
        titles = _menu_titles(main_window)
        assert ToolCategory.BASE.value in titles
        assert ToolCategory.IDENTIFICATION.value in titles

    def test_base_menu_lists_base_tool(self, main_window: MainWindow) -> None:
        """The Base category menu contains an action for the base tool."""
        menu = _menu_by_title(main_window, ToolCategory.BASE.value)
        assert menu is not None
        action_labels = {a.text() for a in menu.actions()}
        assert _FakeBaseTool.name in action_labels

    def test_identification_menu_lists_extension_tool(self, main_window: MainWindow) -> None:
        """The Identification category menu contains the extension tool."""
        menu = _menu_by_title(main_window, ToolCategory.IDENTIFICATION.value)
        assert menu is not None
        action_labels = {a.text() for a in menu.actions()}
        assert _FakeIdentificationTool.name in action_labels


class TestAutoOpenOnStartup:
    """Tools registered with ``auto_open=True`` are docked at startup."""

    def test_auto_open_base_tool_is_instantiated(self, main_window: MainWindow) -> None:
        """The fake base tool, marked auto-open, appears in the instance registry."""
        registry = ToolRegistry()
        assert registry.is_instantiated(_FakeBaseTool.__name__)

    def test_non_auto_open_tool_is_not_instantiated(self, main_window: MainWindow) -> None:
        """The fake identification tool, not auto-open, stays inactive at startup."""
        registry = ToolRegistry()
        assert not registry.is_instantiated(_FakeIdentificationTool.__name__)


class TestOpenAndCloseTool:
    """``open_tool`` adds a dock, ``close_tool`` removes it."""

    def test_open_tool_adds_dock_widget(self, main_window: MainWindow) -> None:
        """Opening a registered tool dock-registers it under its class name."""
        widget = main_window.open_tool(_FakeIdentificationTool.__name__)
        assert widget is not None
        # The dock widget is tracked under the instance key, which for
        # single-instance tools equals the registered class name.
        assert _FakeIdentificationTool.__name__ in main_window._docking_manager._dock_widgets

    def test_close_tool_removes_dock_widget(self, main_window: MainWindow) -> None:
        """Closing a tool removes its dock widget from the docking manager."""
        main_window.open_tool(_FakeIdentificationTool.__name__)
        main_window.close_tool(_FakeIdentificationTool.__name__)
        assert _FakeIdentificationTool.__name__ not in main_window._docking_manager._dock_widgets

    def test_reopen_single_instance_returns_none(self, main_window: MainWindow) -> None:
        """Opening a single-instance tool twice focuses the existing widget."""
        first = main_window.open_tool(_FakeIdentificationTool.__name__)
        second = main_window.open_tool(_FakeIdentificationTool.__name__)
        assert first is not None
        assert second is None  # focused existing, did not create a new one
