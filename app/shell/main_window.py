"""Main application window (REQ-HS-001, REQ-HS-004, REQ-HS-007)."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QMainWindow, QWidget
from PySide6QtAds import CDockManager

from app.core.config import ConfigManager
from app.core.roles import RoleManager
from app.plugin.registry import ToolRegistry
from app.shell.docking_manager import DockingManager
from app.shell.layout import LayoutPersistence
from app.shell.navigation import NavigationBar
from app.shell.ui.ui_main_window import Ui_MainWindow

_logger = logging.getLogger("vi_toolbox.shell.main_window")

_LOG_DIR = Path.home() / ".vi_toolbox" / "logs"


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

        self.initialize()

    def initialize(self) -> None:
        """Build the UI, restore layout, and open base tools.

        Called once by :meth:`__init__`.  Sequence:

        1. Set Qt ADS config flags (must happen before ``CDockManager`` is
           created inside ``setupUi``).
        2. Load the ``.ui`` file — creates the ``CDockManager`` and toolbar.
        3. Wrap the dock manager and build the navigation bar.
        4. Restore previously saved layout (REQ-HS-007).
        5. Open all base tools automatically.
        """
        # Config flags must be set before CDockManager is instantiated
        CDockManager.setConfigFlag(CDockManager.eConfigFlag.DockAreaHasUndockButton, False)
        CDockManager.setConfigFlag(CDockManager.eConfigFlag.DockAreaHasTabsMenuButton, False)
        CDockManager.setConfigFlag(CDockManager.eConfigFlag.FocusHighlighting, True)

        # Load the .ui file (creates dockManager and navigationToolBar)
        self._ui = Ui_MainWindow()
        self._ui.setupUi(self)

        # Wrap the CDockManager created by setupUi
        self._docking_manager = DockingManager(self._ui.dockManager)

        # Build NavigationBar and embed it in the toolbar from the .ui
        self._nav_bar = NavigationBar(self._tool_registry, self)
        self._ui.navigationToolBar.addWidget(self._nav_bar)

        # Wire signals
        self._nav_bar.tool_selected.connect(self.open_tool)
        self._nav_bar.action_triggered.connect(self._handle_action)

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
            Tool name as registered in
            :class:`~app.plugin.registry.ToolRegistry`.
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

    def _handle_action(self, action: str) -> None:
        """Dispatch static navigation bar actions.

        Parameters
        ----------
        action : str
            Action key emitted by :class:`~app.shell.navigation.NavigationBar`.
        """
        if action == "open_log_folder":
            _LOG_DIR.mkdir(parents=True, exist_ok=True)
            os.startfile(str(_LOG_DIR))  # Windows only (REQ-EC-004)
        elif action == "about":
            _logger.info("About: VI-Toolbox v0.1.0")
        else:
            _logger.warning("Unknown action: %s", action)
