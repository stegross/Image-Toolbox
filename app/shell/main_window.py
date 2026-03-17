"""Main application window (REQ-HS-001, REQ-HS-004, REQ-HS-007)."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QMainWindow, QToolBar, QWidget

from app.core.config import ConfigManager
from app.core.roles import RoleManager
from app.plugin.registry import ToolRegistry
from app.shell.docking_manager import DockingManager
from app.shell.layout import LayoutPersistence
from app.shell.navigation import NavigationBar

_logger = logging.getLogger("vi_toolbox.shell.main_window")


class MainWindow(QMainWindow):
    """Top-level application window for VI-Toolbox.

    Owns the docking area, navigation bar, and all currently open tool
    widgets.  Delegates layout persistence to
    :class:`~app.shell.layout.LayoutPersistence` and tool lifecycle to
    :class:`~app.plugin.registry.ToolRegistry`.

    Parameters
    ----------
    tool_registry : ToolRegistry
        Shared registry of all registered tool classes.
    role_manager : RoleManager
        Used to check permissions before opening a tool.
    config_manager : ConfigManager
        Used to load per-tool configs and save them on shutdown.
    layout_persistence : LayoutPersistence
        Handles saving/restoring the dock layout between sessions.
    parent : QWidget | None
        Optional parent widget.
    """

    def __init__(
        self,
        tool_registry: ToolRegistry,
        role_manager: RoleManager,
        config_manager: ConfigManager,
        layout_persistence: LayoutPersistence,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tool_registry = tool_registry
        self._role_manager = role_manager
        self._config_manager = config_manager
        self._layout_persistence = layout_persistence

        self._docking_manager = DockingManager(self)
        self._nav_bar = NavigationBar(self._tool_registry, self)

        self.initialize()

    def initialize(self) -> None:
        """Build the UI, restore layout, and open base tools.

        Called once by :meth:`__init__`.  The sequence follows the startup
        diagram:

        1. Configure window properties.
        2. Embed navigation bar as a non-movable toolbar.
        3. Set the dock manager as the central widget.
        4. Restore previously saved layout (if any).
        5. Open all base tools automatically.
        """
        self.setWindowTitle("VI - Toolbox")
        self.resize(1280, 800)

        # Navigation bar as a non-movable toolbar above the dock area
        nav_toolbar = QToolBar("Navigation", self)
        nav_toolbar.setObjectName("NavigationToolBar")
        nav_toolbar.setMovable(False)
        nav_toolbar.setFloatable(False)
        nav_toolbar.addWidget(self._nav_bar)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, nav_toolbar)

        # Dock manager occupies the central widget area
        self.setCentralWidget(self._docking_manager.get_widget())

        # Connect navigation bar signal
        self._nav_bar.tool_selected.connect(self.open_tool)

        # Restore layout from previous session (REQ-HS-007)
        self.restore_layout()

        # Open base tools automatically
        self._open_base_tools()

        _logger.info("MainWindow initialised.")

    def open_tool(self, name: str) -> None:
        """Open a tool by name, respecting instance and permission rules.

        If *name* is already instantiated and ``allow_multiple_instances``
        is ``False``, the existing dock widget is focused instead.

        Parameters
        ----------
        name : str
            Tool name as registered in :class:`~app.plugin.registry.ToolRegistry`.
        """
        try:
            tool_cls = self._tool_registry.get_tool(name)
        except KeyError:
            _logger.error("open_tool: unknown tool '%s'", name)
            return

        already_open = self._tool_registry.is_instantiated(name)
        allow_multiple = getattr(tool_cls, "allow_multiple_instances", False)

        if already_open and not allow_multiple:
            _logger.debug("Tool '%s' already open — focusing existing widget.", name)
            self._docking_manager.focus_widget(name)
            return

        if not self._role_manager.has_permission(name):
            _logger.warning("Access denied: user has no permission for '%s'.", name)
            return

        # Instantiate and dock the tool
        tool_instance = tool_cls()
        widget = tool_instance.create_widget(self)
        closable = getattr(tool_cls, "closable", True)

        self._docking_manager.add_tool_widget(name, widget, closable=closable)
        self._tool_registry.set_instance(name, widget)
        tool_instance.on_activate()

        _logger.info("Tool opened: %s", name)

    def close_tool(self, name: str) -> None:
        """Close and remove a tool widget from the dock area.

        Parameters
        ----------
        name : str
            Tool name.
        """
        self._docking_manager.remove_tool_widget(name)
        self._tool_registry.remove_instance(name)
        _logger.info("Tool closed: %s", name)

    def save_layout(self) -> None:
        """Serialise and persist the current dock layout."""
        state = self._docking_manager.save_state()
        self._layout_persistence.save(state)

    def restore_layout(self) -> None:
        """Restore the dock layout from the last saved session (REQ-HS-007)."""
        state = self._layout_persistence.load()
        if state is not None:
            self._docking_manager.restore_state(state)
            _logger.info("Layout restored from previous session.")
        else:
            _logger.info("No saved layout found — using default.")

    # ------------------------------------------------------------------
    # Qt overrides
    # ------------------------------------------------------------------

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        """Handle window close: save configs and layout, then quit.

        Parameters
        ----------
        event : QCloseEvent
            The close event from Qt.
        """
        _logger.info("Shutdown initiated.")
        self._config_manager.save_all()
        self.save_layout()
        event.accept()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _open_base_tools(self) -> None:
        """Open all base tools that have ``auto_open_on_startup = True``."""
        for tool_cls in self._tool_registry.get_base_tools():
            if getattr(tool_cls, "auto_open_on_startup", False):
                self.open_tool(tool_cls.name)
